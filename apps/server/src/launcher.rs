use crate::{
    evidence::{self, ArtifactName, Bundle, RuntimeFacts},
    observer::{self, ObserverRequest, ObserverStatus},
    policy::{self, Snapshot},
    protocol::{Request, Response},
    Limits, Store,
};
use anyhow::{bail, ensure, Context, Result};
use containerd_client::{
    services::v1::{
        container::Runtime, containers_client::ContainersClient, tasks_client::TasksClient,
        Container, CreateContainerRequest, CreateTaskRequest, DeleteContainerRequest,
        DeleteTaskRequest, GetRequest, StartRequest,
    },
    tonic::{self, transport::Channel},
};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs,
    os::{
        fd::{FromRawFd, OwnedFd},
        unix::fs::{MetadataExt, PermissionsExt},
    },
    path::{Path, PathBuf},
    time::Duration,
};

pub const LAUNCHER_SOCKET: &str = "/run/actryn/launcher.sock";
pub const SERVER_SOCKET: &str = "/run/actryn-server/server.sock";
pub const OBSERVER_SOCKET: &str = "/run/actryn/observer.sock";
pub const STATE_ROOT: &str = "/var/lib/actryn-server";
pub const CGROUP_ROOT: &str = "/sys/fs/cgroup/actryn";
pub const BROKER_ROOT: &str = "/run/actryn/brokers";
const NAMESPACE: &str = "actryn";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Artifact {
    pub rootfs: PathBuf,
    pub argv: Vec<String>,
}
impl Artifact {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.rootfs.is_absolute() && fs::canonicalize(&self.rootfs)? == self.rootfs,
            "artifact rootfs must be canonical"
        );
        trusted_path(&self.rootfs)?;
        ensure!(self.rootfs.is_dir(), "artifact rootfs is not a directory");
        ensure!(
            !self.argv.is_empty() && self.argv.len() <= 32 && self.argv[0].starts_with('/'),
            "invalid approved entrypoint"
        );
        ensure!(
            self.argv
                .iter()
                .all(|v| v.len() <= 4096 && !v.contains('\0')),
            "invalid argv"
        );
        Ok(())
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LauncherConfig {
    pub server_uid: u32,
    pub operator_uid: u32,
    pub io_device: String,
    pub artifacts: BTreeMap<String, Artifact>,
}
impl LauncherConfig {
    pub fn read(path: &Path) -> Result<Self> {
        trusted_path(path)?;
        let bytes = fs::read(path)?;
        ensure!(bytes.len() <= 65536, "configuration too large");
        let config: Self = serde_json::from_slice(&bytes)?;
        let parts: Vec<_> = config.io_device.split(':').collect();
        ensure!(
            parts.len() == 2
                && parts
                    .iter()
                    .all(|v| !v.is_empty() && v.parse::<u32>().is_ok()),
            "invalid I/O device"
        );
        ensure!(
            config.server_uid != 0 && config.operator_uid != config.server_uid,
            "service must be unprivileged and separate from operator"
        );
        ensure!(
            !config.artifacts.is_empty() && config.artifacts.len() <= 8,
            "invalid artifact registry"
        );
        for (digest, artifact) in &config.artifacts {
            ensure!(
                crate::store::valid_digest(digest),
                "invalid artifact digest"
            );
            artifact.validate()?;
            crate::artifact::validate_approved(digest, artifact)?;
        }
        Ok(config)
    }
}
pub fn trusted_path(path: &Path) -> Result<()> {
    for parent in path.ancestors() {
        let m = fs::symlink_metadata(parent)?;
        ensure!(
            !m.file_type().is_symlink() && m.uid() == 0 && m.mode() & 0o022 == 0,
            "untrusted path {}",
            parent.display()
        );
    }
    Ok(())
}
pub fn now_ms() -> Result<i64> {
    let mut ts = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    ensure!(
        unsafe { libc::clock_gettime(libc::CLOCK_BOOTTIME, &mut ts) } == 0,
        "clock read failed"
    );
    ts.tv_sec
        .checked_mul(1000)
        .and_then(|v| v.checked_add(ts.tv_nsec / 1_000_000))
        .context("clock overflow")
}
fn request<T>(value: T) -> tonic::Request<T> {
    let mut r = tonic::Request::new(value);
    r.metadata_mut()
        .insert("containerd-namespace", NAMESPACE.parse().unwrap());
    r.set_timeout(Duration::from_secs(5));
    r
}
fn cgroup_path(id: &str) -> String {
    format!("/actryn/{id}")
}
fn cgroup_dir(id: &str) -> PathBuf {
    Path::new(CGROUP_ROOT).join(id)
}
#[derive(Clone, Debug, Serialize, Deserialize)]
struct Binding {
    boot_id: String,
    cgroup_id: u64,
    observer: Option<ObserverStatus>,
    snapshot: Option<Snapshot>,
    #[serde(default)]
    device_policy: Option<crate::device_policy::Proof>,
    ambiguous_create: bool,
}
impl Binding {
    fn verify(
        &self,
        current: &Snapshot,
        boot_id: &str,
        cgroup_id: u64,
        cgroup: &str,
        io_device: &str,
    ) -> Result<()> {
        ensure!(
            self.boot_id == boot_id && !self.ambiguous_create,
            "retired runtime binding"
        );
        let expected = self.snapshot.as_ref().context("unverified task")?;
        ensure!(
            current.start_ticks == expected.start_ticks && cgroup_id == self.cgroup_id,
            "reused task/cgroup identity"
        );
        policy::verify_snapshot(current, expected.pid, cgroup, io_device)?;
        crate::device_policy::verify(
            self.device_policy
                .as_ref()
                .context("fixed device policy was not verified")?,
            &current.device_programs_direct,
            &current.device_programs,
        )?;
        ensure!(
            current.device_programs_direct == expected.device_programs_direct
                && current.device_programs == expected.device_programs,
            "prepared device policy inventory changed"
        );
        Ok(())
    }
}

pub struct Launcher {
    pub store: Store,
    config: LauncherConfig,
    containers: ContainersClient<Channel>,
    tasks: TasksClient<Channel>,
    boot_id: String,
    pidfds: BTreeMap<String, OwnedFd>,
    logs: BTreeMap<String, Vec<LogCapture>>,
}
impl Launcher {
    pub async fn new(config: LauncherConfig) -> Result<Self> {
        ensure!(unsafe { libc::geteuid() } == 0, "launcher must run as root");
        fs::create_dir_all(STATE_ROOT)?;
        trusted_path(Path::new(STATE_ROOT))?;
        for (directory, mode) in [
            (BROKER_ROOT, 0o700),
            ("/run/actryn-server", 0o755),
            ("/var/lib/actryn-server/broker", 0o700),
        ] {
            fs::create_dir_all(directory)?;
            fs::set_permissions(directory, fs::Permissions::from_mode(mode))?;
            let path = std::ffi::CString::new(directory)?;
            ensure!(
                unsafe { libc::chown(path.as_ptr(), config.server_uid, u32::MAX) } == 0,
                "service directory ownership failed"
            );
        }
        fs::create_dir_all(CGROUP_ROOT)?;
        fs::write(
            Path::new(CGROUP_ROOT).join("cgroup.subtree_control"),
            "+cpu +memory +pids +io",
        )?;
        let channel = containerd_client::connect("/run/containerd/containerd.sock").await?;
        let store = Store::open(
            Path::new(STATE_ROOT).join("launcher.sqlite"),
            Limits::default(),
        )?;
        Ok(Self {
            store,
            config,
            containers: ContainersClient::new(channel.clone()),
            tasks: TasksClient::new(channel),
            boot_id: fs::read_to_string("/proc/sys/kernel/random/boot_id")?
                .trim()
                .into(),
            pidfds: BTreeMap::new(),
            logs: BTreeMap::new(),
        })
    }
    fn observer_request(&self, op: &str, id: &str, cgroup_id: u64) -> ObserverRequest {
        ObserverRequest {
            op: op.into(),
            attempt_id: id.into(),
            boot_id: self.boot_id.clone(),
            cgroup_id,
            cgroup_path: cgroup_path(id),
        }
    }
    pub async fn recover(&mut self) -> Result<()> {
        for id in self.store.recover()? {
            if Path::new(STATE_ROOT).join(&id).exists() {
                // A previous reader may have died with undrained FIFO bytes or unsynced data.
                self.store.record_gap(&id, "log_incomplete")?;
            }
            if let Err(error) = self.cleanup(&id).await {
                eprintln!("unreconciled runtime {id}: {error:#}");
            }
        }
        Ok(())
    }
    pub async fn handle(&mut self, request: Request) -> Response {
        if let Request::Export { attempt_id } = &request {
            return match self.export_evidence(attempt_id) {
                Ok(bundle) => Response::Evidence { bundle },
                Err(error) => Response::Error {
                    message: format!("{error:#}"),
                },
            };
        }
        let result: Result<_> = async {
            match request {
                Request::Prepare { artifact_digest } => {
                    let id = self.prepare(&artifact_digest).await?;
                    self.store.inspect(&id)
                }
                Request::Start { attempt_id } => {
                    self.start(&attempt_id).await?;
                    self.store.inspect(&attempt_id)
                }
                Request::Stop { attempt_id } => {
                    self.store.cancel(&attempt_id)?;
                    self.cleanup(&attempt_id).await?;
                    self.store.inspect(&attempt_id)
                }
                Request::Inspect { attempt_id } => self.store.inspect(&attempt_id),
                Request::Result { .. } => bail!("result lookup belongs to the broker service"),
                Request::BindRobot { .. }
                | Request::RobotQuery { .. }
                | Request::RobotCancel { .. } => {
                    bail!("Robot delegation belongs to the broker service")
                }
                Request::Export { .. } => unreachable!(),
            }
        }
        .await;
        match result {
            Ok(inspection) => Response::Ok { inspection },
            Err(error) => Response::Error {
                message: format!("{error:#}"),
            },
        }
    }
    fn export_evidence(&self, id: &str) -> Result<Bundle> {
        let inspection = self.store.inspect(id)?;
        let mut attempt = inspection.attempt;
        let binding = attempt.binding.take();
        let complete = attempt.state == "reaped"
            && !inspection
                .evidence_gaps
                .iter()
                .any(|v| v == "log_incomplete");
        let mut bundle = Bundle::new(id)?;
        bundle.add(ArtifactName::Attempt, serde_json::to_value(&attempt)?)?;
        if let Some(binding) = binding {
            bundle.add(
                ArtifactName::RuntimeBinding,
                serde_json::from_str(&binding)?,
            )?;
        } else {
            bundle.omit(ArtifactName::RuntimeBinding, "preparation_never_bound", 1)?;
        }
        if let Some(facts) = self.store.runtime_evidence(id)? {
            bundle.add(ArtifactName::RuntimeFacts, serde_json::from_str(&facts)?)?;
        } else {
            bundle.omit(
                ArtifactName::RuntimeFacts,
                "final_resource_snapshot_unavailable",
                1,
            )?;
        }
        let directory = Path::new(STATE_ROOT).join(id);
        for (name, stderr) in [(ArtifactName::Stdout, false), (ArtifactName::Stderr, true)] {
            match evidence::log_evidence(&directory, stderr, complete) {
                Ok(log) => {
                    bundle.add(name, serde_json::to_value(log)?)?;
                }
                Err(_) => bundle.omit(name, "retained_log_unavailable", 1)?,
            }
        }
        for gap in inspection.evidence_gaps {
            bundle.omit(ArtifactName::RuntimeFacts, &gap, 1)?;
        }
        Ok(bundle)
    }
    async fn prepare(&mut self, digest: &str) -> Result<String> {
        let artifact = self
            .config
            .artifacts
            .get(digest)
            .context("artifact is not installed/approved")?
            .clone();
        artifact.validate()?;
        crate::artifact::validate_approved(digest, &artifact)?;
        let attempt = self.store.prepare(digest, now_ms()?)?;
        let id = attempt.id;
        if let Err(error) = self.prepare_runtime(&id, digest, &artifact).await {
            self.store.cancel(&id)?;
            if let Err(cleanup) = self.cleanup(&id).await {
                eprintln!("retained preparation {id}: {cleanup:#}");
            }
            return Err(error).context(format!("prepare failed; attempt {id}"));
        }
        Ok(id)
    }
    async fn prepare_runtime(&mut self, id: &str, digest: &str, artifact: &Artifact) -> Result<()> {
        let cg = cgroup_dir(id);
        fs::create_dir(&cg)?;
        for (file, value) in [
            ("memory.max", policy::MEMORY_MAX.to_string()),
            ("memory.swap.max", "0".into()),
            ("pids.max", policy::PIDS_MAX.to_string()),
            ("cpu.max", policy::CPU_MAX.into()),
            (
                "io.max",
                format!(
                    "{} rbps={} wbps={} riops={} wiops={}",
                    self.config.io_device,
                    policy::IO_RATE,
                    policy::IO_RATE,
                    policy::IO_OPS,
                    policy::IO_OPS
                ),
            ),
        ] {
            fs::write(cg.join(file), value)
                .with_context(|| format!("install cgroup policy {file}"))?;
        }
        let cgroup_id = fs::metadata(&cg)?.ino();
        let mut binding = Binding {
            boot_id: self.boot_id.clone(),
            cgroup_id,
            observer: None,
            snapshot: None,
            device_policy: None,
            ambiguous_create: false,
        };
        // Record retirement identity before registering an externally retained observer context.
        self.store
            .record_binding(id, &serde_json::to_string(&binding)?)?;
        let observer = observer::exchange(
            Path::new(OBSERVER_SOCKET),
            &self.observer_request("register", id, cgroup_id),
        )
        .await?;
        observer.check(None)?;
        binding.observer = Some(observer);
        self.store
            .record_binding(id, &serde_json::to_string(&binding)?)?;
        let broker = Path::new(BROKER_ROOT).join(id);
        fs::create_dir(&broker)?;
        fs::set_permissions(&broker, fs::Permissions::from_mode(0o711))?;
        let path = std::ffi::CString::new(broker.as_os_str().as_encoded_bytes())?;
        ensure!(
            unsafe { libc::chown(path.as_ptr(), self.config.server_uid, u32::MAX) } == 0,
            "broker directory ownership failed"
        );
        let spec = policy::fixed_spec(
            artifact.rootfs.to_str().context("rootfs UTF-8")?,
            broker.to_str().context("broker UTF-8")?,
            &cgroup_path(id),
            &artifact.argv,
        );
        self.containers
            .create(request(CreateContainerRequest {
                container: Some(Container {
                    id: id.into(),
                    image: digest.into(),
                    runtime: Some(Runtime {
                        name: "io.containerd.runc.v2".into(),
                        options: None,
                    }),
                    spec: Some(prost_types::Any {
                        type_url: "types.containerd.io/opencontainers/runtime-spec/1/Spec".into(),
                        value: serde_json::to_vec(&spec)?,
                    }),
                    ..Default::default()
                }),
            }))
            .await?;
        let output_dir = Path::new(STATE_ROOT).join(id);
        fs::create_dir(&output_dir)?;
        let mut handles = vec![];
        let mut paths = vec![];
        for name in ["stdout", "stderr"] {
            let fifo = output_dir.join(format!("{name}.fifo"));
            let log = output_dir.join(format!("{name}.log"));
            let path = std::ffi::CString::new(fifo.as_os_str().as_encoded_bytes())?;
            ensure!(
                unsafe { libc::mkfifo(path.as_ptr(), 0o600) } == 0,
                "FIFO creation failed"
            );
            handles.push(start_log_reader(&fifo, &log)?);
            paths.push(fifo);
        }
        self.logs.insert(id.into(), handles);
        binding.ambiguous_create = true;
        self.store
            .record_binding(id, &serde_json::to_string(&binding)?)?;
        let created = self
            .tasks
            .create(request(CreateTaskRequest {
                container_id: id.into(),
                stdout: paths[0].to_string_lossy().into(),
                stderr: paths[1].to_string_lossy().into(),
                ..Default::default()
            }))
            .await?
            .into_inner();
        binding.ambiguous_create = false;
        let pidfd = unsafe { libc::syscall(libc::SYS_pidfd_open, created.pid, 0) };
        ensure!(pidfd >= 0, "pidfd unavailable");
        self.pidfds
            .insert(id.into(), unsafe { OwnedFd::from_raw_fd(pidfd as i32) });
        self.store
            .record_binding(id, &serde_json::to_string(&binding)?)?;
        // runc's setup needs mknod; constrain the completed, still-paused task before admission.
        binding.device_policy = Some(crate::device_policy::install(&cg, cgroup_id)?);
        self.store
            .record_binding(id, &serde_json::to_string(&binding)?)?;
        let snapshot = policy::snapshot(created.pid, &cgroup_path(id), &cg)?;
        binding.snapshot = Some(snapshot);
        binding.verify(
            binding.snapshot.as_ref().context("unverified task")?,
            &self.boot_id,
            fs::metadata(&cg)?.ino(),
            &cgroup_path(id),
            &self.config.io_device,
        )?;
        let task = self
            .tasks
            .get(request(GetRequest {
                container_id: id.into(),
                exec_id: String::new(),
            }))
            .await?
            .into_inner()
            .process
            .context("task absent")?;
        ensure!(
            task.pid == created.pid && task.status == 1,
            "task executed before verification"
        );
        self.store
            .mark_prepared(id, &serde_json::to_string(&binding)?)?;
        Ok(())
    }
    async fn start(&mut self, id: &str) -> Result<()> {
        let a = self.store.inspect(id)?.attempt;
        let artifact = self
            .config
            .artifacts
            .get(&a.artifact_digest)
            .context("artifact approval missing")?;
        crate::artifact::validate_approved(&a.artifact_digest, artifact)?;
        ensure!(a.state == "prepared", "attempt is not prepared");
        let verified: Result<Binding> = (|| {
            let binding: Binding =
                serde_json::from_str(a.binding.as_deref().context("missing binding")?)?;
            let expected = binding.snapshot.as_ref().context("unverified task")?;
            let current = policy::snapshot(expected.pid, &cgroup_path(id), &cgroup_dir(id))?;
            binding.verify(
                &current,
                &self.boot_id,
                fs::metadata(cgroup_dir(id))?.ino(),
                &cgroup_path(id),
                &self.config.io_device,
            )?;
            Ok(binding)
        })();
        let binding = match verified {
            Ok(binding) => binding,
            Err(error) => {
                self.store.cancel(id)?;
                if let Err(cleanup) = self.cleanup(id).await {
                    eprintln!("retained failed start {id}: {cleanup:#}");
                }
                return Err(error).context(format!("start verification failed; attempt {id}"));
            }
        };
        let health = observer::exchange(
            Path::new(OBSERVER_SOCKET),
            &self.observer_request("health", id, binding.cgroup_id),
        )
        .await?;
        health.check(Some(
            &binding
                .observer
                .as_ref()
                .context("observer was not verified")?
                .collector_epoch,
        ))?;
        let socket = Path::new(BROKER_ROOT).join(id).join("broker.sock");
        use std::os::unix::fs::FileTypeExt;
        ensure!(
            fs::symlink_metadata(socket)?.file_type().is_socket(),
            "per-attempt broker not ready"
        );
        self.store.start(id, now_ms()?)?;
        if let Err(error) = self
            .tasks
            .start(request(StartRequest {
                container_id: id.into(),
                exec_id: String::new(),
            }))
            .await
        {
            self.store.cancel(id)?;
            let _ = self.cleanup(id).await;
            return Err(error.into());
        }
        Ok(())
    }
    pub async fn cleanup(&mut self, id: &str) -> Result<()> {
        ensure!(crate::store::valid_id(id), "invalid attempt id");
        let a = self.store.inspect(id)?.attempt;
        let binding = a
            .binding
            .as_deref()
            .map(serde_json::from_str::<Binding>)
            .transpose()?;
        let cg = cgroup_dir(id);
        let task = match self
            .tasks
            .get(request(GetRequest {
                container_id: id.into(),
                exec_id: String::new(),
            }))
            .await
        {
            Ok(response) => response.into_inner().process,
            Err(error) if error.code() == tonic::Code::NotFound => None,
            Err(error) => return Err(error).context("cleanup: containerd Tasks.Get"),
        };
        if binding.as_ref().is_some_and(|b| b.ambiguous_create) && task.is_none() {
            bail!("create outcome unknown; reservation quarantined");
        }
        if cg.exists() {
            fs::write(cg.join("cgroup.kill"), "1").context("cleanup: kill descendants")?;
            let until = tokio::time::Instant::now() + Duration::from_secs(2);
            while fs::read_to_string(cg.join("cgroup.events"))?
                .lines()
                .any(|s| s == "populated 1")
            {
                ensure!(
                    tokio::time::Instant::now() < until,
                    "descendants remain; capacity retained"
                );
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            let observer = if let Some(binding) = &binding {
                observer::exchange(
                    Path::new(OBSERVER_SOCKET),
                    &self.observer_request("health", id, binding.cgroup_id),
                )
                .await
                .ok()
            } else {
                None
            };
            let facts = RuntimeFacts {
                resources: evidence::capture_resources(&cg, now_ms()?),
                observer_health_unavailable: observer.is_none(),
                observer,
            };
            self.store
                .record_runtime_evidence(id, &serde_json::to_string(&facts)?)?;
        }
        if task.is_some() {
            match self
                .tasks
                .delete(request(DeleteTaskRequest {
                    container_id: id.into(),
                }))
                .await
            {
                Ok(_) => {}
                Err(e) if e.code() == tonic::Code::NotFound => {}
                Err(e) => return Err(e).context("cleanup: containerd Tasks.Delete"),
            }
        }
        match self
            .containers
            .delete(request(DeleteContainerRequest { id: id.into() }))
            .await
        {
            Ok(_) => {}
            Err(e) if e.code() == tonic::Code::NotFound => {}
            Err(e) => return Err(e).context("cleanup: containerd Containers.Delete"),
        }
        if let Some(captures) = self.logs.get_mut(id) {
            for capture in captures.iter_mut() {
                capture.keepalive.take();
            }
            let until = tokio::time::Instant::now() + Duration::from_secs(2);
            while captures.iter().any(|capture| !capture.task.is_finished()) {
                ensure!(
                    tokio::time::Instant::now() < until,
                    "log writer still draining; capacity retained"
                );
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        }
        if let Some(captures) = self.logs.remove(id) {
            for capture in captures {
                if !matches!(capture.task.await, Ok(Ok(()))) {
                    self.store.record_gap(id, "log_incomplete")?;
                }
            }
        }
        self.pidfds.remove(id);
        if let Some(binding) = binding {
            observer::exchange(
                Path::new(OBSERVER_SOCKET),
                &self.observer_request("unregister", id, binding.cgroup_id),
            )
            .await?;
        }
        if cg.exists() {
            fs::remove_dir(cg).context("cleanup: remove empty cgroup")?;
        }
        let broker = Path::new(BROKER_ROOT).join(id);
        if broker.exists() {
            for entry in fs::read_dir(&broker)? {
                let entry = entry?;
                ensure!(!entry.file_type()?.is_dir(), "unexpected broker directory");
                fs::remove_file(entry.path())?;
            }
            fs::remove_dir(broker)?;
        }
        self.store.mark_reaped(id)?;
        Ok(())
    }
    pub async fn tick(&mut self) -> Result<()> {
        let now = now_ms()?;
        for attempt in self.store.attempts()? {
            if attempt.state == "reaped" {
                continue;
            }
            if attempt.state == "running" {
                let result = self
                    .tasks
                    .get(request(GetRequest {
                        container_id: attempt.id.clone(),
                        exec_id: String::new(),
                    }))
                    .await;
                if let Some(process) = result
                    .as_ref()
                    .ok()
                    .and_then(|r| r.get_ref().process.as_ref())
                {
                    if process.status == 3 {
                        self.store
                            .retire(&attempt.id, &format!("exited:{}", process.exit_status))?;
                    }
                }
                if let Some(binding) = attempt
                    .binding
                    .as_deref()
                    .and_then(|v| serde_json::from_str::<Binding>(v).ok())
                {
                    let health = observer::exchange(
                        Path::new(OBSERVER_SOCKET),
                        &self.observer_request("health", &attempt.id, binding.cgroup_id),
                    )
                    .await;
                    if health
                        .and_then(|h| {
                            h.check(Some(
                                &binding
                                    .observer
                                    .as_ref()
                                    .context("observer was not verified")?
                                    .collector_epoch,
                            ))
                        })
                        .is_err()
                    {
                        self.store.record_gap(&attempt.id, "observer_unavailable")?;
                    }
                }
            }
            if attempt.deadline_ms <= now {
                self.store.cancel(&attempt.id)?;
            }
            if self.store.inspect(&attempt.id)?.attempt.state == "retiring" {
                if let Err(error) = self.cleanup(&attempt.id).await {
                    eprintln!("cleanup pending {}: {error:#}", attempt.id);
                }
            }
        }
        Ok(())
    }
}
struct LogCapture {
    task: tokio::task::JoinHandle<Result<()>>,
    keepalive: Option<fs::File>,
}
fn start_log_reader(fifo: &Path, log: &Path) -> Result<LogCapture> {
    use std::os::{fd::AsRawFd, unix::fs::OpenOptionsExt};
    let pipe = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(fifo)?;
    let keepalive = fs::OpenOptions::new()
        .write(true)
        .custom_flags(libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(fifo)?;
    let fd = tokio::io::unix::AsyncFd::new(pipe)?;
    let output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(log)?;
    let mut output = tokio::fs::File::from_std(output);
    let loss = log.with_extension("truncated");
    let task = tokio::spawn(async move {
        use tokio::io::AsyncWriteExt;
        let mut retained = 0usize;
        let mut dropped = false;
        let mut buf = [0u8; 8192];
        loop {
            let mut ready = fd.readable().await?;
            match ready.try_io(|inner| {
                let n =
                    unsafe { libc::read(inner.as_raw_fd(), buf.as_mut_ptr().cast(), buf.len()) };
                if n < 0 {
                    Err(std::io::Error::last_os_error())
                } else {
                    Ok(n as usize)
                }
            }) {
                Ok(Ok(0)) => break,
                Ok(Ok(n)) => {
                    let keep = n.min(524288 - retained);
                    output.write_all(&buf[..keep]).await?;
                    retained += keep;
                    if keep < n && !dropped {
                        tokio::fs::write(
                            &loss,
                            b"output exceeded retained log cap; later bytes discarded\n",
                        )
                        .await?;
                        dropped = true;
                    }
                }
                Ok(Err(error)) => return Err(error.into()),
                Err(_) => continue,
            }
        }
        output.sync_all().await?;
        Ok(())
    });
    Ok(LogCapture {
        task,
        keepalive: Some(keepalive),
    })
}

pub fn lock_service(path: &Path) -> Result<fs::File> {
    use std::{os::fd::AsRawFd, os::unix::fs::OpenOptionsExt};
    let file = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let m = file.metadata()?;
    ensure!(
        m.uid() == unsafe { libc::geteuid() } && m.mode() & 0o077 == 0,
        "invalid service lock owner/mode"
    );
    ensure!(
        unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0,
        "service already owns this state directory"
    );
    Ok(file)
}

#[cfg(test)]
mod binding_tests {
    use super::*;

    fn binding() -> Binding {
        let snapshot: Snapshot = serde_json::from_value(serde_json::json!({
            "pid":123,"start_ticks":456,"cgroup":"/actryn/test",
            "uid":65532,"gid":65532,"capabilities":0,"no_new_privileges":true,
            "seccomp_mode":2,"private_namespaces":true,"network_routes":0,
            "memory_max":268435456,"pids_max":64,"cpu_max":"50000 100000",
            "io_max":"8:0 rbps=1048576 wbps=1048576 riops=128 wiops=128",
            "device_programs":[7,42,99],"device_programs_direct":[7,42],
            "device_attach_flags":2,"unexpected_mounts":[],"root_readonly":true
        }))
        .unwrap();
        Binding {
            boot_id: "boot".into(),
            cgroup_id: 789,
            observer: None,
            snapshot: Some(snapshot),
            ambiguous_create: false,
            device_policy: Some(crate::device_policy::Proof {
                program_id: 42,
                instruction_sha256: crate::device_policy::instruction_sha256(),
            }),
        }
    }

    fn verify(binding: &Binding, current: &Snapshot) -> Result<()> {
        binding.verify(current, "boot", 789, "/actryn/test", "8:0")
    }

    #[test]
    fn fixed_policy_and_prepared_inventories_must_survive_until_start() {
        let good = binding();
        let current = good.snapshot.as_ref().unwrap();
        verify(&good, current).unwrap();
        for fault in [
            "proof",
            "hash",
            "id",
            "direct",
            "effective",
            "direct_added",
            "effective_added",
            "flags",
            "pid",
            "start",
            "boot",
            "cgroup",
            "ambiguous",
        ] {
            let mut changed = good.clone();
            let mut current = current.clone();
            match fault {
                "proof" => changed.device_policy = None,
                "hash" => {
                    changed.device_policy.as_mut().unwrap().instruction_sha256 = "0".repeat(64)
                }
                "id" => changed.device_policy.as_mut().unwrap().program_id = 99,
                "direct" => current.device_programs_direct = vec![7],
                "effective" => current.device_programs = vec![7, 99],
                "direct_added" => current.device_programs_direct = vec![7, 42, 99],
                "effective_added" => current.device_programs.push(100),
                "flags" => current.device_attach_flags = 0,
                "pid" => current.pid += 1,
                "start" => current.start_ticks += 1,
                "boot" => changed.boot_id = "another-boot".into(),
                "cgroup" => changed.cgroup_id += 1,
                "ambiguous" => changed.ambiguous_create = true,
                _ => unreachable!(),
            }
            assert!(
                verify(&changed, &current).is_err(),
                "accepted changed {fault}"
            );
        }
    }

    #[test]
    fn historical_binding_decodes_for_cleanup_without_becoming_startable() {
        let good = binding();
        let mut old = serde_json::to_value(&good).unwrap();
        old.as_object_mut().unwrap().remove("device_policy");
        let snapshot = old["snapshot"].as_object_mut().unwrap();
        snapshot.remove("device_programs_direct");
        snapshot.remove("device_attach_flags");
        let decoded: Binding = serde_json::from_value(old).unwrap();
        assert!(decoded.device_policy.is_none());
        assert!(decoded
            .snapshot
            .as_ref()
            .unwrap()
            .device_programs_direct
            .is_empty());
        assert!(verify(&decoded, good.snapshot.as_ref().unwrap()).is_err());
    }
}
