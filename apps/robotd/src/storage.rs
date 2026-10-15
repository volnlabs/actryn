use anyhow::{ensure, Result};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::Path,
};

pub fn private_directory(path: &Path) -> Result<()> {
    if !path.exists() {
        fs::create_dir(path)?;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
        File::open(path.parent().unwrap())?.sync_all()?;
    }
    let m = fs::symlink_metadata(path)?;
    ensure!(
        m.is_dir() && m.uid() == unsafe { libc::geteuid() } && m.mode() & 0o077 == 0,
        "private state directory required"
    );
    Ok(())
}

/// Caller serializes writes to this file; fsync failure never reports durability.
pub fn replace(path: &Path, bytes: &[u8]) -> Result<()> {
    ensure!(bytes.len() <= 65_536, "state file capacity");
    let tmp = path.with_extension("pending");
    let mut f = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(&tmp)?;
    let m = f.metadata()?;
    ensure!(
        m.is_file() && m.uid() == unsafe { libc::geteuid() } && m.mode() & 0o077 == 0,
        "untrusted state temporary file"
    );
    f.write_all(bytes)?;
    f.sync_all()?;
    fs::rename(tmp, path)?;
    File::open(path.parent().unwrap())?.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounded_atomic_state_rejects_symlink_and_preserves_previous_generation() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("state.json");
        replace(&path, b"first").unwrap();
        replace(&path, b"second").unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"second");
        assert!(replace(&path, &vec![0; 65537]).is_err());
        std::os::unix::fs::symlink(&path, path.with_extension("pending")).unwrap();
        assert!(replace(&path, b"bad").is_err());
        assert_eq!(fs::read(&path).unwrap(), b"second");
        assert_eq!(fs::metadata(path).unwrap().mode() & 0o777, 0o600);
    }
}
