//! Opt-in integration: no mock device or userspace authority substitute.
use robot_runtime::*;
use std::{
    thread,
    time::{Duration, Instant},
};
fn poll(engine: &Engine, timeout: Duration, mut ready: impl FnMut() -> bool) {
    let end = Instant::now() + timeout;
    while !ready() {
        assert!(Instant::now() < end, "timed out: {:?}", engine.status());
        engine.tick().unwrap();
        thread::sleep(Duration::from_millis(25));
    }
}
#[test]
#[ignore = "requires isolated ARM64 guest, loaded actual module, connected fixture and administrative credentials"]
fn actual_module_two_steps_and_pre_id_tombstone() {
    let dir = tempfile::tempdir().unwrap();
    let engine = Engine::open(dir.path()).unwrap();
    engine.recover().unwrap();
    poll(&engine, Duration::from_secs(13), || {
        !engine.status().unwrap().recovery_pending
    });
    engine.rearm().unwrap();
    poll(&engine, Duration::from_secs(2), || {
        engine.status().unwrap().kernel.state == 1
    });
    let now = authority_client::boottime_ns().unwrap();
    let binding = Binding {
        principal: [1; 32],
        attempt: [2; 16],
        namespace: [3; 16],
        session_deadline_ns: now + 30_000_000_000,
    };
    engine
        .prepare(binding.clone(), 1, configuration_digest())
        .unwrap();
    let mut granted = false;
    poll(&engine, Duration::from_secs(2), || {
        if !granted {
            granted = engine.grant(now + 25_000_000_000).is_ok();
        }
        granted
    });
    engine.activate().unwrap();
    for key in [[4; 32], [5; 32]] {
        let observation = engine.observe().unwrap();
        let target = Target {
            left_ticks: 5,
            right_ticks: -5,
            duration_ms: 5000,
        };
        let first = engine
            .propose(&binding, key, [6; 32], target, observation.id)
            .unwrap();
        assert!(first.operation.is_some());
        let duplicate = engine
            .propose(&binding, key, [6; 32], target, observation.id)
            .unwrap();
        assert_eq!(
            duplicate.operation.unwrap().operation,
            first.operation.unwrap().operation
        );
        assert!(engine
            .propose(&binding, key, [7; 32], target, observation.id)
            .is_err());
        poll(&engine, Duration::from_secs(5), || {
            engine.query(&binding, key).unwrap().unwrap().reconciled
        });
        assert_eq!(
            engine.query(&binding, key).unwrap().unwrap().verdict,
            Verdict::TargetReached
        );
    }
    let cancelled = engine.cancel(&binding, [8; 32]).unwrap();
    assert!(!cancelled.cancellation_durable);
    poll(&engine, Duration::from_secs(2), || {
        engine
            .query(&binding, [8; 32])
            .unwrap()
            .unwrap()
            .cancellation_durable
    });
    let observation = engine.observe().unwrap();
    assert!(engine
        .propose(
            &binding,
            [8; 32],
            [6; 32],
            Target {
                left_ticks: 1,
                right_ticks: 1,
                duration_ms: 1000
            },
            observation.id
        )
        .unwrap()
        .operation
        .is_none());
    engine.revoke().unwrap();
    assert!(engine.activate().is_err());
    drop(engine);
    let historical = Engine::inspect(dir.path(), [1; 32], [2; 16], [3; 16], [8; 32]).unwrap();
    assert!(!historical.live_authority);
    assert!(historical.snapshot.unwrap().cancellation_durable);
    assert!(Engine::inspect(dir.path(), [9; 32], [2; 16], [3; 16], [8; 32]).is_err());
}
