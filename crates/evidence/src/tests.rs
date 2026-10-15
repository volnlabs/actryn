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
