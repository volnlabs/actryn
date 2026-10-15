use serde::{Deserialize, Serialize};
use std::{fmt, io};
pub type Result<T> = std::result::Result<T, Error>;
#[derive(Debug)]
pub enum Error {
    Io(io::Error),
    Intent(robot_intent::Error),
    Evidence(evidence::Error),
    Denied(&'static str),
    Conflict,
    Busy,
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for Error {}
impl From<io::Error> for Error {
    fn from(v: io::Error) -> Self {
        Self::Io(v)
    }
}
impl From<robot_intent::Error> for Error {
    fn from(v: robot_intent::Error) -> Self {
        Self::Intent(v)
    }
}
impl From<evidence::Error> for Error {
    fn from(v: evidence::Error) -> Self {
        Self::Evidence(v)
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Binding {
    pub principal: [u8; 32],
    pub attempt: [u8; 16],
    pub namespace: [u8; 16],
    pub session_deadline_ns: u64,
}
impl Binding {
    pub(crate) fn validate(&self, now: u64) -> Result<()> {
        if self.principal == [0; 32]
            || self.attempt == [0; 16]
            || self.namespace == [0; 16]
            || self.session_deadline_ns <= now
        {
            return Err(Error::Denied("invalid or expired binding"));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Prepared {
    pub binding: Binding,
    pub instance: u64,
    pub configuration_digest: [u8; 32],
    pub runtime_epoch: [u8; 16],
}
#[derive(Clone, Debug, Serialize)]
pub struct Observation {
    pub id: u64,
    pub device: [u8; 16],
    pub boot: u64,
    pub session: u64,
    pub runtime_epoch: [u8; 16],
    pub source_sequence: u64,
    pub controller_ns: u64,
    pub acquired_earliest_ns: u64,
    pub acquired_latest_ns: u64,
    pub valid_until_ns: u64,
    pub left_encoder: i64,
    pub right_encoder: i64,
    pub simulated: bool,
}
impl Observation {
    pub(crate) fn fresh(&self, now: u64) -> Result<()> {
        if now < self.acquired_latest_ns
            || now >= self.valid_until_ns
            || now.saturating_sub(self.acquired_earliest_ns) > 1_000_000_000
        {
            return Err(Error::Denied("retained observation stale"));
        }
        Ok(())
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum Verdict {
    Pending,
    TargetReached,
    TimedOut,
    Cancelled,
    OutcomeUnknown,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Operation {
    pub device: [u8; 16],
    pub boot: u64,
    pub session: u64,
    pub runtime_nonce: [u8; 16],
    pub grant: u64,
    pub instance: u64,
    pub operation: u64,
    pub stream: u64,
}
impl From<robot_intent::OperationId> for Operation {
    fn from(v: robot_intent::OperationId) -> Self {
        Self {
            device: v.device,
            boot: v.boot,
            session: v.session,
            runtime_nonce: v.runtime_nonce,
            grant: v.grant,
            instance: v.instance,
            operation: v.operation,
            stream: v.stream,
        }
    }
}
impl From<Operation> for robot_intent::OperationId {
    fn from(v: Operation) -> Self {
        Self {
            device: v.device,
            boot: v.boot,
            session: v.session,
            runtime_nonce: v.runtime_nonce,
            grant: v.grant,
            instance: v.instance,
            operation: v.operation,
            stream: v.stream,
        }
    }
}
#[derive(Clone, Debug, Serialize)]
pub struct Snapshot {
    pub namespace: [u8; 16],
    pub key: [u8; 32],
    pub digest: Option<[u8; 32]>,
    pub operation: Option<Operation>,
    pub revision: u64,
    pub durable_revision: u64,
    pub phase: String,
    pub terminal: bool,
    pub closure: String,
    pub cancellation_durable: bool,
    pub persistence_failed: bool,
    pub verdict: Verdict,
    pub reconciled: bool,
}
impl Snapshot {
    pub(crate) fn from_registry(
        v: robot_intent::Snapshot,
        verdict: Verdict,
        reconciled: bool,
    ) -> Self {
        let cancellation_durable = v.key_cancelled_durable();
        Self {
            namespace: v.namespace,
            key: v.key,
            digest: v.digest,
            operation: if v.durable_revision > 0 {
                v.operation.map(Into::into)
            } else {
                None
            },
            revision: v.revision,
            durable_revision: v.durable_revision,
            phase: format!("{:?}", v.phase),
            terminal: v.terminal,
            closure: format!("{:?}", v.closure),
            cancellation_durable,
            persistence_failed: v.persistence_failed,
            verdict,
            reconciled,
        }
    }
}
#[derive(Clone, Debug, Serialize)]
pub struct Health {
    pub healthy: bool,
    pub inhibited: bool,
    pub registry_fault: Option<String>,
    pub evidence_issues: Vec<String>,
    pub pending_records: usize,
    pub pending_bytes: usize,
    pub frontiers: Vec<Frontier>,
}
#[derive(Clone, Debug, Serialize)]
pub struct Frontier {
    pub producer: usize,
    pub read: u64,
    pub queued: u64,
    pub durable: u64,
    pub source_gap_count: u64,
}
#[derive(Clone, Debug, Serialize)]
pub struct RuntimeStatus {
    pub kernel: authority_client::Status,
    pub prepared: Option<Prepared>,
    pub retiring: bool,
    pub recovery_pending: bool,
    pub preparation_ready: bool,
    pub recovery_ready: bool,
    pub event_loss_baseline: Option<u32>,
    pub event_stream_healthy: bool,
    pub health: Health,
    pub operation: Option<Snapshot>,
}
#[derive(Clone, Copy, Debug, Serialize)]
pub enum Progress {
    Pending,
    Ready,
}

#[derive(Clone, Debug, Serialize)]
pub struct Historical {
    pub prepared: Prepared,
    pub snapshot: Option<Snapshot>,
    pub live_authority: bool,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn external_id_is_withheld_until_its_binding_is_durable() {
        let id = robot_intent::OperationId {
            device: [1; 16],
            boot: 1,
            session: 1,
            runtime_nonce: [2; 16],
            grant: 1,
            instance: 1,
            operation: 1,
            stream: 1,
        };
        let mut raw = robot_intent::Snapshot {
            namespace: [3; 16],
            key: [4; 32],
            digest: Some([5; 32]),
            operation: Some(id),
            revision: 1,
            durable_revision: 0,
            phase: robot_intent::Phase::PendingIntent,
            terminal: false,
            closure: robot_intent::Closure::NotRequested,
            persistence_failed: false,
        };
        assert!(
            Snapshot::from_registry(raw.clone(), Verdict::Pending, false)
                .operation
                .is_none()
        );
        raw.durable_revision = 1;
        assert!(Snapshot::from_registry(raw, Verdict::Pending, false)
            .operation
            .is_some());
    }
}
