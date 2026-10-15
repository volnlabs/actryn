use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};

pub const COVERAGE: &[&str] = &[
    "process.lifecycle",
    "syscall.openat",
    "syscall.connect",
    "syscall.bpf",
    "syscall.perf_event_open",
    "syscall.mount",
    "syscall.unshare",
    "syscall.setns",
];

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub op: String,
    pub attempt_id: String,
    pub boot_id: String,
    pub cgroup_id: u64,
    pub cgroup_path: String,
}

impl Request {
    pub fn validate(&self, boot: &str) -> Result<()> {
        ensure!(
            matches!(self.op.as_str(), "register" | "health" | "unregister"),
            "unknown operation"
        );
        ensure!(
            self.attempt_id.len() == 32
                && self
                    .attempt_id
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()),
            "invalid attempt identity"
        );
        ensure!(
            self.boot_id == boot && self.cgroup_id != 0,
            "retired boot or invalid cgroup"
        );
        ensure!(
            self.cgroup_path == format!("/actryn/{}", self.attempt_id),
            "invalid cgroup path"
        );
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct Status {
    pub ready: bool,
    pub collector_epoch: String,
    pub coverage: Vec<String>,
    pub sequence: u64,
    pub lost: u64,
}

#[derive(Debug, Serialize)]
pub struct Event {
    pub monotonic_ns: u64,
    pub cgroup_id: u64,
    pub pid: u32,
    pub tid: u32,
    pub sequence: u64,
    pub result: i64,
    pub related_pid: u32,
    pub kind: u32,
    pub syscall: i32,
    pub comm: String,
    pub origin: &'static str,
    pub classification: &'static str,
}
impl Event {
    pub fn decode(raw: &[u8]) -> Result<Self> {
        ensure!(raw.len() == 72, "invalid BPF record size");
        let u64_at = |i| u64::from_ne_bytes(raw[i..i + 8].try_into().unwrap());
        let u32_at = |i| u32::from_ne_bytes(raw[i..i + 4].try_into().unwrap());
        let kind = u32_at(44);
        ensure!(
            (1..=5).contains(&kind) && u32_at(52) == 0,
            "invalid BPF record kind or reserved bytes"
        );
        let result = u64_at(32) as i64;
        Ok(Self {
            monotonic_ns: u64_at(0),
            cgroup_id: u64_at(8),
            pid: (u64_at(16) >> 32) as u32,
            tid: u64_at(16) as u32,
            sequence: u64_at(24),
            result,
            related_pid: u32_at(40),
            kind,
            syscall: u32_at(48) as i32,
            comm: String::from_utf8_lossy(raw[56..].split(|v| *v == 0).next().unwrap()).into(),
            origin: "linux.tracepoint",
            classification: if kind == 2 && result < 0 {
                "access_failed"
            } else {
                "observed"
            },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn os_failure_is_never_a_policy_attributed_denial() {
        let mut bytes = [0; 72];
        bytes[32..40].copy_from_slice(&(-13_i64).to_ne_bytes());
        bytes[44..48].copy_from_slice(&2_u32.to_ne_bytes());
        assert_eq!(
            Event::decode(&bytes).unwrap().classification,
            "access_failed"
        );
        bytes[44] = 9;
        assert!(Event::decode(&bytes).is_err());
        assert!(Event::decode(&bytes[..71]).is_err());
    }
    #[test]
    fn registration_cannot_escape_attempt_or_boot() {
        let mut r = Request {
            op: "register".into(),
            attempt_id: "a".repeat(32),
            boot_id: "boot".into(),
            cgroup_id: 8,
            cgroup_path: format!("/actryn/{}", "a".repeat(32)),
        };
        r.validate("boot").unwrap();
        assert!(r.validate("next-boot").is_err());
        r.cgroup_path = "/actryn/../system.slice".into();
        assert!(r.validate("boot").is_err());
        r.cgroup_path = format!("/actryn/{}", "a".repeat(32));
        r.op = "load".into();
        assert!(r.validate("boot").is_err());
    }
}
