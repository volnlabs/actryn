//! Test-only read-only adapter to the production checkpoint/MCAP reader.
use anyhow::{ensure, Context, Result};
use evidence::{EventKind, Origin, Recorder};
use serde_json::{json, Value};
use std::path::Path;

fn inspect(path: &Path) -> Result<Value> {
    let recovered = Recorder::recover(path)?;
    let faults = recovered
        .records
        .iter()
        .filter(|record| record.kind == EventKind::SourceGap)
        .collect::<Vec<_>>();
    ensure!(faults.len() <= 64, "test reader fault-report capacity");
    let mut decoded = Vec::new();
    for record in faults {
        let payload = record
            .payload
            .as_ref()
            .context("source fault metadata absent")?;
        ensure!(
            record.metadata && record.origin == Origin::Kernel && payload.len() <= 8192,
            "trusted bounded kernel fault metadata required"
        );
        let previous = recovered.records.iter().rev().find(|candidate| {
            candidate.producer == record.producer
                && candidate.sequence < record.sequence
                && candidate.kind == EventKind::Transition
                && candidate.metadata
        });
        decoded.push(json!({
            "producer": record.producer, "origin": format!("{:?}", record.origin),
            "record_ordinal": record.sequence, "source_time_ns": record.source_time_ns,
            "captured_ns": record.captured_ns, "metadata": record.metadata,
            "input_bytes": record.input_bytes,
            "payload_sha256": record.digest.iter().map(|b|format!("{b:02x}")).collect::<String>(),
            "metadata_value": serde_json::from_slice::<Value>(payload)?,
            "previous_kernel_record": previous.map(|r| -> Result<Value> { Ok(json!({
                "record_ordinal":r.sequence,
                "metadata_value":serde_json::from_slice::<Value>(r.payload.as_ref().context("previous metadata absent")?)?
            })) }).transpose()?
        }));
    }
    let through = recovered
        .records
        .iter()
        .map(|record| record.captured_ns)
        .max()
        .unwrap_or(0);
    let replay = recovered.execution_replay(through);
    let summaries = recovered.source_summary().iter().map(|source| json!({
        "producer":source.producer, "missing_record_ordinals":source.gaps,
        "source_gap_record_ordinals":source.source_gap_records,
        "first_record_ordinal":source.first_sequence, "last_record_ordinal":source.last_sequence,
        "durable_frontier":source.durable_frontier
    })).collect::<Vec<_>>();
    Ok(json!({
        "format":"actryn-a11-decoded-1", "reader":"production evidence::Recorder::recover",
        "attempt":recovered.manifest.attempt, "profile_digest":recovered.manifest.profile_digest,
        "configuration_digest":recovered.manifest.configuration_digest,
        "policy":format!("{:?}", recovered.manifest.policy),
        "records":recovered.records.len(), "source_faults":decoded, "sources":summaries,
        "frontiers":recovered.frontiers.iter().map(|f|json!({"read":f.read,"queued":f.queued,
            "durable":f.durable,"gap_count":f.gap_count})).collect::<Vec<_>>(),
        "issues":recovered.issues, "raw_remnants":recovered.raw_remnants,
        "volatile_tail_unknown":recovered.volatile_tail_unknown,
        "execution_replay_eligible":replay.eligible, "replay_missing":replay.missing
    }))
}

fn main() -> Result<()> {
    let arguments = std::env::args_os().collect::<Vec<_>>();
    ensure!(
        arguments.len() == 2,
        "usage: source_gap_reader EXPORTED_CAPTURE_DIRECTORY"
    );
    println!(
        "{}",
        serde_json::to_string_pretty(&inspect(Path::new(&arguments[1]))?)?
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use evidence::{CapturePolicy, CaptureSpec, Limits, ProducerSpec};

    #[test]
    fn production_reader_retains_typed_fault_and_denies_execution_replay() {
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
                    clock_domain: "test".into(),
                    clock_error_ns: 0,
                    requested: vec![EventKind::Transition, EventKind::SourceGap],
                    required_for_replay: false,
                }],
            },
            Limits::default(),
        )
        .unwrap();
        let producer = recorder.producer(0).unwrap();
        producer
            .read_metadata(1, 1, EventKind::Transition, b"{\"sequence\":10}")
            .unwrap();
        producer
            .read_metadata(
                2,
                2,
                EventKind::SourceGap,
                b"{\"fault\":{\"previous_sequence\":10,\"observed_sequence\":12}}",
            )
            .unwrap();
        recorder.queue_read();
        writer.flush().unwrap();
        drop(writer);
        let result = inspect(&path).unwrap();
        assert_eq!(result["frontiers"][0]["gap_count"], 1);
        assert_eq!(result["source_faults"][0]["record_ordinal"], 2);
        assert_eq!(
            result["source_faults"][0]["previous_kernel_record"]["metadata_value"]["sequence"],
            10
        );
        assert_eq!(
            result["source_faults"][0]["metadata_value"]["fault"]["observed_sequence"],
            12
        );
        assert_eq!(result["sources"][0]["missing_record_ordinals"], json!([]));
        assert_eq!(result["execution_replay_eligible"], false);
    }
}
