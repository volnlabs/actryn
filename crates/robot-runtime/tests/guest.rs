//! Opt-in integration: no mock device or userspace authority substitute.
use robot_runtime::*;
use std::{
    os::unix::fs::PermissionsExt,
    thread,
    time::{Duration, Instant},
};
struct StateDirectory(Option<tempfile::TempDir>);
impl StateDirectory {
    fn path(&self) -> &std::path::Path {
        self.0.as_ref().unwrap().path()
    }
}
impl Drop for StateDirectory {
    fn drop(&mut self) {
        if std::thread::panicking() {
            if let Some(dir) = self.0.take() {
                eprintln!("retained failed runtime evidence: {}", dir.keep().display());
            }
        }
    }
}
fn diagnostic(engine: &Engine) -> String {
    match engine.status() {
        Ok(status) => {
            serde_json::to_string(&status).unwrap_or_else(|e| format!("status encode: {e}"))
        }
        Err(error) => format!("status unavailable: {error}"),
    }
}
fn poll(engine: &Engine, stage: &str, timeout: Duration, mut ready: impl FnMut() -> bool) {
    eprintln!("stage {stage} begin: {}", diagnostic(engine));
    let end = Instant::now() + timeout;
    while !ready() {
        assert!(
            Instant::now() < end,
            "stage {stage} timed out: {}",
            diagnostic(engine)
        );
        if let Err(error) = engine.tick() {
            panic!("stage {stage} tick failed: {error}; {}", diagnostic(engine));
        }
        thread::sleep(Duration::from_millis(25));
    }
    eprintln!("stage {stage} complete: {}", diagnostic(engine));
}
#[test]
#[ignore = "requires isolated ARM64 guest, loaded actual module, connected fixture and administrative credentials"]
fn actual_module_two_steps_and_pre_id_tombstone() {
    let dir = StateDirectory(Some(tempfile::tempdir().unwrap()));
    std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let engine = Engine::open(dir.path()).unwrap();
    engine.recover().unwrap();
    poll(&engine, "recover HELLO", Duration::from_secs(13), || {
        !engine.status().unwrap().recovery_pending
    });
    engine.rearm().unwrap();
    poll(&engine, "rearm BASELINE", Duration::from_secs(2), || {
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
    poll(
        &engine,
        "namespace durability and GRANT",
        Duration::from_secs(2),
        || {
            if !granted {
                granted = engine.grant(now + 25_000_000_000).is_ok();
            }
            granted
        },
    );
    engine.activate().unwrap();
    for key in [[4; 32], [5; 32]] {
        let observation = engine.observe().unwrap();
        let target = Target {
            left_ticks: 5,
            right_ticks: -5,
            duration_ms: 5000,
        };
        engine
            .propose(&binding, key, [6; 32], target, observation.id)
            .unwrap();
        poll(
            &engine,
            &format!("durable operation ID key {}", key[0]),
            Duration::from_secs(2),
            || {
                engine
                    .query(&binding, key)
                    .unwrap()
                    .unwrap()
                    .operation
                    .is_some()
            },
        );
        let first = engine.query(&binding, key).unwrap().unwrap();
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
        poll(
            &engine,
            &format!("normal reconciliation key {}", key[0]),
            Duration::from_secs(5),
            || engine.query(&binding, key).unwrap().unwrap().reconciled,
        );
        assert_eq!(
            engine.query(&binding, key).unwrap().unwrap().verdict,
            Verdict::TargetReached
        );
    }
    let cancelled = engine.cancel(&binding, [8; 32]).unwrap();
    assert!(!cancelled.cancellation_durable);
    poll(
        &engine,
        "absent-key cancellation durability",
        Duration::from_secs(2),
        || {
            engine
                .query(&binding, [8; 32])
                .unwrap()
                .unwrap()
                .cancellation_durable
        },
    );
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
