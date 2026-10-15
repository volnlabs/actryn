use std::{fmt, io};
pub type NamespaceId = [u8; 16];
pub type RequestKey = [u8; 32];
pub type Result<T> = std::result::Result<T, Error>;
#[derive(Debug)]
pub enum Error {
    Rejected(&'static str),
    Conflict,
    Capacity,
    Faulted,
    Io(io::Error),
    Sqlite(rusqlite::Error),
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
/// Complete controller/runtime operation epoch. The kernel supplies these IDs;
/// this registry cannot mint a grant, stream, operation or replacement identity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct OperationId {
    pub device: [u8; 16],
    pub boot: u64,
    pub session: u64,
    pub runtime_nonce: [u8; 16],
    pub grant: u64,
    pub instance: u64,
    pub operation: u64,
    pub stream: u64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Intent {
    pub digest: [u8; 32],
    pub configuration_digest: [u8; 32],
    pub instance: u64,
    pub grant: u64,
    pub context_revision: u64,
    pub deadline_ns: u64,
    pub observation: u64,
    pub payload: Vec<u8>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AuthorityError {
    Denied,
    Unavailable,
    OutcomeUnknown,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CloseAck {
    Requested,
    LocallyClosed { transition: u64 },
}
/// Trusted short synchronous kernel callbacks; none may wait for storage, UART
/// completion, reconciliation or reenter the registry. `submit` performs fresh
/// kernel live-condition validation. The kernel remains the sole authority.
pub trait Authority: Send + Sync + 'static {
    fn allocate(&self, intent: &Intent) -> std::result::Result<OperationId, AuthorityError>;
    fn submit(
        &self,
        operation: &OperationId,
        intent: &Intent,
    ) -> std::result::Result<(), AuthorityError>;
    fn close(&self, operation: &OperationId) -> std::result::Result<CloseAck, AuthorityError>;
}
#[repr(u8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    PendingIntent = 1,
    IntentDurable,
    Submitted,
    CancelPending,
    CancelledDurable,
    Completed,
    Rejected,
    OutcomeUnknown,
}
impl Phase {
    pub(crate) fn parse(n: u8) -> Result<Self> {
        Ok(match n {
            1 => Self::PendingIntent,
            2 => Self::IntentDurable,
            3 => Self::Submitted,
            4 => Self::CancelPending,
            5 => Self::CancelledDurable,
            6 => Self::Completed,
            7 => Self::Rejected,
            8 => Self::OutcomeUnknown,
            _ => return Err(Error::Rejected("invalid persisted phase")),
        })
    }
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Closure {
    #[default]
    NotRequested,
    NotAllocated,
    Requested,
    LocallyClosed {
        transition: u64,
    },
    Failed(AuthorityError),
}
impl From<std::result::Result<CloseAck, AuthorityError>> for Closure {
    fn from(ack: std::result::Result<CloseAck, AuthorityError>) -> Self {
        match ack {
            Ok(CloseAck::Requested) => Self::Requested,
            Ok(CloseAck::LocallyClosed { transition }) => Self::LocallyClosed { transition },
            Err(error) => Self::Failed(error),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Snapshot {
    pub namespace: NamespaceId,
    pub key: RequestKey,
    pub digest: Option<[u8; 32]>,
    pub operation: Option<OperationId>,
    pub revision: u64,
    pub durable_revision: u64,
    pub phase: Phase,
    pub terminal: bool,
    pub closure: Closure,
    pub persistence_failed: bool,
}
impl Snapshot {
    pub fn key_cancelled_durable(&self) -> bool {
        self.phase == Phase::CancelledDurable
            && self.durable_revision >= self.revision
            && !self.persistence_failed
    }
}
#[derive(Clone, Debug)]
pub struct Limits {
    pub keys: usize,
    pub cancellation_keys: usize,
    pub namespaces: usize,
    pub pending_jobs: usize,
    pub closure_jobs: usize,
    pub max_payload_bytes: usize,
    pub database_bytes: u64,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            keys: 1024,
            cancellation_keys: 64,
            namespaces: 16,
            pending_jobs: 128,
            closure_jobs: 32,
            max_payload_bytes: 4096,
            database_bytes: 16_777_216,
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Fault {
    Storage,
    Capacity,
    Queue,
    AuthorityUnknown,
    WriterStopped,
    CounterExhausted,
}
#[derive(Clone, Debug)]
pub struct Health {
    pub admission_open: bool,
    pub revoke_required: bool,
    pub fault: Option<Fault>,
    pub pending_jobs: usize,
    pub keys: usize,
    pub namespaces: usize,
    pub persistence_failed: bool,
}

/// Historical projection only; unfinished durable records are OUTCOME_UNKNOWN.
/// This does not mutate a durable revision or claim downstream reconciliation.
#[derive(Clone, Debug)]
pub struct Inspection {
    pub namespace_exists: bool,
    pub snapshot: Option<Snapshot>,
}
