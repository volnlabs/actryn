use anyhow::{ensure, Context, Result};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::{
        fd::AsRawFd,
        unix::fs::{MetadataExt, OpenOptionsExt},
    },
    path::{Path, PathBuf},
};

pub const MAX_STATE: u64 = 65_536;
pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
pub fn unhex(value: &str, size: usize) -> Result<Vec<u8>> {
    ensure!(
        value.len() == size * 2
            && value
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "expected {size}-byte lowercase hexadecimal identity"
    );
    Ok(value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            u8::from_str_radix(std::str::from_utf8(pair).expect("ASCII checked"), 16)
                .expect("hex checked")
        })
        .collect())
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Pair {
    pub schema: u32,
    pub endpoint: String,
    pub dns_name: String,
    pub device_certificate_sha256: String,
    pub ca_pem: String,
    pub robot_epoch: String,
}
impl Pair {
    pub fn validate(&self) -> Result<()> {
        ensure!(self.schema == 1, "unsupported pairing schema");
        let _: std::net::SocketAddr = self
            .endpoint
            .parse()
            .context("endpoint must be a numeric IP:port")?;
        ensure!(
            !self.dns_name.is_empty()
                && self.dns_name.len() <= 253
                && self
                    .dns_name
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'.'),
            "invalid TLS DNS name"
        );
        unhex(&self.device_certificate_sha256, 32)?;
        unhex(&self.robot_epoch, 16)?;
        robot_rpc::certificates(self.ca_pem.as_bytes())?;
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SavedHandle {
    pub robot_epoch: String,
    pub namespace: String,
    pub attempt: String,
    pub key: String,
    pub state: String,
    pub proposal: Option<SavedProposal>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SavedProposal {
    pub observation_id: u64,
    pub parent_digest: String,
    pub left_delta_ticks: i64,
    pub right_delta_ticks: i64,
    pub duration_ms: u64,
}
impl SavedHandle {
    pub fn validate(&self) -> Result<()> {
        unhex(&self.robot_epoch, 16)?;
        unhex(&self.namespace, 16)?;
        unhex(&self.attempt, 16)?;
        unhex(&self.key, 32)?;
        ensure!(
            matches!(
                self.state.as_str(),
                "ready" | "proposal_attempted" | "cancel_requested"
            ),
            "invalid handle state"
        );
        ensure!(
            self.state != "ready" || self.proposal.is_none(),
            "ready handle contains a proposal"
        );
        ensure!(
            self.state != "proposal_attempted" || self.proposal.is_some(),
            "attempted handle lacks proposal"
        );
        if let Some(proposal) = &self.proposal {
            proposal.validate()?;
        }
        Ok(())
    }
    pub fn wire(&self) -> Result<robot_rpc::wire::Handle> {
        self.validate()?;
        Ok(robot_rpc::wire::Handle {
            namespace: unhex(&self.namespace, 16)?,
            attempt: unhex(&self.attempt, 16)?,
            key: unhex(&self.key, 32)?,
        })
    }
}
impl SavedProposal {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.observation_id > 0
                && (-100..=100).contains(&self.left_delta_ticks)
                && (-100..=100).contains(&self.right_delta_ticks)
                && (1..=10000).contains(&self.duration_ms),
            "proposal exceeds fixed wheel skill bounds"
        );
        unhex(&self.parent_digest, 32)?;
        Ok(())
    }
    pub fn wire(&self, handle: &SavedHandle) -> Result<robot_rpc::wire::Proposal> {
        self.validate()?;
        Ok(robot_rpc::wire::Proposal {
            handle: Some(handle.wire()?),
            observation_id: self.observation_id,
            parent_digest: unhex(&self.parent_digest, 32)?,
            target: Some(robot_rpc::wire::Target {
                left_delta_ticks: self.left_delta_ticks,
                right_delta_ticks: self.right_delta_ticks,
                duration_ms: self.duration_ms,
            }),
        })
    }
}
fn parent(path: &Path) -> Result<PathBuf> {
    let directory = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let metadata = fs::symlink_metadata(directory)?;
    ensure!(
        metadata.is_dir()
            && metadata.mode() & 0o022 == 0
            && (metadata.uid() == unsafe { libc::geteuid() } || metadata.uid() == 0),
        "state parent must be a protected directory"
    );
    Ok(directory.to_owned())
}
pub fn read_file(path: &Path, max: u64, secret: bool) -> Result<Vec<u8>> {
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let metadata = file.metadata()?;
    ensure!(
        metadata.is_file() && metadata.len() <= max,
        "input file type/size"
    );
    if secret {
        ensure!(
            (metadata.uid() == unsafe { libc::geteuid() } || metadata.uid() == 0)
                && metadata.mode() & 0o077 == 0,
            "private file ownership/permissions"
        );
    }
    let mut bytes = vec![];
    (&mut file).take(max + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() as u64 <= max, "input grew beyond size limit");
    Ok(bytes)
}
pub fn read_json<T: DeserializeOwned>(path: &Path) -> Result<T> {
    Ok(serde_json::from_slice(&read_file(path, MAX_STATE, true)?)?)
}
pub fn save_new<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let directory = parent(path)?;
    let bytes = serde_json::to_vec(value)?;
    ensure!(bytes.len() as u64 <= MAX_STATE, "state exceeds size cap");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    File::open(directory)?.sync_all()?;
    Ok(())
}
pub fn load_handle(path: &Path) -> Result<SavedHandle> {
    let handle: SavedHandle = read_json(path)?;
    handle.validate()?;
    Ok(handle)
}
pub fn load_pair(path: &Path) -> Result<Pair> {
    let pair: Pair = read_json(path)?;
    pair.validate()?;
    Ok(pair)
}
fn transition(path: &Path, proposal: Option<SavedProposal>) -> Result<SavedHandle> {
    let directory = parent(path)?;
    let mut lock_name = path.as_os_str().to_os_string();
    lock_name.push(".actryn-lock");
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(Path::new(&lock_name))?;
    let meta = lock.metadata()?;
    ensure!(
        meta.is_file() && meta.uid() == unsafe { libc::geteuid() } && meta.mode() & 0o077 == 0,
        "untrusted handle lock"
    );
    ensure!(
        unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0,
        "handle is in use by another command"
    );
    let mut handle = load_handle(path)?;
    if let Some(proposal) = proposal {
        ensure!(
            handle.state == "ready",
            "proposal already attempted or cancelled; query the existing handle instead"
        );
        proposal.validate()?;
        handle.proposal = Some(proposal);
        handle.state = "proposal_attempted".into();
    } else {
        handle.state = "cancel_requested".into();
    }
    let temporary = directory.join(format!(
        ".actryn-write-{}",
        hex(&robot_rpc::random_id::<16>()?)
    ));
    save_new(&temporary, &handle)?;
    if let Err(error) = fs::rename(&temporary, path) {
        let _ = fs::remove_file(&temporary);
        return Err(error.into());
    }
    File::open(directory)?.sync_all()?;
    Ok(handle)
}
pub fn begin_proposal(path: &Path, proposal: SavedProposal) -> Result<SavedHandle> {
    transition(path, Some(proposal))
}
pub fn close_handle(path: &Path) -> Result<SavedHandle> {
    transition(path, None)
}
