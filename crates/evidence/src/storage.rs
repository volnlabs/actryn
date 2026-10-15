use super::*;
use mcap::{records::MessageHeader, WriteOptions};
use rusqlite::{params, Connection, OpenFlags};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions as FileOptions},
    io::{Read, Seek, SeekFrom, Write},
    path::PathBuf,
};
const MAX_BATCH_BYTES: u64 = 8_388_608;
/// Enforce the reserved file ceiling even if upstream format overhead changes.
struct BoundedFile {
    file: File,
    maximum: u64,
    position: u64,
}
impl Write for BoundedFile {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let available = self.maximum - self.position;
        if !bytes.is_empty() && available == 0 {
            return Err(io::Error::other("reserved MCAP file ceiling"));
        }
        let count = self
            .file
            .write(&bytes[..bytes.len().min(available as usize)])?;
        self.position += count as u64;
        Ok(count)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.file.flush()
    }
}
impl Seek for BoundedFile {
    fn seek(&mut self, from: SeekFrom) -> io::Result<u64> {
        let position = match from {
            SeekFrom::Start(n) => n as i128,
            SeekFrom::Current(n) => self.position as i128 + n as i128,
            SeekFrom::End(n) => self.file.metadata()?.len() as i128 + n as i128,
        };
        if position < 0 || position > self.maximum as i128 {
            return Err(io::Error::other("seek beyond reserved MCAP file"));
        }
        self.position = self.file.seek(SeekFrom::Start(position as u64))?;
        Ok(self.position)
    }
}

pub(crate) struct Store {
    root: PathBuf,
    db: Connection,
    _lock: File,
    next: i64,
    frontiers: Vec<u64>,
    disk_bytes: u64,
    batch_bytes: u64,
    reserved_disk: u64,
    #[cfg(test)]
    pub fail_after_sync: bool,
    #[cfg(test)]
    pub block: Option<Arc<std::sync::Barrier>>,
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn origin(n: u8) -> Result<Origin> {
    Ok(match n {
        1 => Origin::Runtime,
        2 => Origin::Kernel,
        3 => Origin::Controller,
        4 => Origin::Broker,
        5 => Origin::Agent,
        6 => Origin::Operator,
        _ => return Err(Error::Rejected("invalid origin")),
    })
}
fn fixed<const N: usize>(bytes: Vec<u8>) -> Result<[u8; N]> {
    bytes
        .try_into()
        .map_err(|_| Error::Rejected("invalid fixed metadata"))
}
fn sequence(bytes: Vec<u8>) -> Result<u64> {
    Ok(u64::from_le_bytes(fixed(bytes)?))
}
fn batch_name(id: i64) -> String {
    format!("batch-{id:020}.mcap")
}
impl Store {
    pub fn create(root: &Path, spec: &CaptureSpec, limits: &Limits) -> Result<Self> {
        fs::create_dir(root)?;
        let lock = FileOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(root.join("capture.lock"))?;
        lock.try_lock()
            .map_err(|_| Error::Rejected("capture already owned"))?;
        lock.sync_all()?;
        let mut db = Connection::open(root.join("checkpoints.sqlite"))?;
        db.pragma_update(None, "page_size", 4096)?;
        let checkpoint_pages = limits.disk_bytes / 8 / 4096;
        db.pragma_update(None, "max_page_count", checkpoint_pages as i64)?;
        db.execute_batch("PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL; PRAGMA temp_store=MEMORY;
            CREATE TABLE meta(key TEXT PRIMARY KEY,value BLOB NOT NULL);
            CREATE TABLE producers(id INTEGER PRIMARY KEY,identity BLOB NOT NULL,session BLOB NOT NULL,origin INTEGER NOT NULL,
                clock TEXT NOT NULL,error BLOB NOT NULL,requested BLOB NOT NULL,required INTEGER NOT NULL);
            CREATE TABLE batches(id INTEGER PRIMARY KEY,bytes INTEGER NOT NULL,hash BLOB NOT NULL,records INTEGER NOT NULL);
            CREATE TABLE checkpoints(batch INTEGER NOT NULL,producer INTEGER NOT NULL,sequence BLOB NOT NULL,PRIMARY KEY(batch,producer));")?;
        let tx = db.transaction()?;
        for (key, value) in [
            ("format", b"ACTRYN-EVIDENCE-2".as_slice()),
            ("attempt", spec.attempt.as_slice()),
            ("profile", spec.profile_digest.as_slice()),
            ("configuration", spec.configuration_digest.as_slice()),
            (
                "policy",
                if spec.policy == CapturePolicy::MetadataOnly {
                    b"metadata".as_slice()
                } else {
                    b"payload".as_slice()
                },
            ),
            ("retention", spec.retention.as_bytes()),
            ("redaction", spec.redaction.as_bytes()),
        ] {
            tx.execute("INSERT INTO meta VALUES(?1,?2)", params![key, value])?;
        }
        for (key, value) in [
            ("disk_bytes", limits.disk_bytes),
            ("batch_bytes", limits.batch_bytes),
            ("volatile_bytes", limits.volatile_bytes as u64),
            ("volatile_records", limits.volatile_records as u64),
            ("reserved_bytes", limits.reserved_bytes as u64),
            ("reserved_records", limits.reserved_records as u64),
            (
                "max_pending_age_ns",
                limits.max_pending_age.as_nanos() as u64,
            ),
            ("heartbeat_ns", limits.heartbeat.as_nanos() as u64),
        ] {
            tx.execute(
                "INSERT INTO meta VALUES(?1,?2)",
                params![key, value.to_le_bytes().as_slice()],
            )?;
        }
        for (id, p) in spec.producers.iter().enumerate() {
            tx.execute(
                "INSERT INTO producers VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
                params![
                    id as i64,
                    p.identity.as_slice(),
                    p.session.to_le_bytes().as_slice(),
                    p.origin as u8,
                    p.clock_domain,
                    p.clock_error_ns.to_le_bytes().as_slice(),
                    p.requested.iter().map(|k| *k as u8).collect::<Vec<_>>(),
                    p.required_for_replay
                ],
            )?;
        }
        tx.commit()?;
        File::open(root)?.sync_all()?;
        if let Some(parent) = root.parent() {
            File::open(if parent.as_os_str().is_empty() {
                Path::new(".")
            } else {
                parent
            })?
            .sync_all()?;
        }
        Ok(Self {
            root: root.to_owned(),
            db,
            _lock: lock,
            next: 1,
            frontiers: vec![0; spec.producers.len()],
            disk_bytes: limits.disk_bytes,
            batch_bytes: limits.batch_bytes,
            // DB main file plus a conservative rollback-journal allowance. SQLite
            // max_page_count bounds the main file; no WAL or temp-file growth is used.
            reserved_disk: checkpoint_pages * 4096 * 3,
            #[cfg(test)]
            fail_after_sync: false,
            #[cfg(test)]
            block: None,
        })
    }
    pub fn commit(&mut self, batch: &[Pending], spec: &CaptureSpec) -> Result<()> {
        #[cfg(test)]
        if let Some(barrier) = &self.block {
            barrier.wait();
            barrier.wait();
        }
        // Reserve before creating a file. Unchunked MCAP event overhead fits the
        // charged Pending header; fixed/channel allowance covers header/footer/metadata.
        let reservation = batch
            .iter()
            .map(|pending| pending.charge as u64)
            .sum::<u64>()
            + spec.producers.len() as u64 * 1024
            + 4096;
        if reservation > self.batch_bytes
            || reservation > self.disk_bytes.saturating_sub(self.reserved_disk)
        {
            return Err(Error::DiskBudget);
        }
        let path = self.root.join(batch_name(self.next));
        let file = FileOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)?;
        let mut writer = WriteOptions::new()
            .use_chunks(false)
            .compression(None)
            .emit_summary_records(false)
            .emit_summary_offsets(false)
            .profile("actryn-evidence-v2")
            .create(BoundedFile {
                file,
                maximum: reservation,
                position: 0,
            })?;
        let mut channels = Vec::new();
        for (id, p) in spec.producers.iter().enumerate() {
            let metadata = BTreeMap::from([
                ("origin".into(), format!("{:?}", p.origin)),
                ("identity".into(), hex(&p.identity)),
                ("session".into(), p.session.to_string()),
                ("clock_domain".into(), p.clock_domain.clone()),
                ("clock_error_ns".into(), p.clock_error_ns.to_string()),
            ]);
            channels.push(writer.add_channel(
                0,
                &format!("actryn/{id}"),
                "actryn-evidence-v2",
                &metadata,
            )?);
        }
        let mut frontiers = self.frontiers.clone();
        for pending in batch {
            let r = &pending.record;
            writer.write_to_known_channel(
                &MessageHeader {
                    channel_id: channels[r.producer],
                    sequence: 0,
                    log_time: r.captured_ns,
                    publish_time: r.source_time_ns,
                },
                &encode(r),
            )?;
            frontiers[r.producer] = r.sequence;
        }
        writer.finish()?;
        let mut file = writer.into_inner().file;
        file.flush()?;
        file.sync_all()?;
        File::open(&self.root)?.sync_all()?;
        let byte_len = file.metadata()?.len();
        if byte_len > reservation || byte_len > self.batch_bytes {
            return Err(Error::Rejected("MCAP batch exceeds bound"));
        }
        let mut input = File::open(&path)?;
        let mut digest = Sha256::new();
        let mut buffer = [0u8; 8192];
        loop {
            let count = input.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            digest.update(&buffer[..count]);
        }
        let hash: [u8; 32] = digest.finalize().into();
        #[cfg(test)]
        if self.fail_after_sync {
            return Err(io::Error::other("injected loss after MCAP sync before checkpoint").into());
        }
        let tx = self.db.transaction()?;
        tx.execute(
            "INSERT INTO batches VALUES(?1,?2,?3,?4)",
            params![
                self.next,
                byte_len as i64,
                hash.as_slice(),
                batch.len() as i64
            ],
        )?;
        for (producer, seq) in frontiers.iter().enumerate() {
            tx.execute(
                "INSERT INTO checkpoints VALUES(?1,?2,?3)",
                params![self.next, producer as i64, seq.to_le_bytes().as_slice()],
            )?;
        }
        tx.commit()?;
        self.reserved_disk += byte_len;
        self.frontiers = frontiers;
        self.next = self
            .next
            .checked_add(1)
            .ok_or(Error::Rejected("batch counter exhausted"))?;
        Ok(())
    }
}
fn encode(r: &CapturedRecord) -> Vec<u8> {
    let data = r.payload.as_deref().unwrap_or_default();
    let mut out = Vec::with_capacity(80 + data.len());
    out.extend_from_slice(b"EVR2");
    out.extend_from_slice(&(r.producer as u16).to_le_bytes());
    out.push(r.kind as u8);
    out.push(u8::from(r.payload.is_some()) | (u8::from(r.metadata) << 1));
    for n in [r.sequence, r.source_time_ns, r.captured_ns, r.input_bytes] {
        out.extend_from_slice(&n.to_le_bytes());
    }
    out.extend_from_slice(&r.digest);
    out.extend_from_slice(&(data.len() as u64).to_le_bytes());
    out.extend_from_slice(data);
    out
}
fn decode(bytes: &[u8], spec: &CaptureSpec) -> Result<CapturedRecord> {
    if bytes.len() < 80 || &bytes[..4] != b"EVR2" {
        return Err(Error::Rejected("invalid event encoding"));
    }
    let producer = u16::from_le_bytes(bytes[4..6].try_into().unwrap()) as usize;
    let p = spec
        .producers
        .get(producer)
        .ok_or(Error::Rejected("unknown source"))?;
    let kind = EventKind::from_byte(bytes[6])?;
    if (kind != EventKind::Prefix && !p.requested.contains(&kind))
        || (p.origin == Origin::Agent && kind != EventKind::AgentPayload)
    {
        return Err(Error::Rejected("event outside source capability"));
    }
    let get = |offset| u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap());
    let len = usize::try_from(get(72)).map_err(|_| Error::Rejected("event length overflow"))?;
    if len != bytes.len() - 80
        || bytes[7] > 3
        || (bytes[7] & 1 == 0 && len != 0)
        || get(8) == 0
        || get(32) > 1_048_576
    {
        return Err(Error::Rejected("invalid event payload length/sequence"));
    }
    let digest: [u8; 32] = bytes[40..72].try_into().unwrap();
    let metadata = bytes[7] & 2 != 0;
    if metadata
        && (bytes[7] & 1 == 0
            || p.origin == Origin::Agent
            || matches!(
                kind,
                EventKind::Input | EventKind::ModelOutput | EventKind::AgentPayload
            ))
    {
        return Err(Error::Rejected("invalid structural metadata flag"));
    }
    let payload = (bytes[7] & 1 == 1).then(|| bytes[80..].to_vec());
    if let Some(payload) = &payload {
        if Sha256::digest(payload).as_slice() != digest || payload.len() as u64 != get(32) {
            return Err(Error::Rejected("payload integrity/length mismatch"));
        }
    }
    if kind == EventKind::Prefix
        && (payload.as_deref() != Some(get(16).to_le_bytes().as_slice()) || get(16) > get(24))
    {
        return Err(Error::Rejected("invalid source prefix seal"));
    }
    Ok(CapturedRecord {
        producer,
        origin: p.origin,
        sequence: get(8),
        source_time_ns: get(16),
        captured_ns: get(24),
        kind,
        payload,
        metadata,
        digest,
        input_bytes: get(32),
    })
}
#[derive(Debug)]
pub struct Recovery {
    pub manifest: CaptureSpec,
    pub limits: Limits,
    pub frontiers: Vec<Frontiers>,
    pub records: Vec<CapturedRecord>,
    pub raw_remnants: Vec<PathBuf>,
    pub issues: Vec<String>,
    pub volatile_tail_unknown: bool,
}
#[derive(Debug, PartialEq, Eq)]
pub struct ReplayEligibility {
    pub eligible: bool,
    pub missing: Vec<String>,
}
#[derive(Clone, Debug)]
pub struct SourceSummary {
    pub producer: usize,
    pub requested: Vec<EventKind>,
    pub retained_streams: Vec<EventKind>,
    pub payload_streams: Vec<EventKind>,
    pub metadata_streams: Vec<EventKind>,
    pub first_sequence: Option<u64>,
    pub last_sequence: Option<u64>,
    pub gaps: Vec<(u64, u64)>,
    pub durable_frontier: u64,
}
impl Recovery {
    /// Together with `manifest`, this is the capture manifest's actual retention,
    /// durable sequence ranges and explicit source gaps. Interventions remain typed records.
    pub fn source_summary(&self) -> Vec<SourceSummary> {
        self.manifest
            .producers
            .iter()
            .enumerate()
            .map(|(index, spec)| {
                let records = self
                    .records
                    .iter()
                    .filter(|r| r.producer == index)
                    .collect::<Vec<_>>();
                let mut retained = Vec::new();
                let mut payload = Vec::new();
                let mut metadata = Vec::new();
                let mut gaps = Vec::new();
                let mut previous = 0u64;
                for record in &records {
                    if !retained.contains(&record.kind) {
                        retained.push(record.kind);
                    }
                    if record.metadata && !metadata.contains(&record.kind) {
                        metadata.push(record.kind);
                    }
                    if record.payload.is_some()
                        && !record.metadata
                        && !payload.contains(&record.kind)
                    {
                        payload.push(record.kind);
                    }
                    if previous
                        .checked_add(1)
                        .is_some_and(|next| record.sequence > next)
                    {
                        gaps.push((previous + 1, record.sequence - 1));
                    }
                    previous = record.sequence;
                }
                SourceSummary {
                    producer: index,
                    requested: spec.requested.clone(),
                    retained_streams: retained,
                    payload_streams: payload,
                    metadata_streams: metadata,
                    first_sequence: records.first().map(|r| r.sequence),
                    last_sequence: records.last().map(|r| r.sequence),
                    gaps,
                    durable_frontier: self.frontiers[index].durable,
                }
            })
            .collect()
    }
    /// Inspection/event playback only. This library contains no command, device or
    /// credential interface; execution must separately enforce the isolated profile.
    pub fn execution_replay(&self, through_ns: u64) -> ReplayEligibility {
        let mut missing = Vec::new();
        if self.manifest.policy != CapturePolicy::FullPayload {
            missing.push("metadata-only capture".into());
        }
        if !self.issues.is_empty() {
            missing.push("unsupported durable checkpoint or raw tail".into());
        }
        let activation = self.records.iter().find(|r| {
            r.kind == EventKind::Activation
                && r.origin == Origin::Runtime
                && r.captured_ns <= through_ns
                && r.payload.is_some()
        });
        if activation.is_none() {
            missing.push("retained instance activation boundary".into());
        }
        if !self.records.iter().any(|record| {
            record.kind == EventKind::Configuration
                && record.captured_ns <= through_ns
                && record.payload.as_ref().is_some_and(|payload| {
                    <[u8; 32]>::from(Sha256::digest(payload)) == self.manifest.configuration_digest
                })
        }) {
            missing.push("retained configuration matching immutable configuration digest".into());
        }
        for kind in [
            EventKind::Configuration,
            EventKind::Input,
            EventKind::ModelOutput,
            EventKind::Execution,
            EventKind::Intervention,
        ] {
            if !self
                .records
                .iter()
                .any(|r| r.kind == kind && r.captured_ns <= through_ns && r.payload.is_some())
            {
                missing.push(format!("retained {kind:?} prefix"));
            }
        }
        for (index, p) in self
            .manifest
            .producers
            .iter()
            .enumerate()
            .filter(|(_, p)| p.required_for_replay)
        {
            let prefix = self
                .records
                .iter()
                .filter(|r| r.producer == index)
                .collect::<Vec<_>>();
            let seal = prefix
                .iter()
                .position(|r| r.kind == EventKind::Prefix && r.source_time_ns >= through_ns);
            let Some(seal) = seal else {
                missing.push(format!("producer {index} complete-prefix seal"));
                continue;
            };
            let mut expected = 1u64;
            for record in &prefix[..=seal] {
                if record.sequence != expected {
                    missing.push(format!("producer {index} sequence gap"));
                    break;
                }
                expected = expected.saturating_add(1);
            }
            if prefix[..=seal]
                .iter()
                .any(|r| r.captured_ns <= through_ns && r.payload.is_none())
            {
                missing.push(format!(
                    "producer {index} missing payload (hash is insufficient)"
                ));
            }
            for kind in &p.requested {
                if !prefix[..=seal]
                    .iter()
                    .any(|r| r.kind == *kind && r.captured_ns <= through_ns && r.payload.is_some())
                {
                    missing.push(format!("producer {index} requested {kind:?} stream absent"));
                }
            }
        }
        if !self
            .manifest
            .producers
            .iter()
            .any(|p| p.required_for_replay)
        {
            missing.push("no required source-prefix contract".into());
        }
        ReplayEligibility {
            eligible: missing.is_empty(),
            missing,
        }
    }
}
fn meta(db: &Connection, key: &str) -> Result<Vec<u8>> {
    Ok(db.query_row("SELECT value FROM meta WHERE key=?1", [key], |r| r.get(0))?)
}
fn load_manifest(db: &Connection) -> Result<CaptureSpec> {
    if meta(db, "format")? != b"ACTRYN-EVIDENCE-2" {
        return Err(Error::Rejected("unsupported capture format"));
    }
    let policy = match meta(db, "policy")?.as_slice() {
        b"metadata" => CapturePolicy::MetadataOnly,
        b"payload" => CapturePolicy::FullPayload,
        _ => return Err(Error::Rejected("invalid capture policy")),
    };
    let mut statement=db.prepare("SELECT id,identity,session,origin,clock,error,requested,required FROM producers ORDER BY id")?;
    let mut rows = statement.query([])?;
    let mut producers = Vec::new();
    while let Some(row) = rows.next()? {
        let id: i64 = row.get(0)?;
        let origin_code: u8 = row.get(3)?;
        let requested: Vec<u8> = row.get(6)?;
        if id != producers.len() as i64 || id >= 32 {
            return Err(Error::Rejected("invalid source manifest"));
        }
        producers.push(ProducerSpec {
            identity: fixed(row.get(1)?)?,
            session: sequence(row.get(2)?)?,
            origin: origin(origin_code)?,
            clock_domain: row.get(4)?,
            clock_error_ns: sequence(row.get(5)?)?,
            requested: requested
                .into_iter()
                .map(EventKind::from_byte)
                .collect::<Result<_>>()?,
            required_for_replay: row.get(7)?,
        });
    }
    Ok(CaptureSpec {
        attempt: fixed(meta(db, "attempt")?)?,
        profile_digest: fixed(meta(db, "profile")?)?,
        configuration_digest: fixed(meta(db, "configuration")?)?,
        policy,
        retention: String::from_utf8(meta(db, "retention")?)
            .map_err(|_| Error::Rejected("invalid retention"))?,
        redaction: String::from_utf8(meta(db, "redaction")?)
            .map_err(|_| Error::Rejected("invalid redaction"))?,
        producers,
    })
}
pub(crate) fn recover(root: &Path) -> Result<Recovery> {
    // Recovery opens only SQLite read-only and recording files read-only. It cannot
    // resume a capture, repair raw data, mint producer handles or dispatch work.
    let db = Connection::open_with_flags(
        root.join("checkpoints.sqlite"),
        OpenFlags::SQLITE_OPEN_READ_ONLY,
    )?;
    let manifest = load_manifest(&db)?;
    let number = |key| sequence(meta(&db, key)?);
    let limits = Limits {
        disk_bytes: number("disk_bytes")?,
        batch_bytes: number("batch_bytes")?,
        volatile_bytes: number("volatile_bytes")?
            .try_into()
            .map_err(|_| Error::Rejected("invalid volatile limit"))?,
        volatile_records: number("volatile_records")?
            .try_into()
            .map_err(|_| Error::Rejected("invalid record limit"))?,
        reserved_bytes: number("reserved_bytes")?
            .try_into()
            .map_err(|_| Error::Rejected("invalid reserve"))?,
        reserved_records: number("reserved_records")?
            .try_into()
            .map_err(|_| Error::Rejected("invalid reserve"))?,
        max_pending_age: Duration::from_nanos(number("max_pending_age_ns")?),
        heartbeat: Duration::from_nanos(number("heartbeat_ns")?),
    };

    let mut result = Recovery {
        frontiers: vec![Frontiers::default(); manifest.producers.len()],
        manifest,
        limits,
        records: Vec::new(),
        raw_remnants: Vec::new(),
        issues: Vec::new(),
        volatile_tail_unknown: true,
    };
    let mut supported = BTreeSet::new();
    let mut expected = 1i64;
    let mut statement = db.prepare("SELECT id,bytes,hash,records FROM batches ORDER BY id")?;
    let mut rows = statement.query([])?;
    while let Some(row) = rows.next()? {
        let id: i64 = row.get(0)?;
        let length = u64::try_from(row.get::<_, i64>(1)?)
            .map_err(|_| Error::Rejected("negative batch length"))?;
        let hash: Vec<u8> = row.get(2)?;
        let count = usize::try_from(row.get::<_, i64>(3)?)
            .map_err(|_| Error::Rejected("negative record count"))?;
        let path = root.join(batch_name(id));
        let loaded = (|| -> Result<(Vec<CapturedRecord>, Vec<Frontiers>)> {
            if id != expected
                || length > MAX_BATCH_BYTES
                || length > result.limits.batch_bytes
                || count > 4096
                || fs::metadata(&path)?.len() != length
            {
                return Err(Error::Rejected("unsupported batch size/order"));
            }
            let bytes = fs::read(&path)?;
            if Sha256::digest(&bytes).as_slice() != hash {
                return Err(Error::Rejected("MCAP checkpoint hash mismatch"));
            }
            let mut records = Vec::new();
            let mut frontiers = result.frontiers.clone();
            for message in mcap::MessageStream::new(&bytes)? {
                let message = message?;
                let record = decode(&message.data, &result.manifest)?;
                let p = &result.manifest.producers[record.producer];
                if message.channel.topic != format!("actryn/{}", record.producer)
                    || message.channel.metadata.get("origin") != Some(&format!("{:?}", p.origin))
                    || message.channel.metadata.get("identity") != Some(&hex(&p.identity))
                    || message.channel.metadata.get("session") != Some(&p.session.to_string())
                    || message.log_time != record.captured_ns
                    || message.publish_time != record.source_time_ns
                {
                    return Err(Error::Rejected("source channel metadata mismatch"));
                }
                let f = &mut frontiers[record.producer];
                if record.sequence <= f.durable || records.len() >= count {
                    return Err(Error::Rejected("nonmonotonic/excess records"));
                }
                if f.durable.checked_add(1) != Some(record.sequence) {
                    f.gap_count = f.gap_count.saturating_add(1);
                }
                f.durable = record.sequence;
                f.read = record.sequence;
                f.queued = record.sequence;
                records.push(record);
            }
            if records.len() != count {
                return Err(Error::Rejected("MCAP record count mismatch"));
            }
            let mut checks = db.prepare(
                "SELECT producer,sequence FROM checkpoints WHERE batch=?1 ORDER BY producer",
            )?;
            let pairs = checks
                .query_map([id], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, Vec<u8>>(1)?)))?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            if pairs.len() != frontiers.len() {
                return Err(Error::Rejected("incomplete checkpoint"));
            }
            for (index, (producer, seq)) in pairs.into_iter().enumerate() {
                if index as i64 != producer || sequence(seq)? != frontiers[index].durable {
                    return Err(Error::Rejected("unsupported durable frontier"));
                }
            }
            Ok((records, frontiers))
        })();
        match loaded {
            Ok((records, frontiers)) => {
                result.records.extend(records);
                result.frontiers = frontiers;
                supported.insert(path);
                expected += 1;
            }
            Err(error) => {
                result
                    .issues
                    .push(format!("batch {id} excluded with following tail: {error}"));
                break;
            }
        }
    }
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        if path.extension().is_some_and(|s| s == "mcap") && !supported.contains(&path) {
            result.raw_remnants.push(path);
        }
    }
    result.raw_remnants.sort();
    if !result.raw_remnants.is_empty() {
        result
            .issues
            .push("uncommitted/unsupported raw recording remnants retained".into());
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn mcap_file_cannot_exceed_reserved_ceiling() {
        let path = std::env::temp_dir().join(format!("actryn-bounded-file-{}", std::process::id()));
        let file = FileOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&path)
            .unwrap();
        let mut bounded = BoundedFile {
            file,
            maximum: 4,
            position: 0,
        };
        bounded.write_all(b"abcd").unwrap();
        assert!(bounded.write_all(b"e").is_err());
        assert!(bounded.seek(SeekFrom::Start(5)).is_err());
        assert!(bounded.seek(SeekFrom::Current(-5)).is_err());
        bounded.seek(SeekFrom::Start(0)).unwrap();
        bounded.write_all(b"z").unwrap();
        assert_eq!(bounded.file.metadata().unwrap().len(), 4);
        drop(bounded);
        fs::remove_file(path).unwrap();
    }
}
