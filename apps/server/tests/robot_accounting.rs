use actryn_server::{
    robot::{Binding, Observation, RemoteSnapshot, Verdict},
    Limits, Publication, Store,
};
use serde_json::json;

fn prepared(s: &mut Store) -> String {
    let a = s
        .prepare(&format!("sha256:{}", "a".repeat(64)), 100)
        .unwrap();
    s.mark_prepared(&a.id, "launcher binding").unwrap();
    a.id
}
fn binding(attempt: &str) -> Binding {
    Binding {
        attempt_id: attempt.into(),
        namespace: attempt.into(),
        principal: "server".into(),
        peer_digest: format!("sha256:{}", "c".repeat(64)),
        client_certificate_sha256: "d".repeat(64),
        robot_epoch: "e".repeat(32),
        robot_configuration_digest: "f".repeat(64),
        robot_profile_digest: "a".repeat(64),
        created_ms: 100,
        deadline_ms: 60_000,
    }
}
fn observation() -> Observation {
    Observation {
        id: 1,
        acquired_earliest_ns: 1,
        acquired_latest_ns: 2,
        valid_until_ns: 1_000_000_001,
        controller_ns: 1,
        left_ticks: 0,
        right_ticks: 0,
        simulated: true,
        context_revision: 1,
        received_ms: 101,
    }
}
fn snapshot(intent: &actryn_server::robot::Intent, unknown: bool) -> RemoteSnapshot {
    serde_json::from_value(json!({"namespace":actryn_server::robot::unhex::<16>(&intent.handle.namespace).unwrap(),
        "key":actryn_server::robot::unhex::<32>(&intent.handle.key).unwrap(), "digest":null,
        "operation":{"device":vec![1;16],"boot":1,"session":1,"runtime_nonce":vec![2;16],"grant":1,"instance":1,"operation":1,"stream":1},
        "revision":1,"durable_revision":1,"phase":"Completed","terminal":true,"closure":"NotRequested",
        "cancellation_durable":false,"persistence_failed":false,"verdict":if unknown {"OutcomeUnknown"} else {"TargetReached"},"reconciled":true})).unwrap()
}
#[test]
fn binding_is_prepared_only_and_cannot_be_rebound() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("db"), Limits::default()).unwrap();
    let a = prepared(&mut s);
    let b = binding(&a);
    s.robot_bind(&b, 100).unwrap();
    assert!(s.robot_bind(&b, 100).is_err());
    s.start(&a, 100).unwrap();
    assert_eq!(s.robot_binding(&a).unwrap().unwrap(), b);
    assert!(s.robot_bind(&b, 101).is_err());
    s.cancel(&a).unwrap();
    s.mark_reaped(&a).unwrap();
    let next = prepared(&mut s);
    let mut reused = binding(&next);
    reused.namespace = b.namespace;
    assert!(s.robot_bind(&reused, 102).is_err());
}
#[test]
fn cancellation_before_dispatch_and_restart_preserve_the_original_handle() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("db");
    let mut s = Store::open(&path, Limits::default()).unwrap();
    let a = prepared(&mut s);
    s.robot_bind(&binding(&a), 100).unwrap();
    s.start(&a, 100).unwrap();
    let intent = s.robot_reserve(&a, "key", "input-digest", 101).unwrap();
    s.robot_cancel_key(&a, "key").unwrap();
    assert!(s.robot_observe(&a, "key", &observation(), 102).is_err());
    s.cancel(&a).unwrap();
    s.mark_reaped(&a).unwrap();
    drop(s);
    let mut s = Store::open(&path, Limits::default()).unwrap();
    s.recover().unwrap();
    let saved = s.robot_intent(&a, "key").unwrap();
    assert_eq!(saved.handle, intent.handle);
    assert!(saved.outstanding_debit && saved.cancellation_requested);
    assert!(s.robot_reserve(&a, "key", "input-digest", 103).is_err());
}
#[test]
fn unknown_work_stays_charged_and_only_matching_reconciled_result_settles() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("db"), Limits::default()).unwrap();
    let a = prepared(&mut s);
    s.robot_bind(&binding(&a), 100).unwrap();
    s.start(&a, 100).unwrap();
    let intent = s.robot_reserve(&a, "first", "input-digest", 101).unwrap();
    s.robot_observe(&a, "first", &observation(), 102).unwrap();
    s.robot_dispatch(&a, "first", &format!("sha256:{}", "0".repeat(64)), 103)
        .unwrap();
    assert!(s.robot_reserve(&a, "second", "input-2", 104).is_err());
    let mut unknown_work = snapshot(&intent, true);
    unknown_work.phase = "OutcomeUnknown".into();
    s.robot_snapshot(&a, "first", &unknown_work).unwrap();
    assert!(s.robot_intent(&a, "first").unwrap().outstanding_debit);
    let mut wrong = snapshot(&intent, false);
    wrong.key = [0; 32];
    assert!(s.robot_snapshot(&a, "first", &wrong).is_err());
    let mut pending = snapshot(&intent, false);
    pending.reconciled = false;
    s.robot_snapshot(&a, "first", &pending).unwrap();
    assert!(s.robot_intent(&a, "first").unwrap().outstanding_debit);
    let mut terminal = snapshot(&intent, false);
    terminal.revision = 2;
    s.robot_snapshot(&a, "first", &terminal).unwrap();
    assert!(s.robot_intent(&a, "first").unwrap().outstanding_debit);
    assert!(s.robot_reserve(&a, "second", "input-2", 105).is_err());
    terminal.durable_revision = 2;
    s.robot_snapshot(&a, "first", &terminal).unwrap();
    assert!(!s.robot_intent(&a, "first").unwrap().outstanding_debit);
    assert!(s.robot_reserve(&a, "second", "input-2", 105).is_ok());
}
#[test]
fn unknown_task_requires_durable_completed_reconciliation_and_exact_identity() {
    for fault in [
        "none",
        "unknown_work",
        "unreconciled",
        "partial",
        "persistence",
        "cancelled",
        "absent",
        "key",
        "namespace",
        "operation",
        "zero_revision",
    ] {
        let dir = tempfile::tempdir().unwrap();
        let mut store = Store::open(dir.path().join("db"), Limits::default()).unwrap();
        let a = prepared(&mut store);
        store.robot_bind(&binding(&a), 100).unwrap();
        store.start(&a, 100).unwrap();
        let intent = store.robot_reserve(&a, "first", "digest", 101).unwrap();
        let mut accepted = snapshot(&intent, true);
        accepted.reconciled = false;
        store.robot_snapshot(&a, "first", &accepted).unwrap();
        let mut completed = snapshot(&intent, true);
        match fault {
            "none" => (),
            "unknown_work" => completed.phase = "OutcomeUnknown".into(),
            "unreconciled" => completed.reconciled = false,
            "partial" => completed.revision = 2,
            "persistence" => completed.persistence_failed = true,
            "cancelled" => completed.phase = "CancelledDurable".into(),
            "absent" => completed.operation = None,
            "key" => completed.key = [7; 32],
            "namespace" => completed.namespace = [7; 16],
            "operation" => completed.operation.as_mut().unwrap().stream += 1,
            "zero_revision" => {
                completed.revision = 0;
                completed.durable_revision = 0;
            }
            _ => unreachable!(),
        }
        let result = store.robot_snapshot(&a, "first", &completed);
        if matches!(
            fault,
            "absent" | "key" | "namespace" | "operation" | "zero_revision"
        ) {
            assert!(result.is_err(), "{fault}");
        } else {
            result.unwrap();
        }
        let saved = store.robot_intent(&a, "first").unwrap();
        assert_eq!(saved.outstanding_debit, fault != "none", "{fault}");
        assert_eq!(
            saved.summary().remote_verdict,
            Some(Verdict::OutcomeUnknown)
        );
        assert_eq!(
            store.robot_reserve(&a, "second", "digest2", 102).is_ok(),
            fault == "none",
            "{fault}"
        );
    }
}

#[test]
fn late_unknown_task_completion_settles_once_after_restart_without_publication() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("db");
    let mut store = Store::open(&path, Limits::default()).unwrap();
    let a = prepared(&mut store);
    store.robot_bind(&binding(&a), 100).unwrap();
    store.start(&a, 100).unwrap();
    let intent = store.robot_reserve(&a, "first", "digest", 101).unwrap();
    store
        .robot_observe(&a, "first", &observation(), 102)
        .unwrap();
    let proposal = format!("sha256:{}", "0".repeat(64));
    store.robot_dispatch(&a, "first", &proposal, 103).unwrap();
    let call = store.reserve_call(&a, "first", "digest", 1, 101).unwrap();
    store.mark_dispatched(&call.id, 102).unwrap();
    let mut pending = snapshot(&intent, true);
    pending.reconciled = false;
    store.robot_snapshot(&a, "first", &pending).unwrap();
    store.cancel(&a).unwrap();
    store.mark_reaped(&a).unwrap();
    drop(store);
    let mut store = Store::open(&path, Limits::default()).unwrap();
    store.recover().unwrap();
    assert!(store.robot_intent(&a, "first").unwrap().outstanding_debit);
    let completed = snapshot(&intent, true);
    let saved = store.robot_snapshot(&a, "first", &completed).unwrap();
    assert!(!saved.outstanding_debit && saved.cancellation_requested);
    assert_eq!(
        saved.summary().remote_verdict,
        Some(Verdict::OutcomeUnknown)
    );
    assert_eq!(
        store.settle(&call.id, 0, b"late reply", 104).unwrap(),
        Publication::Suppressed
    );
    assert!(store.robot_dispatch(&a, "first", &proposal, 104).is_err());
    assert_eq!(store.result(&a, "first", 104).unwrap().1, None);
    assert_eq!(store.inspect(&a).unwrap().attempt.outcome, "cancelled");
    let next = prepared(&mut store);
    store.robot_bind(&binding(&next), 100).unwrap();
    store.start(&next, 100).unwrap();
    let next_intent = store.robot_reserve(&next, "next", "digest2", 105).unwrap();
    for reply in [completed.clone(), pending, completed] {
        let again = store.robot_snapshot(&a, "first", &reply).unwrap();
        assert!(!again.outstanding_debit && again.last_remote.unwrap().reconciled);
        let outstanding = store.robot_pending().unwrap();
        assert_eq!(outstanding.len(), 1);
        assert_eq!(outstanding[0].1.handle, next_intent.handle);
        assert!(store
            .robot_reserve(&next, "overflow", "digest3", 106)
            .is_err());
        assert_eq!(store.result(&a, "first", 106).unwrap().1, None);
    }
}

#[test]
fn absent_unknown_task_cancellation_remains_charged() {
    let dir = tempfile::tempdir().unwrap();
    let mut store = Store::open(dir.path().join("db"), Limits::default()).unwrap();
    let a = prepared(&mut store);
    store.robot_bind(&binding(&a), 100).unwrap();
    store.start(&a, 100).unwrap();
    let intent = store.robot_reserve(&a, "key", "digest", 101).unwrap();
    let mut absent = snapshot(&intent, true);
    absent.operation = None;
    absent.phase = "CancelledDurable".into();
    absent.closure = "NotAllocated".into();
    absent.cancellation_durable = true;
    store.robot_snapshot(&a, "key", &absent).unwrap();
    assert!(store.robot_intent(&a, "key").unwrap().outstanding_debit);
}

#[test]
fn original_observation_cannot_be_replaced_and_dispatch_cannot_repeat() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("db"), Limits::default()).unwrap();
    let a = prepared(&mut s);
    s.robot_bind(&binding(&a), 100).unwrap();
    s.start(&a, 100).unwrap();
    s.robot_reserve(&a, "key", "digest", 101).unwrap();
    s.robot_observe(&a, "key", &observation(), 102).unwrap();
    let mut changed = observation();
    changed.id = 2;
    assert!(s.robot_observe(&a, "key", &changed, 103).is_err());
    let digest = format!("sha256:{}", "0".repeat(64));
    s.robot_dispatch(&a, "key", &digest, 103).unwrap();
    assert!(s.robot_dispatch(&a, "key", &digest, 104).is_err());
    assert_eq!(
        s.robot_intent(&a, "key").unwrap().observation.unwrap().id,
        1
    );
}

#[test]
fn four_old_unknown_robot_debits_exhaust_global_capacity_after_restart() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("db");
    let mut s = Store::open(&path, Limits::default()).unwrap();
    for _ in 0..4 {
        let a = prepared(&mut s);
        s.robot_bind(&binding(&a), 100).unwrap();
        s.start(&a, 100).unwrap();
        s.robot_reserve(&a, "key", "digest", 101).unwrap();
        s.cancel(&a).unwrap();
        s.mark_reaped(&a).unwrap();
    }
    drop(s);
    let mut s = Store::open(&path, Limits::default()).unwrap();
    s.recover().unwrap();
    assert_eq!(s.robot_pending().unwrap().len(), 4);
    let a = prepared(&mut s);
    s.robot_bind(&binding(&a), 100).unwrap();
    s.start(&a, 100).unwrap();
    assert!(s.robot_reserve(&a, "key", "digest", 101).is_err());
}

#[test]
fn durable_absent_key_cancellation_settles_but_retained_keys_cannot_replay() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("db"), Limits::default()).unwrap();
    let a = prepared(&mut s);
    s.robot_bind(&binding(&a), 100).unwrap();
    s.start(&a, 100).unwrap();
    for n in 0..16 {
        let key = format!("key-{n}");
        let intent = s.robot_reserve(&a, &key, "digest", 101).unwrap();
        let mut closed = snapshot(&intent, false);
        closed.operation = None;
        closed.reconciled = false;
        closed.phase = "CancelledDurable".into();
        closed.closure = "NotAllocated".into();
        // Current live no-operation query uses Pending even after the tombstone is durable.
        closed.verdict = actryn_server::robot::Verdict::Pending;
        closed.cancellation_durable = true;
        s.robot_cancel_key(&a, &key).unwrap();
        s.robot_snapshot(&a, &key, &closed).unwrap();
        assert!(!s.robot_intent(&a, &key).unwrap().outstanding_debit);
    }
    assert!(s.robot_reserve(&a, "key-15", "digest", 102).is_err());
    assert!(s.robot_reserve(&a, "overflow", "digest", 102).is_err());
    for n in 0..64 {
        s.record_denial(&a, &format!("{n:02}{}", "x".repeat(126)), &"\0".repeat(128))
            .unwrap();
    }
    let inspection = s.inspect(&a).unwrap();
    assert!(serde_json::to_vec(&inspection).unwrap().len() < 65_000);
    assert!(inspection.denials_omitted > 0);
    assert_eq!(inspection.denials.len() + inspection.denials_omitted, 64);
    let mut export = actryn_server::evidence::Bundle::new(&a).unwrap();
    export.add_broker(inspection).unwrap();
    export.validate_bound().unwrap();
    assert!(export
        .omissions
        .iter()
        .any(|o| o.artifact == actryn_server::evidence::ArtifactName::Robot));
}

#[test]
fn malformed_terminal_and_cancellation_reports_cannot_release_remote_debits() {
    let dir = tempfile::tempdir().unwrap();
    let mut store = Store::open(dir.path().join("db"), Limits::default()).unwrap();
    let a = prepared(&mut store);
    store.robot_bind(&binding(&a), 100).unwrap();
    store.start(&a, 100).unwrap();
    let intent = store.robot_reserve(&a, "key", "digest", 101).unwrap();
    let mut cancelled = snapshot(&intent, false);
    cancelled.operation = None;
    cancelled.reconciled = false;
    cancelled.cancellation_durable = true;
    cancelled.phase = "CancelledDurable".into();
    cancelled.closure = "NotAllocated".into();
    cancelled.verdict = actryn_server::robot::Verdict::Pending;
    let mut invalid = cancelled.clone();
    invalid.phase = "Submitted".into();
    invalid.terminal = false;
    assert!(store.robot_snapshot(&a, "key", &invalid).is_err());
    invalid = cancelled.clone();
    invalid.revision = 2;
    assert!(store.robot_snapshot(&a, "key", &invalid).is_err());
    invalid = cancelled.clone();
    invalid.durable_revision = 2;
    assert!(store.robot_snapshot(&a, "key", &invalid).is_err());
    invalid = cancelled.clone();
    invalid.closure = "NotRequested".into();
    assert!(store.robot_snapshot(&a, "key", &invalid).is_err());
    invalid = snapshot(&intent, false);
    invalid.phase = "InventedTerminal".into();
    assert!(store.robot_snapshot(&a, "key", &invalid).is_err());
    invalid = snapshot(&intent, false);
    invalid.closure = "InventedClosure".into();
    assert!(store.robot_snapshot(&a, "key", &invalid).is_err());
    for field in [
        "device",
        "boot",
        "session",
        "runtime_nonce",
        "grant",
        "instance",
        "operation",
        "stream",
    ] {
        let mut value = serde_json::to_value(snapshot(&intent, false)).unwrap();
        value["operation"][field] = if matches!(field, "device" | "runtime_nonce") {
            json!(vec![0; 16])
        } else {
            json!(0)
        };
        let invalid: RemoteSnapshot = serde_json::from_value(value).unwrap();
        assert!(
            store.robot_snapshot(&a, "key", &invalid).is_err(),
            "{field}"
        );
    }
    assert!(store.robot_intent(&a, "key").unwrap().outstanding_debit);
    store.robot_snapshot(&a, "key", &cancelled).unwrap();
    assert!(!store.robot_intent(&a, "key").unwrap().outstanding_debit);
}

#[test]
fn trusted_model_context_does_not_accept_the_agent_observation_as_authority() {
    let input = actryn_server::model::ModelInput {
        goal: "one index".into(),
        observation_id: "agent-forgery".into(),
    };
    assert!(serde_json::from_value::<actryn_server::model::ModelInput>(
        json!({"goal":"x","observation_id":"fake","trusted_robot_observation":{"id":2}})
    )
    .is_err());
    let body =
        actryn_server::model::request_body_with_observation(&input, Some(&observation())).unwrap();
    let prompt: serde_json::Value = serde_json::from_str(body["input"].as_str().unwrap()).unwrap();
    assert_eq!(prompt["trusted_robot_observation"]["id"], 1);
    assert!(!body["input"].as_str().unwrap().contains("agent-forgery"));
}
