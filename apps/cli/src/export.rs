use crate::state::{hex, unhex};
use anyhow::{ensure, Context, Result};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::Write,
    os::unix::fs::OpenOptionsExt,
    path::Path,
};

pub const MAX_BYTES: u64 = 64 * 1024 * 1024;
pub fn save_manifest(path: &Path, value: &Value) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    ensure!(bytes.len() <= 2 * 1024 * 1024, "export manifest bound");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    File::open(path.parent().context("manifest directory")?)?.sync_all()?;
    Ok(())
}
pub struct CaptureFile {
    file: File,
    name: String,
    pub size: u64,
    pub offset: u64,
    hash: Sha256,
    expected: String,
}
impl CaptureFile {
    pub fn create(root: &Path, entry: &Value) -> Result<Self> {
        let name = entry["file"].as_str().context("capture filename missing")?;
        ensure!(
            robot_rpc::valid_capture_file(name),
            "invalid capture filename"
        );
        let size = entry["size"]
            .as_u64()
            .filter(|n| *n <= MAX_BYTES)
            .context("capture size")?;
        let expected = entry["sha256"].as_str().context("capture hash")?.to_owned();
        unhex(&expected, 32)?;
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(root.join(name))?;
        Ok(Self {
            file,
            name: name.into(),
            size,
            offset: 0,
            hash: Sha256::new(),
            expected,
        })
    }
    pub fn append(&mut self, chunk: &Value) -> Result<()> {
        ensure!(
            chunk["file"] == self.name
                && chunk["offset"] == self.offset
                && chunk["size"] == self.size,
            "capture chunk identity changed"
        );
        let encoded = chunk["data_hex"]
            .as_str()
            .context("capture bytes missing")?;
        ensure!(
            !encoded.is_empty() && encoded.len() <= 32768 && encoded.len() % 2 == 0,
            "capture chunk bound"
        );
        let bytes = unhex(encoded, encoded.len() / 2)?;
        let end = self
            .offset
            .checked_add(bytes.len() as u64)
            .context("capture offset overflow")?;
        ensure!(
            end <= self.size && chunk["next_offset"] == end,
            "capture chunk offset"
        );
        self.file.write_all(&bytes)?;
        self.hash.update(&bytes);
        self.offset = end;
        Ok(())
    }
    pub fn finish(self) -> Result<()> {
        ensure!(
            self.offset == self.size && hex(&self.hash.finalize()) == self.expected,
            "capture hash/size mismatch"
        );
        self.file.sync_all()?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn no_overwrite_or_escape_and_unverified_chunks_never_finish() {
        let dir = tempfile::tempdir().unwrap();
        let entry =
            json!({"file":"checkpoints.sqlite","size":3,"sha256":hex(&Sha256::digest(b"abc"))});
        let mut file = CaptureFile::create(dir.path(), &entry).unwrap();
        assert!(CaptureFile::create(dir.path(), &entry).is_err());
        assert!(file.append(&json!({"file":"checkpoints.sqlite","size":3,"offset":1,"data_hex":"616263","next_offset":4})).is_err());
        file.append(&json!({"file":"checkpoints.sqlite","size":3,"offset":0,"data_hex":"616264","next_offset":3})).unwrap();
        assert!(file.finish().is_err());
        let mut escape = entry.clone();
        escape["file"] = json!("../key.pem");
        assert!(CaptureFile::create(dir.path(), &escape).is_err());
        let good_dir = tempfile::tempdir().unwrap();
        let mut good = CaptureFile::create(good_dir.path(), &entry).unwrap();
        good.append(&json!({"file":"checkpoints.sqlite","size":3,"offset":0,"data_hex":"616263","next_offset":3})).unwrap();
        good.finish().unwrap();
    }
}
