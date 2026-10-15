use actryn_server::{Limits, Publication, Store};

fn active(store: &mut Store, now: i64) -> String {
    let a = store
        .prepare(&format!("sha256:{}", "a".repeat(64)), now)
        .unwrap();
    store.mark_prepared(&a.id, "binding").unwrap();
    store.start(&a.id, now).unwrap();
    a.id
}

#[test]
fn result_lookup_returns_original_without_resend_and_respects_terminal_fences() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("state.db"), Limits::default()).unwrap();
    let a = active(&mut s, 100);
    let call = s.reserve_call(&a, "original", "digest", 10, 101).unwrap();
    s.mark_dispatched(&call.id, 102).unwrap();
    s.settle(&call.id, 7, b"original-attested-output", 103)
        .unwrap();
    for _ in 0..2 {
        let (record, output) = s.result(&a, "original", 104).unwrap();
        assert_eq!(record.id, call.id);
        assert_eq!(record.consumed_tokens, 7);
        assert_eq!(
            output.as_deref(),
            Some(b"original-attested-output".as_slice())
        );
    }
    assert_eq!(s.inspect(&a).unwrap().calls.len(), 1);
    assert!(s.result(&a, "missing", 104).is_err());
    assert_eq!(s.result(&a, "original", 30_101).unwrap().1, None);
    s.cancel_call(&a, "original").unwrap();
    assert_eq!(s.result(&a, "original", 105).unwrap().1, None);
}

#[test]
fn recovery_preserves_terminal_outcome_and_charges_uncertain_external_work() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("state.db");
    let mut s = Store::open(&path, Limits::default()).unwrap();
    let a = active(&mut s, 100);
    let call = s.reserve_call(&a, "in-flight", "digest", 10, 101).unwrap();
    s.mark_dispatched(&call.id, 102).unwrap();
    s.cancel(&a).unwrap();
    drop(s);
    let mut s = Store::open(path, Limits::default()).unwrap();
    assert_eq!(s.recover().unwrap(), vec![a.clone()]);
    let inspection = s.inspect(&a).unwrap();
    assert_eq!(inspection.attempt.outcome, "cancelled");
    assert_eq!(inspection.calls[0].state, "unknown");
    assert!(inspection.calls[0].publication_closed);
}

#[test]
fn admission_respects_retained_history_and_all_request_keys() {
    let dir = tempfile::tempdir().unwrap();
    let limits = Limits {
        retained_attempts: 1,
        ..Limits::default()
    };
    let mut s = Store::open(dir.path().join("state.db"), limits.clone()).unwrap();
    let a = active(&mut s, 100);
    for n in 0..limits.keys_per_attempt {
        s.cancel_call(&a, &format!("cancel-{n}")).unwrap();
    }
    assert!(s
        .reserve_call(&a, "no-key-capacity", "digest", 1, 101)
        .is_err());
    s.cancel(&a).unwrap();
    s.mark_reaped(&a).unwrap();
    assert!(s
        .prepare(&format!("sha256:{}", "a".repeat(64)), 102)
        .is_err());
    assert_eq!(s.attempts().unwrap().len(), 1);
}

#[test]
fn sqlite_write_stall_cannot_dispatch_or_open_closed_publication() {
    use actryn_server::broker::PublicationGate;
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("state.db");
    let mut s = Store::open(&path, Limits::default()).unwrap();
    let a = active(&mut s, 100);
    let call = s.reserve_call(&a, "held", "digest", 10, 101).unwrap();
    let blocker = rusqlite::Connection::open(&path).unwrap();
    blocker.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(s.mark_dispatched(&call.id, 102).is_err());
    assert_eq!(s.inspect(&a).unwrap().calls[0].state, "reserved");
    let gate = PublicationGate::default();
    gate.close();
    assert!(s.cancel(&a).is_err());
    assert!(gate
        .publish(|| panic!("closed publication opened during disk stall"))
        .is_err());
    blocker.execute_batch("ROLLBACK").unwrap();
    s.cancel(&a).unwrap();
    assert!(s.mark_dispatched(&call.id, 103).is_err());
}

#[test]
fn preparation_capacity_stays_charged_until_reaped() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("state.db"), Limits::default()).unwrap();
    let a = s
        .prepare(&format!("sha256:{}", "a".repeat(64)), 100)
        .unwrap();
    s.cancel(&a.id).unwrap();
    let b = s
        .prepare(&format!("sha256:{}", "a".repeat(64)), 101)
        .unwrap();
    s.cancel(&b.id).unwrap();
    assert!(s
        .prepare(&format!("sha256:{}", "a".repeat(64)), 102)
        .is_err());
    s.mark_reaped(&a.id).unwrap();
    assert!(s
        .prepare(&format!("sha256:{}", "a".repeat(64)), 103)
        .is_ok());
}

#[test]
fn expired_preparation_cannot_start() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("state.db"), Limits::default()).unwrap();
    let a = s
        .prepare(&format!("sha256:{}", "a".repeat(64)), 100)
        .unwrap();
    s.mark_prepared(&a.id, "binding").unwrap();
    assert!(s.start(&a.id, 60_100).is_err());
}

#[test]
fn cancellation_tombstone_wins_and_changed_duplicate_rejects() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("state.db"), Limits::default()).unwrap();
    let a = active(&mut s, 100);
    s.cancel_call(&a, "early").unwrap();
    assert!(s.reserve_call(&a, "early", "digest", 10, 101).is_err());
    let r = s.reserve_call(&a, "once", "digest", 10, 101).unwrap();
    assert_eq!(
        s.reserve_call(&a, "once", "digest", 10, 101).unwrap().id,
        r.id
    );
    assert!(s.reserve_call(&a, "once", "changed", 10, 101).is_err());
}

#[test]
fn cancelled_dispatched_work_remains_charged_across_restart() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("state.db");
    let limits = Limits {
        per_attempt_jobs: 1,
        global_jobs: 1,
        ..Limits::default()
    };
    let mut s = Store::open(&path, limits.clone()).unwrap();
    let a = active(&mut s, 100);
    let r = s.reserve_call(&a, "one", "digest", 10, 101).unwrap();
    s.mark_dispatched(&r.id, 102).unwrap();
    s.cancel(&a).unwrap();
    s.mark_reaped(&a).unwrap();
    drop(s);
    let mut s = Store::open(&path, limits).unwrap();
    s.recover().unwrap();
    let b = active(&mut s, 200);
    assert!(s.reserve_call(&b, "two", "digest", 10, 201).is_err());
    assert_eq!(
        s.settle(&r.id, 100, b"late", 202).unwrap(),
        Publication::Suppressed
    );
    assert!(s.reserve_call(&b, "two", "digest", 10, 203).is_ok());
    assert_eq!(s.inspect(&a).unwrap().calls[0].consumed_tokens, 100);
}

#[test]
fn oversized_output_never_publishes_and_success_cost_is_not_refunded() {
    let dir = tempfile::tempdir().unwrap();
    let limits = Limits {
        response_bytes: 4,
        max_calls_per_attempt: 1,
        ..Limits::default()
    };
    let mut s = Store::open(dir.path().join("state.db"), limits).unwrap();
    let a = active(&mut s, 1);
    let r = s.reserve_call(&a, "first", "digest", 2, 2).unwrap();
    s.mark_dispatched(&r.id, 3).unwrap();
    assert_eq!(
        s.settle(&r.id, 50, b"too long", 4).unwrap(),
        Publication::OutputLimit
    );
    assert!(s.reserve_call(&a, "next", "digest", 2, 5).is_err());
    assert_eq!(s.inspect(&a).unwrap().calls[0].consumed_tokens, 50);
}

#[test]
fn reservation_race_cannot_exceed_global_capacity() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("state.db");
    let limits = Limits {
        per_attempt_jobs: 8,
        global_jobs: 1,
        ..Limits::default()
    };
    let mut s = Store::open(&path, limits.clone()).unwrap();
    let a = active(&mut s, 1);
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let workers: Vec<_> = (0..2)
        .map(|i| {
            let path = path.clone();
            let a = a.clone();
            let limits = limits.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                let mut s = Store::open(path, limits).unwrap();
                barrier.wait();
                s.reserve_call(&a, &format!("key{i}"), "digest", 1, 2)
                    .is_ok()
            })
        })
        .collect();
    assert_eq!(
        workers
            .into_iter()
            .filter_map(|t| t.join().ok())
            .filter(|v| *v)
            .count(),
        1
    );
}

#[test]
fn restart_never_restores_prepared_or_running_attempts() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("state.db");
    let mut s = Store::open(&path, Limits::default()).unwrap();
    let a = active(&mut s, 1);
    let r = s.reserve_call(&a, "one", "digest", 1, 2).unwrap();
    drop(s);
    let mut s = Store::open(&path, Limits::default()).unwrap();
    assert_eq!(s.recover().unwrap(), vec![a.clone()]);
    assert!(s.start(&a, 3).is_err());
    assert!(s.mark_dispatched(&r.id, 3).is_err());
    assert_eq!(s.inspect(&a).unwrap().attempt.state, "retiring");
}

#[test]
fn trusted_launcher_adoption_cannot_resurrect_cancelled_broker_namespace() {
    let dir = tempfile::tempdir().unwrap();
    let mut launcher = Store::open(dir.path().join("launcher.db"), Limits::default()).unwrap();
    let a = launcher
        .prepare(&format!("sha256:{}", "b".repeat(64)), 1)
        .unwrap();
    launcher.mark_prepared(&a.id, "binding").unwrap();
    let attempt = launcher.inspect(&a.id).unwrap().attempt;
    let mut broker = Store::open(dir.path().join("broker.db"), Limits::default()).unwrap();
    broker.adopt_prepared(&attempt).unwrap();
    broker.cancel(&a.id).unwrap();
    assert!(broker.adopt_prepared(&attempt).is_err());
}

#[test]
fn normal_exit_and_diagnostic_loss_remain_distinct_facts() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("state.db"), Limits::default()).unwrap();
    let a = active(&mut s, 1);
    s.record_gap(&a, "observer_unavailable").unwrap();
    s.retire(&a, "exited:0").unwrap();
    s.mark_reaped(&a).unwrap();
    let report = s.inspect(&a).unwrap();
    assert_eq!(report.attempt.outcome, "exited:0");
    assert_eq!(report.evidence_gaps, vec!["observer_unavailable"]);
}

#[test]
fn repeated_cleanup_is_idempotent() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("state.db"), Limits::default()).unwrap();
    let a = active(&mut s, 1);
    s.cancel(&a).unwrap();
    s.mark_reaped(&a).unwrap();
    s.mark_reaped(&a).unwrap();
}

#[test]
fn attributable_broker_denials_are_bounded_and_inspectable() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(dir.path().join("state.db"), Limits::default()).unwrap();
    let a = active(&mut s, 1);
    for i in 0..65 {
        s.record_denial(&a, &format!("key{i}"), "admin.grant")
            .unwrap();
    }
    let report = s.inspect(&a).unwrap();
    assert_eq!(report.denials.len(), 64);
    assert_eq!(report.evidence_gaps, vec!["policy_denial_overflow"]);
}
