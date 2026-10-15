//! Finite, typed diagnostic evidence. Exporting evidence never republishes a tool proposal.
use crate::{observer::ObserverStatus, Inspection};
use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fs, io::Read, os::unix::fs::OpenOptionsExt, path::Path};

pub const MAX_BUNDLE_BYTES: usize = 60 * 1024;
pub const LOG_CAP: usize = 524_288;
pub const LOG_TAIL_BYTES: usize = 2048;
const ARTIFACT_CAP: usize = 16 * 1024;
fn artifact_cap(name: ArtifactName) -> usize {
    match name {
        ArtifactName::Attempt => 1024,
        ArtifactName::Stdout | ArtifactName::Stderr => 5 * 1024,
        ArtifactName::Broker => 10 * 1024,
        ArtifactName::Robot => 4 * 1024,
        ArtifactName::RuntimeBinding | ArtifactName::RuntimeFacts => ARTIFACT_CAP,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactName {
    Attempt,
    RuntimeBinding,
    RuntimeFacts,
    Stdout,
    Stderr,
    Broker,
    Robot,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct Artifact {
    pub name: ArtifactName,
    /// Digest and length of content serialized as compact UTF-8 JSON with sorted object keys.
    pub sha256: String,
    pub bytes: usize,
    pub content: Value,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct Omission {
    pub artifact: ArtifactName,
    pub reason: String,
    pub omitted_records: usize,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct Bundle {
    pub schema: String,
    pub attempt_id: String,
    pub artifacts: Vec<Artifact>,
    pub omissions: Vec<Omission>,
    pub execution_replay_eligible: bool,
}
impl Bundle {
    pub fn new(attempt_id: &str) -> Result<Self> {
        ensure!(
            crate::store::valid_id(attempt_id),
            "invalid evidence identity"
        );
        Ok(Self {
            schema: "actryn.server.evidence.v1".into(),
            attempt_id: attempt_id.into(),
            artifacts: vec![],
            omissions: vec![],
            execution_replay_eligible: false,
        })
    }
    pub fn add(&mut self, name: ArtifactName, content: Value) -> Result<()> {
        ensure!(
            !self.artifacts.iter().any(|a| a.name == name),
            "duplicate evidence artifact"
        );
        let bytes = serde_json::to_vec(&content)?;
        ensure!(
            bytes.len() <= artifact_cap(name),
            "evidence artifact exceeds fixed cap"
        );
        self.artifacts.push(Artifact {
            name,
            sha256: format!("sha256:{:x}", Sha256::digest(&bytes)),
            bytes: bytes.len(),
            content,
        });
        if let Err(error) = self.validate_bound() {
            self.artifacts.pop();
            return Err(error);
        }
        Ok(())
    }
    pub fn omit(&mut self, name: ArtifactName, reason: &str, count: usize) -> Result<()> {
        ensure!(
            self.omissions.len() < 16
                && reason.len() <= 64
                && reason.bytes().all(|b| b.is_ascii_lowercase() || b == b'_'),
            "evidence omission limit"
        );
        self.omissions.push(Omission {
            artifact: name,
            reason: reason.into(),
            omitted_records: count,
        });
        self.validate_bound()
    }
    pub fn validate_bound(&self) -> Result<()> {
        ensure!(
            serde_json::to_vec(self)?.len() <= MAX_BUNDLE_BYTES,
            "evidence bundle exceeds fixed cap"
        );
        Ok(())
    }
    pub fn add_broker(&mut self, inspection: Inspection) -> Result<()> {
        ensure!(
            inspection.attempt.id == self.attempt_id,
            "broker evidence attempt mismatch"
        );
        if let Some(binding) = inspection.robot_binding {
            let total = inspection.robot_requests.len();
            let mut requests = inspection.robot_requests;
            let outstanding = requests.iter().filter(|r| r.outstanding_debit).count();
            // Preserve unresolved handles first. Full observations/replies stay in the durable store.
            requests.sort_by_key(|r| !r.outstanding_debit);
            let content = loop {
                let value = json!({"classification":"trusted_peer_delegation_metadata","binding":binding,"requests":requests,"requests_retained":total,"outstanding_debits":outstanding,"detail_lookup":"robot_query_by_attempt_and_request_key"});
                if serde_json::to_vec(&value)?.len() <= artifact_cap(ArtifactName::Robot) {
                    break value;
                }
                ensure!(!requests.is_empty(), "Robot binding exceeds evidence cap");
                requests.pop();
            };
            if requests.len() < total {
                self.omit(
                    ArtifactName::Robot,
                    "robot_records_omitted_from_export",
                    total - requests.len(),
                )?;
            }
            self.add(ArtifactName::Robot, content)?;
        }
        let total = inspection.denials.len() + inspection.denials_omitted;
        let mut denials = inspection.denials;
        let content = loop {
            let value = json!({"classification":"broker_application_policy_and_delegated_accounting",
                "attempt_state":inspection.attempt.state,"attempt_outcome":inspection.attempt.outcome,
                "calls":inspection.calls,"policy_denials":denials,"policy_denials_retained":total,
                "evidence_gaps":inspection.evidence_gaps});
            if serde_json::to_vec(&value)?.len() <= artifact_cap(ArtifactName::Broker) {
                break value;
            }
            ensure!(!denials.is_empty(), "broker metadata exceeds evidence cap");
            denials.pop();
        };
        if denials.len() < total {
            self.omit(
                ArtifactName::Broker,
                "denial_records_omitted_from_export",
                total - denials.len(),
            )?;
        }
        self.add(ArtifactName::Broker, content)
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ResourceFacts {
    pub classification: String,
    pub captured_boottime_ms: i64,
    pub stage: String,
    pub counters: BTreeMap<String, String>,
    pub unavailable: Vec<String>,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct RuntimeFacts {
    pub resources: ResourceFacts,
    pub observer: Option<ObserverStatus>,
    pub observer_health_unavailable: bool,
}
/// Reads only the fixed cgroup counter inventory. No failure is labelled a policy denial.
pub fn capture_resources(cgroup: &Path, now: i64) -> ResourceFacts {
    let mut result = ResourceFacts {
        classification: "observed_cgroup_v2_counters".into(),
        captured_boottime_ms: now,
        stage: "after_descendants_empty_before_runtime_delete".into(),
        counters: BTreeMap::new(),
        unavailable: vec![],
    };
    for name in [
        "memory.current",
        "memory.peak",
        "memory.events",
        "cpu.stat",
        "io.stat",
        "pids.current",
        "pids.peak",
        "pids.events",
    ] {
        let read = (|| -> Result<String> {
            let mut bytes = vec![];
            fs::File::open(cgroup.join(name))?
                .take(2049)
                .read_to_end(&mut bytes)?;
            ensure!(bytes.len() <= 2048, "counter exceeds cap");
            let value = String::from_utf8(bytes)?;
            ensure!(
                value
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b" \t\n:=_".contains(&b)),
                "unexpected counter encoding"
            );
            let cap = if name == "io.stat" { 2048 } else { 1024 };
            ensure!(
                serde_json::to_vec(&value)?.len() <= cap,
                "encoded counter exceeds cap"
            );
            Ok(value)
        })();
        match read {
            Ok(value) => {
                result.counters.insert(name.into(), value);
            }
            Err(_) => result.unavailable.push(name.into()),
        }
    }
    result
}

#[derive(Debug, Serialize, Deserialize)]
pub struct LogEvidence {
    pub classification: String,
    pub retained_bytes: usize,
    pub retained_sha256: String,
    pub source_truncated: bool,
    pub file_complete: bool,
    pub tail_omitted_bytes: usize,
    pub tail_encoding: String,
    pub tail: String,
}
/// Called with an internal attempt directory and an enum-selected stream, never a caller path.
pub fn log_evidence(directory: &Path, stderr: bool, complete: bool) -> Result<LogEvidence> {
    let name = if stderr { "stderr" } else { "stdout" };
    let file = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(directory.join(format!("{name}.log")))?;
    ensure!(file.metadata()?.is_file(), "log is not a regular file");
    let mut bytes = vec![];
    file.take((LOG_CAP + 1) as u64).read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= LOG_CAP, "retained log exceeds fixed cap");
    let offset = bytes.len().saturating_sub(LOG_TAIL_BYTES);
    let tail = bytes[offset..]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    Ok(LogEvidence {
        classification: "untrusted_agent_output_not_policy_attribution".into(),
        retained_bytes: bytes.len(),
        retained_sha256: format!("sha256:{:x}", Sha256::digest(&bytes)),
        source_truncated: directory.join(format!("{name}.truncated")).exists(),
        file_complete: complete,
        tail_omitted_bytes: offset,
        tail_encoding: "hex".into(),
        tail,
    })
}
