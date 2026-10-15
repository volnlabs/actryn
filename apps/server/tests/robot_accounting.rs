use actryn_server::{
    robot::{Binding, Observation, RemoteSnapshot},
    Limits, Store,
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
        "revision":1,"durable_revision":1,"phase":"Completed","terminal":true,"closure":"Open",
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
fn terminal_unknown_stays_charged_and_only_matching_reconciled_result_settles() {
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
    s.robot_snapshot(&a, "first", &snapshot(&intent, true))
        .unwrap();
    assert!(s.robot_intent(&a, "first").unwrap().outstanding_debit);
    let mut wrong = snapshot(&intent, false);
    wrong.key = [0; 32];
    assert!(s.robot_snapshot(&a, "first", &wrong).is_err());
    let mut pending = snapshot(&intent, false);
    pending.reconciled = false;
    s.robot_snapshot(&a, "first", &pending).unwrap();
    assert!(s.robot_intent(&a, "first").unwrap().outstanding_debit);
    s.robot_snapshot(&a, "first", &snapshot(&intent, false))
        .unwrap();
    assert!(!s.robot_intent(&a, "first").unwrap().outstanding_debit);
    assert!(s.robot_reserve(&a, "second", "input-2", 105).is_ok());
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
        closed.phase = "Cancelled".into();
        closed.closure = "KeyCancelled".into();
        closed.verdict = actryn_server::robot::Verdict::Cancelled;
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
