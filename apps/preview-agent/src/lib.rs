//! Credential-free deterministic proposal client. Authorization belongs to the local robot operator.
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    fs::{File, OpenOptions},
    io::{Read, Write},
    os::unix::{fs::OpenOptionsExt, net::UnixStream},
    path::Path,
    time::Duration,
};
pub const BROKER: &str = "/run/actryn-broker/broker.sock";
pub const INPUT: &str = "/etc/actryn/input.json";
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub schema: u32,
    pub goal: String,
    pub observation_id: String,
    pub request_key: String,
}
impl Input {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.schema == 1
                && !self.goal.is_empty()
                && self.goal.len() <= 1024
                && !self.goal.contains('\0'),
            "invalid preview goal/schema"
        );
        for text in [&self.observation_id, &self.request_key] {
            ensure!(
                !text.is_empty()
                    && text.len() <= 128
                    && text
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"-_.:".contains(&c)),
                "invalid preview request identity"
            );
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Target {
    left_delta_ticks: i64,
    right_delta_ticks: i64,
    duration_ms: u64,
}
pub fn decode_reply(input: &Input, bytes: &[u8]) -> Result<Value> {
    ensure!(bytes.len() <= 65536, "broker response exceeds bound");
    let response: Value = serde_json::from_slice(bytes)?;
    ensure!(response["result"] == "ok", "broker rejected proposal");
    let value = &response["value"];
    ensure!(
        value["origin"] == "server_attested"
            && value["request_key"] == input.request_key
            && value["model"] == "offline-fixture",
        "broker response binding mismatch"
    );
    let attempt = value["attempt_id"]
        .as_str()
        .context("attempt identity missing")?;
    ensure!(
        attempt.len() == 32
            && attempt
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)),
        "invalid attempt identity"
    );
    let target: Target = serde_json::from_value(value["output"].clone())?;
    ensure!(
        (-100..=100).contains(&target.left_delta_ticks)
            && (-100..=100).contains(&target.right_delta_ticks)
            && (1..=10000).contains(&target.duration_ms),
        "broker target exceeds wheel skill bounds"
    );
    Ok(value.clone())
}
pub fn mark_submitted(path: &Path) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    file.write_all(b"one submission attempted; query the retained broker key\n")?;
    file.sync_all()?;
    File::open(path.parent().context("marker parent missing")?)?.sync_all()?;
    Ok(())
}
pub fn run() -> Result<Value> {
    ensure!(
        unsafe { libc::geteuid() } == 65532,
        "preview agent must run in the installed sandbox"
    );
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(INPUT)?;
    ensure!(
        file.metadata()?.is_file() && file.metadata()?.len() <= 4096,
        "preview input type/size"
    );
    let mut data = Vec::new();
    file.take(4097).read_to_end(&mut data)?;
    ensure!(data.len() <= 4096, "preview input too large");
    let input: Input = serde_json::from_slice(&data)?;
    input.validate()?;
    let request = serde_json::to_vec(
        &json!({"op":"call","method":"model.offline","request_key":input.request_key,"input":{"goal":input.goal,"observation_id":input.observation_id}}),
    )?;
    mark_submitted(Path::new("/tmp/actryn-preview-submitted"))?;
    let mut stream = UnixStream::connect(BROKER)?;
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    stream.set_write_timeout(Some(Duration::from_secs(5)))?;
    stream.write_all(&(request.len() as u32).to_be_bytes())?;
    stream.write_all(&request)?;
    let mut prefix = [0u8; 4];
    stream.read_exact(&mut prefix)?;
    let length = u32::from_be_bytes(prefix) as usize;
    ensure!(length > 0 && length <= 65536, "broker reply frame bound");
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes)?;
    decode_reply(&input, &bytes)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn input_is_typed_bounded_and_reply_must_be_same_broker_call() {
        let input:Input=serde_json::from_str(r#"{"schema":1,"goal":"one restrained index","observation_id":"offline-reference","request_key":"preview-1"}"#).unwrap();
        input.validate().unwrap();
        assert!(serde_json::from_str::<Input>(
            r#"{"schema":1,"goal":"g","observation_id":"o","request_key":"k","tool":"admin.grant"}"#
        )
        .is_err());
        let mut bad = input.clone();
        bad.request_key = "../other".into();
        assert!(bad.validate().is_err());
        let result = serde_json::json!({"result":"ok","value":{"origin":"server_attested","attempt_id":"a".repeat(32),"request_key":"preview-1","model":"offline-fixture","output":{"left_delta_ticks":10,"right_delta_ticks":10,"duration_ms":1000}}});
        assert!(decode_reply(&input, &serde_json::to_vec(&result).unwrap()).is_ok());
        let mut bad = result.clone();
        bad["value"]["output"]["left_delta_ticks"] = serde_json::json!(101);
        assert!(decode_reply(&input, &serde_json::to_vec(&bad).unwrap()).is_err());
        let mut bad = result;
        bad["value"]["request_key"] = serde_json::json!("different");
        assert!(decode_reply(&input, &serde_json::to_vec(&bad).unwrap()).is_err());
    }
    #[test]
    fn one_submission_marker_prevents_restart_resend() {
        let dir = tempfile::tempdir().unwrap();
        let marker = dir.path().join("submitted");
        mark_submitted(&marker).unwrap();
        assert!(mark_submitted(&marker).is_err());
    }
}
