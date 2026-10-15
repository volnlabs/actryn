use anyhow::{bail, ensure, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Seek, SeekFrom},
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::Path,
};

const FILES: usize = 8192;
const BYTES: u64 = 64 * 1024 * 1024;
const CHUNK: usize = 16 * 1024;
use robot_rpc::valid_capture_file as allowed;
fn open(path: &Path) -> Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)?;
    let m = file.metadata()?;
    ensure!(
        m.is_file()
            && m.uid() == unsafe { libc::geteuid() }
            && m.nlink() == 1
            && m.mode() & 0o077 == 0
            && m.len() <= BYTES,
        "invalid capture file"
    );
    Ok(file)
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// The caller verifies the retained principal binding and that preparation ended.
/// No writer can change the capture while a read holds its existing lifetime lock.
pub fn read(root: &Path, name: &str, offset: u64) -> Result<Value> {
    let m = fs::symlink_metadata(root)?;
    ensure!(
        m.is_dir() && m.uid() == unsafe { libc::geteuid() } && m.mode() & 0o077 == 0,
        "private capture directory required"
    );
    let lock = open(&root.join("capture.lock"))?;
    lock.try_lock()
        .map_err(|_| anyhow::anyhow!("capture writer still active"))?;
    if !name.is_empty() {
        ensure!(allowed(name), "unsupported capture filename");
        let mut file = open(&root.join(name))?;
        let size = file.metadata()?.len();
        ensure!(offset <= size, "capture offset exceeds file");
        file.seek(SeekFrom::Start(offset))?;
        let mut bytes = vec![0; CHUNK.min((size - offset) as usize)];
        file.read_exact(&mut bytes)?;
        return Ok(
            json!({"file":name,"offset":offset,"size":size,"data_hex":hex(&bytes),"next_offset":offset+bytes.len() as u64}),
        );
    }
    let mut entries = Vec::new();
    let mut total = 0u64;
    for entry in fs::read_dir(root)?.take(FILES + 2) {
        let entry = entry?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| anyhow::anyhow!("capture filename encoding"))?;
        if name == "capture.lock" {
            continue;
        }
        ensure!(allowed(&name), "unexpected capture file");
        let m = fs::symlink_metadata(entry.path())?;
        ensure!(
            m.is_file()
                && m.uid() == unsafe { libc::geteuid() }
                && m.nlink() == 1
                && m.mode() & 0o077 == 0,
            "invalid capture entry"
        );
        total = total
            .checked_add(m.len())
            .ok_or_else(|| anyhow::anyhow!("capture size overflow"))?;
        ensure!(
            total <= BYTES && entries.len() < FILES,
            "capture export capacity"
        );
        entries.push((name, m.len()));
    }
    entries.sort_unstable();
    let offset = usize::try_from(offset)?;
    ensure!(offset <= entries.len(), "capture list offset");
    let end = (offset + 32).min(entries.len());
    let mut files = Vec::new();
    for (name, size) in &entries[offset..end] {
        let mut file = open(&root.join(name))?;
        let mut hash = Sha256::new();
        let mut bytes = [0; 32768];
        let mut consumed = 0;
        loop {
            let n = file.read(&mut bytes)?;
            if n == 0 {
                break;
            }
            consumed += n as u64;
            if consumed > *size {
                bail!("capture changed while reading");
            }
            hash.update(&bytes[..n]);
        }
        ensure!(consumed == *size, "capture changed while reading");
        files.push(json!({"file":name,"size":size,"sha256":hex(&hash.finalize())}));
    }
    Ok(
        json!({"files":files,"next_offset":if end < entries.len() {Some(end)}else{None},"file_count":entries.len(),"total_bytes":total,"volatile_tail_unknown":true,"execution_replay_eligible":false,"replay_reason":"metadata-only capture; raw remnants require checkpoint validation"}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{symlink, PermissionsExt};
    fn fixture() -> tempfile::TempDir {
        let root = tempfile::tempdir().unwrap();
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
        for (name, bytes) in [
            ("capture.lock", b"".as_slice()),
            ("checkpoints.sqlite", b"retained".as_slice()),
        ] {
            fs::write(root.path().join(name), bytes).unwrap();
            fs::set_permissions(root.path().join(name), fs::Permissions::from_mode(0o600)).unwrap();
        }
        root
    }
    #[test]
    fn export_hashes_retired_bytes_and_rejects_live_writer_or_path_escape() {
        let root = fixture();
        let lock = open(&root.path().join("capture.lock")).unwrap();
        lock.try_lock().unwrap();
        assert!(read(root.path(), "", 0).is_err());
        drop(lock);
        let manifest = read(root.path(), "", 0).unwrap();
        assert_eq!(
            manifest["files"][0]["sha256"],
            hex(&Sha256::digest(b"retained"))
        );
        assert_eq!(manifest["execution_replay_eligible"], false);
        assert_eq!(
            read(root.path(), "checkpoints.sqlite", 3).unwrap()["data_hex"],
            hex(b"ained")
        );
        assert!(read(root.path(), "../identity/key.pem", 0).is_err());
        assert!(read(root.path(), "checkpoints.sqlite", 9).is_err());
        symlink(
            "checkpoints.sqlite",
            root.path().join("batch-00000000000000000001.mcap"),
        )
        .unwrap();
        assert!(read(root.path(), "", 0).is_err());
        assert!(read(root.path(), "batch-00000000000000000001.mcap", 0).is_err());
    }
    #[test]
    fn file_and_directory_capacity_never_produces_a_partial_manifest() {
        let root = fixture();
        let file = OpenOptions::new()
            .write(true)
            .open(root.path().join("checkpoints.sqlite"))
            .unwrap();
        file.set_len(BYTES + 1).unwrap();
        assert!(read(root.path(), "", 0).is_err());
        assert!(read(root.path(), "checkpoints.sqlite", 0).is_err());
        assert!(!allowed("batch-0000000000000000000a.mcap"));
    }
}
