use super::*;
use std::{fs, path::PathBuf, sync::atomic::AtomicU64};
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "actryn-evidence-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        Self(path)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn spec(policy: CapturePolicy) -> CaptureSpec {
    CaptureSpec {
        attempt: [1; 16],
        profile_digest: [2; 32],
        configuration_digest: Sha256::digest(b"retained exact payload or explicit empty ledger")
            .into(),
        policy,
        retention: "local test only".into(),
        redaction: "none".into(),
        producers: vec![ProducerSpec {
            identity: [4; 16],
            session: 1,
            origin: Origin::Runtime,
            clock_domain: "robot-boottime".into(),
            clock_error_ns: 10,
            requested: vec![
                EventKind::Activation,
                EventKind::Configuration,
                EventKind::Input,
                EventKind::ModelOutput,
                EventKind::Execution,
                EventKind::Intervention,
                EventKind::Transition,
            ],
            required_for_replay: true,
        }],
    }
}

// A separate process exits without dropping its SQLite connection, reproducing
// a crash after dirty database pages reach disk but before transaction commit.
#[test]
#[ignore = "subprocess used only by hot-journal recovery tests"]
fn crash_with_hot_checkpoint_journal() {
    let root = std::env::var_os("ACTRYN_HOT_JOURNAL_TEST_ROOT").expect("test child only");
    let db = rusqlite::Connection::open(Path::new(&root).join("checkpoints.sqlite")).unwrap();
    db.execute_batch("PRAGMA synchronous=FULL; BEGIN IMMEDIATE; DELETE FROM checkpoints; DELETE FROM batches; UPDATE meta SET value=x'63726173686564' WHERE key='retention';").unwrap();
    // SAFETY: this live connection is used only by this thread; cacheflush does
    // not close or transfer ownership of its handle.
    assert_eq!(
        unsafe { rusqlite::ffi::sqlite3_db_cacheflush(db.handle()) },
        0
    );
    std::process::exit(71);
}

fn hot_capture() -> Temp {
    let dir = Temp::new();
    let (recorder, mut writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::FullPayload), Limits::default()).unwrap();
    recorder
        .producer(0)
        .unwrap()
        .read(1, 10, EventKind::Input, b"committed")
        .unwrap();
    recorder.queue_read();
    writer.flush().unwrap();
    drop(writer);
    drop(recorder);
    let mut child = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "tests::crash_with_hot_checkpoint_journal",
            "--ignored",
        ])
        .env("ACTRYN_HOT_JOURNAL_TEST_ROOT", &dir.0)
        .spawn()
        .unwrap();
    let until = Instant::now() + Duration::from_secs(5);
    let status = loop {
        if let Some(status) = child.try_wait().unwrap() {
            break status;
        }
        if Instant::now() >= until {
            child.kill().unwrap();
            child.wait().unwrap();
            panic!("SQLite crash helper timed out");
        }
        thread::sleep(Duration::from_millis(5));
    };
    assert_eq!(status.code(), Some(71));
    dir
}

fn capture_hashes(root: &Path) -> std::collections::BTreeMap<PathBuf, Vec<u8>> {
    fs::read_dir(root)
        .unwrap()
        .map(|entry| {
            let path = entry.unwrap().path();
            (
                path.file_name().unwrap().into(),
                Sha256::digest(fs::read(&path).unwrap()).to_vec(),
            )
        })
        .collect()
}

#[test]
fn hot_journal_recovers_committed_prefix_without_touching_originals() {
    let dir = hot_capture();
    let before = capture_hashes(&dir.0);
    let db = rusqlite::Connection::open_with_flags(
        dir.0.join("checkpoints.sqlite"),
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )
    .unwrap();
    let error = db
        .query_row("SELECT count(*) FROM meta", [], |r| r.get::<_, i64>(0))
        .unwrap_err();
    assert!(matches!(error, rusqlite::Error::SqliteFailure(e, _) if e.extended_code == 776));
    drop(db);
    let recovered = Recorder::recover(&dir.0).unwrap();
    assert_eq!(recovered.manifest.retention, "local test only");
    assert_eq!(recovered.frontiers[0].durable, 1);
    assert_eq!(
        recovered.records[0].payload.as_deref(),
        Some(b"committed".as_slice())
    );
    assert!(recovered
        .issues
        .iter()
        .any(|issue| issue.contains("private SQLite rollback")));
    assert!(recovered.volatile_tail_unknown);
    assert!(!recovered.execution_replay(u64::MAX).eligible);
    assert_eq!(capture_hashes(&dir.0), before);
}

#[test]
fn hot_journal_rejects_truncated_corrupt_and_unsupported_tails() {
    let dir = hot_capture();
    let path = dir.0.join("checkpoints.sqlite-journal");
    let journal = fs::read(&path).unwrap();
    let be = |range: std::ops::Range<usize>| {
        u32::from_be_bytes(journal[range].try_into().unwrap()) as usize
    };
    let sector = be(20..24);
    let end = sector + be(8..12) * (4096 + 8);
    let next = end.div_ceil(sector) * sector;
    assert_eq!(
        journal.len(),
        next + sector,
        "real empty next-header fixture"
    );
    let mut bad = Vec::new();
    for length in [1, 27, sector - 1, sector, end - 1, next, journal.len() - 1] {
        bad.push((format!("truncated-{length}"), journal[..length].to_vec()));
    }
    for (name, offset) in [
        ("magic", 1),
        ("checksum", sector + 4 + 4096),
        ("empty-header-magic", next),
        ("empty-header-count", next + 11),
        ("empty-header-padding", next + 28),
        ("alignment-padding", end),
    ] {
        let mut bytes = journal.clone();
        bytes[offset] ^= 1;
        bad.push((name.into(), bytes));
    }
    for (name, range, number) in [
        ("unsynced-count", 8..12, 0u32),
        ("unbounded-count", 8..12, u32::MAX),
        ("zero-pages", 16..20, 0),
        ("bad-sector", 20..24, 513),
        ("wrong-page-size", 24..28, 8192),
    ] {
        let mut bytes = journal.clone();
        bytes[range].copy_from_slice(&number.to_be_bytes());
        bad.push((name.into(), bytes));
    }
    let mut duplicate = journal.clone();
    duplicate[sector + 4104..sector + 4108].copy_from_slice(&journal[sector..sector + 4]);
    bad.push(("duplicate-page".into(), duplicate));
    let mut appended = journal.clone();
    appended.push(0);
    bad.push(("appended-tail".into(), appended));
    for (name, bytes) in bad {
        fs::write(&path, bytes).unwrap();
        let before = capture_hashes(&dir.0);
        assert!(Recorder::recover(&dir.0).is_err(), "accepted {name}");
        assert_eq!(capture_hashes(&dir.0), before, "changed {name}");
    }
    // The exact complete segment without an initialized next header is also
    // supported (the retained actual QEMU-crash capture has this layout).
    fs::write(&path, &journal[..end]).unwrap();
    assert_eq!(Recorder::recover(&dir.0).unwrap().frontiers[0].durable, 1);
}

#[test]
fn hot_journal_integrity_check_rejects_btree_corruption_beyond_sampled_checksum() {
    let dir = hot_capture();
    let path = dir.0.join("checkpoints.sqlite-journal");
    let mut journal = fs::read(&path).unwrap();
    let sector = u32::from_be_bytes(journal[20..24].try_into().unwrap()) as usize;
    let count = u32::from_be_bytes(journal[8..12].try_into().unwrap()) as usize;
    let btree = (0..count)
        .map(|n| sector + n * 4104)
        .find(|offset| {
            journal[*offset..*offset + 4] != [0, 0, 0, 1]
                && matches!(journal[*offset + 4], 2 | 5 | 10 | 13)
        })
        .unwrap();
    // Offset 0 is the non-page-one btree type and is outside SQLite's sampled
    // checksum (96, 296, ...). SQLite must reject it after scratch rollback.
    journal[btree + 4] = 0xff;
    fs::write(path, journal).unwrap();
    let before = capture_hashes(&dir.0);
    assert!(Recorder::recover(&dir.0).is_err());
    assert_eq!(capture_hashes(&dir.0), before);
}

#[test]
fn hot_journal_rejects_active_writer_wal_and_unsafe_input_files() {
    use std::os::unix::fs::symlink;
    let dir = hot_capture();
    let lock = fs::File::open(dir.0.join("capture.lock")).unwrap();
    lock.try_lock().unwrap();
    assert!(matches!(
        Recorder::recover(&dir.0),
        Err(Error::Rejected("capture writer active during rollback"))
    ));
    drop(lock);
    for name in ["checkpoints.sqlite-wal", "checkpoints.sqlite-shm"] {
        fs::write(dir.0.join(name), []).unwrap();
        assert!(Recorder::recover(&dir.0).is_err());
        fs::remove_file(dir.0.join(name)).unwrap();
    }
    for name in [
        "checkpoints.sqlite",
        "checkpoints.sqlite-journal",
        "capture.lock",
    ] {
        let path = dir.0.join(name);
        let saved = dir.0.join("saved-original");
        fs::rename(&path, &saved).unwrap();
        symlink(&saved, &path).unwrap();
        assert!(Recorder::recover(&dir.0).is_err(), "symlink {name}");
        fs::remove_file(&path).unwrap();
        // A nonblocking type guard must reject a FIFO before SQLite opens it.
        let cpath = std::ffi::CString::new(path.as_os_str().as_encoded_bytes()).unwrap();
        assert_eq!(unsafe { libc::mkfifo(cpath.as_ptr(), 0o600) }, 0);
        assert!(Recorder::recover(&dir.0).is_err(), "FIFO {name}");
        fs::remove_file(&path).unwrap();
        fs::hard_link(&saved, &path).unwrap();
        assert!(Recorder::recover(&dir.0).is_err(), "hardlink {name}");
        fs::remove_file(&path).unwrap();
        fs::rename(saved, path).unwrap();
    }
    let link = dir.0.with_extension("symlink");
    symlink(&dir.0, &link).unwrap();
    assert!(Recorder::recover(&link).is_err());
    fs::remove_file(link).unwrap();
    // Exported immutable capture copies intentionally have no writer lock.
    fs::remove_file(dir.0.join("capture.lock")).unwrap();
    assert_eq!(Recorder::recover(&dir.0).unwrap().frontiers[0].durable, 1);
}

#[test]
fn hot_journal_input_caps_reject_sparse_oversized_files_without_copying() {
    for (name, maximum) in [
        ("checkpoints.sqlite", 128u64 << 20),
        ("checkpoints.sqlite-journal", 256u64 << 20),
    ] {
        let dir = hot_capture();
        let file = fs::OpenOptions::new()
            .write(true)
            .open(dir.0.join(name))
            .unwrap();
        file.set_len(maximum + 1).unwrap();
        assert!(matches!(
            Recorder::recover(&dir.0),
            Err(Error::Rejected("private rollback input type/link/size"))
        ));
        assert_eq!(file.metadata().unwrap().len(), maximum + 1);
    }
}

#[test]
fn invalid_database_is_not_repaired_by_hot_journal_fallback() {
    let dir = hot_capture();
    let path = dir.0.join("checkpoints.sqlite");
    for bytes in [
        b"not a database".as_slice(),
        b"SQLite format 3\0".as_slice(),
        b"".as_slice(),
    ] {
        fs::write(&path, bytes).unwrap();
        let before = capture_hashes(&dir.0);
        assert!(Recorder::recover(&dir.0).is_err());
        assert_eq!(capture_hashes(&dir.0), before);
    }
}

#[test]
fn normal_reader_rejects_wal_sidecars_before_sqlite_opens_them() {
    let dir = Temp::new();
    let (recorder, writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::MetadataOnly), Limits::default()).unwrap();
    drop(writer);
    drop(recorder);
    for name in ["checkpoints.sqlite-wal", "checkpoints.sqlite-shm"] {
        fs::write(dir.0.join(name), []).unwrap();
        let before = capture_hashes(&dir.0);
        assert!(matches!(
            Recorder::recover(&dir.0),
            Err(Error::Rejected("WAL/SHM not supported by private rollback"))
        ));
        assert_eq!(capture_hashes(&dir.0), before);
        fs::remove_file(dir.0.join(name)).unwrap();
    }
}
#[test]
fn stalled_writer_expires_despite_reader_heartbeat() {
    let dir = Temp::new();
    let limits = Limits {
        max_pending_age: Duration::from_millis(10),
        heartbeat: Duration::from_millis(1),
        ..Limits::default()
    };
    let (recorder, mut writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::MetadataOnly), limits).unwrap();
    let producer = recorder.producer(0).unwrap();
    producer.read(1, 0, EventKind::Input, b"x").unwrap();
    recorder.queue_read();
    let barrier = Arc::new(std::sync::Barrier::new(2));
    writer.store.block = Some(barrier.clone());
    let thread = thread::spawn(move || writer.flush());
    barrier.wait();
    std::thread::sleep(Duration::from_millis(15));
    producer.heartbeat();
    let health = recorder.health();
    assert!(health.revoke_required);
    assert!(health.issues.contains(&HealthIssue::PendingAge));
    assert_eq!(health.frontiers[0].durable, 0);
    assert!(health.reader_heartbeat_ns > 0);
    barrier.wait();
    assert_eq!(thread.join().unwrap().unwrap(), 1);
    assert!(recorder.health().revoke_required); // progress cannot clear a latched loss
}
#[test]
fn frontiers_are_distinct_and_real_mcap_is_checkpointed() {
    let dir = Temp::new();
    let (recorder, mut writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::FullPayload), Limits::default()).unwrap();
    let producer = recorder.producer(0).unwrap();
    producer.read(1, 10, EventKind::Input, b"payload").unwrap();
    assert_eq!(
        recorder.health().frontiers[0],
        Frontiers {
            read: 1,
            ..Frontiers::default()
        }
    );
    recorder.queue_read();
    assert_eq!(
        recorder.health().frontiers[0],
        Frontiers {
            read: 1,
            queued: 1,
            ..Frontiers::default()
        }
    );
    assert_eq!(writer.flush().unwrap(), 1);
    assert_eq!(
        recorder.health().frontiers[0],
        Frontiers {
            read: 1,
            queued: 1,
            durable: 1,
            gap_count: 0
        }
    );
    let capture = Recorder::recover(&dir.0).unwrap();
    assert_eq!(
        capture.records[0].payload.as_deref(),
        Some(b"payload".as_slice())
    );
    assert_eq!(capture.records[0].origin, Origin::Runtime);
    assert!(capture.raw_remnants.is_empty());
    assert!(!capture.execution_replay(recorder.now_ns()).eligible);
}
#[test]
fn sync_precedes_checkpoint_and_raw_remnants_are_preserved() {
    let dir = Temp::new();
    let (recorder, mut writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::FullPayload), Limits::default()).unwrap();
    let p = recorder.producer(0).unwrap();
    p.read(1, 0, EventKind::Input, b"first").unwrap();
    recorder.queue_read();
    writer.flush().unwrap();
    p.read(2, 1, EventKind::Input, b"uncommitted").unwrap();
    recorder.queue_read();
    writer.store.fail_after_sync = true;
    assert!(writer.flush().is_err());
    assert!(recorder
        .health()
        .issues
        .contains(&HealthIssue::StorageFailure));
    let capture = Recorder::recover(&dir.0).unwrap();
    assert_eq!(capture.frontiers[0].durable, 1);
    assert_eq!(capture.records.len(), 1);
    assert_eq!(capture.raw_remnants.len(), 1);
    let raw = fs::read(&capture.raw_remnants[0]).unwrap();
    assert_eq!(mcap::MessageStream::new(&raw).unwrap().count(), 1); // complete synced file, absent SQLite checkpoint
    assert!(capture.raw_remnants[0].exists());
}
#[test]
fn corrupt_checkpoint_excludes_the_remaining_prefix_without_deleting_files() {
    let dir = Temp::new();
    let (recorder, mut writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::FullPayload), Limits::default()).unwrap();
    let p = recorder.producer(0).unwrap();
    for seq in 1..=3 {
        p.read(seq, seq, EventKind::Input, b"x").unwrap();
        recorder.queue_read();
        writer.flush().unwrap();
    }
    let path = dir.0.join("batch-00000000000000000002.mcap");
    let original = fs::read(&path).unwrap();
    fs::write(&path, &original[..original.len() / 2]).unwrap();
    let recovery = Recorder::recover(&dir.0).unwrap();
    assert_eq!(recovery.records.len(), 1);
    assert_eq!(recovery.frontiers[0].durable, 1);
    assert_eq!(recovery.raw_remnants.len(), 2);
    assert_eq!(fs::read(path).unwrap().len(), original.len() / 2);
}
#[test]
fn capacity_reserves_urgent_transition_events_and_exposes_overflow() {
    let dir = Temp::new();
    let limits = Limits {
        volatile_records: 3,
        reserved_records: 1,
        ..Limits::default()
    };
    let (recorder, _writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::FullPayload), limits).unwrap();
    let p = recorder.producer(0).unwrap();
    p.read(1, 0, EventKind::Input, b"1").unwrap();
    p.read(2, 0, EventKind::Input, b"2").unwrap();
    assert!(recorder.health().revoke_required);
    assert!(p.read(3, 0, EventKind::Input, b"3").is_err());
    p.read(3, 0, EventKind::Transition, b"revoke locally closed")
        .unwrap();
    assert!(p.read(4, 0, EventKind::Transition, b"overflow").is_err());
    assert_eq!(recorder.health().overflow_count, 1);
    assert_eq!(recorder.health().pending_records, 3);
}
#[test]
fn byte_budget_is_enforced_and_agent_payload_cannot_forge_origin() {
    let dir = Temp::new();
    let mut manifest = spec(CapturePolicy::FullPayload);
    manifest.producers.push(ProducerSpec {
        identity: [5; 16],
        session: 1,
        origin: Origin::Agent,
        clock_domain: "agent claims".into(),
        clock_error_ns: 0,
        requested: vec![EventKind::AgentPayload],
        required_for_replay: false,
    });
    let limits = Limits {
        volatile_bytes: 1024,
        reserved_bytes: 256,
        ..Limits::default()
    };
    let (recorder, mut writer) = Recorder::create(&dir.0, manifest, limits).unwrap();
    let agent = recorder.producer(1).unwrap();
    assert!(agent.read(1, 0, EventKind::Activation, b"forged").is_err());
    assert!(agent.seal_prefix(1, 0).is_err());
    agent
        .read(
            1,
            0,
            EventKind::AgentPayload,
            br#"{"origin":"Kernel","kind":"Activation"}"#,
        )
        .unwrap();
    recorder.queue_read();
    writer.flush().unwrap();
    let capture = Recorder::recover(&dir.0).unwrap();
    assert_eq!(capture.records[0].origin, Origin::Agent);
    assert!(agent
        .read(2, 0, EventKind::AgentPayload, &vec![0; 1024])
        .is_err());
    assert!(recorder.health().revoke_required);
}
#[test]
fn source_gap_and_metadata_hashes_do_not_enable_execution_replay() {
    let dir = Temp::new();
    let (recorder, mut writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::MetadataOnly), Limits::default()).unwrap();
    let p = recorder.producer(0).unwrap();
    p.read(2, 0, EventKind::Activation, b"activation hash is not state")
        .unwrap();
    assert!(recorder.health().issues.contains(&HealthIssue::SourceGap));
    recorder.queue_read();
    writer.flush().unwrap();
    let capture = Recorder::recover(&dir.0).unwrap();
    assert_eq!(capture.frontiers[0].gap_count, 1);
    assert_eq!(capture.source_summary()[0].gaps, vec![(1, 1)]);
    assert!(capture.records[0].payload.is_none());
    let replay = capture.execution_replay(recorder.now_ns());
    assert!(!replay.eligible);
    assert!(replay.missing.iter().any(|m| m.contains("activation")));
}
#[test]
fn execution_replay_requires_retained_activation_inputs_and_sealed_complete_prefix() {
    let dir = Temp::new();
    let (recorder, mut writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::FullPayload), Limits::default()).unwrap();
    let p = recorder.producer(0).unwrap();
    for (index, kind) in [
        EventKind::Activation,
        EventKind::Configuration,
        EventKind::Input,
        EventKind::ModelOutput,
        EventKind::Execution,
        EventKind::Intervention,
        EventKind::Transition,
    ]
    .into_iter()
    .enumerate()
    {
        p.read(
            index as u64 + 1,
            0,
            kind,
            b"retained exact payload or explicit empty ledger",
        )
        .unwrap();
    }
    let through = recorder.now_ns();
    recorder.queue_read();
    writer.flush().unwrap();
    assert!(
        !Recorder::recover(&dir.0)
            .unwrap()
            .execution_replay(through)
            .eligible
    );
    p.seal_prefix(8, through).unwrap();
    recorder.queue_read();
    writer.flush().unwrap();
    let recovery = Recorder::recover(&dir.0).unwrap();
    let eligible = recovery.execution_replay(through);
    assert!(eligible.eligible, "{:?}", eligible.missing);
    assert!(!recovery.execution_replay(recorder.now_ns() + 1).eligible);
}

#[test]
fn disk_and_batch_reservations_fail_before_creating_unfunded_files() {
    let dir = Temp::new();
    let limits = Limits {
        disk_bytes: 1_048_576,
        batch_bytes: 65_536,
        ..Limits::default()
    };
    let (recorder, mut writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::FullPayload), limits.clone()).unwrap();
    let p = recorder.producer(0).unwrap();
    let payload = vec![42; 60_000];
    let mut committed = 0u64;
    for sequence in 1..=20 {
        p.read(sequence, 0, EventKind::Input, &payload).unwrap();
        recorder.queue_read();
        match writer.flush() {
            Ok(1) => committed += 1,
            Err(Error::DiskBudget) => break,
            other => panic!("{other:?}"),
        }
    }
    assert!(committed > 0 && committed < 20);
    assert!(recorder
        .health()
        .issues
        .contains(&HealthIssue::DiskCapacity));
    let recovery = Recorder::recover(&dir.0).unwrap();
    assert_eq!(recovery.records.len() as u64, committed);
    assert!(recovery.raw_remnants.is_empty());
    let bytes = fs::read_dir(&dir.0)
        .unwrap()
        .map(|entry| entry.unwrap().metadata().unwrap().len())
        .sum::<u64>();
    assert!(bytes <= limits.disk_bytes);
    let dir = Temp::new();
    let (recorder, mut writer) = Recorder::create(
        &dir.0,
        spec(CapturePolicy::FullPayload),
        Limits {
            batch_bytes: 16_384,
            ..Limits::default()
        },
    )
    .unwrap();
    recorder
        .producer(0)
        .unwrap()
        .read(1, 0, EventKind::Input, &vec![0; 20_000])
        .unwrap();
    recorder.queue_read();
    assert!(matches!(writer.flush(), Err(Error::DiskBudget)));
    assert!(!dir.0.join("batch-00000000000000000001.mcap").exists());
}

#[test]
fn trusted_metadata_is_retained_but_does_not_enable_execution_replay() {
    let dir = Temp::new();
    let (recorder, mut writer) =
        Recorder::create(&dir.0, spec(CapturePolicy::MetadataOnly), Limits::default()).unwrap();
    let producer = recorder.producer(0).unwrap();
    producer
        .read_metadata(1, 0, EventKind::Activation, b"trusted activation metadata")
        .unwrap();
    producer
        .read(2, 0, EventKind::Execution, b"raw execution payload")
        .unwrap();
    assert!(producer
        .read_metadata(3, 0, EventKind::ModelOutput, b"not metadata")
        .is_err());
    assert!(producer
        .read_metadata(3, 0, EventKind::Input, b"not metadata")
        .is_err());
    recorder.queue_read();
    writer.flush().unwrap();
    let recovery = Recorder::recover(&dir.0).unwrap();
    assert_eq!(
        recovery.records[0].payload.as_deref(),
        Some(b"trusted activation metadata".as_slice())
    );
    assert!(recovery.records[0].metadata);
    assert!(!recovery.records[1].metadata);
    assert!(recovery.records[1].payload.is_none());
    assert!(!recovery.execution_replay(0).eligible);
    let summary = recovery.source_summary();
    assert!(summary[0].metadata_streams.contains(&EventKind::Activation));
    assert!(!summary[0].payload_streams.contains(&EventKind::Activation));
}

#[test]
fn agent_capability_cannot_claim_metadata() {
    let dir = Temp::new();
    let mut capture = spec(CapturePolicy::MetadataOnly);
    capture.producers[0].origin = Origin::Agent;
    capture.producers[0].required_for_replay = false;
    capture.producers[0].requested = vec![EventKind::AgentPayload];
    let (recorder, _writer) = Recorder::create(&dir.0, capture, Limits::default()).unwrap();
    assert!(recorder
        .producer(0)
        .unwrap()
        .read_metadata(1, 0, EventKind::AgentPayload, b"forged")
        .is_err());
}

#[test]
fn external_source_fault_is_durable_without_fabricating_an_ordinal_gap() {
    let dir = Temp::new();
    let fault = EventKind::from_byte(11).expect("trusted source-fault event kind");
    let mut manifest = spec(CapturePolicy::MetadataOnly);
    manifest.producers[0].required_for_replay = false;
    manifest.producers[0].requested.push(fault);
    let (recorder, mut writer) = Recorder::create(&dir.0, manifest, Limits::default()).unwrap();
    let producer = recorder.producer(0).unwrap();
    producer
        .read_metadata(1, 5, EventKind::Transition, b"source sequence 500")
        .unwrap();
    producer
        .read_metadata(
            2,
            7,
            fault,
            b"source sequence 502; expected 501; lost 9 -> 10",
        )
        .unwrap();
    let health = recorder.health();
    assert!(health.revoke_required);
    assert!(health.issues.contains(&HealthIssue::SourceGap));
    assert_eq!(health.frontiers[0].gap_count, 1);
    assert_eq!(health.frontiers[0].read, 2);
    assert_eq!(health.frontiers[0].durable, 0);
    recorder.queue_read();
    writer.flush().unwrap();
    let recovered = Recorder::recover(&dir.0).unwrap();
    assert_eq!(recovered.frontiers[0].gap_count, 1);
    assert_eq!(recovered.frontiers[0].durable, 2);
    assert_eq!(
        recovered.records[1].payload.as_deref(),
        Some(b"source sequence 502; expected 501; lost 9 -> 10".as_slice())
    );
    assert!(recovered.source_summary()[0].gaps.is_empty());
    assert_eq!(recovered.source_summary()[0].source_gap_records, vec![2]);
    assert!(!recovered.execution_replay(0).eligible);
    assert!(recovered
        .execution_replay(0)
        .missing
        .iter()
        .any(|reason| reason.contains("source fault")));
}

#[test]
fn source_fault_uses_reserve_and_latches_even_when_reserve_is_exhausted() {
    let fault = EventKind::from_byte(11).expect("trusted source-fault event kind");
    for exhaust in [false, true] {
        let dir = Temp::new();
        let mut manifest = spec(CapturePolicy::MetadataOnly);
        manifest.producers[0].requested.push(fault);
        let limits = Limits {
            volatile_records: 2,
            reserved_records: 1,
            ..Limits::default()
        };
        let (recorder, mut writer) = Recorder::create(&dir.0, manifest, limits).unwrap();
        let producer = recorder.producer(0).unwrap();
        producer
            .read(1, 0, EventKind::Input, b"fill ordinary capacity")
            .unwrap();
        if exhaust {
            producer
                .read_metadata(2, 1, EventKind::Transition, b"fill reserve")
                .unwrap();
        }
        let result =
            producer.read_metadata(if exhaust { 3 } else { 2 }, 2, fault, b"actual source loss");
        assert_eq!(result.is_err(), exhaust);
        let health = recorder.health();
        assert!(health.revoke_required && health.issues.contains(&HealthIssue::SourceGap));
        assert_eq!(health.frontiers[0].gap_count, 1);
        if exhaust {
            assert!(producer
                .read_metadata(3, 2, fault, b"actual source loss")
                .is_err());
            assert_eq!(recorder.health().frontiers[0].gap_count, 1);
        }
        recorder.queue_read();
        writer.flush().unwrap();
        let recovered = Recorder::recover(&dir.0).unwrap();
        assert_eq!(recovered.frontiers[0].gap_count, u64::from(!exhaust));
        assert!(recovered.volatile_tail_unknown);
    }
}

#[test]
fn untrusted_or_unretained_source_faults_cannot_claim_durable_fault_metadata() {
    let fault = EventKind::from_byte(11).expect("trusted source-fault event kind");
    let dir = Temp::new();
    let mut manifest = spec(CapturePolicy::MetadataOnly);
    manifest.producers[0].requested.push(fault);
    let (recorder, _writer) = Recorder::create(&dir.0, manifest, Limits::default()).unwrap();
    assert!(recorder
        .producer(0)
        .unwrap()
        .read(1, 0, fault, b"hash only")
        .is_err());
    assert_eq!(recorder.health().frontiers[0].gap_count, 0);
    let dir = Temp::new();
    let mut manifest = spec(CapturePolicy::MetadataOnly);
    manifest.producers[0].origin = Origin::Agent;
    manifest.producers[0].required_for_replay = false;
    manifest.producers[0].requested = vec![EventKind::AgentPayload];
    let (recorder, _writer) = Recorder::create(&dir.0, manifest, Limits::default()).unwrap();
    assert!(recorder
        .producer(0)
        .unwrap()
        .read_metadata(1, 0, fault, b"forged")
        .is_err());
    assert_eq!(recorder.health().frontiers[0].gap_count, 0);
}
