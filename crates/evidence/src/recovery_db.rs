//! Private-copy rollback for an offline DELETE-journal capture. Never open an
//! original database writable or discard its journal to make it readable.
use super::*;
use rusqlite::{Connection, OpenFlags};
use std::{
    collections::BTreeSet,
    fs::{self, File, Metadata, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::PathBuf,
};

// Recorder creation caps disk_bytes at 1 GiB and SQLite at one eighth of it.
const MAX_DB: u64 = 128 * 1024 * 1024;
const MAX_JOURNAL: u64 = 2 * MAX_DB;
const PAGE: usize = 4096;
const DB: &str = "checkpoints.sqlite";
const JOURNAL: &str = "checkpoints.sqlite-journal";
const MAGIC: &[u8] = b"\xd9\xd5\x05\xf9\x20\xa1\x63\xd7";

pub(crate) struct RecoveryDb {
    pub db: Connection,
    pub issues: Vec<String>,
    // Fields drop in declaration order: close SQLite before removing scratch.
    _scratch: Option<tempfile::TempDir>,
}

pub(crate) fn open(root: &Path) -> Result<RecoveryDb> {
    if !fs::symlink_metadata(root)?.is_dir() {
        return Err(Error::Rejected(
            "recovery root must be a directory, not a symlink",
        ));
    }
    // Reject FIFOs/devices/symlinks and oversized inputs before SQLite can open
    // them. This guard does not interpret or repair a cold/live-writer journal.
    no_wal(root)?;
    if Source::open(root.join(DB), MAX_DB)?.metadata.len() < PAGE as u64 {
        return Err(Error::Rejected("truncated recorder database"));
    }
    match Source::open(root.join(JOURNAL), MAX_JOURNAL) {
        Ok(_) => (),
        Err(Error::Io(e)) if e.kind() == io::ErrorKind::NotFound => (),
        Err(e) => return Err(e),
    }
    let db = Connection::open_with_flags(
        root.join(DB),
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NOFOLLOW,
    )?;
    // Force SQLite's hot-journal check before loading any manifest/checkpoints.
    let probe = db.query_row("SELECT count(*) FROM sqlite_schema", [], |r| {
        r.get::<_, i64>(0)
    });
    match probe {
        Ok(_) => Ok(RecoveryDb {
            db,
            issues: Vec::new(),
            _scratch: None,
        }),
        Err(rusqlite::Error::SqliteFailure(e, _))
            if e.extended_code == rusqlite::ffi::SQLITE_READONLY_ROLLBACK =>
        {
            drop(db);
            rollback_copy(root)
        }
        Err(e) => Err(e.into()),
    }
}

fn no_wal(root: &Path) -> Result<()> {
    for name in ["checkpoints.sqlite-wal", "checkpoints.sqlite-shm"] {
        match fs::symlink_metadata(root.join(name)) {
            Err(e) if e.kind() == io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.into()),
            Ok(_) => return Err(Error::Rejected("WAL/SHM not supported by private rollback")),
        }
    }
    Ok(())
}

fn same(a: &Metadata, b: &Metadata) -> bool {
    a.dev() == b.dev()
        && a.ino() == b.ino()
        && a.len() == b.len()
        && a.mtime() == b.mtime()
        && a.mtime_nsec() == b.mtime_nsec()
        && a.ctime() == b.ctime()
        && a.ctime_nsec() == b.ctime_nsec()
}

struct Source {
    path: PathBuf,
    file: File,
    metadata: Metadata,
    maximum: u64,
}
impl Source {
    fn open(path: PathBuf, maximum: u64) -> Result<Self> {
        let named = fs::symlink_metadata(&path)?;
        if !named.is_file() || named.nlink() != 1 || named.len() > maximum {
            return Err(Error::Rejected("private rollback input type/link/size"));
        }
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
            .open(&path)?;
        let metadata = file.metadata()?;
        if !metadata.is_file() || metadata.nlink() != 1 || metadata.len() > maximum {
            return Err(Error::Rejected("private rollback input type/link/size"));
        }
        if !same(&named, &metadata) {
            return Err(Error::Rejected(
                "private rollback input changed while opening",
            ));
        }
        Ok(Self {
            path,
            file,
            metadata,
            maximum,
        })
    }
    fn stable(&self) -> Result<()> {
        let named = fs::symlink_metadata(&self.path)?;
        if !named.is_file()
            || !same(&self.metadata, &named)
            || !same(&self.metadata, &self.file.metadata()?)
        {
            return Err(Error::Rejected("private rollback input changed"));
        }
        Ok(())
    }
    fn read(&mut self) -> Result<Vec<u8>> {
        let mut bytes = Vec::new();
        (&mut self.file)
            .take(self.maximum + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() as u64 != self.metadata.len() {
            return Err(Error::Rejected("private rollback input length changed"));
        }
        self.stable()?;
        Ok(bytes)
    }
    fn verify(&mut self, expected: &[u8]) -> Result<()> {
        self.stable()?;
        self.file.seek(SeekFrom::Start(0))?;
        let mut hash = Sha256::new();
        let mut buffer = [0; 65536];
        let mut count = 0u64;
        loop {
            let n = self.file.read(&mut buffer)?;
            if n == 0 {
                break;
            }
            count += n as u64;
            if count > self.maximum {
                return Err(Error::Rejected("private rollback input grew"));
            }
            hash.update(&buffer[..n]);
        }
        if count != self.metadata.len() || hash.finalize().as_slice() != expected {
            return Err(Error::Rejected("private rollback input hash changed"));
        }
        self.stable()
    }
}

fn be32(bytes: &[u8]) -> u32 {
    u32::from_be_bytes(bytes.try_into().unwrap())
}

// https://www.sqlite.org/fileformat2.html#the_rollback_journal
// Validate the supported single, fully synced segment before SQLite playback:
// SQLite itself may stop at a malformed/truncated tail without reporting error.
// Checksum algorithm is pager_cksum in our bundled libsqlite3-sys 0.38.2 source.
fn validate(db: &[u8], journal: &[u8]) -> Result<()> {
    if db.len() < PAGE
        || !db.len().is_multiple_of(PAGE)
        || &db[..16] != b"SQLite format 3\0"
        || db[16..20] != [0x10, 0, 1, 1]
    {
        return Err(Error::Rejected("unsupported rollback database header/size"));
    }
    if journal.len() < 28 || &journal[..8] != MAGIC {
        return Err(Error::Rejected("invalid rollback journal header"));
    }
    let count = be32(&journal[8..12]) as usize;
    let seed = be32(&journal[12..16]);
    let pages = be32(&journal[16..20]) as usize;
    let sector = be32(&journal[20..24]) as usize;
    if be32(&journal[24..28]) as usize != PAGE
        || !(512..=65536).contains(&sector)
        || !sector.is_power_of_two()
        || pages == 0
        || pages > db.len() / PAGE
        || count == 0
        || count > pages
    {
        return Err(Error::Rejected(
            "unsupported/truncated rollback journal segment",
        ));
    }
    let end = sector + count * (PAGE + 8);
    if journal.len() != end {
        // sqlite3_db_cacheflush may initialize the next header after syncing
        // this segment. writeJournalHdr leaves magic/count zero until sync.
        // Accept only that complete, empty header; no page/torn/unknown tail.
        let next = end.div_ceil(sector) * sector;
        if journal.len() != next + sector
            || journal.len() < end
            || journal[end..next].iter().any(|b| *b != 0)
            || journal[next..next + 12].iter().any(|b| *b != 0)
            || journal[next + 16..next + 28] != journal[16..28]
            || journal[next + 28..].iter().any(|b| *b != 0)
        {
            return Err(Error::Rejected(
                "unsupported/truncated rollback journal tail",
            ));
        }
    }
    let mut seen = BTreeSet::new();
    for record in journal[sector..end].chunks_exact(PAGE + 8) {
        let page = be32(&record[..4]) as usize;
        if page == 0 || page > pages || !seen.insert(page) {
            return Err(Error::Rejected("invalid/duplicate rollback page"));
        }
        let data = &record[4..4 + PAGE];
        let mut checksum = seed;
        let mut i = PAGE - 200;
        while i > 0 {
            checksum = checksum.wrapping_add(data[i] as u32);
            i = i.saturating_sub(200);
        }
        if checksum != be32(&record[4 + PAGE..]) {
            return Err(Error::Rejected("rollback page checksum mismatch"));
        }
    }
    Ok(())
}

fn write_private(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    Ok(())
}

fn rollback_copy(root: &Path) -> Result<RecoveryDb> {
    let directory = fs::symlink_metadata(root)?;
    if !directory.is_dir() {
        return Err(Error::Rejected(
            "rollback root must be a directory, not a symlink",
        ));
    }
    no_wal(root)?;
    // Retired captures retain this lock; immutable exports intentionally omit it.
    // An absent lock is not permission to race a writer: stable exported inputs
    // remain the caller's precondition, supplemented by two-pass identity/hash checks.
    let _lock = match Source::open(root.join("capture.lock"), 0) {
        Ok(lock) => {
            lock.file
                .try_lock()
                .map_err(|_| Error::Rejected("capture writer active during rollback"))?;
            Some(lock)
        }
        Err(Error::Io(e)) if e.kind() == io::ErrorKind::NotFound => None,
        Err(e) => return Err(e),
    };
    let mut source_db = Source::open(root.join(DB), MAX_DB)?;
    let mut source_journal = Source::open(root.join(JOURNAL), MAX_JOURNAL)?;
    let db_bytes = source_db.read()?;
    let journal_bytes = source_journal.read()?;
    validate(&db_bytes, &journal_bytes)?;
    let db_hash = Sha256::digest(&db_bytes);
    let journal_hash = Sha256::digest(&journal_bytes);
    let scratch = tempfile::Builder::new()
        .prefix("actryn-evidence-rollback-")
        .tempdir()?;
    write_private(&scratch.path().join(DB), &db_bytes)?;
    write_private(&scratch.path().join(JOURNAL), &journal_bytes)?;
    source_db.verify(&db_hash)?;
    source_journal.verify(&journal_hash)?;
    no_wal(root)?;
    let after = fs::symlink_metadata(root)?;
    if !after.is_dir() || after.dev() != directory.dev() || after.ino() != directory.ino() {
        return Err(Error::Rejected("rollback root changed"));
    }
    let db = Connection::open_with_flags(
        scratch.path().join(DB),
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NOFOLLOW,
    )?;
    db.busy_timeout(Duration::ZERO)?;
    let integrity: String = db.query_row("PRAGMA integrity_check", [], |r| r.get(0))?;
    if integrity != "ok" || scratch.path().join(JOURNAL).exists() {
        return Err(Error::Rejected(
            "private rollback integrity/retirement failed",
        ));
    }
    db.execute_batch("PRAGMA query_only=ON;")?;
    let hex = |bytes: &[u8]| bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
    Ok(RecoveryDb {
        db,
        issues: vec![format!("private SQLite rollback after READONLY_ROLLBACK (776); original DB SHA256 {}; journal SHA256 {}; only committed checkpoints supported; uncommitted/volatile tail unknown", hex(&db_hash), hex(&journal_hash))],
        _scratch: Some(scratch),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn copied_inputs_must_keep_identity_metadata_and_hash() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("source");
        fs::write(&path, b"original").unwrap();
        let mut source = Source::open(path.clone(), 8).unwrap();
        let hash = Sha256::digest(source.read().unwrap());
        source.verify(&hash).unwrap();
        assert!(source.verify(&Sha256::digest(b"different")).is_err());
        fs::write(&path, b"modified").unwrap();
        assert!(source.verify(&hash).is_err());
        let mut source = Source::open(path.clone(), 8).unwrap();
        let hash = Sha256::digest(source.read().unwrap());
        fs::rename(&path, directory.path().join("old-inode")).unwrap();
        fs::write(&path, b"modified").unwrap();
        assert!(source.verify(&hash).is_err());
    }
}
