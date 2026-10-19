//! Fixed-peer Robot delegation. Caller strings never select an endpoint or credential.
use anyhow::{ensure, Context, Result};
use robot_rpc::wire::{self, request::Command};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{path::Path, sync::Arc};

pub const PEER_CONFIG: &str = "/etc/actryn/robot-peer.json";
pub const KEY_CREDENTIAL: &str = "/run/credentials/actryn-serverd.service/robot-client-key";
pub const PER_ATTEMPT_JOBS: usize = 1;
pub const GLOBAL_JOBS: usize = 4;
pub const KEYS_PER_ATTEMPT: usize = 16;
pub const CLOSURE_CAPACITY: usize = 16;
pub const REMOTE_REPORT_BYTES: usize = 4096;

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
pub fn unhex<const N: usize>(text: &str) -> Result<[u8; N]> {
    ensure!(
        text.len() == 2 * N
            && text
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "invalid fixed hex identity"
    );
    let mut value = [0; N];
    for (i, byte) in value.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[i * 2..i * 2 + 2], 16)?;
    }
    Ok(value)
}
pub fn digest(value: &impl Serialize) -> Result<String> {
    Ok(format!(
        "sha256:{:x}",
        Sha256::digest(serde_json::to_vec(value)?)
    ))
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Binding {
    pub attempt_id: String,
    pub namespace: String,
    pub principal: String,
    pub peer_digest: String,
    pub client_certificate_sha256: String,
    pub robot_epoch: String,
    pub robot_configuration_digest: String,
    pub robot_profile_digest: String,
    pub created_ms: i64,
    pub deadline_ms: i64,
}
impl Binding {
    pub fn validate(&self) -> Result<()> {
        unhex::<16>(&self.attempt_id)?;
        unhex::<16>(&self.namespace)?;
        unhex::<16>(&self.robot_epoch)?;
        unhex::<32>(&self.client_certificate_sha256)?;
        unhex::<32>(&self.robot_configuration_digest)?;
        unhex::<32>(&self.robot_profile_digest)?;
        ensure!(
            crate::store::valid_digest(&self.peer_digest)
                && !self.principal.is_empty()
                && self.principal.len() <= 128
                && self
                    .principal
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"-_.".contains(&c))
                && self.created_ms >= 0
                && self.deadline_ms > self.created_ms
                && self.deadline_ms - self.created_ms <= 120_000,
            "invalid robot binding"
        );
        Ok(())
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Handle {
    pub attempt: String,
    pub namespace: String,
    pub key: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub id: u64,
    pub acquired_earliest_ns: u64,
    pub acquired_latest_ns: u64,
    pub valid_until_ns: u64,
    pub controller_ns: u64,
    pub left_ticks: i64,
    pub right_ticks: i64,
    pub simulated: bool,
    pub context_revision: u64,
    /// Local receipt time; Robot timestamps remain in the Robot's BOOTTIME domain.
    pub received_ms: i64,
}
impl Observation {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.id > 0
                && self.context_revision > 0
                && self.simulated
                && self.received_ms >= 0
                && self.acquired_earliest_ns <= self.acquired_latest_ns
                && self.acquired_latest_ns < self.valid_until_ns
                && self.valid_until_ns - self.acquired_earliest_ns <= 1_000_000_000,
            "invalid trusted software observation"
        );
        Ok(())
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Reserved,
    Observed,
    DispatchIntent,
    Accepted,
    Unknown,
    Settled,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Intent {
    pub request_key: String,
    pub request_digest: String,
    pub handle: Handle,
    pub robot_epoch: String,
    pub phase: Phase,
    pub cancellation_requested: bool,
    pub outstanding_debit: bool,
    pub deadline_ms: i64,
    pub observation: Option<Observation>,
    pub observation_digest: Option<String>,
    #[serde(default)]
    pub execution_observation: Option<Observation>,
    #[serde(default)]
    pub execution_observation_digest: Option<String>,
    pub parent_digest: Option<String>,
    pub proposal_digest: Option<String>,
    pub last_remote: Option<RemoteSnapshot>,
    pub historical_response: bool,
    pub remote_unavailable: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Summary {
    pub request_key: String,
    pub handle: Handle,
    pub robot_epoch: String,
    pub phase: Phase,
    pub cancellation_requested: bool,
    pub outstanding_debit: bool,
    pub deadline_ms: i64,
    pub observation_id: Option<u64>,
    pub observation_digest: Option<String>,
    pub execution_observation_id: Option<u64>,
    pub execution_observation_digest: Option<String>,
    pub proposal_digest: Option<String>,
    pub remote_verdict: Option<Verdict>,
    pub cancellation_durable: bool,
    pub reconciled: bool,
    pub historical_response: bool,
    pub remote_unavailable: bool,
}
impl Intent {
    pub fn summary(&self) -> Summary {
        Summary {
            request_key: self.request_key.clone(),
            handle: self.handle.clone(),
            robot_epoch: self.robot_epoch.clone(),
            phase: self.phase.clone(),
            cancellation_requested: self.cancellation_requested,
            outstanding_debit: self.outstanding_debit,
            deadline_ms: self.deadline_ms,
            observation_id: self.observation.as_ref().map(|o| o.id),
            observation_digest: self.observation_digest.clone(),
            execution_observation_id: self.execution_observation.as_ref().map(|o| o.id),
            execution_observation_digest: self.execution_observation_digest.clone(),
            proposal_digest: self.proposal_digest.clone(),
            remote_verdict: self.last_remote.as_ref().map(|s| s.verdict.clone()),
            cancellation_durable: self
                .last_remote
                .as_ref()
                .is_some_and(|s| s.cancellation_durable),
            reconciled: self.last_remote.as_ref().is_some_and(|s| s.reconciled),
            historical_response: self.historical_response,
            remote_unavailable: self.remote_unavailable,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
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
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub enum Verdict {
    Pending,
    TargetReached,
    TimedOut,
    Cancelled,
    OutcomeUnknown,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RemoteSnapshot {
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
impl RemoteSnapshot {
    pub fn validate_for(&self, intent: &Intent) -> Result<()> {
        ensure!(
            self.namespace == unhex::<16>(&intent.handle.namespace)?
                && self.key == unhex::<32>(&intent.handle.key)?,
            "remote handle mismatch"
        );
        ensure!(
            self.phase.len() <= 48
                && self.closure.len() <= 48
                && self.durable_revision <= self.revision
                && serde_json::to_vec(self)?.len() <= REMOTE_REPORT_BYTES,
            "remote report exceeds fixed bounds"
        );
        let terminal_phase = match self.phase.as_str() {
            "PendingIntent" | "IntentDurable" | "Submitted" => false,
            "CancelPending" | "CancelledDurable" | "Completed" | "Rejected" | "OutcomeUnknown" => {
                true
            }
            _ => anyhow::bail!("unknown remote phase"),
        };
        ensure!(
            self.terminal == terminal_phase,
            "remote phase/terminal mismatch"
        );
        let closure_known = matches!(
            self.closure.as_str(),
            "NotRequested"
                | "NotAllocated"
                | "Requested"
                | "Failed(Denied)"
                | "Failed(Unavailable)"
                | "Failed(OutcomeUnknown)"
        ) || self
            .closure
            .strip_prefix("LocallyClosed { transition: ")
            .and_then(|value| value.strip_suffix(" }"))
            .and_then(|value| value.parse::<u64>().ok())
            .is_some_and(|transition| transition > 0);
        ensure!(closure_known, "unknown remote closure");
        if self.cancellation_durable {
            ensure!(
                self.phase == "CancelledDurable"
                    && self.revision > 0
                    && self.durable_revision == self.revision
                    && !self.persistence_failed,
                "remote cancellation is not durably terminal"
            );
            ensure!(
                self.operation.is_some() || self.closure == "NotAllocated",
                "absent operation cancellation has inconsistent closure"
            );
        }
        if let Some(operation) = &self.operation {
            ensure!(
                self.closure != "NotAllocated",
                "allocated operation has absent closure"
            );
            ensure!(
                operation.device != [0; 16]
                    && operation.runtime_nonce != [0; 16]
                    && operation.boot > 0
                    && operation.session > 0
                    && operation.grant > 0
                    && operation.instance > 0
                    && operation.operation > 0
                    && operation.stream > 0,
                "invalid remote operation identity"
            );
        }
        if let Some(old) = &intent.last_remote {
            ensure!(
                self.revision >= old.revision && self.durable_revision >= old.durable_revision,
                "remote revision regressed"
            );
            if let Some(operation) = &old.operation {
                ensure!(
                    self.operation.as_ref() == Some(operation),
                    "remote operation changed"
                );
            }
            if let Some(digest) = old.digest {
                ensure!(self.digest == Some(digest), "remote intent digest changed");
            }
        }
        Ok(())
    }
    pub fn settled(&self) -> bool {
        !self.persistence_failed
            && self.revision > 0
            && self.durable_revision == self.revision
            && self.terminal
            && ((self.cancellation_durable
                && self.phase == "CancelledDurable"
                && self.closure == "NotAllocated"
                && self.operation.is_none()
                && self.verdict != Verdict::OutcomeUnknown)
                || (matches!(self.phase.as_str(), "Completed" | "CancelledDurable")
                    && self.reconciled
                    && self.operation.is_some()
                    // Durable Completed/reconciled proves resource closure even when
                    // task success remains unknown. Unknown work is a different phase.
                    && (matches!(
                        self.verdict,
                        Verdict::TargetReached | Verdict::TimedOut | Verdict::Cancelled
                    ) || (self.phase == "Completed" && self.verdict == Verdict::OutcomeUnknown))))
    }
}

/// Public metadata only. PEM fields contain the CA and public workload certificate, never a key.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PeerConfig {
    pub endpoint: String,
    pub dns_name: String,
    pub robot_leaf_sha256: String,
    pub principal: String,
    pub robot_configuration_digest: String,
    pub robot_profile_digest: String,
    pub ca_pem: String,
    pub client_certificate_pem: String,
}
pub struct Peer {
    config: PeerConfig,
    tls: Arc<rustls::ClientConfig>,
    digest: String,
    client_pin: String,
}
pub enum RemoteReply {
    Snapshot(RemoteSnapshot),
    Historical(Option<RemoteSnapshot>),
    Absent,
}

/// systemd exposes credentials to the service UID in a protected read-only directory.
/// Unlike public root configuration, this file may be owned by the service account.
fn credential_permissions(mode: u32, owner: u32, uid: u32, acl: &[u8]) -> bool {
    if (owner == 0 || owner == uid) && mode & 0o077 == 0 {
        return true;
    }
    if owner != 0 || mode & 0o777 != 0o440 || uid == 0 {
        return false;
    }
    // Linux POSIX ACL v2: root and this service may read; no group/other access.
    let mut expected = 2_u32.to_le_bytes().to_vec();
    for (tag, permissions, id) in [
        (1_u16, 4_u16, u32::MAX),
        (2, 4, uid),
        (4, 0, u32::MAX),
        (16, 4, u32::MAX),
        (32, 0, u32::MAX),
    ] {
        expected.extend_from_slice(&tag.to_le_bytes());
        expected.extend_from_slice(&permissions.to_le_bytes());
        expected.extend_from_slice(&id.to_le_bytes());
    }
    acl == expected
}
pub(crate) fn read_credential(path: &Path, limit: usize) -> Result<Vec<u8>> {
    use std::{
        io::Read,
        os::fd::AsRawFd,
        os::unix::fs::{MetadataExt, OpenOptionsExt},
    };
    let uid = unsafe { libc::geteuid() };
    for parent in path.ancestors().skip(1) {
        let m = std::fs::symlink_metadata(parent)?;
        ensure!(
            m.is_dir() && (m.uid() == 0 || m.uid() == uid) && m.mode() & 0o022 == 0,
            "untrusted credential directory"
        );
    }
    let mut f = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let m = f.metadata()?;
    let mut acl = [0_u8; 44];
    let acl_len = if m.mode() & 0o077 != 0 {
        unsafe {
            libc::fgetxattr(
                f.as_raw_fd(),
                c"system.posix_acl_access".as_ptr(),
                acl.as_mut_ptr().cast(),
                acl.len(),
            )
        }
    } else {
        0
    };
    ensure!(
        m.is_file()
            && m.nlink() == 1
            && acl_len >= 0
            && credential_permissions(m.mode(), m.uid(), uid, &acl[..acl_len.max(0) as usize])
            && m.len() <= limit as u64,
        "untrusted credential metadata"
    );
    let mut bytes = vec![];
    (&mut f).take(limit as u64 + 1).read_to_end(&mut bytes)?;
    ensure!(!bytes.is_empty() && bytes.len() <= limit, "credential size");
    Ok(bytes)
}
fn response_report(response: wire::Response) -> Result<Value> {
    match response.result.context("Robot result missing")? {
        wire::response::Result::Report(report) => {
            ensure!(
                report.json.len() <= robot_rpc::MAX_MESSAGE,
                "Robot report bound"
            );
            Ok(serde_json::from_slice(&report.json)?)
        }
        wire::response::Result::Failure(f) => {
            anyhow::bail!("Robot rejected request; code {}", f.code)
        }
        _ => anyhow::bail!("unexpected Robot result"),
    }
}
fn report_digest(value: &Value) -> Result<String> {
    let bytes: [u8; 32] = serde_json::from_value(value.clone())?;
    Ok(hex(&bytes))
}
impl Peer {
    pub fn load() -> Result<Self> {
        let bytes = robot_rpc::read_protected(Path::new(PEER_CONFIG), 65536, false)?;
        let config: PeerConfig = serde_json::from_slice(&bytes)?;
        let address: std::net::SocketAddr = config.endpoint.parse()?;
        ensure!(
            address.port() > 0
                && config.dns_name.len() <= 253
                && robot_rpc::valid_principal(&config.principal),
            "invalid fixed Robot peer"
        );
        unhex::<32>(&config.robot_leaf_sha256)?;
        unhex::<32>(&config.robot_configuration_digest)?;
        unhex::<32>(&config.robot_profile_digest)?;
        let key = read_credential(Path::new(KEY_CREDENTIAL), 8192)?;
        let tls = robot_rpc::client_tls(
            config.ca_pem.as_bytes(),
            config.client_certificate_pem.as_bytes(),
            &key,
        )?;
        let certs = robot_rpc::certificates(config.client_certificate_pem.as_bytes())?;
        let client_pin = hex(&Sha256::digest(
            certs.first().context("workload leaf missing")?.as_ref(),
        ));
        Ok(Self {
            digest: digest(&config)?,
            config,
            tls,
            client_pin,
        })
    }
    pub fn verify_binding(&self, b: &Binding) -> Result<()> {
        b.validate()?;
        ensure!(
            b.peer_digest == self.digest
                && b.client_certificate_sha256 == self.client_pin
                && b.principal == self.config.principal
                && b.robot_configuration_digest == self.config.robot_configuration_digest
                && b.robot_profile_digest == self.config.robot_profile_digest,
            "Robot peer/workload differs from immutable binding"
        );
        Ok(())
    }
    fn request(epoch: &str, command: Command) -> Result<wire::Request> {
        let request = wire::Request {
            version: robot_rpc::VERSION,
            request_id: robot_rpc::random_id::<16>()?.to_vec(),
            robot_epoch: if epoch.is_empty() {
                vec![]
            } else {
                unhex::<16>(epoch)?.to_vec()
            },
            command: Some(command),
        };
        request.validate()?;
        Ok(request)
    }
    pub async fn prepare(&self, request: &wire::Request) -> Result<robot_rpc::PreparedRpc> {
        robot_rpc::PreparedRpc::connect(
            self.config.endpoint.parse()?,
            self.config.dns_name.clone(),
            self.tls.clone(),
            unhex::<32>(&self.config.robot_leaf_sha256)?,
            request,
        )
        .await
    }
    async fn exchange(&self, request: &wire::Request) -> Result<wire::Response> {
        self.prepare(request)
            .await?
            .try_send_once()?
            .read_response()
            .await
    }
    async fn describe(&self) -> Result<String> {
        let response = self
            .exchange(&Self::request("", Command::Describe(wire::Empty {}))?)
            .await?;
        let epoch = hex(&response.robot_epoch);
        let report = response_report(response)?;
        ensure!(
            report["identity"]["device_certificate_sha256"] == self.config.robot_leaf_sha256
                && report_digest(&report["configuration_digest"])?
                    == self.config.robot_configuration_digest
                && report_digest(&report["profile_sha256"])? == self.config.robot_profile_digest,
            "Robot identity/configuration differs from installed peer"
        );
        Ok(epoch)
    }
    pub async fn bind(&self, attempt: &str, namespace: &str, deadline: i64) -> Result<Binding> {
        unhex::<16>(attempt)?;
        unhex::<16>(namespace)?;
        let epoch = self.describe().await?;
        let now = crate::launcher::now_ms()?;
        let binding = Binding {
            attempt_id: attempt.into(),
            namespace: namespace.into(),
            principal: self.config.principal.clone(),
            peer_digest: self.digest.clone(),
            client_certificate_sha256: self.client_pin.clone(),
            robot_epoch: epoch,
            robot_configuration_digest: self.config.robot_configuration_digest.clone(),
            robot_profile_digest: self.config.robot_profile_digest.clone(),
            created_ms: now,
            deadline_ms: deadline.min(now + 120_000),
        };
        binding.validate()?;
        Ok(binding)
    }
    pub async fn observe(&self, b: &Binding) -> Result<Observation> {
        self.verify_binding(b)?;
        let response = self
            .exchange(&Self::request(
                &b.robot_epoch,
                Command::Observe(wire::Handle {
                    namespace: unhex::<16>(&b.namespace)?.to_vec(),
                    attempt: unhex::<16>(&b.attempt_id)?.to_vec(),
                    key: vec![],
                }),
            )?)
            .await?;
        let Some(wire::response::Result::Observation(o)) = response.result else {
            anyhow::bail!("Robot observation unavailable");
        };
        let observation = Observation {
            id: o.id,
            acquired_earliest_ns: o.acquired_earliest_ns,
            acquired_latest_ns: o.acquired_latest_ns,
            valid_until_ns: o.valid_until_ns,
            controller_ns: o.controller_ns,
            left_ticks: o.left_ticks,
            right_ticks: o.right_ticks,
            simulated: o.simulated,
            context_revision: o.context_revision,
            received_ms: crate::launcher::now_ms()?,
        };
        observation.validate()?;
        Ok(observation)
    }
    pub fn proposal(
        &self,
        b: &Binding,
        intent: &Intent,
        target: &crate::model::Proposal,
    ) -> Result<wire::Request> {
        self.verify_binding(b)?;
        target.validate()?;
        ensure!(
            intent.handle.attempt == b.attempt_id
                && intent.handle.namespace == b.namespace
                && intent.robot_epoch == b.robot_epoch,
            "proposal binding mismatch"
        );
        let observation = intent
            .execution_observation
            .as_ref()
            .or(intent.observation.as_ref())
            .context("trusted observation missing")?;
        Self::request(
            &b.robot_epoch,
            Command::Propose(wire::Proposal {
                handle: Some(intent.handle.wire()?),
                observation_id: observation.id,
                target: Some(wire::Target {
                    left_delta_ticks: target.left_delta_ticks,
                    right_delta_ticks: target.right_delta_ticks,
                    duration_ms: target.duration_ms as u64,
                }),
                parent_digest: unhex::<32>(
                    intent
                        .parent_digest
                        .as_deref()
                        .context("lineage missing")?
                        .strip_prefix("sha256:")
                        .context("lineage format")?,
                )?
                .to_vec(),
            }),
        )
    }
    /// Describe can discover a new envelope epoch only for these retained-handle closure/read operations.
    pub async fn retained(
        &self,
        b: &Binding,
        intent: &Intent,
        cancel: bool,
    ) -> Result<RemoteReply> {
        self.verify_binding(b)?;
        tokio::time::timeout(std::time::Duration::from_secs(8), async {
            let epoch = self.describe().await?;
            let command = if cancel {
                Command::Cancel(intent.handle.wire()?)
            } else {
                Command::Query(intent.handle.wire()?)
            };
            let response = self.exchange(&Self::request(&epoch, command)?).await?;
            Self::remote_reply(response)
        })
        .await?
    }
    pub fn remote_reply(response: wire::Response) -> Result<RemoteReply> {
        let value = response_report(response)?;
        if value.get("prepared").is_some() && value.get("live_authority") == Some(&json!(false)) {
            let snapshot = if value["snapshot"].is_null() {
                None
            } else {
                Some(serde_json::from_value(value["snapshot"].clone())?)
            };
            return Ok(RemoteReply::Historical(snapshot));
        }
        let value = if value.get("snapshot").is_some() {
            value["snapshot"].clone()
        } else {
            value
        };
        if value.is_null() {
            return Ok(RemoteReply::Absent);
        }
        ensure!(
            serde_json::to_vec(&value)?.len() <= REMOTE_REPORT_BYTES,
            "Robot snapshot bound"
        );
        Ok(RemoteReply::Snapshot(serde_json::from_value(value)?))
    }
}
impl Handle {
    fn wire(&self) -> Result<wire::Handle> {
        Ok(wire::Handle {
            namespace: unhex::<16>(&self.namespace)?.to_vec(),
            attempt: unhex::<16>(&self.attempt)?.to_vec(),
            key: unhex::<32>(&self.key)?.to_vec(),
        })
    }
}

/// Captured before any Robot proposal publication. This immutable closure inventory never reads SQLite.
pub struct Captured {
    pub binding: Binding,
    pub intent: Intent,
    // One atomic state prevents a stale captured Arc from starting after settlement/removal.
    state: std::sync::atomic::AtomicU8,
}
const CLOSURE_RUNNING: u8 = 1;
const CLOSURE_SETTLED: u8 = 2;
impl Captured {
    pub fn begin(&self) -> bool {
        self.state
            .compare_exchange(
                0,
                CLOSURE_RUNNING,
                std::sync::atomic::Ordering::AcqRel,
                std::sync::atomic::Ordering::Acquire,
            )
            .is_ok()
    }
    fn running(&self) -> bool {
        self.state.load(std::sync::atomic::Ordering::Acquire) & CLOSURE_RUNNING != 0
    }
}
#[derive(Default)]
pub struct Closures {
    entries: std::sync::Mutex<std::collections::BTreeMap<(String, String), Arc<Captured>>>,
}
impl Closures {
    pub fn any_running(&self) -> bool {
        self.entries
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .values()
            .any(|v| v.running())
    }
    pub fn capture(&self, binding: &Binding, intent: &Intent) -> Result<Arc<Captured>> {
        let mut entries = self
            .entries
            .lock()
            .map_err(|_| anyhow::anyhow!("closure inventory poisoned"))?;
        let key = (binding.attempt_id.clone(), intent.request_key.clone());
        if let Some(old) = entries.get(&key) {
            ensure!(
                old.intent.handle == intent.handle && old.binding == *binding,
                "closure handle changed"
            );
            return Ok(old.clone());
        }
        ensure!(
            entries.len() < CLOSURE_CAPACITY,
            "reserved Robot closure capacity exhausted"
        );
        let value = Arc::new(Captured {
            binding: binding.clone(),
            intent: intent.clone(),
            state: std::sync::atomic::AtomicU8::new(0),
        });
        entries.insert(key, value.clone());
        Ok(value)
    }
    pub fn for_attempt(&self, attempt: &str, key: Option<&str>) -> Vec<Arc<Captured>> {
        self.entries
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .iter()
            .filter(|((a, k), _)| a == attempt && key.is_none_or(|key| key == k))
            .map(|(_, v)| v.clone())
            .collect()
    }
    pub fn settled(&self, attempt: &str, key: &str) {
        let mut entries = self.entries.lock().unwrap_or_else(|p| p.into_inner());
        let key = (attempt.into(), key.into());
        if let Some(captured) = entries.get(&key) {
            let old = captured
                .state
                .fetch_or(CLOSURE_SETTLED, std::sync::atomic::Ordering::AcqRel);
            if old & CLOSURE_RUNNING == 0 {
                entries.remove(&key);
            }
        }
    }
    pub fn finished(&self, captured: &Arc<Captured>) {
        let mut entries = self.entries.lock().unwrap_or_else(|p| p.into_inner());
        let state = captured
            .state
            .fetch_and(!CLOSURE_RUNNING, std::sync::atomic::Ordering::AcqRel);
        let key = (
            captured.intent.handle.attempt.clone(),
            captured.intent.request_key.clone(),
        );
        if state & CLOSURE_SETTLED != 0
            && entries
                .get(&key)
                .is_some_and(|entry| Arc::ptr_eq(entry, captured))
        {
            entries.remove(&key);
        }
    }
}

#[cfg(test)]
mod credential_tests {
    use super::*;
    #[test]
    fn systemd_acl_grants_only_root_and_the_named_service_read_access() {
        // Exact metadata observed on Debian systemd 257, without credential bytes.
        let acl = unhex::<44>("0200000001000400ffffffff02000400db03000004000000ffffffff10000400ffffffff20000000ffffffff").unwrap().to_vec();
        assert!(credential_permissions(0o440, 0, 987, &acl));
        assert!(!credential_permissions(0o440, 0, 988, &acl));
        assert!(!credential_permissions(0o440, 987, 987, &acl));
        for mode in [0o444, 0o460, 0o640] {
            assert!(!credential_permissions(mode, 0, 987, &acl));
        }
        for length in 0..acl.len() {
            assert!(!credential_permissions(0o440, 0, 987, &acl[..length]));
        }
        for offset in [0, 4, 6, 14, 22, 30, 38] {
            let mut changed = acl.clone();
            changed[offset] ^= 1;
            assert!(!credential_permissions(0o440, 0, 987, &changed));
        }
        let mut additional_reader = acl.clone();
        additional_reader.extend_from_slice(&acl[12..20]);
        assert!(!credential_permissions(0o440, 0, 987, &additional_reader));
        assert!(credential_permissions(0o400, 987, 987, &[]));
        assert!(credential_permissions(0o600, 0, 987, &[]));
        assert!(!credential_permissions(0o400, 988, 987, &[]));
    }
}
