//! Bounded recorder memory. Storage belongs exclusively to `Writer`; no admission,
//! health or transition-event method performs filesystem/database operations.
mod recovery_db;
mod storage;
use sha2::{Digest, Sha256};
use std::{
    collections::VecDeque,
    fmt, io,
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
pub use storage::{Recovery, ReplayEligibility, SourceSummary};

pub type Result<T> = std::result::Result<T, Error>;
#[derive(Debug)]
pub enum Error {
    Rejected(&'static str),
    Io(io::Error),
    Sqlite(rusqlite::Error),
    Mcap(mcap::McapError),
    DiskBudget,
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for Error {}
impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Self::Io(e)
    }
}
impl From<rusqlite::Error> for Error {
    fn from(e: rusqlite::Error) -> Self {
        Self::Sqlite(e)
    }
}
impl From<mcap::McapError> for Error {
    fn from(e: mcap::McapError) -> Self {
        Self::Mcap(e)
    }
}
#[repr(u8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Origin {
    Runtime = 1,
    Kernel,
    Controller,
    Broker,
    Agent,
    Operator,
}
#[repr(u8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EventKind {
    Activation = 1,
    Configuration,
    Input,
    ModelOutput,
    Execution,
    Intervention,
    Observation,
    AgentPayload,
    Transition,
    Prefix,
    /// A trusted source reports an external discontinuity, independently of
    /// this producer's recorder-local record ordinals.
    SourceGap,
}
impl EventKind {
    fn from_byte(n: u8) -> Result<Self> {
        Ok(match n {
            1 => Self::Activation,
            2 => Self::Configuration,
            3 => Self::Input,
            4 => Self::ModelOutput,
            5 => Self::Execution,
            6 => Self::Intervention,
            7 => Self::Observation,
            8 => Self::AgentPayload,
            9 => Self::Transition,
            10 => Self::Prefix,
            11 => Self::SourceGap,
            _ => return Err(Error::Rejected("unknown event kind")),
        })
    }
    fn reserved(self) -> bool {
        matches!(
            self,
            Self::Transition | Self::Intervention | Self::SourceGap
        )
    }
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum CapturePolicy {
    #[default]
    MetadataOnly,
    FullPayload,
}
#[derive(Clone, Debug)]
pub struct ProducerSpec {
    pub identity: [u8; 16],
    pub session: u64,
    pub origin: Origin,
    pub clock_domain: String,
    pub clock_error_ns: u64,
    pub requested: Vec<EventKind>,
    pub required_for_replay: bool,
}
#[derive(Clone, Debug)]
pub struct CaptureSpec {
    pub attempt: [u8; 16],
    pub profile_digest: [u8; 32],
    pub configuration_digest: [u8; 32],
    pub policy: CapturePolicy,
    pub retention: String,
    pub redaction: String,
    pub producers: Vec<ProducerSpec>,
}
#[derive(Clone, Debug)]
pub struct Limits {
    pub disk_bytes: u64,
    pub batch_bytes: u64,
    pub volatile_bytes: usize,
    pub volatile_records: usize,
    pub reserved_bytes: usize,
    pub reserved_records: usize,
    pub max_pending_age: Duration,
    pub heartbeat: Duration,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            disk_bytes: 67_108_864,
            batch_bytes: 2_097_152,
            volatile_bytes: 1_048_576,
            volatile_records: 4096,
            reserved_bytes: 16384,
            reserved_records: 64,
            max_pending_age: Duration::from_millis(2000),
            heartbeat: Duration::from_millis(100),
        }
    }
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Frontiers {
    /// Positions in the producer's declared record sequence, not an implicit
    /// device sequence. Embeddings must retain external source identities.
    pub read: u64,
    pub queued: u64,
    pub durable: u64,
    /// Missing record ranges plus explicit source-fault reports; not the
    /// number of missing external device events. Recovery counts durable only.
    pub gap_count: u64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HealthIssue {
    Capacity,
    PendingAge,
    StorageFailure,
    SourceGap,
    WriterStopped,
    DiskCapacity,
}
#[derive(Clone, Debug)]
pub struct Health {
    pub admission_open: bool,
    pub revoke_required: bool,
    pub issues: Vec<HealthIssue>,
    pub pending_bytes: usize,
    pub pending_records: usize,
    pub pending_age: Duration,
    pub reader_heartbeat_ns: u64,
    pub writer_heartbeat_ns: u64,
    pub overflow_count: u64,
    pub frontiers: Vec<Frontiers>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapturedRecord {
    pub producer: usize,
    pub origin: Origin,
    pub sequence: u64,
    pub source_time_ns: u64,
    pub captured_ns: u64,
    pub kind: EventKind,
    pub payload: Option<Vec<u8>>,
    pub metadata: bool,
    pub digest: [u8; 32],
    pub input_bytes: u64,
}
struct Pending {
    record: CapturedRecord,
    at: Instant,
    charge: usize,
}
struct State {
    staged: VecDeque<Pending>,
    queued: VecDeque<Pending>,
    frontiers: Vec<Frontiers>,
    reported_source_faults: Vec<u64>,
    pending_bytes: usize,
    pending_records: usize,
    pending_since: Option<Instant>,
    issues: Vec<HealthIssue>,
    overflow_count: u64,
    reader_heartbeat_ns: u64,
    writer_heartbeat_ns: u64,
}
impl State {
    fn issue(&mut self, issue: HealthIssue) {
        if !self.issues.contains(&issue) {
            self.issues.push(issue);
        }
    }
}
struct Shared {
    state: Mutex<State>,
    spec: CaptureSpec,
    limits: Limits,
    clock: Instant,
}
#[derive(Clone)]
pub struct Recorder {
    shared: Arc<Shared>,
}
/// A channel capability issued by the trusted embedding caller, never by payload.
#[derive(Clone)]
pub struct Producer {
    shared: Arc<Shared>,
    index: usize,
}
pub struct Writer {
    shared: Arc<Shared>,
    store: storage::Store,
    failed: bool,
}
fn lock(shared: &Shared) -> std::sync::MutexGuard<'_, State> {
    // Poisoning cannot silently restore eligibility.
    shared.state.lock().unwrap_or_else(|poison| {
        let mut state = poison.into_inner();
        state.issue(HealthIssue::StorageFailure);
        state
    })
}
fn now(shared: &Shared) -> u64 {
    u64::try_from(shared.clock.elapsed().as_nanos()).unwrap_or(u64::MAX)
}
fn pending_too_old(start: Instant, maximum: Duration) -> bool {
    start.elapsed() >= maximum
}
impl Recorder {
    /// Preparation only: creates a NEW capture directory and durable immutable manifest.
    pub fn create(
        path: impl AsRef<Path>,
        spec: CaptureSpec,
        limits: Limits,
    ) -> Result<(Self, Writer)> {
        if limits.disk_bytes < 1_048_576
            || limits.disk_bytes > 1_073_741_824
            || limits.batch_bytes < 16_384
            || limits.batch_bytes > 8_388_608
            || limits.batch_bytes > limits.disk_bytes / 2
            || limits.max_pending_age.as_nanos() > u64::MAX as u128
            || limits.volatile_records == 0
            || limits.volatile_records > 4096
            || limits.volatile_bytes < 512
            || limits.volatile_bytes > 1_048_576
            || limits.reserved_records == 0
            || limits.reserved_records >= limits.volatile_records
            || limits.reserved_bytes < 256
            || limits.reserved_bytes >= limits.volatile_bytes
            || limits.max_pending_age.is_zero()
            || limits.heartbeat.is_zero()
            || limits.heartbeat > limits.max_pending_age
            || spec.producers.is_empty()
            || spec.producers.len() > 32
            || spec.retention.len() > 256
            || spec.redaction.len() > 256
        {
            return Err(Error::Rejected("invalid finite recorder limits/manifest"));
        }
        for (i, p) in spec.producers.iter().enumerate() {
            if p.identity == [0; 16]
                || p.session == 0
                || p.clock_domain.is_empty()
                || p.clock_domain.len() > 128
                || p.requested.is_empty()
                || p.requested.len() > 10
                || spec.producers[..i]
                    .iter()
                    .any(|other| other.identity == p.identity && other.session == p.session)
                || (p.origin == Origin::Agent
                    && (p.required_for_replay
                        || p.requested.iter().any(|k| *k != EventKind::AgentPayload)))
            {
                return Err(Error::Rejected("invalid producer capability"));
            }
        }
        let store = storage::Store::create(path.as_ref(), &spec, &limits)?;
        let shared = Arc::new(Shared {
            state: Mutex::new(State {
                staged: VecDeque::new(),
                queued: VecDeque::new(),
                frontiers: vec![Frontiers::default(); spec.producers.len()],
                reported_source_faults: vec![0; spec.producers.len()],
                pending_bytes: 0,
                pending_records: 0,
                pending_since: None,
                issues: Vec::new(),
                overflow_count: 0,
                reader_heartbeat_ns: 0,
                writer_heartbeat_ns: 0,
            }),
            spec,
            limits,
            clock: Instant::now(),
        });
        Ok((
            Self {
                shared: shared.clone(),
            },
            Writer {
                shared,
                store,
                failed: false,
            },
        ))
    }
    /// Caller authentication precedes issuing this non-forgeable origin binding.
    pub fn producer(&self, index: usize) -> Option<Producer> {
        (index < self.shared.spec.producers.len()).then(|| Producer {
            shared: self.shared.clone(),
            index,
        })
    }
    pub fn now_ns(&self) -> u64 {
        now(&self.shared)
    }
    /// Transfers copied records to a bounded writer batch; no storage work.
    pub fn queue_read(&self) {
        let mut state = lock(&self.shared);
        while let Some(record) = state.staged.pop_front() {
            state.frontiers[record.record.producer].queued = record.record.sequence;
            state.queued.push_back(record);
        }
    }
    /// Must be polled independently by the manager at least once per heartbeat.
    /// Health loss latches; immediate close/revoke is required (zero continuation).
    pub fn health(&self) -> Health {
        let mut state = lock(&self.shared);
        if state
            .pending_since
            .is_some_and(|start| pending_too_old(start, self.shared.limits.max_pending_age))
        {
            state.issue(HealthIssue::PendingAge);
        }
        Health {
            admission_open: state.issues.is_empty(),
            revoke_required: !state.issues.is_empty(),
            issues: state.issues.clone(),
            pending_bytes: state.pending_bytes,
            pending_records: state.pending_records,
            pending_age: state
                .pending_since
                .map_or(Duration::ZERO, |start| start.elapsed()),
            reader_heartbeat_ns: state.reader_heartbeat_ns,
            writer_heartbeat_ns: state.writer_heartbeat_ns,
            overflow_count: state.overflow_count,
            frontiers: state.frontiers.clone(),
        }
    }
    pub fn recover(path: impl AsRef<Path>) -> Result<Recovery> {
        storage::recover(path.as_ref())
    }
}
impl Producer {
    pub fn origin(&self) -> Origin {
        self.shared.spec.producers[self.index].origin
    }
    pub fn heartbeat(&self) {
        lock(&self.shared).reader_heartbeat_ns = now(&self.shared);
    }
    pub fn read(
        &self,
        sequence: u64,
        source_time_ns: u64,
        kind: EventKind,
        payload: &[u8],
    ) -> Result<()> {
        if kind == EventKind::Prefix {
            return Err(Error::Rejected("use trusted seal_prefix API"));
        }
        self.copy(sequence, source_time_ns, kind, payload, false)
    }
    /// Retains bounded trusted structural metadata, without changing raw payload
    /// policy. Agent, input and model-output bytes cannot use this path.
    pub fn read_metadata(
        &self,
        sequence: u64,
        source_time_ns: u64,
        kind: EventKind,
        metadata: &[u8],
    ) -> Result<()> {
        if self.origin() == Origin::Agent
            || matches!(
                kind,
                EventKind::Input
                    | EventKind::ModelOutput
                    | EventKind::AgentPayload
                    | EventKind::Prefix
            )
        {
            return Err(Error::Rejected(
                "source/kind cannot claim structural metadata",
            ));
        }
        self.copy(sequence, source_time_ns, kind, metadata, true)
    }
    /// Trusted source asserts its complete stream prefix through a recorder-clock
    /// interval. A seal is evidence from that capability, not independent proof.
    pub fn seal_prefix(&self, sequence: u64, through_ns: u64) -> Result<()> {
        if through_ns > now(&self.shared) {
            return Err(Error::Rejected("future prefix seal"));
        }
        self.copy(
            sequence,
            through_ns,
            EventKind::Prefix,
            &through_ns.to_le_bytes(),
            true,
        )
    }
    fn copy(
        &self,
        sequence: u64,
        source_time_ns: u64,
        kind: EventKind,
        payload: &[u8],
        metadata: bool,
    ) -> Result<()> {
        let spec = &self.shared.spec.producers[self.index];
        let limits = &self.shared.limits;
        if (kind != EventKind::Prefix && !spec.requested.contains(&kind))
            || (spec.origin == Origin::Agent && kind != EventKind::AgentPayload)
        {
            return Err(Error::Rejected("kind outside source capability"));
        }
        if kind == EventKind::SourceGap && (!metadata || payload.is_empty()) {
            return Err(Error::Rejected(
                "source fault requires retained trusted metadata",
            ));
        }
        let reserved = kind.reserved() && spec.origin != Origin::Agent;
        let retained = metadata
            || self.shared.spec.policy == CapturePolicy::FullPayload
            || kind == EventKind::Prefix;
        let charge = std::mem::size_of::<Pending>()
            .checked_add(if retained { payload.len() } else { 32 })
            .ok_or(Error::Rejected("record size overflow"))?;
        let mut state = lock(&self.shared);
        let frontier = state.frontiers[self.index];
        if sequence == 0 || sequence <= frontier.read {
            return Err(Error::Rejected("retired producer sequence"));
        }
        // A known source fault closes health even when its bounded evidence
        // reserve is exhausted. A repeated failed admission does not count it
        // twice; no durable claim is made until its record is checkpointed.
        if kind == EventKind::SourceGap {
            state.issue(HealthIssue::SourceGap);
            if sequence > state.reported_source_faults[self.index] {
                state.reported_source_faults[self.index] = sequence;
                state.frontiers[self.index].gap_count =
                    state.frontiers[self.index].gap_count.saturating_add(1);
            }
        }
        if state
            .pending_since
            .is_some_and(|start| pending_too_old(start, limits.max_pending_age))
        {
            state.issue(HealthIssue::PendingAge);
        }
        if !reserved && !state.issues.is_empty() {
            return Err(Error::Rejected("recorder unhealthy"));
        }
        let max_bytes = limits.volatile_bytes - if reserved { 0 } else { limits.reserved_bytes };
        let max_records =
            limits.volatile_records - if reserved { 0 } else { limits.reserved_records };
        if payload.len() > limits.volatile_bytes
            || charge > max_bytes.saturating_sub(state.pending_bytes)
            || state.pending_records >= max_records
        {
            state.issue(HealthIssue::Capacity);
            state.overflow_count = state.overflow_count.saturating_add(1);
            return Err(Error::Rejected("bounded recorder capacity"));
        }
        if frontier.read.checked_add(1) != Some(sequence) {
            state.frontiers[self.index].gap_count =
                state.frontiers[self.index].gap_count.saturating_add(1);
            if spec.required_for_replay {
                state.issue(HealthIssue::SourceGap);
            }
        }
        let captured_ns = now(&self.shared);
        let at = Instant::now();
        let record = CapturedRecord {
            producer: self.index,
            origin: spec.origin,
            sequence,
            source_time_ns,
            captured_ns,
            kind,
            payload: retained.then(|| payload.to_vec()),
            metadata,
            digest: Sha256::digest(payload).into(),
            input_bytes: payload.len() as u64,
        };
        state.staged.push_back(Pending { record, at, charge });
        state.pending_records += 1;
        state.pending_bytes += charge;
        state.pending_since.get_or_insert(at);
        state.frontiers[self.index].read = sequence;
        state.reader_heartbeat_ns = captured_ns;
        if !reserved && (state.pending_records >= max_records || state.pending_bytes >= max_bytes) {
            state.issue(HealthIssue::Capacity);
        }
        Ok(())
    }
}
impl Writer {
    /// Performs storage only after releasing the queue mutex. Frontiers and capacity
    /// advance only after MCAP sync and SQLite FULL checkpoint commit succeed.
    pub fn flush(&mut self) -> Result<usize> {
        if self.failed {
            return Err(Error::Rejected("writer previously failed"));
        }
        let batch: Vec<_> = {
            let mut state = lock(&self.shared);
            state.writer_heartbeat_ns = now(&self.shared);
            state.queued.drain(..).collect()
        };
        if batch.is_empty() {
            return Ok(0);
        }
        if let Err(error) = self.store.commit(&batch, &self.shared.spec) {
            self.failed = true;
            lock(&self.shared).issue(if matches!(error, Error::DiskBudget) {
                HealthIssue::DiskCapacity
            } else {
                HealthIssue::StorageFailure
            });
            return Err(error);
        }
        let count = batch.len();
        let mut state = lock(&self.shared);
        for pending in batch {
            state.frontiers[pending.record.producer].durable = pending.record.sequence;
            state.pending_bytes -= pending.charge;
            state.pending_records -= 1;
        }
        state.pending_since = state
            .staged
            .front()
            .map(|p| p.at)
            .into_iter()
            .chain(state.queued.front().map(|p| p.at))
            .min();
        state.writer_heartbeat_ns = now(&self.shared);
        Ok(count)
    }
    /// Run on a dedicated storage thread. Stop/join is an operator shutdown action,
    /// never part of admission, urgent cancellation or recorder-health revocation.
    pub fn run(mut self, stop: Arc<AtomicBool>) -> Result<()> {
        while !stop.load(Ordering::Acquire) {
            self.flush()?;
            thread::sleep(self.shared.limits.heartbeat);
        }
        self.flush()?;
        Ok(())
    }
}
impl Drop for Writer {
    fn drop(&mut self) {
        lock(&self.shared).issue(HealthIssue::WriterStopped);
    }
}
#[cfg(test)]
mod tests;
