//! Bounded test-only adapter to the production checkpoint/MCAP reader.
use anyhow::{ensure, Context, Result};
use evidence::{EventKind, Origin, Recorder};
use serde_json::{json, Value};
use std::{io::Write, path::Path};

fn inspect(path: &Path) -> Result<Value> {
    let recovered = Recorder::recover(path)?;
    ensure!(recovered.records.len() <= 4096, "campaign record capacity");
    let mut records = Vec::new();
    for record in &recovered.records {
        if !matches!(
            record.kind,
            EventKind::Transition | EventKind::Execution | EventKind::SourceGap
        ) {
            continue;
        }
        ensure!(
            record.metadata && matches!(record.origin, Origin::Kernel | Origin::Runtime),
            "expected trusted structured metadata"
        );
        let payload = record.payload.as_ref().context("metadata absent")?;
        ensure!(payload.len() <= 8192, "metadata bound");
        records.push(
            json!({"producer":record.producer,"record_ordinal":record.sequence,
            "source_time_ns":record.source_time_ns,"captured_ns":record.captured_ns,
            "origin":format!("{:?}",record.origin),"kind":format!("{:?}",record.kind),
            "value":serde_json::from_slice::<Value>(payload)?}),
        );
    }
    let through = recovered
        .records
        .iter()
        .map(|r| r.captured_ns)
        .max()
        .unwrap_or(0);
    let replay = recovered.execution_replay(through);
    let report = json!({"format":"actryn-failure-capture-1",
        "reader":"production evidence::Recorder::recover",
        "attempt":recovered.manifest.attempt,"configuration_digest":recovered.manifest.configuration_digest,
        "policy":format!("{:?}",recovered.manifest.policy),"records":records,
        "record_count":recovered.records.len(),"issues":recovered.issues,"raw_remnants":recovered.raw_remnants,
        "frontiers":recovered.frontiers.iter().map(|f|json!({"read":f.read,"queued":f.queued,
            "durable":f.durable,"gap_count":f.gap_count})).collect::<Vec<_>>(),
        "sources":recovered.source_summary().iter().map(|s|json!({"producer":s.producer,
            "missing_record_ordinals":s.gaps,"source_gap_record_ordinals":s.source_gap_records,
            "first_record_ordinal":s.first_sequence,"last_record_ordinal":s.last_sequence,
            "durable_frontier":s.durable_frontier})).collect::<Vec<_>>(),
        "volatile_tail_unknown":recovered.volatile_tail_unknown,
        "execution_replay_eligible":replay.eligible,"replay_missing":replay.missing});
    ensure!(
        serde_json::to_vec(&report)?.len() <= 4 * 1024 * 1024,
        "campaign report capacity"
    );
    Ok(report)
}

#[test]
#[ignore = "requires explicitly supplied retired actual-guest capture; never starts a guest"]
fn decode_retired_campaign_capture() -> Result<()> {
    let input = std::env::var_os("ACTRYN_TEST_CAPTURE").context("ACTRYN_TEST_CAPTURE required")?;
    let output = std::env::var_os("ACTRYN_TEST_CAPTURE_REPORT")
        .context("ACTRYN_TEST_CAPTURE_REPORT required")?;
    let report = inspect(Path::new(&input))?;
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output)?;
    file.write_all(&serde_json::to_vec_pretty(&report)?)?;
    Ok(())
}

#[test]
fn production_reader_keeps_external_sequence_separate_from_record_ordinal() {
    use evidence::{CapturePolicy, CaptureSpec, Limits, ProducerSpec};
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("capture");
    let (recorder, mut writer) = Recorder::create(
        &path,
        CaptureSpec {
            attempt: [1; 16],
            profile_digest: [2; 32],
            configuration_digest: [3; 32],
            policy: CapturePolicy::MetadataOnly,
            retention: "test".into(),
            redaction: "metadata".into(),
            producers: vec![ProducerSpec {
                identity: [4; 16],
                session: 1,
                origin: Origin::Kernel,
                clock_domain: "CLOCK_BOOTTIME".into(),
                clock_error_ns: 0,
                requested: vec![EventKind::Transition],
                required_for_replay: false,
            }],
        },
        Limits::default(),
    )
    .unwrap();
    recorder
        .producer(0)
        .unwrap()
        .read_metadata(
            1,
            10,
            EventKind::Transition,
            br#"{"sequence":47,"kind":65550,"status":{"operation":9}}"#,
        )
        .unwrap();
    recorder.queue_read();
    writer.flush().unwrap();
    drop(writer);
    let report = inspect(&path).unwrap();
    assert_eq!(report["records"][0]["record_ordinal"], 1);
    assert_eq!(report["records"][0]["value"]["sequence"], 47);
    assert_eq!(report["records"][0]["value"]["status"]["operation"], 9);
    assert_eq!(report["frontiers"][0]["durable"], 1);
    assert_eq!(report["execution_replay_eligible"], false);
}
