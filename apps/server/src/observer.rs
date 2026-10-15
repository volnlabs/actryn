use crate::protocol::{read_frame, write_frame};
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use std::{path::Path, time::Duration};
use tokio::net::UnixStream;
pub const REQUIRED_COVERAGE: &[&str] = &[
    "process.lifecycle",
    "syscall.openat",
    "syscall.connect",
    "syscall.bpf",
    "syscall.perf_event_open",
    "syscall.mount",
    "syscall.unshare",
    "syscall.setns",
];
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObserverRequest {
    pub op: String,
    pub attempt_id: String,
    pub boot_id: String,
    pub cgroup_id: u64,
    pub cgroup_path: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObserverStatus {
    pub ready: bool,
    pub collector_epoch: String,
    pub coverage: Vec<String>,
    pub sequence: u64,
    pub lost: u64,
}
impl ObserverStatus {
    pub fn check(&self, epoch: Option<&str>) -> Result<()> {
        ensure!(
            self.ready && !self.collector_epoch.is_empty() && self.collector_epoch.len() <= 128,
            "observer not ready"
        );
        ensure!(
            epoch.is_none_or(|expected| expected == self.collector_epoch),
            "observer lifetime changed"
        );
        ensure!(self.lost == 0, "observer has reported lost evidence");
        ensure!(
            REQUIRED_COVERAGE
                .iter()
                .all(|required| self.coverage.iter().any(|v| v == required)),
            "required observer coverage missing"
        );
        Ok(())
    }
}
pub async fn exchange(path: &Path, request: &ObserverRequest) -> Result<ObserverStatus> {
    tokio::time::timeout(Duration::from_secs(1), async {
        let mut stream = UnixStream::connect(path)
            .await
            .context("connect observer")?;
        ensure!(stream.peer_cred()?.uid() == 0, "observer peer is not root");
        write_frame(&mut stream, &serde_json::to_vec(request)?)
            .await
            .context("write observer request")?;
        let response = read_frame(&mut stream)
            .await
            .context("read observer reply")?;
        serde_json::from_slice(&response).context("decode observer reply")
    })
    .await
    .context("observer exchange deadline")?
    .with_context(|| format!("observer {} for attempt {}", request.op, request.attempt_id))
}
