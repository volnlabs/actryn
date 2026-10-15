//! Append-only boot journal. A torn/invalid record refuses service; never repair
//! or reset the namespace automatically. The locked file is never renamed.
use fixture_wire::crc32;
use std::{
    fs::{File, OpenOptions},
    io::{self, Read, Seek, SeekFrom, Write},
    os::unix::fs::OpenOptionsExt,
    path::Path,
};
const MAGIC: &[u8; 8] = b"ACTSIM2\0";
const HEADER: usize = 24;
const RECORD: usize = 20;
const MAX_BYTES: usize = 65536;
pub struct PersistentState {
    file: File,
    pub device: [u8; 16],
    pub boot: u64,
}
fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}
impl PersistentState {
    pub fn open(path: &Path) -> io::Result<Self> {
        let (mut file, created) = match OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)
        {
            Ok(file) => (file, true),
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                (OpenOptions::new().read(true).write(true).open(path)?, false)
            }
            Err(e) => return Err(e),
        };
        file.try_lock()
            .map_err(|e| io::Error::other(format!("fixture state already locked: {e}")))?;
        if created {
            let mut device = [0; 16];
            device[..3].copy_from_slice(b"SIM");
            File::open("/dev/urandom")?.read_exact(&mut device[3..])?;
            file.write_all(MAGIC)?;
            file.write_all(&device)?;
            file.sync_all()?;
            File::open(
                path.parent()
                    .filter(|p| !p.as_os_str().is_empty())
                    .unwrap_or(Path::new(".")),
            )?
            .sync_all()?;
        }
        if file.metadata()?.len() > MAX_BYTES as u64 {
            return Err(invalid("boot journal exceeds bound"));
        }
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        if bytes.len() < HEADER
            || &bytes[..8] != MAGIC
            || !(bytes.len() - HEADER).is_multiple_of(RECORD)
        {
            return Err(invalid(
                "ambiguous fixture state; operator servicing required",
            ));
        }
        let device = bytes[8..24].try_into().unwrap();
        if &bytes[8..11] != b"SIM" {
            return Err(invalid("not a software identity"));
        }
        let mut boot = 0u64;
        for entry in bytes[HEADER..].chunks_exact(RECORD) {
            let number = u64::from_le_bytes(entry[..8].try_into().unwrap());
            let inverse = u64::from_le_bytes(entry[8..16].try_into().unwrap());
            let crc = u32::from_le_bytes(entry[16..20].try_into().unwrap());
            if Some(number) != boot.checked_add(1)
                || inverse != !number
                || crc32(&entry[..16]) != crc
            {
                return Err(invalid("corrupt/nonmonotonic fixture boot journal"));
            }
            boot = number;
        }
        // Existing header-only state may be an interrupted first initialization.
        if !created && boot == 0 {
            return Err(invalid("incomplete fixture initialization"));
        }
        let mut state = Self { file, device, boot };
        state.advance()?;
        Ok(state)
    }
    pub fn advance(&mut self) -> io::Result<u64> {
        let boot = self
            .boot
            .checked_add(1)
            .ok_or_else(|| invalid("boot exhausted"))?;
        if self.file.metadata()?.len() + RECORD as u64 > MAX_BYTES as u64 {
            return Err(invalid("boot journal full; servicing required"));
        }
        let mut entry = [0; RECORD];
        entry[..8].copy_from_slice(&boot.to_le_bytes());
        entry[8..16].copy_from_slice(&(!boot).to_le_bytes());
        let crc = crc32(&entry[..16]);
        entry[16..].copy_from_slice(&crc.to_le_bytes());
        self.file.seek(SeekFrom::End(0))?;
        self.file.write_all(&entry)?;
        self.file.sync_all()?;
        self.boot = boot;
        Ok(boot)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn durable_restart_lock_and_torn_record() {
        let dir = std::env::temp_dir().join(format!("actryn-state-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("state");
        let _ = std::fs::remove_file(&path);
        let first = PersistentState::open(&path).unwrap();
        assert_eq!(first.boot, 1);
        assert!(PersistentState::open(&path).is_err());
        let device = first.device;
        drop(first);
        let second = PersistentState::open(&path).unwrap();
        assert_eq!(second.boot, 2);
        assert_eq!(second.device, device);
        drop(second);
        OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap()
            .write_all(&[1])
            .unwrap();
        assert!(PersistentState::open(&path).is_err());
        std::fs::remove_dir_all(dir).unwrap();
    }
}
