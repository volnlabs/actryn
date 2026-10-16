//! Fixed native skill manager. Only the kernel can authorize effects.
mod bindings;
mod bridge;
mod capture;
mod clock;
mod events;
mod skill;
mod types;
use authority_client::{boottime_ns, AuthorityDevice, Event, Opcode, Request, Role, Status};
use bridge::Bridge;
use capture::Capture;
use clock::Mapping;
use evidence::EventKind;
use robot_intent::{Intent, Namespace, OperationId, Registry};
use sha2::{Digest, Sha256};
pub use skill::Target;
use skill::{Action, Step};
use std::{
    collections::VecDeque,
    fs::{self, File, OpenOptions},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex, RwLock,
    },
    thread::{self, JoinHandle},
    time::Duration,
};
pub use types::*;
const MS: u64 = 1_000_000;
const CONFIG:&[u8]=b"wheel.index_step.v1;context=1;delta<=100;duration<=10000ms;duty=100;cadence=100ms;slew=1000/s;credit<=100ms";
pub fn configuration_digest() -> [u8; 32] {
    Sha256::digest(CONFIG).into()
}
pub fn profile_digest() -> [u8; 32] {
    Sha256::digest(include_bytes!(
        "../../../targets/qemu-arm64-fixture/1/profile.toml"
    ))
    .into()
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
struct Context {
    prepared: Prepared,
    registry: Registry,
    namespace: Namespace,
    capture: Capture,
    closed: AtomicBool,
}
struct Active {
    key: [u8; 32],
    id: OperationId,
    step: Step,
    deadline: u64,
    verdict: Verdict,
    reconciled: bool,
    last_sample_ns: u64,
    last_sequence: u64,
}
struct Slot {
    context: Arc<Context>,
    stop: Arc<AtomicBool>,
    workers: Vec<JoinHandle<()>>,
    retiring: bool,
    created_ns: u64,
    grant_deadline: u64,
    active: Option<Active>,
}
struct Core {
    slot: Option<Slot>,
    mapping: Option<Mapping>,
    recovery: Option<(u64, u64)>,
    recover_reset: bool,
    rearm_pending: bool,
    observations: VecDeque<Observation>,
    next_observation: u64,
    event_stream: Option<events::Continuity>,
    registered_observation: u64,
    last_applied_ctl: u64,
}
impl Core {
    fn event_stream_ready(&self, status: &Status) -> bool {
        self.event_stream.as_ref().is_some_and(|stream| {
            !stream.faulted
                && stream.epoch == status.runtime_nonce
                && stream.lost_baseline == status.events_lost
        })
    }
}
/// One prepared instance at a time, including construction and retirement. The
/// library has no network decoder or agent-controlled device path.
pub struct Engine {
    root: PathBuf,
    _lock: File,
    bridge: Arc<Bridge>,
    events: AuthorityDevice,
    core: Mutex<Core>,
    context: RwLock<Option<Arc<Context>>>,
    reserved: AtomicBool,
    generation: AtomicU64,
    inhibited: AtomicBool,
}
impl Engine {
    /// Installs process-wide exec denial before binding actual kernel roles.
    /// Preparation/storage methods belong on the service's preparation worker.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let root = path.as_ref();
        if !root.exists() {
            fs::create_dir_all(root)?;
            fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
        }
        let metadata = fs::symlink_metadata(root)?;
        if !metadata.is_dir()
            || metadata.uid() != unsafe { libc::geteuid() }
            || metadata.mode() & 0o077 != 0
        {
            return Err(Error::Denied(
                "runtime root must be owned, private directory",
            ));
        }
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(root.join("runtime.lock"))?;
        lock.try_lock().map_err(|_| Error::Busy)?;
        let metadata = lock.metadata()?;
        if !metadata.is_file()
            || metadata.uid() != unsafe { libc::geteuid() }
            || metadata.mode() & 0o077 != 0
        {
            return Err(Error::Denied("runtime lock permissions"));
        }
        authority_client::deny_exec()?;
        let admin = AuthorityDevice::bind(Role::Admin)?;
        let bridge = Arc::new(Bridge {
            admin,
            runtime: RwLock::new(None),
            acquisition: RwLock::new(None),
            enabled: AtomicBool::new(false),
            session_deadline: AtomicU64::new(0),
        });
        bridge.bind_runtime()?;
        let events = AuthorityDevice::bind(Role::Events)?;
        Ok(Self {
            root: path.as_ref().to_owned(),
            _lock: lock,
            bridge,
            events,
            core: Mutex::new(Core {
                slot: None,
                mapping: None,
                recovery: None,
                recover_reset: false,
                rearm_pending: false,
                observations: VecDeque::with_capacity(32),
                next_observation: 0,
                event_stream: None,
                registered_observation: 0,
                last_applied_ctl: 0,
            }),
            context: RwLock::new(None),
            reserved: AtomicBool::new(false),
            generation: AtomicU64::new(1),
            inhibited: AtomicBool::new(true),
        })
    }
    /// Urgent close. No core/registry lock, persistence, worker join or receipt wait.
    pub fn revoke(&self) -> Result<()> {
        self.inhibited.store(true, Ordering::Release);
        let incremented = advance_generation(&self.generation);
        if let Some(context) = self.context.read().unwrap().as_ref() {
            context.closed.store(true, Ordering::Release);
        }
        self.bridge.revoke()?;
        if incremented.is_err() {
            return Err(Error::Denied("runtime generation exhausted"));
        }
        Ok(())
    }
    /// Explicit local recovery. Existing writer resources remain charged until
    /// finished; repeated calls poll, never resend a pending RECOVER.
    pub fn recover(&self) -> Result<Progress> {
        self.inhibited.store(true, Ordering::Release);
        self.bridge.enabled.store(false, Ordering::Release);
        let mut core = self.core.lock().unwrap();
        if core.recovery.is_some() {
            drop(core);
            self.tick()?;
            return self.recovery_progress();
        }
        if core.slot.is_none() && self.reserved.load(Ordering::Acquire) {
            advance_generation(&self.generation)
                .map_err(|_| Error::Denied("runtime generation exhausted"))?;
            return Ok(Progress::Pending);
        }
        if let Some(slot) = core.slot.as_mut() {
            if !slot.retiring {
                slot.context
                    .registry
                    .retire_namespace(&slot.context.namespace)?;
                slot.retiring = true;
                slot.stop.store(true, Ordering::Release);
                let _ = self.bridge.revoke();
            }
            if slot.workers.iter().any(|w| !w.is_finished()) {
                return Ok(Progress::Pending);
            }
            for worker in slot.workers.drain(..) {
                if worker.join().is_err() {
                    return Err(Error::Denied("writer panicked"));
                }
            }
            core.slot = None;
            *self.context.write().unwrap() = None;
            self.reserved.store(false, Ordering::Release);
        }
        let status = self.bridge.admin.status()?;
        if !core.recover_reset
            && core.event_stream_ready(&status)
            && recovered_mapping_ready(core.mapping, &status, boottime_ns()?)
        {
            return Ok(Progress::Ready);
        }
        // Dropping the runtime role faults the old owner even after an idle revoke.
        if !core.recover_reset {
            self.bridge.release_runtime();
            self.bridge.bind_runtime()?;
            core.recover_reset = true;
        }
        core.mapping = None;
        core.observations.clear();
        core.registered_observation = 0;
        core.rearm_pending = false;
        core.event_stream = None;
        // Old captures stay incomplete. Drain their bounded FIFO before taking
        // the cumulative loss baseline for the explicit new exchange.
        let mut drained = false;
        for _ in 0..256 {
            match self.events.read_event() {
                Ok(_) => (),
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    drained = true;
                    break;
                }
                Err(error) => return Err(error.into()),
            }
        }
        if !drained {
            return Err(Error::Denied("kernel event recovery drain capacity"));
        }
        let lost_baseline = self.bridge.admin.status()?.events_lost;
        if lost_baseline == u32::MAX {
            return Err(Error::Denied("kernel event loss counter exhausted"));
        }
        let sent = boottime_ns()?;
        core.recovery = Some((
            sent,
            sent.checked_add(12_000 * MS)
                .ok_or(Error::Denied("clock overflow"))?,
        ));
        let mut request = Request::new(Opcode::Recover);
        if let Err(e) = self.bridge.admin.request(&mut request) {
            core.recovery = None;
            return Err(e.into());
        }
        core.event_stream = Some(events::Continuity::new(
            self.bridge.admin.status()?.runtime_nonce,
            lost_baseline,
        )?);
        Ok(Progress::Pending)
    }
    fn recovery_progress(&self) -> Result<Progress> {
        let c = self.core.lock().unwrap();
        let status = self.bridge.admin.status()?;
        Ok(
            if c.recovery.is_none()
                && c.event_stream_ready(&status)
                && recovered_mapping_ready(c.mapping, &status, boottime_ns()?)
            {
                Progress::Ready
            } else {
                Progress::Pending
            },
        )
    }
    pub fn rearm(&self) -> Result<Progress> {
        let mut core = self.core.lock().unwrap();
        if core.recovery.is_some() || core.mapping.is_none() {
            return Err(Error::Denied("matched recovery required"));
        }
        let status = self.bridge.admin.status()?;
        core.mapping.unwrap().controller_lower(boottime_ns()?)?;
        if status.flags & 1 == 0 || !core.event_stream_ready(&status) {
            return Err(Error::Denied("matched recovery required"));
        }
        if status.state == 1 {
            return Ok(Progress::Ready);
        }
        if core.rearm_pending {
            return Ok(Progress::Pending);
        }
        self.bridge
            .admin
            .request(&mut Request::new(Opcode::Rearm))?;
        core.rearm_pending = true;
        Ok(Progress::Pending)
    }
    pub fn prepare(&self, binding: Binding, instance: u64, digest: [u8; 32]) -> Result<Prepared> {
        let now = boottime_ns()?;
        binding.validate(now)?;
        if instance == 0
            || digest != configuration_digest()
            || binding.session_deadline_ns - now > 120_000 * MS
        {
            return Err(Error::Denied(
                "immutable configuration/instance/session bound",
            ));
        }
        let status = self.bridge.admin.status()?;
        if status.state != 1 || status.flags & 1 == 0 {
            return Err(Error::Denied("explicit rearm required"));
        }
        if !self.core.lock().unwrap().event_stream_ready(&status) {
            return Err(Error::Denied("matched event recovery required"));
        }
        if self
            .reserved
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(Error::Busy);
        }
        let generation = self.generation.load(Ordering::Acquire);
        if generation == u64::MAX {
            self.reserved.store(false, Ordering::Release);
            return Err(Error::Denied("runtime generation exhausted"));
        }
        let built = (|| -> Result<_> {
            let prepared = Prepared {
                binding: binding.clone(),
                instance,
                configuration_digest: digest,
                runtime_epoch: status.runtime_nonce,
            };
            let (registry, intent_writer) = Registry::open(
                self.root.join("intent.sqlite"),
                status.runtime_nonce,
                robot_intent::Limits::default(),
                self.bridge.clone(),
            )?;
            let namespace = registry.prepare_namespace(binding.attempt, binding.namespace)?;
            bindings::persist(&self.root, &prepared)?;
            let capture_path = self.root.join(format!(
                "capture-{}-{}",
                hex(&status.runtime_nonce),
                hex(&binding.namespace)
            ));
            let (capture, evidence_writer) =
                Capture::create(&capture_path, &binding, status.runtime_nonce)?;
            capture.record(
                0,
                now,
                EventKind::Configuration,
                &String::from_utf8_lossy(CONFIG),
            )?;
            capture.record(0, now, EventKind::Transition, &prepared)?;
            capture.record(
                0,
                now,
                EventKind::Configuration,
                &serde_json::json!({"kernel_historical_events_lost":status.events_lost,
                    "recovery_epoch":status.runtime_nonce,"old_capture_repaired":false}),
            )?;
            let context = Arc::new(Context {
                prepared: prepared.clone(),
                registry,
                namespace,
                capture,
                closed: AtomicBool::new(false),
            });
            let stop = Arc::new(AtomicBool::new(false));
            let a = stop.clone();
            let intent_thread = thread::spawn(move || {
                let _ = intent_writer.run(a, Duration::from_millis(5));
            });
            let b = stop.clone();
            let evidence_thread = thread::spawn(move || {
                let _ = evidence_writer.run(b);
            });
            Ok((
                prepared,
                context,
                stop,
                vec![intent_thread, evidence_thread],
            ))
        })();
        let (prepared, context, stop, workers) = match built {
            Ok(v) => v,
            Err(e) => {
                self.reserved.store(false, Ordering::Release);
                self.inhibited.store(true, Ordering::Release);
                return Err(e);
            }
        };
        let late = boottime_ns().map_or(true, |current| current.saturating_sub(now) > 5000 * MS)
            || self.generation.load(Ordering::Acquire) != generation;
        let mut core = self.core.lock().unwrap();
        *self.context.write().unwrap() = Some(context.clone());
        core.slot = Some(Slot {
            context,
            stop: stop.clone(),
            workers,
            retiring: late,
            created_ns: now,
            grant_deadline: 0,
            active: None,
        });
        if late {
            let context = &core.slot.as_ref().unwrap().context;
            context.closed.store(true, Ordering::Release);
            let _ = context.registry.retire_namespace(&context.namespace);
            stop.store(true, Ordering::Release);
            return Err(Error::Denied(
                "preparation expired/retired during construction",
            ));
        }
        Ok(prepared)
    }
    pub fn grant(&self, deadline_ns: u64) -> Result<Status> {
        let now = boottime_ns()?;
        let mut core = self.core.lock().unwrap();
        let slot = core
            .slot
            .as_mut()
            .ok_or(Error::Denied("prepare required"))?;
        slot.context.prepared.binding.validate(now)?;
        if slot.retiring
            || slot.context.closed.load(Ordering::Acquire)
            || !slot
                .context
                .registry
                .namespace_ready(&slot.context.namespace)
            || !slot.context.capture.preparation_ready()
            || deadline_ns <= now
            || deadline_ns - now > 60_000 * MS
            || deadline_ns > slot.context.prepared.binding.session_deadline_ns
        {
            return Err(Error::Denied("grant bound/namespace not durable"));
        }
        let health = self.health_for(Some(&slot.context));
        if !health.healthy {
            return Err(Error::Denied("unhealthy preparation"));
        }
        let generation = self.generation.load(Ordering::Acquire);
        let mut r = Request::new(Opcode::Grant);
        r.instance = slot.context.prepared.instance;
        r.deadline_ns = deadline_ns;
        r.digest = configuration_digest();
        self.bridge.admin.request(&mut r)?;
        if self.generation.load(Ordering::Acquire) != generation
            || slot.context.closed.load(Ordering::Acquire)
        {
            self.bridge.revoke()?;
            return Err(Error::Denied("grant retired concurrently"));
        }
        slot.grant_deadline = deadline_ns;
        self.bridge.session_deadline.store(
            slot.context.prepared.binding.session_deadline_ns,
            Ordering::Release,
        );
        Ok(self.bridge.admin.status()?)
    }
    pub fn activate(&self) -> Result<Status> {
        let now = boottime_ns()?;
        let core = self.core.lock().unwrap();
        let slot = core
            .slot
            .as_ref()
            .ok_or(Error::Denied("prepare required"))?;
        slot.context.prepared.binding.validate(now)?;
        if slot.retiring
            || slot.context.closed.load(Ordering::Acquire)
            || !self.health_for(Some(&slot.context)).healthy
        {
            return Err(Error::Denied("instance retired/unhealthy"));
        }
        let s = self.bridge.admin.status()?;
        let mut h = Request::new(Opcode::Health);
        h.runtime_nonce = s.runtime_nonce;
        h.deadline_ns = (now + 2000 * MS).min(slot.context.prepared.binding.session_deadline_ns);
        self.bridge.runtime_request(&mut h)?;
        let mut r = Request::new(Opcode::Activate);
        r.runtime_nonce = s.runtime_nonce;
        r.grant = s.grant;
        r.instance = slot.context.prepared.instance;
        let generation = self.generation.load(Ordering::Acquire);
        self.bridge.runtime_request(&mut r)?;
        if let Err(error) =
            slot.context
                .capture
                .record(0, now, EventKind::Activation, &slot.context.prepared)
        {
            let _ = self.bridge.revoke();
            return Err(error);
        }
        self.inhibited.store(false, Ordering::Release);
        self.bridge.enabled.store(true, Ordering::Release);
        if self.generation.load(Ordering::Acquire) != generation
            || slot.context.closed.load(Ordering::Acquire)
        {
            self.inhibited.store(true, Ordering::Release);
            self.bridge.revoke()?;
            return Err(Error::Denied("activation retired concurrently"));
        }
        Ok(self.bridge.admin.status()?)
    }
    pub fn observe(&self) -> Result<Observation> {
        self.tick()?;
        let core = self.core.lock().unwrap();
        let observation = core
            .observations
            .back()
            .cloned()
            .ok_or(Error::Denied("no actual controller observation"))?;
        observation.fresh(boottime_ns()?)?;
        Ok(observation)
    }
    fn current(&self, binding: &Binding) -> Result<Arc<Context>> {
        let context = self
            .context
            .read()
            .unwrap()
            .clone()
            .ok_or(Error::Denied("no prepared binding"))?;
        if &context.prepared.binding != binding {
            return Err(Error::Denied("immutable binding mismatch"));
        }
        Ok(context)
    }
    pub fn propose(
        &self,
        binding: &Binding,
        key: [u8; 32],
        parent_digest: [u8; 32],
        target: Target,
        observation_id: u64,
    ) -> Result<Snapshot> {
        let context = self.current(binding)?;
        target.validate()?;
        let digest = proposal_digest(
            binding,
            context.prepared.instance,
            parent_digest,
            target,
            observation_id,
        );
        if let Some(existing) = context.registry.query(binding.namespace, key) {
            if existing.digest.is_some_and(|old| old != digest) {
                return Err(Error::Conflict);
            }
            return Ok(self.snapshot(existing));
        }
        let now = boottime_ns()?;
        binding.validate(now)?;
        if self.inhibited.load(Ordering::Acquire) || parent_digest == [0; 32] {
            return Err(Error::Denied("proposal inhibited/empty parent"));
        }
        let mut core = self.core.lock().unwrap();
        let obs = core
            .observations
            .iter()
            .find(|v| v.id == observation_id)
            .cloned()
            .ok_or(Error::Denied("observation not retained"))?;
        obs.fresh(now)?;
        let slot = core
            .slot
            .as_ref()
            .ok_or(Error::Denied("no prepared instance"))?;
        if slot.retiring
            || slot.active.as_ref().is_some_and(|a| !a.reconciled)
            || !self.health_for(Some(&context)).healthy
        {
            return Err(Error::Busy);
        }
        let status = self.bridge.admin.status()?;
        if status.state != 2
            || status.runtime_nonce != context.prepared.runtime_epoch
            || status.flags & 8 == 0
        {
            return Err(Error::Denied("kernel grant not live"));
        }
        register_observation(&self.bridge, &mut core, &obs)?;
        let deadline = now
            .checked_add(target.duration_ms * MS)
            .ok_or(Error::Denied("deadline overflow"))?
            .min(binding.session_deadline_ns)
            .min(status.deadline_ns);
        let step = Step::new([obs.left_encoder, obs.right_encoder], target, deadline)?;
        let intent = Intent {
            digest,
            configuration_digest: configuration_digest(),
            instance: context.prepared.instance,
            grant: status.grant,
            context_revision: 1,
            deadline_ns: deadline,
            observation: observation_id,
            payload: serde_json::to_vec(&(binding, parent_digest, target, observation_id))
                .map_err(|_| Error::Denied("intent serialization"))?,
        };
        let result = context.registry.propose(&context.namespace, key, intent)?;
        if let Some(id) = result.operation {
            core.slot.as_mut().unwrap().active = Some(Active {
                key,
                id,
                step,
                deadline,
                verdict: Verdict::Pending,
                reconciled: false,
                last_sample_ns: now,
                last_sequence: 0,
            });
        }
        if let Err(error) = context.capture.record(
            0,
            now,
            EventKind::Execution,
            &(key, digest, target, observation_id),
        ) {
            let _ = self.bridge.revoke();
            return Err(error);
        }
        drop(core);
        Ok(self.snapshot(result))
    }
    /// Read-only historical query is available even without a live Engine/kernel.
    /// Caller authenticates principal scope; retained immutable binding is checked.
    pub fn inspect(
        path: impl AsRef<Path>,
        principal: [u8; 32],
        attempt: [u8; 16],
        namespace: [u8; 16],
        key: [u8; 32],
    ) -> Result<Historical> {
        let prepared = bindings::load(path.as_ref(), principal, attempt, namespace)?;
        let inspected = robot_intent::inspect(
            &path.as_ref().join("intent.sqlite"),
            attempt,
            namespace,
            key,
            robot_intent::Limits::default(),
        )?;
        if !inspected.namespace_exists {
            return Err(Error::Denied(
                "binding exists but durable namespace unavailable",
            ));
        }
        let snapshot = inspected.snapshot.map(|s| {
            let verdict = if s.key_cancelled_durable() {
                Verdict::Cancelled
            } else {
                Verdict::OutcomeUnknown
            };
            Snapshot::from_registry(s, verdict, false)
        });
        Ok(Historical {
            prepared,
            snapshot,
            live_authority: false,
        })
    }
    pub fn query(&self, binding: &Binding, key: [u8; 32]) -> Result<Option<Snapshot>> {
        let context = self.current(binding)?;
        Ok(context
            .registry
            .query(binding.namespace, key)
            .map(|v| self.snapshot(v)))
    }
    pub fn query_operation(
        &self,
        binding: &Binding,
        operation: Operation,
    ) -> Result<Option<Snapshot>> {
        let context = self.current(binding)?;
        let found = context.registry.query_operation(&operation.into());
        if found
            .as_ref()
            .is_some_and(|s| s.namespace != binding.namespace)
        {
            return Err(Error::Denied("operation outside immutable namespace"));
        }
        Ok(found.map(|s| self.snapshot(s)))
    }
    pub fn cancel_operation(&self, binding: &Binding, operation: Operation) -> Result<Snapshot> {
        let context = self.current(binding)?;
        let id = operation.into();
        let found = context
            .registry
            .query_operation(&id)
            .ok_or(Error::Denied("unknown operation"))?;
        if found.namespace != binding.namespace {
            return Err(Error::Denied("operation outside immutable namespace"));
        }
        let result = context.registry.cancel_operation(&id)?;
        let verdict = if result.phase == robot_intent::Phase::Completed {
            Verdict::OutcomeUnknown
        } else {
            Verdict::Cancelled
        };
        Ok(Snapshot::from_registry(result, verdict, false))
    }
    /// Urgent key fence and kernel close; returns pending until tombstone durable.
    pub fn cancel(&self, binding: &Binding, key: [u8; 32]) -> Result<Snapshot> {
        let context = self.current(binding)?;
        let result = context.registry.cancel(&context.namespace, key)?;
        let verdict = if result.phase == robot_intent::Phase::Completed {
            Verdict::OutcomeUnknown
        } else {
            Verdict::Cancelled
        };
        Ok(Snapshot::from_registry(result, verdict, false))
    }
    pub fn retire(&self) -> Result<Progress> {
        self.revoke()?;
        let context = self.context.read().unwrap().clone();
        if let Some(context) = context {
            context.registry.retire_namespace(&context.namespace)?;
        }
        let mut core = self.core.lock().unwrap();
        if let Some(slot) = core.slot.as_mut() {
            slot.retiring = true;
        }
        Ok(Progress::Pending)
    }
    fn snapshot(&self, value: robot_intent::Snapshot) -> Snapshot {
        let core = self.core.lock().unwrap();
        let active = core
            .slot
            .as_ref()
            .and_then(|s| s.active.as_ref())
            .filter(|a| {
                a.key == value.key
                    && core
                        .slot
                        .as_ref()
                        .unwrap()
                        .context
                        .prepared
                        .binding
                        .namespace
                        == value.namespace
            });
        let verdict = active.map_or(
            if matches!(
                value.phase,
                robot_intent::Phase::OutcomeUnknown
                    | robot_intent::Phase::Completed
                    | robot_intent::Phase::Rejected
            ) {
                Verdict::OutcomeUnknown
            } else {
                Verdict::Pending
            },
            |a| a.verdict,
        );
        Snapshot::from_registry(value, verdict, active.is_some_and(|a| a.reconciled))
    }
    fn health_for(&self, context: Option<&Context>) -> Health {
        let mut h = Health {
            healthy: true,
            inhibited: self.inhibited.load(Ordering::Acquire),
            registry_fault: None,
            evidence_issues: vec![],
            pending_records: 0,
            pending_bytes: 0,
            frontiers: vec![],
        };
        if let Some(c) = context {
            let r = c.registry.health();
            let e = c.capture.recorder.health();
            h.healthy = !r.revoke_required && !e.revoke_required;
            h.registry_fault = r.fault.map(|f| format!("{f:?}"));
            h.evidence_issues = e.issues.iter().map(|v| format!("{v:?}")).collect();
            h.pending_records = e.pending_records;
            h.pending_bytes = e.pending_bytes;
            h.frontiers = e
                .frontiers
                .iter()
                .enumerate()
                .map(|(producer, v)| Frontier {
                    producer,
                    read: v.read,
                    queued: v.queued,
                    durable: v.durable,
                    source_gap_count: v.gap_count,
                })
                .collect();
        }
        h
    }
    pub fn health(&self) -> Result<Health> {
        let c = self.context.read().unwrap().clone();
        let mut health = self.health_for(c.as_deref());
        if !health.healthy {
            self.revoke()?;
            health.inhibited = true;
        }
        Ok(health)
    }
    pub fn status(&self) -> Result<RuntimeStatus> {
        let health = self.health()?;
        let kernel = self.bridge.admin.status()?;
        let core = self.core.lock().unwrap();
        let prepared = core.slot.as_ref().map(|s| s.context.prepared.clone());
        let operation = core.slot.as_ref().and_then(|s| {
            s.active.as_ref().and_then(|a| {
                s.context
                    .registry
                    .query(s.context.prepared.binding.namespace, a.key)
                    .map(|v| Snapshot::from_registry(v, a.verdict, a.reconciled))
            })
        });
        Ok(RuntimeStatus {
            kernel,
            prepared,
            retiring: core.slot.as_ref().is_some_and(|s| s.retiring),
            retirement_ready: core.slot.as_ref().is_some_and(|slot| {
                slot.retiring && slot.workers.iter().all(JoinHandle::is_finished)
            }),
            recovery_pending: core.recovery.is_some(),
            preparation_ready: core.slot.as_ref().is_some_and(|slot| {
                !slot.retiring
                    && !slot.context.closed.load(Ordering::Acquire)
                    && slot
                        .context
                        .registry
                        .namespace_ready(&slot.context.namespace)
                    && slot.context.capture.preparation_ready()
            }),
            recovery_ready: core.recovery.is_none()
                && core.event_stream_ready(&kernel)
                && recovered_mapping_ready(core.mapping, &kernel, boottime_ns()?),
            event_loss_baseline: core.event_stream.as_ref().map(|s| s.lost_baseline),
            event_stream_healthy: core.event_stream_ready(&kernel),
            health,
            operation,
        })
    }
    pub fn reconcile(&self) -> Result<RuntimeStatus> {
        self.tick()?;
        self.status()
    }
    /// Service calls at least every 100 ms. Bounded event drain and one sample;
    /// health expiry in the kernel/controller remains independent of this caller.
    pub fn tick(&self) -> Result<()> {
        let result = self.tick_inner();
        if result.is_err() {
            let _ = self.revoke();
        }
        result
    }
    fn tick_inner(&self) -> Result<()> {
        // Health closes authority first; continue draining actual events while
        // inhibited so normal retirement cannot overflow the kernel evidence FIFO.
        self.health()?;
        let mut core = self.core.lock().unwrap();
        for _ in 0..64 {
            match self.events.read_event() {
                Ok(event) => self.event(&mut core, event)?,
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                Err(e) => return Err(e.into()),
            }
        }
        // Records may be acquired while the drain runs; compare them against a
        // current host clock, never a snapshot predating their actual capture.
        let now = boottime_ns()?;
        if core.recovery.is_some_and(|(_, deadline)| now >= deadline) {
            core.recovery = None;
            return Err(Error::Denied("recovery exchange timed out"));
        }
        let status = self.bridge.admin.status()?;
        let Some(slot) = core.slot.as_ref() else {
            return Ok(());
        };
        let context = slot.context.clone();
        if context.closed.load(Ordering::Acquire)
            || now >= context.prepared.binding.session_deadline_ns
            || (!slot.retiring
                && status.state != 2
                && now.saturating_sub(slot.created_ns) > 60_000 * MS)
        {
            self.bridge.revoke()?;
            context.registry.retire_namespace(&context.namespace)?;
            core.slot.as_mut().unwrap().retiring = true;
        }
        if status.state >= 4 {
            if let Some(active) = core.slot.as_mut().unwrap().active.as_mut() {
                if active.verdict == Verdict::Pending {
                    active.verdict = Verdict::OutcomeUnknown;
                }
            }
            core.slot
                .as_ref()
                .unwrap()
                .stop
                .store(true, Ordering::Release);
            return Err(Error::Denied(
                "kernel fault/detach; explicit recovery required",
            ));
        }
        let retiring = core.slot.as_ref().unwrap().retiring;
        if retiring {
            if status.operation == 0 || status.operation_state == 4 {
                core.slot
                    .as_ref()
                    .unwrap()
                    .stop
                    .store(true, Ordering::Release);
            }
            return Ok(());
        }
        if !self.inhibited.load(Ordering::Acquire) {
            let mut health = Request::new(Opcode::Health);
            health.runtime_nonce = status.runtime_nonce;
            health.deadline_ns =
                (now + 2000 * MS).min(context.prepared.binding.session_deadline_ns);
            self.bridge.runtime_request(&mut health)?;
        }
        let Some(active) = core.slot.as_mut().unwrap().active.as_mut() else {
            return Ok(());
        };
        if !bridge::matches(&status, &active.id) {
            active.verdict = Verdict::OutcomeUnknown;
            return Err(Error::Denied("operation epoch changed"));
        }
        let snapshot = context
            .registry
            .query(context.prepared.binding.namespace, active.key)
            .ok_or(Error::Denied("operation key missing"))?;
        if matches!(
            snapshot.phase,
            robot_intent::Phase::CancelPending | robot_intent::Phase::CancelledDurable
        ) {
            active.verdict = Verdict::Cancelled;
        }
        if snapshot.phase == robot_intent::Phase::OutcomeUnknown {
            active.verdict = Verdict::OutcomeUnknown;
            return Err(Error::Denied("uncertain intent outcome"));
        }
        if status.operation_state == 4 {
            active.reconciled = true;
            if snapshot.phase == robot_intent::Phase::Submitted {
                context.registry.complete(&context.namespace, active.key)?;
            }
            return Ok(());
        }
        if now >= active.deadline {
            if active.verdict == Verdict::Pending {
                active.verdict = Verdict::TimedOut;
            }
            return Err(Error::Denied("operation absolute deadline"));
        }
        if active.verdict != Verdict::Pending || status.operation_state != 2 {
            return Ok(());
        }
        let observation = core
            .observations
            .back()
            .cloned()
            .ok_or(Error::Denied("controller feedback missing"))?;
        observation.fresh(now)?;
        let active = core.slot.as_mut().unwrap().active.as_mut().unwrap();
        let action = active
            .step
            .update([observation.left_encoder, observation.right_encoder], now)?;
        match action {
            Action::Expired => {
                active.verdict = Verdict::TimedOut;
                return Err(Error::Denied("skill deadline"));
            }
            Action::Finish => {
                let mut request = Request::operation_identity(Opcode::Finish, &status);
                self.bridge.runtime_request(&mut request)?;
                active.verdict = Verdict::TargetReached;
                context.capture.record(
                    0,
                    now,
                    EventKind::Transition,
                    &(active.key, active.verdict),
                )?;
            }
            Action::Duty(duty) => {
                if status.flags & 6 != 0
                    || status.sequence < active.last_sequence
                    || now.saturating_sub(active.last_sample_ns) < 100 * MS
                    || core
                        .mapping
                        .ok_or(Error::Denied("clock mapping missing"))?
                        .controller_lower(now)?
                        .saturating_sub(core.last_applied_ctl)
                        < 100 * MS
                {
                    return Ok(());
                }
                register_observation(&self.bridge, &mut core, &observation)?;
                let active = core.slot.as_mut().unwrap().active.as_mut().unwrap();
                let mut request = Request::operation_identity(Opcode::Sample, &status);
                request.sequence = active
                    .last_sequence
                    .checked_add(1)
                    .ok_or(Error::Denied("sample sequence exhausted"))?;
                request.deadline_ns = (now + 300 * MS)
                    .min(active.deadline)
                    .min(context.prepared.binding.session_deadline_ns)
                    .min(status.deadline_ns)
                    .min(observation.valid_until_ns)
                    .min(observation.acquired_earliest_ns + 1000 * MS);
                if request.deadline_ns <= now {
                    return Err(Error::Denied("no safe sample horizon"));
                }
                request.observation = observation.id;
                request.context_revision = 1;
                request.left_permille = duty[0];
                request.right_permille = duty[1];
                request.digest = sample_digest(&request);
                self.bridge.runtime_request(&mut request)?;
                active.last_sequence = request.sequence;
                active.last_sample_ns = now;
                context
                    .capture
                    .record(0, now, EventKind::Execution, &request)?;
            }
        }
        Ok(())
    }
    fn event(&self, core: &mut Core, event: Event) -> Result<()> {
        let Some(stream) = core.event_stream.as_mut() else {
            return Ok(());
        };
        match stream.accept(&event) {
            Ok(false) => return Ok(()),
            Ok(true) => (),
            Err(error) => {
                core.mapping = None;
                return Err(error);
            }
        }
        if let Some(slot) = core.slot.as_ref().filter(|s| {
            !s.stop.load(Ordering::Acquire) && !s.context.capture.recorder.health().revoke_required
        }) {
            slot.context
                .capture
                .record(1, event.captured_ns, EventKind::Transition, &event)?;
        }
        if event.status.runtime_nonce != self.bridge.admin.status()?.runtime_nonce {
            return Ok(());
        }
        if event.kind == 0x20002 {
            let (_sent, _) = core
                .recovery
                .ok_or(Error::Denied("unsolicited HELLO acknowledgment"))?;
            core.mapping = Some(Mapping::new(
                event.captured_ns.saturating_sub(10 * MS),
                event.captured_ns,
                event.status.controller_ns,
            )?);
            core.recovery = None;
            core.recover_reset = false;
        }
        // Kernel receipt handling advances its slew reference for STARTED too.
        // Track it without promoting a status poll/START receipt to encoder input.
        if matches!(event.kind, 0x20004 | 0x20006 | 0x20008 | 0x2000a) {
            core.last_applied_ctl = event.status.controller_ns;
        }
        if !matches!(event.kind, 0x20004 | 0x20008 | 0x2000a | 0x2000c) {
            return Ok(());
        }
        if event.status.runtime_nonce != self.bridge.admin.status()?.runtime_nonce {
            return Ok(());
        }
        let mapping = core
            .mapping
            .ok_or(Error::Denied("no trusted controller clock mapping"))?;
        let (earliest, latest) =
            mapping.acquisition(event.status.controller_ns, event.captured_ns)?;
        core.next_observation = core
            .next_observation
            .checked_add(1)
            .ok_or(Error::Denied("observation sequence exhausted"))?;
        let observation = Observation {
            id: core.next_observation,
            device: event.status.device_identity,
            boot: event.status.controller_boot,
            session: event.status.controller_session,
            runtime_epoch: event.status.runtime_nonce,
            source_sequence: event.sequence,
            controller_ns: event.status.controller_ns,
            acquired_earliest_ns: earliest,
            acquired_latest_ns: latest,
            valid_until_ns: earliest
                .checked_add(1000 * MS)
                .ok_or(Error::Denied("observation cutoff overflow"))?,
            left_encoder: event.status.left_encoder,
            right_encoder: event.status.right_encoder,
            simulated: true,
        };
        if core.observations.len() == 32 {
            core.observations.pop_front();
        }
        core.observations.push_back(observation.clone());
        if event.kind == 0x20004 {
            core.rearm_pending = false;
        }
        if let Some(slot) = core.slot.as_ref().filter(|s| {
            !s.stop.load(Ordering::Acquire) && !s.context.capture.recorder.health().revoke_required
        }) {
            slot.context.capture.record(
                1,
                event.captured_ns,
                EventKind::Observation,
                &observation,
            )?;
        }
        Ok(())
    }
}
impl Drop for Engine {
    fn drop(&mut self) {
        let _ = self.bridge.revoke();
        if let Ok(core) = self.core.get_mut() {
            if let Some(slot) = core.slot.as_ref() {
                slot.stop.store(true, Ordering::Release);
            }
        }
        self.bridge.release_runtime();
    }
}
fn register_observation(bridge: &Bridge, core: &mut Core, observation: &Observation) -> Result<()> {
    if observation.id == core.registered_observation {
        return Ok(());
    }
    if observation.id < core.registered_observation {
        return Err(Error::Denied("observation context already superseded"));
    }
    let mut request = Request::new(Opcode::Observe);
    request.runtime_nonce = observation.runtime_epoch;
    request.observation = observation.id;
    request.acquired_earliest_ns = observation.acquired_earliest_ns;
    request.acquired_latest_ns = observation.acquired_latest_ns;
    request.valid_until_ns = observation.valid_until_ns;
    request.context_revision = 1;
    bridge
        .acquisition
        .read()
        .unwrap()
        .as_ref()
        .ok_or(Error::Denied("acquisition role retired"))?
        .request(&mut request)?;
    core.registered_observation = observation.id;
    Ok(())
}
fn recovered_mapping_ready(mapping: Option<Mapping>, status: &Status, now: u64) -> bool {
    status.state == 0
        && status.flags & 1 != 0
        && mapping.is_some_and(|m| m.controller_lower(now).is_ok())
}
fn advance_generation(value: &AtomicU64) -> std::result::Result<u64, u64> {
    value.fetch_update(Ordering::AcqRel, Ordering::Acquire, |v| v.checked_add(1))
}
fn proposal_digest(
    binding: &Binding,
    instance: u64,
    parent: [u8; 32],
    target: Target,
    observation: u64,
) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"actryn wheel proposal 1\0");
    h.update(binding.principal);
    h.update(binding.attempt);
    h.update(binding.namespace);
    h.update(binding.session_deadline_ns.to_le_bytes());
    h.update(configuration_digest());
    h.update(instance.to_le_bytes());
    h.update(parent);
    h.update(target.left_ticks.to_le_bytes());
    h.update(target.right_ticks.to_le_bytes());
    h.update(target.duration_ms.to_le_bytes());
    h.update(observation.to_le_bytes());
    h.finalize().into()
}
fn sample_digest(request: &Request) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"actryn fixed sample 1\0");
    h.update(request.runtime_nonce);
    for value in [
        request.grant,
        request.operation,
        request.stream,
        request.sequence,
        request.deadline_ns,
        request.observation,
        request.context_revision,
    ] {
        h.update(value.to_le_bytes());
    }
    h.update(request.left_permille.to_le_bytes());
    h.update(request.right_permille.to_le_bytes());
    h.finalize().into()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn immutable_binding_and_digest_never_extend_a_retry() {
        let binding = Binding {
            principal: [1; 32],
            attempt: [2; 16],
            namespace: [3; 16],
            session_deadline_ns: 50,
        };
        assert!(binding.validate(49).is_ok());
        assert!(binding.validate(50).is_err());
        let target = Target {
            left_ticks: 1,
            right_ticks: -1,
            duration_ms: 1000,
        };
        let digest = proposal_digest(&binding, 1, [4; 32], target, 7);
        let mut changed = binding.clone();
        changed.session_deadline_ns += 1;
        assert_ne!(digest, proposal_digest(&changed, 1, [4; 32], target, 7));
        changed = binding.clone();
        changed.principal = [9; 32];
        assert_ne!(digest, proposal_digest(&changed, 1, [4; 32], target, 7));
        assert_ne!(digest, proposal_digest(&binding, 1, [4; 32], target, 8));
        assert_eq!(digest, proposal_digest(&binding, 1, [4; 32], target, 7));
    }
    #[test]
    fn expired_or_unacknowledged_mapping_cannot_complete_recovery() {
        let mapping = Mapping::new(990 * MS, 1000 * MS, 2000 * MS).unwrap();
        let mut status = Status {
            state: 0,
            flags: 1,
            ..Status::default()
        };
        assert!(recovered_mapping_ready(Some(mapping), &status, 1001 * MS));
        assert!(!recovered_mapping_ready(
            Some(mapping),
            &status,
            60_990 * MS
        ));
        status.flags = 0;
        assert!(!recovered_mapping_ready(Some(mapping), &status, 1001 * MS));
        status.flags = 1;
        status.state = 4;
        assert!(!recovered_mapping_ready(Some(mapping), &status, 1001 * MS));
    }
    #[test]
    fn generation_exhaustion_never_wraps() {
        let value = AtomicU64::new(u64::MAX - 1);
        assert!(advance_generation(&value).is_ok());
        assert!(advance_generation(&value).is_err());
        assert_eq!(value.load(Ordering::Acquire), u64::MAX);
    }
    #[test]
    fn engine_is_shared_without_an_outer_task_mutex() {
        fn shared<T: Send + Sync>() {}
        shared::<Engine>();
    }
    #[test]
    fn observation_poll_cannot_make_cached_data_fresh() {
        let o = Observation {
            id: 1,
            device: [1; 16],
            boot: 1,
            session: 1,
            runtime_epoch: [2; 16],
            source_sequence: 3,
            controller_ns: 0,
            acquired_earliest_ns: 100,
            acquired_latest_ns: 110,
            valid_until_ns: 1_000_000_100,
            left_encoder: 0,
            right_encoder: 0,
            simulated: true,
        };
        assert!(o.fresh(109).is_err());
        assert!(o.fresh(110).is_ok());
        assert!(o.fresh(1_000_000_100).is_err());
    }
}
