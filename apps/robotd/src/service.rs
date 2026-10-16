use crate::{enrollment, storage};
use anyhow::{bail, ensure, Context, Result};
use authority_client::boottime_ns;
use robot_rpc::{
    wire::{self, request::Command, response::Result as Reply},
    ClockGuard, PeerLifetime, Policy, PrincipalPolicy, Scope, Session,
};
use robot_runtime::{Binding, Engine, Target};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex, RwLock,
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{UnixListener, UnixStream},
    sync::Semaphore,
};

const NS: u64 = 1_000_000_000;
const RUN: &str = "/run/actryn-robot";
pub(crate) fn wall_ns() -> Result<u64> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_nanos()
        .try_into()?)
}
fn fixed<const N: usize>(bytes: &[u8]) -> Result<[u8; N]> {
    bytes
        .try_into()
        .map_err(|_| anyhow::anyhow!("identity size"))
}
fn checked_clock(
    clock: &Mutex<ClockGuard>,
    sample: impl FnOnce() -> Result<(u64, u64)>,
) -> Result<(u64, u64)> {
    let mut clock = clock.lock().unwrap();
    let (wall, boot) = sample()?;
    clock.check(wall, boot)?;
    Ok((wall, boot))
}

fn publish_clock_checkpoint(
    durable: &AtomicU64,
    completed: u64,
    missed_deadline: impl FnOnce(u64),
) {
    // The normal writer and explicit recovery serialize on clock_writer. A late
    // successful write is durable evidence, but cannot erase the missed interval
    // if this thread resumes before the watchdog. Latch/close before publishing
    // the new frontier; only explicit local Recover may restore health.
    let age = completed.saturating_sub(durable.load(Ordering::Acquire));
    if age > 10 * NS {
        missed_deadline(age);
    }
    durable.store(completed, Ordering::Release);
}
fn report(value: impl serde::Serialize) -> Result<Reply> {
    let value = serde_json::to_value(value)?;
    let value = if value.is_object() {
        value
    } else {
        json!({"result":value})
    };
    Ok(Reply::Report(wire::Report {
        json: serde_json::to_vec(&value)?,
    }))
}
struct Gateway {
    peer: Arc<PeerLifetime>,
    heartbeat: u64,
    generation: u64,
}
#[derive(Clone)]
struct Authenticated {
    identity: Session,
    gateway_generation: u64,
    identity_generation: u64,
}
pub struct State {
    root: PathBuf,
    engine: Arc<Engine>,
    epoch: [u8; 16],
    identity: RwLock<Option<enrollment::Identity>>,
    identity_error: RwLock<Option<String>>,
    identity_generation: AtomicU64,
    policy: RwLock<Policy>,
    sessions: Mutex<BTreeMap<String, Authenticated>>,
    binding: RwLock<Option<Binding>>,
    binding_gateway: AtomicU64,
    binding_identity: AtomicU64,
    gateway: Mutex<Option<Gateway>>,
    gateway_generation: AtomicU64,
    clock: Mutex<ClockGuard>,
    clock_writer: Mutex<()>,
    clock_ok: AtomicBool,
    clock_error: RwLock<Option<String>>,
    durable_clock_boot: AtomicU64,
    floor: AtomicU64,
    maintenance: Arc<Semaphore>,
    revocation_writer: Arc<Semaphore>,
    exports: Arc<Semaphore>,
    requests: Arc<Semaphore>,
    principals: Mutex<BTreeMap<String, Arc<Semaphore>>>,
}

fn listener(name: &str, uid: u32) -> Result<UnixListener> {
    let path = Path::new(RUN).join(name);
    if path.try_exists()? {
        fs::remove_file(&path)?;
    }
    let listener = UnixListener::bind(&path)?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
    let c = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())?;
    ensure!(
        unsafe { libc::chown(c.as_ptr(), uid, 0) } == 0,
        "socket owner"
    );
    Ok(listener)
}
fn response(epoch: [u8; 16], request_id: Vec<u8>, result: Result<Reply>) -> wire::Response {
    wire::Response {
        version: robot_rpc::VERSION,
        request_id,
        robot_epoch: epoch.to_vec(),
        result: Some(result.unwrap_or_else(|e| {
            Reply::Failure(wire::Failure {
                code: wire::failure::Code::OutcomeUnknown as i32,
                message: e.to_string().chars().take(512).collect(),
            })
        })),
    }
}
fn maintenance(command: Option<&Command>) -> bool {
    matches!(
        command,
        Some(
            Command::Prepare(_)
                | Command::Rearm(_)
                | Command::Grant(_)
                | Command::Activate(_)
                | Command::EnrollRequest(_)
                | Command::EnrollInstall(_)
                | Command::InstallPrincipal(_)
                | Command::Recover(_)
        )
    )
}
async fn dispatch(
    state: Arc<State>,
    request: wire::Request,
    session: Option<Authenticated>,
    closure: bool,
) -> wire::Response {
    let id = request.request_id.clone();
    if let Some(Command::RevokePrincipal(p)) = request.command.as_ref() {
        let result = (|| -> Result<()> {
            request.validate()?;
            ensure!(
                session.is_none() && request.robot_epoch == state.epoch,
                "local current-epoch revocation required"
            );
            state.revoke_principal(&p.principal)
        })();
        if let Err(e) = result {
            return response(state.epoch, id, Err(e));
        }
    }
    let writer = if matches!(request.command, Some(Command::RevokePrincipal(_))) {
        Some(state.revocation_writer.clone())
    } else if matches!(request.command, Some(Command::EvidenceRead(_))) {
        Some(state.exports.clone())
    } else if maintenance(request.command.as_ref()) {
        Some(state.maintenance.clone())
    } else {
        None
    };
    let permit = if let Some(writer) = writer {
        match writer.try_acquire_owned() {
            Ok(p) => Some(p),
            Err(_) => {
                return response(
                    state.epoch,
                    id,
                    Err(anyhow::anyhow!("maintenance capacity")),
                )
            }
        }
    } else {
        None
    };
    let epoch = state.epoch;
    let result = tokio::task::spawn_blocking(move || {
        let _permit = permit;
        state.handle(request, session.as_ref(), closure)
    })
    .await;
    response(
        epoch,
        id,
        result.map_err(anyhow::Error::from).and_then(|r| r),
    )
}
async fn local(
    state: Arc<State>,
    mut stream: UnixStream,
    operator: u32,
    closure: bool,
) -> Result<()> {
    let uid = stream.peer_cred()?.uid();
    ensure!(uid == 0 || uid == operator, "local operator identity");
    let _queued = if closure {
        None
    } else {
        Some(state.requests.clone().try_acquire_owned()?)
    };
    let request = tokio::time::timeout(
        Duration::from_secs(2),
        robot_rpc::read_message_limit::<wire::Request>(
            &mut stream,
            if closure {
                4096
            } else {
                robot_rpc::MAX_MESSAGE
            },
        ),
    )
    .await??;
    request.validate()?;
    let response = dispatch(state, request, None, closure).await;
    tokio::time::timeout(
        Duration::from_secs(2),
        robot_rpc::write_message(&mut stream, &response),
    )
    .await??;
    Ok(())
}
async fn control(state: Arc<State>, mut stream: UnixStream, uid: u32) -> Result<()> {
    let peer = Arc::new(PeerLifetime::capture(&stream, uid)?);
    let mut hello = [0; 10];
    tokio::time::timeout(Duration::from_secs(2), stream.read_exact(&mut hello)).await??;
    ensure!(&hello == b"ACTRYN-GW1", "gateway control handshake");
    let generation = state
        .gateway_generation
        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |v| v.checked_add(1))
        .map_err(|_| anyhow::anyhow!("gateway generation exhausted"))?;
    {
        let mut gateway = state.gateway.lock().unwrap();
        ensure!(gateway.is_none(), "gateway already registered");
        *gateway = Some(Gateway {
            peer,
            heartbeat: boottime_ns()?,
            generation,
        });
    }
    let outcome = async {
        stream.write_all(&[1]).await?;
        loop {
            let mut byte = [0];
            tokio::time::timeout(Duration::from_secs(3), stream.read_exact(&mut byte)).await??;
            ensure!(byte == [b'H'], "gateway heartbeat");
            let mut current = state.gateway.lock().unwrap();
            let gateway = current.as_mut().context("gateway retired")?;
            ensure!(
                gateway.generation == generation && gateway.peer.alive()?,
                "gateway lifetime ended"
            );
            gateway.heartbeat = boottime_ns()?;
        }
        #[allow(unreachable_code)]
        Ok::<(), anyhow::Error>(())
    }
    .await;
    {
        let mut gateway = state.gateway.lock().unwrap();
        if gateway.as_ref().is_some_and(|g| g.generation == generation) {
            *gateway = None;
        }
    }
    state.close();
    state.sessions.lock().unwrap().clear();
    outcome
}
async fn remote(state: Arc<State>, stream: UnixStream, handshakes: Arc<Semaphore>) -> Result<()> {
    let generation = {
        let gateway = state.gateway.lock().unwrap();
        let g = gateway.as_ref().context("gateway unavailable")?;
        ensure!(g.peer.matches(&stream)?, "relay from another process");
        g.generation
    };
    let permit = handshakes.try_acquire_owned()?;
    let (tls, valid_until, identity_generation) = {
        let identity = state.identity.read().unwrap();
        let identity = identity.as_ref().context("device enrollment required")?;
        (
            identity.tls.clone(),
            identity.valid_until_wall_ns,
            state.identity_generation.load(Ordering::Acquire),
        )
    };
    let mut stream = tokio::time::timeout(
        Duration::from_secs(3),
        tokio_rustls::TlsAcceptor::from(tls).accept(stream),
    )
    .await??;
    ensure!(
        stream.get_ref().1.alpn_protocol() == Some(robot_rpc::ALPN),
        "RPC ALPN"
    );
    let (wall, now) = state.trusted_clock()?;
    let leaf = stream
        .get_ref()
        .1
        .peer_certificates()
        .and_then(|c| c.first())
        .context("client identity missing")?;
    let mut session = Authenticated {
        identity: state
            .policy
            .read()
            .unwrap()
            .authenticated(leaf, wall, now)?,
        gateway_generation: generation,
        identity_generation,
    };
    for certificate in stream
        .get_ref()
        .1
        .peer_certificates()
        .context("client chain missing")?
    {
        let expiry = robot_rpc::certificate_valid_until(certificate, wall)?;
        session.identity.deadline_ns = session.identity.deadline_ns.min(
            now.checked_add(expiry - wall)
                .context("chain deadline overflow")?,
        );
    }
    ensure!(wall < valid_until, "device certificate expired");
    session.identity.deadline_ns = session.identity.deadline_ns.min(
        now.checked_add(valid_until - wall)
            .context("certificate deadline overflow")?,
    );
    let principal_slots = {
        let mut principals = state.principals.lock().unwrap();
        ensure!(
            principals.contains_key(&session.identity.principal) || principals.len() < 128,
            "principal request capacity"
        );
        principals
            .entry(session.identity.principal.clone())
            .or_insert_with(|| Arc::new(Semaphore::new(4)))
            .clone()
    };
    state.remember_session(&session)?;
    drop(permit);
    loop {
        ensure!(
            state
                .gateway
                .lock()
                .unwrap()
                .as_ref()
                .is_some_and(|g| g.generation == generation),
            "gateway generation retired"
        );
        state.authorize(&session, Scope::Read)?;
        // Ordinary local and remote requests share three 64 KiB slots. Two
        // independent 4 KiB local closure slots stay below the 256 KiB ceiling.
        let queued = state.requests.clone().try_acquire_owned()?;
        let principal = principal_slots.clone().try_acquire_owned()?;
        let request = tokio::time::timeout(
            Duration::from_secs(2),
            robot_rpc::read_message::<wire::Request>(&mut stream),
        )
        .await??;
        request.validate()?;
        state.authorize(&session, request.remote_scope()?)?;
        let response = dispatch(state.clone(), request, Some(session.clone()), false).await;
        // Storage work can outlive the session that requested it.
        state.authorize(&session, Scope::Read)?;
        tokio::time::timeout(
            Duration::from_secs(2),
            robot_rpc::write_message(&mut stream, &response),
        )
        .await??;
        drop(principal);
        drop(queued);
    }
}
pub async fn serve(state: Arc<State>, operator: u32, gateway_uid: u32) -> Result<()> {
    let run = fs::symlink_metadata(RUN)?;
    use std::os::unix::fs::MetadataExt;
    ensure!(
        run.is_dir() && run.uid() == 0 && run.mode() & 0o022 == 0,
        "protected runtime directory required"
    );
    let operator_socket = listener("operator.sock", operator)?;
    let closure_socket = listener("closure.sock", operator)?;
    let control_socket = listener("gateway-control.sock", gateway_uid)?;
    let relay_socket = listener("relay.sock", gateway_uid)?;
    let connections = Arc::new(Semaphore::new(8));
    let handshakes = Arc::new(Semaphore::new(2));
    let locals = Arc::new(Semaphore::new(4));
    let closures = Arc::new(Semaphore::new(2));
    let controls = Arc::new(Semaphore::new(1));
    let tick = state.clone();
    std::thread::spawn(move || {
        let mut previous = None;
        loop {
            let now = boottime_ns().unwrap_or(u64::MAX);
            if tick.trusted_clock().is_err()
                || (!tick.bound_gateway_live(now) && tick.binding.read().unwrap().is_some())
            {
                tick.close();
            }
            if let Err(error) = tick.engine.tick() {
                let error = error.to_string();
                if previous.as_ref() != Some(&error) {
                    eprintln!("runtime inhibited: {error}");
                    previous = Some(error);
                }
            }
            std::thread::sleep(Duration::from_millis(25));
        }
    });
    let checkpoint = state.clone();
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_secs(5));
        let _write = checkpoint.clock_writer.lock().unwrap();
        if let Ok((wall, _)) = checkpoint.trusted_clock() {
            let wall = wall.max(checkpoint.floor.load(Ordering::Acquire));
            match storage::replace(
                &checkpoint.root.join("clock.json"),
                &serde_json::to_vec(&wall).unwrap(),
            ) {
                Ok(()) => {
                    checkpoint.floor.store(wall, Ordering::Release);
                    match boottime_ns() {
                        Ok(completed) => publish_clock_checkpoint(
                            &checkpoint.durable_clock_boot,
                            completed,
                            |age| {
                                checkpoint.clock_fault(format!(
                                    "clock checkpoint completion age {age} ns exceeds 10000000000 ns"
                                ));
                            },
                        ),
                        Err(error) => checkpoint.clock_fault(format!(
                            "clock checkpoint completion time unavailable: {error}"
                        )),
                    }
                }
                Err(error) => {
                    checkpoint.clock_fault(format!("clock checkpoint persistence: {error}"));
                }
            }
        }
    });
    notify_ready()?;
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    loop {
        tokio::select! {
            _=term.recv()=>{state.close();return Ok(());},
            result=operator_socket.accept()=>{let(stream,_)=result?;if let Ok(p)=locals.clone().try_acquire_owned(){let s=state.clone();tokio::spawn(async move{let _permit=p;let _=local(s,stream,operator,false).await;});}},
            result=closure_socket.accept()=>{let(stream,_)=result?;if let Ok(p)=closures.clone().try_acquire_owned(){let s=state.clone();tokio::spawn(async move{let _permit=p;let _=local(s,stream,operator,true).await;});}},
            result=control_socket.accept()=>{let(stream,_)=result?;if let Ok(p)=controls.clone().try_acquire_owned(){let s=state.clone();tokio::spawn(async move{let _permit=p;let _=control(s,stream,gateway_uid).await;});}},
            result=relay_socket.accept()=>{let(stream,_)=result?;if let Ok(p)=connections.clone().try_acquire_owned(){let s=state.clone();let h=handshakes.clone();tokio::spawn(async move{let _permit=p;let _=remote(s,stream,h).await;});}},
        }
    }
}
fn notify_ready() -> Result<()> {
    use std::os::{
        linux::net::SocketAddrExt,
        unix::net::{SocketAddr, UnixDatagram},
    };
    if let Some(path) = std::env::var_os("NOTIFY_SOCKET") {
        let b = path.as_encoded_bytes();
        let address = if b.first() == Some(&b'@') {
            SocketAddr::from_abstract_name(&b[1..])?
        } else {
            SocketAddr::from_pathname(&path)?
        };
        let s = UnixDatagram::unbound()?;
        s.set_write_timeout(Some(Duration::from_secs(1)))?;
        s.connect_addr(&address)?;
        ensure!(s.send(b"READY=1")? == 7, "readiness send");
    }
    Ok(())
}
impl State {
    pub fn open(root: PathBuf, engine: Arc<Engine>) -> Result<Self> {
        let now = boottime_ns()?;
        let wall = wall_ns()?;
        let path = root.join("clock.json");
        let floor = if path.try_exists()? {
            serde_json::from_slice::<u64>(&robot_rpc::read_protected(&path, 32, true)?)?
        } else {
            0
        };
        let clock = ClockGuard::new(wall, now, floor)?;
        storage::replace(&path, &serde_json::to_vec(&wall)?)?;
        let p = root.join("policy.json");
        let mut policy: Policy = if p.try_exists()? {
            serde_json::from_slice(&robot_rpc::read_protected(&p, 65536, true)?)?
        } else {
            Policy::default()
        };
        let revoked = fs::read_dir(root.join("revoked"))?
            .take(130)
            .collect::<std::io::Result<Vec<_>>>()?;
        ensure!(revoked.len() <= 129, "revocation retention capacity");
        for entry in revoked {
            if entry.file_name().as_encoded_bytes().ends_with(b".pending") {
                continue;
            }
            let name: String =
                serde_json::from_slice(&robot_rpc::read_protected(&entry.path(), 256, true)?)?;
            ensure!(
                robot_rpc::valid_principal(&name)
                    && entry.file_name() == format!("{name}.json").as_str(),
                "invalid retained revocation"
            );
            policy.revoked.insert(name);
        }
        policy.validate()?;
        let (identity, identity_error) = match enrollment::load(&root.join("identity"), wall) {
            Ok(v) => (v, None),
            Err(e) => (None, Some(e.to_string())),
        };
        Ok(Self {
            root,
            engine,
            epoch: robot_rpc::random_id()?,
            identity: RwLock::new(identity),
            identity_error: RwLock::new(identity_error),
            identity_generation: AtomicU64::new(1),
            policy: RwLock::new(policy),
            sessions: Mutex::new(BTreeMap::new()),
            binding: RwLock::new(None),
            binding_gateway: AtomicU64::new(0),
            binding_identity: AtomicU64::new(0),
            gateway: Mutex::new(None),
            gateway_generation: AtomicU64::new(1),
            clock: Mutex::new(clock),
            clock_writer: Mutex::new(()),
            clock_ok: AtomicBool::new(true),
            clock_error: RwLock::new(None),
            durable_clock_boot: AtomicU64::new(now),
            floor: AtomicU64::new(wall),
            maintenance: Arc::new(Semaphore::new(1)),
            revocation_writer: Arc::new(Semaphore::new(1)),
            exports: Arc::new(Semaphore::new(1)),
            requests: Arc::new(Semaphore::new(3)),
            principals: Mutex::new(BTreeMap::new()),
        })
    }
    fn close(&self) {
        let _ = self.engine.revoke();
    }
    fn revoke_principal(&self, name: &str) -> Result<()> {
        let mut policy = self.policy.write().unwrap();
        ensure!(
            policy.revoked.contains(name)
                || policy.certificates.values().any(|p| p.principal == name),
            "principal is not installed"
        );
        if !policy.revoked.contains(name) && policy.revoked.len() >= 128 {
            drop(policy);
            self.close();
            self.clock_ok.store(false, Ordering::Release);
            bail!("revocation capacity exhausted; authority inhibited");
        }
        policy.revoked.insert(name.to_owned());
        drop(policy);
        self.sessions.lock().unwrap().remove(name);
        use sha2::Digest;
        let id: [u8; 32] = sha2::Sha256::digest(name.as_bytes()).into();
        if self
            .binding
            .read()
            .unwrap()
            .as_ref()
            .is_some_and(|b| b.principal == id)
        {
            self.close();
        }
        Ok(())
    }
    fn trusted_clock(&self) -> Result<(u64, u64)> {
        ensure!(
            self.clock_ok.load(Ordering::Acquire),
            "clock unhealthy; local recovery required"
        );
        let sampled = checked_clock(&self.clock, || {
            let now = boottime_ns()?;
            Ok((wall_ns()?, now))
        });
        let (wall, now) = match sampled {
            Ok(value) => value,
            Err(error) => {
                self.clock_fault(format!("clock continuity: {error}"));
                return Err(error);
            }
        };
        let age = now.saturating_sub(self.durable_clock_boot.load(Ordering::Acquire));
        if age > 10 * NS {
            self.clock_fault(format!(
                "clock checkpoint age {age} ns exceeds 10000000000 ns"
            ));
            bail!("clock durability lost");
        }
        // A concurrent late writer can publish a new frontier only after it has
        // latched unhealthy. Do not let that fresh timestamp mask the latch for
        // a reader which passed the initial health check before publication.
        ensure!(
            self.clock_ok.load(Ordering::Acquire),
            "clock unhealthy; local recovery required"
        );
        Ok((wall, now))
    }
    fn clock_fault(&self, reason: String) {
        self.clock_ok.store(false, Ordering::Release);
        self.close();
        let mut saved = self.clock_error.write().unwrap();
        if saved.is_none() {
            eprintln!("clock inhibited: {reason}");
            *saved = Some(reason);
        }
    }
    fn gateway_live(&self, now: u64) -> bool {
        self.gateway.lock().unwrap().as_ref().is_some_and(|g| {
            now.saturating_sub(g.heartbeat) < 3 * NS && g.peer.alive().unwrap_or(false)
        })
    }
    fn bound_gateway_live(&self, now: u64) -> bool {
        self.gateway_live(now)
            && self.binding_identity.load(Ordering::Acquire)
                == self.identity_generation.load(Ordering::Acquire)
            && self
                .gateway
                .lock()
                .unwrap()
                .as_ref()
                .is_some_and(|g| g.generation == self.binding_gateway.load(Ordering::Acquire))
    }
    fn authorize(&self, session: &Authenticated, scope: Scope) -> Result<()> {
        let (_, now) = self.trusted_clock()?;
        ensure!(self.gateway_live(now), "gateway lifetime unavailable");
        {
            let identity = self.identity.read().unwrap();
            ensure!(
                identity.is_some()
                    && session.identity_generation
                        == self.identity_generation.load(Ordering::Acquire),
                "device identity generation retired"
            );
        }
        ensure!(
            self.gateway
                .lock()
                .unwrap()
                .as_ref()
                .is_some_and(|g| g.generation == session.gateway_generation),
            "gateway generation retired"
        );
        session
            .identity
            .authorize(&self.policy.read().unwrap(), scope, now)
    }
    fn remember_session(&self, session: &Authenticated) -> Result<()> {
        let (_, now) = self.trusted_clock()?;
        // Keep retirement locks through publication so an old handshake cannot
        // overwrite a current session after identity/gateway replacement.
        let identity = self.identity.read().unwrap();
        ensure!(
            identity.is_some()
                && session.identity_generation == self.identity_generation.load(Ordering::Acquire),
            "device identity generation retired"
        );
        let gateway = self.gateway.lock().unwrap();
        let g = gateway.as_ref().context("gateway unavailable")?;
        ensure!(
            g.generation == session.gateway_generation
                && now.saturating_sub(g.heartbeat) < 3 * NS
                && g.peer.alive()?,
            "gateway generation retired"
        );
        let policy = self.policy.read().unwrap();
        session.identity.authorize(&policy, Scope::Read, now)?;
        let mut sessions = self.sessions.lock().unwrap();
        sessions.retain(|_, s| s.identity.deadline_ns > now);
        ensure!(
            sessions.contains_key(&session.identity.principal) || sessions.len() < 128,
            "session capacity"
        );
        sessions.insert(session.identity.principal.clone(), session.clone());
        Ok(())
    }
    fn binding(
        &self,
        handle: &wire::Handle,
        authentication: Option<&Authenticated>,
    ) -> Result<Binding> {
        let b = self
            .binding
            .read()
            .unwrap()
            .clone()
            .context("no active namespace")?;
        ensure!(
            handle.attempt == b.attempt && handle.namespace == b.namespace,
            "namespace/attempt mismatch"
        );
        ensure!(
            authentication.is_none_or(|s| s.identity.principal_id == b.principal
                && s.identity_generation == self.binding_identity.load(Ordering::Acquire)
                && s.gateway_generation == self.binding_gateway.load(Ordering::Acquire)),
            "principal mismatch"
        );
        Ok(b)
    }
    fn history(
        &self,
        handle: &wire::Handle,
        session: Option<&Session>,
    ) -> Result<robot_runtime::Historical> {
        let principal = if let Some(s) = session {
            s.principal_id
        } else {
            // The protected operator may inspect any retained local namespace.
            let name = handle
                .namespace
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>();
            let bytes = robot_rpc::read_protected(
                &self
                    .root
                    .join("runtime")
                    .join(format!("binding-{name}.json")),
                1024,
                true,
            )?;
            let value: Value = serde_json::from_slice(&bytes)?;
            serde_json::from_value(value["prepared"]["binding"]["principal"].clone())?
        };
        Ok(Engine::inspect(
            self.root.join("runtime"),
            principal,
            fixed(&handle.attempt)?,
            fixed(&handle.namespace)?,
            fixed(&handle.key)?,
        )?)
    }
    fn historical(&self, handle: &wire::Handle, session: Option<&Session>) -> Result<Reply> {
        report(self.history(handle, session)?)
    }
    fn inhibited(&self) -> Result<()> {
        let status = self.engine.status()?;
        ensure!(
            status.kernel.state == 0
                && matches!(status.kernel.operation_state, 0 | 4 | 5)
                && status.prepared.is_none(),
            "identity changes require inhibited and retired state"
        );
        Ok(())
    }
    fn handle(
        &self,
        request: wire::Request,
        authentication: Option<&Authenticated>,
        closure: bool,
    ) -> Result<Reply> {
        request.validate()?;
        let command = request.command.as_ref().unwrap();
        if closure {
            ensure!(
                matches!(
                    command,
                    Command::Cancel(_)
                        | Command::Revoke(_)
                        | Command::Retire(_)
                        | Command::RevokePrincipal(_)
                ),
                "reserved closure endpoint"
            );
        }
        if let Some(s) = authentication {
            self.authorize(s, request.remote_scope()?)?;
        }
        let session = authentication.map(|s| &s.identity);
        ensure!(
            request.robot_epoch == self.epoch
                || (request.robot_epoch.is_empty()
                    && matches!(
                        command,
                        Command::Describe(_)
                            | Command::EnrollRequest(_)
                            | Command::EnrollInstall(_)
                    )),
            "manager epoch changed; inspect before a new action"
        );
        match command {
            Command::Describe(_) => report(
                json!({"version":"0.0.1", "profile_sha256":robot_runtime::profile_digest(), "configuration_digest":robot_runtime::configuration_digest(), "physical_acceptance":false,"live_actuation":false,"clock_healthy":self.clock_ok.load(Ordering::Acquire),"clock_error":self.clock_error.read().unwrap().clone(),"identity":self.identity.read().unwrap().as_ref().map(enrollment::report),"identity_error":self.identity_error.read().unwrap().clone(),"runtime":self.engine.status()?}),
            ),
            Command::Observe(h) => {
                self.binding(h, authentication)?;
                let o = self.engine.observe()?;
                Ok(Reply::Observation(wire::Observation {
                    id: o.id,
                    acquired_earliest_ns: o.acquired_earliest_ns,
                    acquired_latest_ns: o.acquired_latest_ns,
                    valid_until_ns: o.valid_until_ns,
                    controller_ns: o.controller_ns,
                    left_ticks: o.left_encoder,
                    right_ticks: o.right_encoder,
                    simulated: true,
                    context_revision: 1,
                }))
            }
            Command::Propose(p) => {
                let h = p.handle.as_ref().unwrap();
                let b = self.binding(h, authentication)?;
                let t = p.target.as_ref().unwrap();
                report(self.engine.propose(
                    &b,
                    fixed(&h.key)?,
                    fixed(&p.parent_digest)?,
                    Target {
                        left_ticks: t.left_delta_ticks,
                        right_ticks: t.right_delta_ticks,
                        duration_ms: t.duration_ms,
                    },
                    p.observation_id,
                )?)
            }
            Command::Query(h) => match self.binding(h, authentication) {
                Ok(b) => report(
                    json!({"snapshot":self.engine.query(&b, fixed(&h.key)?)?,"live_authority":true}),
                ),
                Err(_) => self.historical(h, session),
            },
            Command::Cancel(h) => match self.binding(h, authentication) {
                Ok(b) => report(self.engine.cancel(&b, fixed(&h.key)?)?),
                Err(_) => self.historical(h, session),
            },
            Command::EvidenceRead(e) => {
                ensure!(
                    self.engine.status()?.prepared.is_none(),
                    "retire and recover before exporting capture"
                );
                let history = self.history(e.handle.as_ref().unwrap(), session)?;
                let hex =
                    |bytes: &[u8]| bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
                let capture = self.root.join("runtime").join(format!(
                    "capture-{}-{}",
                    hex(&history.prepared.runtime_epoch),
                    hex(&history.prepared.binding.namespace)
                ));
                let mut value = crate::export::read(&capture, &e.file, e.offset)?;
                if e.file.is_empty() && e.offset == 0 {
                    value["inspection"] = serde_json::to_value(history)?;
                }
                report(value)
            }
            Command::Prepare(p) => {
                let (_, now) = self.trusted_clock()?;
                ensure!(self.gateway_live(now), "authenticated gateway required");
                let session = self
                    .sessions
                    .lock()
                    .unwrap()
                    .get(&p.principal)
                    .cloned()
                    .context("authenticate the installed principal before local preparation")?;
                self.authorize(&session, Scope::Propose)?;
                let binding = Binding {
                    principal: session.identity.principal_id,
                    attempt: fixed(&p.attempt)?,
                    namespace: fixed(&p.namespace)?,
                    session_deadline_ns: session.identity.deadline_ns.min(now + 120 * NS),
                };
                let instance = u64::from_le_bytes(robot_rpc::random_id()?).max(1);
                let prepared = self.engine.prepare(
                    binding.clone(),
                    instance,
                    robot_runtime::configuration_digest(),
                )?;
                let mut current = self.binding.write().unwrap();
                self.binding_gateway
                    .store(session.gateway_generation, Ordering::Release);
                self.binding_identity
                    .store(session.identity_generation, Ordering::Release);
                *current = Some(binding);
                drop(current);
                // Publication precedes the final policy check: concurrent urgent
                // revocation either sees this binding or is caught by this check.
                self.authorize(&session, Scope::Propose)
                    .inspect_err(|_| self.close())?;
                report(prepared)
            }
            Command::Grant(g) => {
                let (_, now) = self.trusted_clock()?;
                ensure!(self.bound_gateway_live(now), "gateway unavailable");
                report(self.engine.grant(now + g.duration_ms * 1_000_000)?)
            }
            Command::Activate(_) => {
                self.trusted_clock()?;
                ensure!(
                    self.bound_gateway_live(boottime_ns()?),
                    "gateway unavailable"
                );
                report(self.engine.activate()?)
            }
            Command::Rearm(_) => {
                self.trusted_clock()?;
                report(self.engine.rearm()?)
            }
            Command::Recover(_) => {
                self.close();
                let _writer = self
                    .clock_writer
                    .try_lock()
                    .map_err(|_| anyhow::anyhow!("clock checkpoint pending"))?;
                let wall = wall_ns()?;
                let now = boottime_ns()?;
                let clock = ClockGuard::new(wall, now, self.floor.load(Ordering::Acquire))?;
                storage::replace(&self.root.join("clock.json"), &serde_json::to_vec(&wall)?)?;
                self.floor.store(wall, Ordering::Release);
                self.durable_clock_boot
                    .store(boottime_ns()?, Ordering::Release);
                *self.clock.lock().unwrap() = clock;
                *self.clock_error.write().unwrap() = None;
                self.clock_ok.store(true, Ordering::Release);
                let result = self.engine.recover()?;
                if self.engine.status()?.prepared.is_none() {
                    *self.binding.write().unwrap() = None;
                }
                report(result)
            }
            Command::Reconcile(_) => report(self.engine.reconcile()?),
            Command::Revoke(_) => {
                self.engine.revoke()?;
                report(json!({"local_revoke_requested":true,"reconciled":false}))
            }
            Command::Retire(_) => report(self.engine.retire()?),
            Command::EnrollRequest(e) => {
                self.inhibited()?;
                report(enrollment::request(
                    &self.root.join("identity"),
                    e.dns_name.clone(),
                )?)
            }
            Command::EnrollInstall(e) => {
                self.inhibited()?;
                let (wall, _) = self.trusted_clock()?;
                {
                    let mut current = self.identity.write().unwrap();
                    self.identity_generation
                        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |v| v.checked_add(1))
                        .map_err(|_| anyhow::anyhow!("identity generation exhausted"))?;
                    *current = None;
                }
                self.sessions.lock().unwrap().clear();
                let identity = match enrollment::install(
                    &self.root.join("identity"),
                    &e.certificate_pem,
                    &e.ca_pem,
                    wall,
                ) {
                    Ok(identity) => identity,
                    Err(e) => {
                        *self.identity_error.write().unwrap() = Some(e.to_string());
                        return Err(e);
                    }
                };
                let value = enrollment::report(&identity);
                *self.identity.write().unwrap() = Some(identity);
                *self.identity_error.write().unwrap() = None;
                self.sessions.lock().unwrap().clear();
                report(value)
            }
            Command::InstallPrincipal(p) => {
                self.inhibited()?;
                let mut policy = self.policy.read().unwrap().clone();
                ensure!(
                    !policy.revoked.contains(&p.principal),
                    "retired principal names cannot be reused"
                );
                let mut scopes = vec![Scope::Read];
                if p.can_propose {
                    scopes.push(Scope::Propose);
                }
                ensure!(
                    policy
                        .certificates
                        .get(&p.certificate_sha256)
                        .is_none_or(|old| old.principal == p.principal),
                    "certificate already belongs to another principal"
                );
                policy.certificates.insert(
                    p.certificate_sha256.clone(),
                    PrincipalPolicy {
                        principal: p.principal.clone(),
                        scopes,
                    },
                );
                policy.validate()?;
                storage::replace(
                    &self.root.join("policy.json"),
                    &serde_json::to_vec(&policy)?,
                )?;
                let mut current = self.policy.write().unwrap();
                policy.revoked.extend(current.revoked.iter().cloned());
                *current = policy;
                report(json!({"installed":p.principal,"certificate_sha256":p.certificate_sha256}))
            }
            Command::RevokePrincipal(p) => {
                storage::replace(
                    &self
                        .root
                        .join("revoked")
                        .join(format!("{}.json", p.principal)),
                    &serde_json::to_vec(&p.principal)?,
                )?;
                report(json!({"revoked":p.principal,"durable":true}))
            }
        }
    }
}

#[cfg(test)]
mod clock_tests {
    use super::*;

    #[test]
    fn late_successful_checkpoint_latches_fault_before_publishing_progress() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("clock.json");
        let durable = AtomicU64::new(NS);
        let healthy = AtomicBool::new(true);
        // Persistence succeeds after the old deadline, before a watchdog runs.
        storage::replace(&path, b"42").unwrap();
        publish_clock_checkpoint(&durable, 12 * NS, |age| {
            assert_eq!(age, 11 * NS);
            assert_eq!(durable.load(Ordering::Acquire), NS);
            healthy.store(false, Ordering::Release);
        });
        assert!(!healthy.load(Ordering::Acquire));
        assert_eq!(durable.load(Ordering::Acquire), 12 * NS);
        assert_eq!(fs::read(path).unwrap(), b"42");
    }

    #[test]
    fn on_time_completion_preserves_health_and_never_clears_a_prior_fault() {
        let durable = AtomicU64::new(NS);
        let healthy = AtomicBool::new(true);
        publish_clock_checkpoint(&durable, 11 * NS, |_| panic!("exact deadline is allowed"));
        assert_eq!(durable.load(Ordering::Acquire), 11 * NS);
        assert!(healthy.load(Ordering::Acquire));
        healthy.store(false, Ordering::Release);
        publish_clock_checkpoint(&durable, 12 * NS, |_| panic!("within deadline"));
        assert!(!healthy.load(Ordering::Acquire));
        assert_eq!(durable.load(Ordering::Acquire), 12 * NS);
    }

    #[test]
    fn watchdog_and_late_completion_cannot_publish_over_an_unlatched_fault() {
        let durable = Arc::new(AtomicU64::new(NS));
        let healthy = Arc::new(AtomicBool::new(true));
        let (closing, closed) = std::sync::mpsc::channel();
        let (release, released) = std::sync::mpsc::channel();
        let progress = durable.clone();
        let health = healthy.clone();
        let writer = std::thread::spawn(move || {
            publish_clock_checkpoint(&progress, 12 * NS, |_| {
                health.store(false, Ordering::Release);
                closing.send(()).unwrap();
                released.recv().unwrap();
            });
        });
        // While urgent closure is in progress, the completion must not make the
        // previous missed interval disappear from a concurrent watchdog.
        let observed = closed.recv_timeout(Duration::from_secs(1));
        if observed.is_ok() {
            assert!(!healthy.load(Ordering::Acquire));
            assert_eq!(durable.load(Ordering::Acquire), NS);
            healthy.store(false, Ordering::Release); // simultaneous watchdog latch
        }
        // Also release a writer scheduled after the assertion deadline, so a
        // failed test cannot leave its join blocked indefinitely.
        let _ = release.send(());
        writer.join().unwrap();
        assert!(observed.is_ok(), "late completion did not invoke closure");
        assert!(!healthy.load(Ordering::Acquire));
        assert_eq!(durable.load(Ordering::Acquire), 12 * NS);
    }

    #[test]
    fn competing_clock_calls_sample_only_after_the_ordering_lock() {
        let clock = Arc::new(Mutex::new(ClockGuard::new(10_000, 100, 0).unwrap()));
        let held = clock.lock().unwrap();
        let shared = clock.clone();
        let (entered, entry) = std::sync::mpsc::channel();
        let (sampled, sample) = std::sync::mpsc::channel();
        let worker = std::thread::spawn(move || {
            entered.send(()).unwrap();
            checked_clock(&shared, || {
                sampled.send(()).unwrap();
                Ok((10_100, 200))
            })
        });
        entry.recv().unwrap();
        let sampled_before_ordering = sample.recv_timeout(Duration::from_millis(50)).is_ok();
        drop(held);
        assert_eq!(worker.join().unwrap().unwrap(), (10_100, 200));
        assert!(
            !sampled_before_ordering,
            "sampling before lock can reverse concurrent clock observations"
        );
    }
}
