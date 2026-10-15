use actryn_server::{
    evidence::{self, ArtifactName, Bundle},
    Limits, Store,
};
use sha2::{Digest, Sha256};

#[test]
fn fixed_log_export_hashes_full_retained_bytes_and_bounds_binary_tail() {
    let dir = tempfile::tempdir().unwrap();
    let data = vec![0u8; evidence::LOG_CAP];
    std::fs::write(dir.path().join("stdout.log"), &data).unwrap();
    std::fs::write(dir.path().join("stdout.truncated"), b"truncated").unwrap();
    let log = evidence::log_evidence(dir.path(), false, true).unwrap();
    assert_eq!(log.retained_bytes, evidence::LOG_CAP);
    assert_eq!(
        log.retained_sha256,
        format!("sha256:{:x}", Sha256::digest(&data))
    );
    assert_eq!(log.tail.len(), 2 * evidence::LOG_TAIL_BYTES);
    assert!(log.source_truncated && log.file_complete);
    assert_eq!(
        log.tail_omitted_bytes,
        evidence::LOG_CAP - evidence::LOG_TAIL_BYTES
    );
    std::os::unix::fs::symlink("stdout.log", dir.path().join("stderr.log")).unwrap();
    assert!(evidence::log_evidence(dir.path(), true, true).is_err());
}

#[test]
fn export_reports_omitted_denials_and_counts_actual_encoded_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let mut store = Store::open(dir.path().join("state.db"), Limits::default()).unwrap();
    let a = store
        .prepare(&format!("sha256:{}", "a".repeat(64)), 0)
        .unwrap();
    for n in 0..64 {
        store
            .record_denial(&a.id, &format!("key-{n}"), &"\0".repeat(128))
            .unwrap();
    }
    let mut bundle = Bundle::new(&a.id).unwrap();
    bundle.add_broker(store.inspect(&a.id).unwrap()).unwrap();
    assert!(!bundle.omissions.is_empty());
    assert!(serde_json::to_vec(&bundle).unwrap().len() <= evidence::MAX_BUNDLE_BYTES);
    for artifact in &bundle.artifacts {
        let encoded = serde_json::to_vec(&artifact.content).unwrap();
        assert_eq!(artifact.bytes, encoded.len());
        assert_eq!(
            artifact.sha256,
            format!("sha256:{:x}", Sha256::digest(&encoded))
        );
    }
    assert!(bundle
        .add(
            ArtifactName::Stdout,
            serde_json::json!("x".repeat(16 * 1024))
        )
        .is_err());
    assert!(!bundle.execution_replay_eligible);
    for name in [
        ArtifactName::RuntimeBinding,
        ArtifactName::RuntimeFacts,
        ArtifactName::Stdout,
        ArtifactName::Stderr,
    ] {
        let _ = bundle.add(name, serde_json::json!("x".repeat(16 * 1024 - 2)));
    }
    bundle.validate_bound().unwrap();
}

#[test]
fn resource_facts_survive_restart_before_runtime_deletion() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("memory.events"),
        "low 0\noom 2\noom_kill 1\n",
    )
    .unwrap();
    std::fs::write(dir.path().join("cpu.stat"), "usage_usec 123\n").unwrap();
    let facts = evidence::capture_resources(dir.path(), 1234);
    assert!(facts.counters["memory.events"].contains("oom_kill 1"));
    assert!(facts.unavailable.contains(&"io.stat".to_owned()));
    let path = dir.path().join("state.db");
    let mut store = Store::open(&path, Limits::default()).unwrap();
    let a = store
        .prepare(&format!("sha256:{}", "a".repeat(64)), 0)
        .unwrap();
    let encoded = serde_json::to_string(&facts).unwrap();
    store.record_runtime_evidence(&a.id, &encoded).unwrap();
    drop(store);
    let mut store = Store::open(path, Limits::default()).unwrap();
    store.recover().unwrap();
    assert_eq!(store.runtime_evidence(&a.id).unwrap(), Some(encoded));
}

#[test]
fn maximum_valid_call_keys_fit_diagnostic_export() {
    let dir = tempfile::tempdir().unwrap();
    let mut store = Store::open(dir.path().join("state.db"), Limits::default()).unwrap();
    let attempt = store
        .prepare(&format!("sha256:{}", "a".repeat(64)), 0)
        .unwrap();
    assert!(store.cancel_call(&attempt.id, &"\0".repeat(128)).is_err());
    for n in 0..16 {
        store
            .cancel_call(&attempt.id, &format!("{n:02}{}", "a".repeat(126)))
            .unwrap();
    }
    let mut bundle = Bundle::new(&attempt.id).unwrap();
    bundle
        .add_broker(store.inspect(&attempt.id).unwrap())
        .unwrap();
    let broker = &bundle.artifacts[0].content;
    assert_eq!(broker["calls"].as_array().unwrap().len(), 16);
    bundle.validate_bound().unwrap();
}
