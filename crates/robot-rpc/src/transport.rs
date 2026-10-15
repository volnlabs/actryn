use anyhow::{ensure, Context, Result};
use std::{
    fs::File,
    os::fd::{AsRawFd, FromRawFd, OwnedFd},
    path::Path,
};
use tokio::net::UnixStream;

/// The supervisor captures this from SO_PEERCRED on its protected control socket.
/// A readable pidfd retires every associated session even if a child retained TLS FDs.
pub struct PeerLifetime {
    pid: u32,
    uid: u32,
    handle: OwnedFd,
}
impl PeerLifetime {
    pub fn capture(stream: &UnixStream, expected_uid: u32) -> Result<Self> {
        let peer = stream.peer_cred()?;
        ensure!(peer.uid() == expected_uid, "unauthorized local peer");
        let pid = peer.pid().context("peer PID unavailable")?;
        ensure!(pid > 0, "invalid peer PID");
        let mut fd: libc::c_int = -1;
        let mut len = std::mem::size_of_val(&fd) as libc::socklen_t;
        // SO_PEERPIDFD (Linux >= 6.5) references the socket's actual peer, avoiding
        // the PID-reuse race between SO_PEERCRED and pidfd_open(claimed_pid).
        let rc = unsafe {
            libc::getsockopt(
                stream.as_raw_fd(),
                libc::SOL_SOCKET,
                77,
                (&mut fd as *mut libc::c_int).cast(),
                &mut len,
            )
        };
        if rc != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        ensure!(fd >= 0, "missing peer process handle");
        let handle = unsafe { OwnedFd::from_raw_fd(fd) };
        ensure!(
            len as usize == std::mem::size_of_val(&fd),
            "peer handle size"
        );
        let lifetime = Self {
            pid: pid as u32,
            uid: expected_uid,
            handle,
        };
        ensure!(lifetime.alive()?, "peer already exited");
        let again = stream.peer_cred()?;
        ensure!(
            again.pid() == Some(pid) && again.uid() == expected_uid,
            "peer identity changed"
        );
        Ok(lifetime)
    }
    pub fn matches(&self, stream: &UnixStream) -> Result<bool> {
        let peer = stream.peer_cred()?;
        Ok(peer.pid() == Some(self.pid as i32) && peer.uid() == self.uid && self.alive()?)
    }
    pub fn alive(&self) -> Result<bool> {
        let mut poll = libc::pollfd {
            fd: self.handle.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        let rc = unsafe { libc::poll(&mut poll, 1, 0) };
        if rc < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(rc == 0)
    }
    pub fn pid(&self) -> u32 {
        self.pid
    }
}
/// Bounded root-owned inputs; caller chooses whether it is a private key.
pub fn read_protected(path: &Path, max: u64, secret: bool) -> Result<Vec<u8>> {
    use std::{
        io::Read,
        os::unix::fs::{MetadataExt, OpenOptionsExt},
    };
    for parent in path.ancestors().skip(1) {
        let metadata = std::fs::symlink_metadata(parent)?;
        ensure!(
            metadata.is_dir() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0,
            "untrusted configuration directory"
        );
    }
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let metadata = file.metadata()?;
    ensure!(
        metadata.is_file()
            && metadata.uid() == 0
            && metadata.mode() & if secret { 0o077 } else { 0o022 } == 0
            && metadata.len() <= max,
        "untrusted configuration file"
    );
    let mut bytes = Vec::new();
    (&mut file).take(max + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() as u64 <= max, "configuration grew beyond limit");
    Ok(bytes)
}
pub fn random_id<const N: usize>() -> Result<[u8; N]> {
    use std::io::Read;
    let mut result = [0; N];
    File::open("/dev/urandom")?.read_exact(&mut result)?;
    Ok(result)
}
