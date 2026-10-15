use super::*;
use rusqlite::{params, Connection, OptionalExtension};
use std::{
    fs::{self, File, OpenOptions},
    path::PathBuf,
};
pub(crate) struct Store {
    db: Connection,
    _lock: File,
    #[cfg(test)]
    pub block: Option<Arc<std::sync::Barrier>>,
    #[cfg(test)]
    pub fail: bool,
}
fn fixed<const N: usize>(bytes: Vec<u8>) -> Result<[u8; N]> {
    bytes
        .try_into()
        .map_err(|_| Error::Rejected("invalid fixed registry field"))
}
fn encode_intent(intent: &Intent) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(&intent.digest);
    out.extend_from_slice(&intent.configuration_digest);
    for n in [
        intent.instance,
        intent.grant,
        intent.context_revision,
        intent.deadline_ns,
        intent.observation,
    ] {
        out.extend_from_slice(&n.to_le_bytes());
    }
    out.extend_from_slice(&intent.payload);
    out
}
fn decode_intent(bytes: Vec<u8>, limit: usize) -> Result<Intent> {
    if bytes.len() < 104 || bytes.len() - 104 > limit {
        return Err(Error::Rejected("invalid stored intent size"));
    }
    let number = |offset| u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap());
    Ok(Intent {
        digest: bytes[..32].try_into().unwrap(),
        configuration_digest: bytes[32..64].try_into().unwrap(),
        instance: number(64),
        grant: number(72),
        context_revision: number(80),
        deadline_ns: number(88),
        observation: number(96),
        payload: bytes[104..].to_vec(),
    })
}
fn encode_operation(operation: OperationId) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(&operation.device);
    out.extend_from_slice(&operation.runtime_nonce);
    for n in [
        operation.boot,
        operation.session,
        operation.grant,
        operation.instance,
        operation.operation,
        operation.stream,
    ] {
        out.extend_from_slice(&n.to_le_bytes());
    }
    out
}
fn decode_operation(bytes: Vec<u8>) -> Result<OperationId> {
    if bytes.len() != 80 {
        return Err(Error::Rejected("invalid stored operation identity"));
    }
    let number = |offset| u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap());
    Ok(OperationId {
        device: bytes[..16].try_into().unwrap(),
        runtime_nonce: bytes[16..32].try_into().unwrap(),
        boot: number(32),
        session: number(40),
        grant: number(48),
        instance: number(56),
        operation: number(64),
        stream: number(72),
    })
}
fn encode_close(closure: Closure) -> Vec<u8> {
    let (code, value) = match closure {
        Closure::NotRequested => (0, 0),
        Closure::NotAllocated => (1, 0),
        Closure::Requested => (2, 0),
        Closure::LocallyClosed { transition } => (3, transition),
        Closure::Failed(AuthorityError::Denied) => (4, 0),
        Closure::Failed(AuthorityError::Unavailable) => (5, 0),
        Closure::Failed(AuthorityError::OutcomeUnknown) => (6, 0),
    };
    let mut out = vec![code];
    out.extend_from_slice(&value.to_le_bytes());
    out
}
fn decode_close(bytes: Vec<u8>) -> Result<Closure> {
    if bytes.len() != 9 {
        return Err(Error::Rejected("invalid closure field"));
    }
    Ok(match bytes[0] {
        0 => Closure::NotRequested,
        1 => Closure::NotAllocated,
        2 => Closure::Requested,
        3 => Closure::LocallyClosed {
            transition: u64::from_le_bytes(bytes[1..].try_into().unwrap()),
        },
        4 => Closure::Failed(AuthorityError::Denied),
        5 => Closure::Failed(AuthorityError::Unavailable),
        6 => Closure::Failed(AuthorityError::OutcomeUnknown),
        _ => return Err(Error::Rejected("invalid closure code")),
    })
}
fn terminal_update_allowed(
    old_revision: i64,
    old_terminal: bool,
    new_revision: i64,
    new_terminal: bool,
) -> bool {
    new_revision > old_revision && (!old_terminal || new_terminal)
}
impl Store {
    pub fn open(
        path: &Path,
        epoch: [u8; 16],
        limits: &Limits,
    ) -> Result<(Self, NamespaceMap, EntryMap)> {
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        fs::create_dir_all(parent)?;
        let mut lock_path = PathBuf::from(path);
        lock_path.set_extension("lock");
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(lock_path)?;
        lock.try_lock()
            .map_err(|_| Error::Rejected("registry already open"))?;
        let mut db = Connection::open(path)?;
        db.pragma_update(None, "page_size", 4096)?;
        db.pragma_update(
            None,
            "max_page_count",
            (limits.database_bytes / 4096) as i64,
        )?;
        let pages: i64 = db.pragma_query_value(None, "max_page_count", |row| row.get(0))?;
        if pages as u64 > limits.database_bytes / 4096 {
            return Err(Error::Rejected(
                "existing database exceeds configured quota",
            ));
        }
        db.execute_batch("PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL; PRAGMA temp_store=MEMORY;
            CREATE TABLE IF NOT EXISTS format(version INTEGER PRIMARY KEY CHECK(version=1)); INSERT OR IGNORE INTO format VALUES(1);
            CREATE TABLE IF NOT EXISTS epochs(epoch BLOB PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS namespaces(id BLOB PRIMARY KEY,attempt BLOB NOT NULL,epoch BLOB NOT NULL,revision INTEGER NOT NULL,retired INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS records(namespace BLOB NOT NULL,key BLOB NOT NULL,revision INTEGER NOT NULL,terminal INTEGER NOT NULL,
                phase INTEGER NOT NULL,intent BLOB,operation BLOB,closure BLOB NOT NULL,PRIMARY KEY(namespace,key));")?;
        let reused: bool = db.query_row(
            "SELECT EXISTS(SELECT 1 FROM epochs WHERE epoch=?1)",
            [epoch.as_slice()],
            |r| r.get(0),
        )?;
        if reused {
            return Err(Error::Rejected("manager epoch cannot reopen"));
        }
        // Startup is nondispatchable. Historical cancelled keys remain tombstones;
        // every unfinished durable intent becomes unknown, never resent.
        let exhausted:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM namespaces WHERE retired=0 AND revision=9223372036854775807) OR EXISTS(SELECT 1 FROM records WHERE terminal=0 AND revision=9223372036854775807)",[],|r|r.get(0))?;
        if exhausted {
            return Err(Error::Rejected(
                "registry revision exhausted; servicing required",
            ));
        }
        let tx = db.transaction()?;
        tx.execute("INSERT INTO epochs VALUES(?1)", [epoch.as_slice()])?;
        tx.execute(
            "UPDATE namespaces SET retired=1,revision=revision+1 WHERE retired=0",
            [],
        )?;
        tx.execute(
            "UPDATE records SET terminal=1,phase=8,revision=revision+1 WHERE terminal=0",
            [],
        )?;
        tx.commit()?;
        File::open(parent)?.sync_all()?;
        let store = Self {
            db,
            _lock: lock,
            #[cfg(test)]
            block: None,
            #[cfg(test)]
            fail: false,
        };
        let mut namespaces = BTreeMap::new();
        let mut statement = store
            .db
            .prepare("SELECT id,attempt,epoch,revision,retired FROM namespaces")?;
        let mut rows = statement.query([])?;
        while let Some(row) = rows.next()? {
            if namespaces.len() >= limits.namespaces {
                return Err(Error::Capacity);
            }
            let id = fixed(row.get(0)?)?;
            let revision = row.get::<_, i64>(3)?;
            if revision <= 0 {
                return Err(Error::Rejected("invalid namespace revision"));
            }
            namespaces.insert(
                id,
                NamespaceRecord {
                    id,
                    attempt: fixed(row.get(1)?)?,
                    epoch: fixed(row.get(2)?)?,
                    revision: revision as u64,
                    ready: false,
                    retired: row.get(4)?,
                },
            );
        }
        drop(rows);
        drop(statement);
        let keys = store
            .db
            .prepare("SELECT namespace,key FROM records LIMIT ?1")?
            .query_map([(limits.keys + 1) as i64], |r| {
                Ok((r.get::<_, Vec<u8>>(0)?, r.get::<_, Vec<u8>>(1)?))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        if keys.len() > limits.keys {
            return Err(Error::Capacity);
        }
        let mut entries = BTreeMap::new();
        for (ns, key) in keys {
            let ns = fixed(ns)?;
            let key = fixed(key)?;
            if !namespaces.contains_key(&ns) {
                return Err(Error::Rejected("orphaned request namespace"));
            }
            let entry = store
                .read_key(ns, key, limits.max_payload_bytes)?
                .ok_or(Error::Rejected("missing key"))?;
            entries.insert((ns, key), entry);
        }
        Ok((store, namespaces, entries))
    }
    pub fn persist(
        &mut self,
        job: &Job,
        parent: Option<&NamespaceRecord>,
        limits: &Limits,
    ) -> Result<Option<Entry>> {
        #[cfg(test)]
        {
            if let Some(barrier) = self.block.take() {
                barrier.wait();
                barrier.wait();
            }
            if self.fail {
                return Err(std::io::Error::other("injected registry persistence failure").into());
            }
        }
        let tx = self.db.transaction()?;
        let ns = match job {
            Job::Namespace(ns) => ns,
            Job::Key(_) => parent.ok_or(Error::Rejected("missing parent namespace"))?,
        };
        if ns.revision > i64::MAX as u64 {
            return Err(Error::Rejected("namespace revision exhausted"));
        }
        tx.execute("INSERT INTO namespaces VALUES(?1,?2,?3,?4,?5) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,retired=excluded.retired
            WHERE namespaces.retired=0 AND excluded.revision>namespaces.revision",params![ns.id.as_slice(),ns.attempt.as_slice(),ns.epoch.as_slice(),ns.revision as i64,ns.retired])?;
        if let Job::Key(entry) = job {
            let s = &entry.snapshot;
            if s.revision > i64::MAX as u64 {
                return Err(Error::Rejected("key revision exhausted"));
            }
            let prior: Option<(i64, bool)> = tx
                .query_row(
                    "SELECT revision,terminal FROM records WHERE namespace=?1 AND key=?2",
                    params![s.namespace.as_slice(), s.key.as_slice()],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()?;
            if prior.is_none_or(|(revision, terminal)| {
                terminal_update_allowed(revision, terminal, s.revision as i64, s.terminal)
            }) {
                let phase = match s.phase {
                    Phase::PendingIntent => Phase::IntentDurable,
                    Phase::CancelPending => Phase::CancelledDurable,
                    other => other,
                };
                tx.execute("INSERT INTO records VALUES(?1,?2,?3,?4,?5,?6,?7,?8) ON CONFLICT(namespace,key) DO UPDATE SET
                    revision=excluded.revision,terminal=excluded.terminal,phase=excluded.phase,intent=excluded.intent,operation=excluded.operation,closure=excluded.closure",
                    params![s.namespace.as_slice(),s.key.as_slice(),s.revision as i64,s.terminal,phase as u8,
                    entry.intent.as_ref().map(encode_intent),s.operation.map(encode_operation),encode_close(s.closure)])?;
            }
        }
        tx.commit()?;
        match job {
            Job::Key(entry) => self.read_key(
                entry.snapshot.namespace,
                entry.snapshot.key,
                limits.max_payload_bytes,
            ),
            Job::Namespace(_) => Ok(None),
        }
    }
    fn read_key(
        &self,
        ns: NamespaceId,
        key: RequestKey,
        max_payload: usize,
    ) -> Result<Option<Entry>> {
        let stored=self.db.query_row("SELECT revision,terminal,phase,intent,operation,closure FROM records WHERE namespace=?1 AND key=?2",
            params![ns.as_slice(),key.as_slice()],|r|Ok((r.get::<_,i64>(0)?,r.get::<_,bool>(1)?,r.get::<_,u8>(2)?,r.get::<_,Option<Vec<u8>>>(3)?,r.get::<_,Option<Vec<u8>>>(4)?,r.get::<_,Vec<u8>>(5)?))).optional()?;
        let Some((revision, terminal, phase, intent, operation, closure)) = stored else {
            return Ok(None);
        };
        if revision <= 0 {
            return Err(Error::Rejected("invalid key revision"));
        }
        let intent = intent.map(|b| decode_intent(b, max_payload)).transpose()?;
        Ok(Some(Entry {
            snapshot: Snapshot {
                namespace: ns,
                key,
                digest: intent.as_ref().map(|i| i.digest),
                operation: operation.map(decode_operation).transpose()?,
                revision: revision as u64,
                durable_revision: revision as u64,
                phase: Phase::parse(phase)?,
                terminal,
                closure: decode_close(closure)?,
                persistence_failed: false,
            },
            intent,
        }))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn terminal_wins_even_when_newer_work_arrives_late() {
        assert!(!terminal_update_allowed(2, true, 1, false));
        assert!(!terminal_update_allowed(2, true, 3, false));
        assert!(terminal_update_allowed(1, false, 2, true));
    }
}
