use super::*;
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicBool, AtomicU64, Ordering},
    thread,
    time::Duration,
};
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!(
            "actryn-intent-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        )))
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
        let _ = fs::remove_file(self.0.with_extension("lock"));
    }
}
struct Kernel {
    epoch: [u8; 16],
    next: AtomicU64,
    live: AtomicBool,
    unknown: AtomicBool,
    events: Mutex<Vec<(&'static str, OperationId)>>,
}
impl Kernel {
    fn new(epoch: u8) -> Arc<Self> {
        Arc::new(Self {
            epoch: [epoch; 16],
            next: AtomicU64::new(1),
            live: AtomicBool::new(true),
            unknown: AtomicBool::new(false),
            events: Mutex::new(Vec::new()),
        })
    }
    fn count(&self, kind: &str) -> usize {
        self.events
            .lock()
            .unwrap()
            .iter()
            .filter(|(event, _)| *event == kind)
            .count()
    }
}
impl Authority for Kernel {
    fn allocate(&self, intent: &Intent) -> std::result::Result<OperationId, AuthorityError> {
        let counter = self.next.fetch_add(1, Ordering::SeqCst);
        let op = OperationId {
            device: [7; 16],
            boot: 1,
            session: 1,
            runtime_nonce: self.epoch,
            grant: intent.grant,
            instance: intent.instance,
            operation: counter,
            stream: counter,
        };
        self.events.lock().unwrap().push(("allocate", op));
        Ok(op)
    }
    fn submit(&self, op: &OperationId, _: &Intent) -> std::result::Result<(), AuthorityError> {
        self.events.lock().unwrap().push(("submit", *op));
        if self.unknown.load(Ordering::SeqCst) {
            return Err(AuthorityError::OutcomeUnknown);
        }
        if !self.live.load(Ordering::SeqCst) {
            return Err(AuthorityError::Denied);
        }
        Ok(())
    }
    fn close(&self, op: &OperationId) -> std::result::Result<CloseAck, AuthorityError> {
        self.events.lock().unwrap().push(("close", *op));
        Ok(CloseAck::LocallyClosed {
            transition: op.operation,
        })
    }
}
fn intent() -> Intent {
    Intent {
        digest: [3; 32],
        configuration_digest: [4; 32],
        instance: 1,
        grant: 1,
        context_revision: 1,
        deadline_ns: 1000,
        observation: 1,
        payload: b"fixed typed wheel target".to_vec(),
    }
}
fn ready(path: &Path, limits: Limits) -> (Registry, Writer, Namespace, Arc<Kernel>) {
    let kernel = Kernel::new(1);
    let (registry, mut writer) = Registry::open(path, [1; 16], limits, kernel.clone()).unwrap();
    let ns = registry.prepare_namespace([2; 16], [3; 16]).unwrap();
    assert!(!registry.namespace_ready(&ns));
    writer.flush().unwrap();
    assert!(registry.namespace_ready(&ns));
    (registry, writer, ns, kernel)
}
#[test]
fn durable_intent_precedes_submission_and_duplicate_never_resubmits() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    let pending = registry.propose(&ns, [1; 32], intent()).unwrap();
    assert_eq!(pending.phase, Phase::PendingIntent);
    assert_eq!(kernel.count("submit"), 0);
    assert!(pending.operation.is_some());
    assert_eq!(registry.propose(&ns, [1; 32], intent()).unwrap(), pending);
    assert_eq!(kernel.count("allocate"), 1);
    writer.flush().unwrap();
    let submitted = registry.query(ns.id(), [1; 32]).unwrap();
    assert_eq!(submitted.phase, Phase::Submitted);
    assert!(submitted.durable_revision >= 1);
    assert_eq!(kernel.count("submit"), 1);
    registry.propose(&ns, [1; 32], intent()).unwrap();
    writer.flush().unwrap();
    assert_eq!(kernel.count("submit"), 1);
    let mut changed = intent();
    changed.digest = [8; 32];
    assert!(matches!(
        registry.propose(&ns, [1; 32], changed),
        Err(Error::Conflict)
    ));
    let mut changed = intent();
    changed.payload.push(0);
    assert!(matches!(
        registry.propose(&ns, [1; 32], changed),
        Err(Error::Conflict)
    ));
}
#[test]
fn cancelled_absent_key_is_fenced_before_durability_and_survives_ack_loss() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    let pending = registry.cancel(&ns, [1; 32]).unwrap();
    assert!(!pending.key_cancelled_durable());
    assert_eq!(pending.phase, Phase::CancelPending);
    assert_eq!(
        registry.propose(&ns, [1; 32], intent()).unwrap().phase,
        Phase::CancelPending
    );
    assert_eq!(kernel.count("allocate"), 0);
    writer.flush().unwrap();
    assert!(registry
        .query(ns.id(), [1; 32])
        .unwrap()
        .key_cancelled_durable());
    drop(writer);
    drop(registry);
    drop(ns); // acknowledgement was lost; caller only queries after restart
    let (recovered, mut writer) =
        Registry::open(&temp.0, [2; 16], Limits::default(), Kernel::new(2)).unwrap();
    let historical = recovered.lookup_namespace([3; 16]).unwrap();
    assert!(!recovered.namespace_ready(&historical));
    assert!(recovered
        .query([3; 16], [1; 32])
        .unwrap()
        .key_cancelled_durable());
    assert!(recovered.prepare_namespace([2; 16], [3; 16]).is_err());
    assert!(recovered.propose(&historical, [2; 32], intent()).is_err());
    writer.flush().unwrap();
}
#[test]
fn allocated_cancel_does_not_wait_for_blocked_storage_before_id_reply() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    let pending = registry.propose(&ns, [1; 32], intent()).unwrap();
    let barrier = Arc::new(std::sync::Barrier::new(2));
    writer.block_storage(barrier.clone());
    let storage = thread::spawn(move || writer.flush());
    barrier.wait();
    let (tx, rx) = std::sync::mpsc::channel();
    let cancel_registry = registry.clone();
    let cancel_ns = ns.clone();
    let cancel = thread::spawn(move || {
        tx.send(cancel_registry.cancel(&cancel_ns, [1; 32]).unwrap())
            .unwrap()
    });
    let snapshot = rx
        .recv_timeout(Duration::from_secs(1))
        .expect("cancel blocked behind storage");
    cancel.join().unwrap();
    assert_eq!(snapshot.operation, pending.operation);
    assert_eq!(snapshot.phase, Phase::CancelPending);
    assert!(!snapshot.key_cancelled_durable());
    assert!(matches!(snapshot.closure, Closure::LocallyClosed { .. }));
    assert_eq!(kernel.count("close"), 1);
    assert_eq!(kernel.count("submit"), 0);
    barrier.wait();
    storage.join().unwrap().unwrap();
    assert!(registry
        .query(ns.id(), [1; 32])
        .unwrap()
        .key_cancelled_durable());
    assert_eq!(kernel.count("submit"), 0);
}
#[test]
fn cancel_between_durable_commit_and_final_check_prevents_dispatch() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    registry.propose(&ns, [1; 32], intent()).unwrap();
    let barrier = Arc::new(std::sync::Barrier::new(2));
    writer.after_persist = Some(barrier.clone());
    let storage = thread::spawn(move || writer.flush());
    barrier.wait();
    registry.cancel(&ns, [1; 32]).unwrap();
    barrier.wait();
    storage.join().unwrap().unwrap();
    assert_eq!(kernel.count("submit"), 0);
    assert_eq!(kernel.count("close"), 1);
    assert!(registry
        .query(ns.id(), [1; 32])
        .unwrap()
        .key_cancelled_durable());
}
#[test]
fn final_kernel_check_is_fresh_and_cancel_after_submit_closes_same_ids() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    let pending = registry.propose(&ns, [1; 32], intent()).unwrap();
    kernel.live.store(false, Ordering::SeqCst);
    writer.flush().unwrap();
    assert_eq!(
        registry.query(ns.id(), [1; 32]).unwrap().phase,
        Phase::Rejected
    );
    assert_eq!(kernel.count("close"), 1);
    kernel.live.store(true, Ordering::SeqCst);
    registry.propose(&ns, [2; 32], intent()).unwrap();
    writer.flush().unwrap();
    let submitted = registry.query(ns.id(), [2; 32]).unwrap();
    registry
        .cancel_operation(&submitted.operation.unwrap())
        .unwrap();
    assert_eq!(
        registry
            .query_operation(&submitted.operation.unwrap())
            .unwrap()
            .phase,
        Phase::CancelPending
    );
    assert_ne!(submitted.operation, pending.operation);
    writer.flush().unwrap();
    assert!(registry
        .query(ns.id(), [2; 32])
        .unwrap()
        .key_cancelled_durable());
}
#[test]
fn database_terminal_wins_against_delayed_and_even_newer_nonterminal_intents() {
    let temp = Temp::new();
    let (registry, mut writer, ns, _) = ready(&temp.0, Limits::default());
    registry.propose(&ns, [1; 32], intent()).unwrap();
    let allocation = { lock(&registry.shared).ordinary.pop_front().unwrap() };
    registry.cancel(&ns, [1; 32]).unwrap();
    let cancellation = { lock(&registry.shared).control.pop_front().unwrap() };
    let parent = lock(&registry.shared)
        .namespaces
        .get(&ns.id())
        .unwrap()
        .clone();
    writer
        .store
        .persist(&cancellation, Some(&parent), &Limits::default())
        .unwrap();
    let old = writer
        .store
        .persist(&allocation, Some(&parent), &Limits::default())
        .unwrap()
        .unwrap();
    assert_eq!(old.snapshot.phase, Phase::CancelledDurable);
    let mut changed = allocation;
    let Job::Key(ref mut entry) = changed else {
        unreachable!()
    };
    entry.snapshot.revision = 99;
    let result = writer
        .store
        .persist(&changed, Some(&parent), &Limits::default())
        .unwrap()
        .unwrap();
    assert_eq!(result.snapshot.revision, 2);
    assert!(result.snapshot.key_cancelled_durable());
}
#[test]
fn restart_retains_unknown_and_never_resends_or_reopens_namespaces() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    registry.propose(&ns, [1; 32], intent()).unwrap();
    writer.flush().unwrap();
    assert_eq!(kernel.count("submit"), 1);
    drop(writer);
    drop(registry);
    drop(ns);
    let recovered_kernel = Kernel::new(2);
    let (registry, mut writer) = Registry::open(
        &temp.0,
        [2; 16],
        Limits::default(),
        recovered_kernel.clone(),
    )
    .unwrap();
    let old = registry.lookup_namespace([3; 16]).unwrap();
    let unknown = registry.query(old.id(), [1; 32]).unwrap();
    assert_eq!(unknown.phase, Phase::OutcomeUnknown);
    assert!(unknown.terminal);
    assert!(!registry.namespace_ready(&old));
    assert_eq!(registry.propose(&old, [1; 32], intent()).unwrap(), unknown);
    assert!(registry.propose(&old, [2; 32], intent()).is_err());
    writer.flush().unwrap();
    assert_eq!(recovered_kernel.count("allocate"), 0);
    assert_eq!(recovered_kernel.count("submit"), 0);
}
#[test]
fn persistence_failure_preserves_pending_cancellation_and_unknown_allocations() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    registry.propose(&ns, [1; 32], intent()).unwrap();
    registry.cancel(&ns, [1; 32]).unwrap();
    writer.inject_failure();
    assert!(writer.flush().is_err());
    let failed = registry.query(ns.id(), [1; 32]).unwrap();
    assert_eq!(failed.phase, Phase::CancelPending);
    assert!(failed.persistence_failed);
    assert!(!failed.key_cancelled_durable());
    assert!(registry.health().revoke_required);
    assert!(registry.propose(&ns, [2; 32], intent()).is_err());
    assert_eq!(kernel.count("submit"), 0);
}
#[test]
fn key_exhaustion_retires_namespace_and_closes_allocated_work() {
    let temp = Temp::new();
    let limits = Limits {
        keys: 2,
        cancellation_keys: 1,
        ..Limits::default()
    };
    let (registry, mut writer, ns, kernel) = ready(&temp.0, limits);
    registry.propose(&ns, [1; 32], intent()).unwrap();
    assert!(registry.propose(&ns, [2; 32], intent()).is_err());
    registry.cancel(&ns, [2; 32]).unwrap();
    assert!(matches!(
        registry.cancel(&ns, [3; 32]),
        Err(Error::Capacity)
    ));
    assert!(!registry.namespace_ready(&ns));
    assert!(registry.health().revoke_required);
    assert_eq!(kernel.count("close"), 1);
    writer.flush().unwrap();
    assert_eq!(kernel.count("submit"), 0);
    assert!(registry.propose(&ns, [4; 32], intent()).is_err());
}
#[test]
fn persistence_queue_reserve_is_finite_and_exhaustion_still_closes() {
    let temp = Temp::new();
    let limits = Limits {
        pending_jobs: 3,
        closure_jobs: 1,
        ..Limits::default()
    };
    let (registry, _writer, ns, kernel) = ready(&temp.0, limits);
    registry.propose(&ns, [1; 32], intent()).unwrap();
    registry.propose(&ns, [2; 32], intent()).unwrap();
    assert!(registry.propose(&ns, [3; 32], intent()).is_err());
    registry.cancel(&ns, [1; 32]).unwrap();
    assert_eq!(kernel.count("close"), 1);
    let exhausted = registry.cancel(&ns, [9; 32]).unwrap();
    assert!(exhausted.persistence_failed);
    assert!(!exhausted.key_cancelled_durable());
    assert!(!registry.namespace_ready(&ns));
    assert!(registry.health().pending_jobs <= 3);
    assert_eq!(kernel.count("close"), 2);
    assert_eq!(kernel.count("submit"), 0);
}
#[test]
fn pending_namespace_cancel_persists_parent_and_completed_records_stay_terminal() {
    let temp = Temp::new();
    let kernel = Kernel::new(1);
    let (registry, mut writer) =
        Registry::open(&temp.0, [1; 16], Limits::default(), kernel.clone()).unwrap();
    let ns = registry.prepare_namespace([2; 16], [3; 16]).unwrap();
    registry.cancel(&ns, [1; 32]).unwrap();
    writer.flush().unwrap();
    assert!(registry
        .query(ns.id(), [1; 32])
        .unwrap()
        .key_cancelled_durable());
    registry.propose(&ns, [2; 32], intent()).unwrap();
    writer.flush().unwrap();
    let completed = registry.complete(&ns, [2; 32]).unwrap();
    assert_eq!(completed.phase, Phase::Completed);
    writer.flush().unwrap();
    assert_eq!(
        registry.cancel(&ns, [2; 32]).unwrap().phase,
        Phase::Completed
    );
    assert_eq!(kernel.count("close"), 0);
}

#[test]
fn later_storage_failure_does_not_erase_an_acknowledged_durable_tombstone() {
    let temp = Temp::new();
    let (registry, mut writer, ns, _) = ready(&temp.0, Limits::default());
    registry.cancel(&ns, [1; 32]).unwrap();
    writer.flush().unwrap();
    assert!(registry
        .query(ns.id(), [1; 32])
        .unwrap()
        .key_cancelled_durable());
    registry.propose(&ns, [2; 32], intent()).unwrap();
    writer.inject_failure();
    assert!(writer.flush().is_err());
    assert!(registry
        .query(ns.id(), [1; 32])
        .unwrap()
        .key_cancelled_durable());
    let unknown = registry.query(ns.id(), [2; 32]).unwrap();
    assert_eq!(unknown.phase, Phase::OutcomeUnknown);
    assert!(unknown.persistence_failed);
    assert!(unknown.revision > unknown.durable_revision);
}
#[test]
fn unknown_submit_faults_without_resubmission_and_closes_allocated_identity() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    registry.propose(&ns, [1; 32], intent()).unwrap();
    kernel.unknown.store(true, Ordering::SeqCst);
    writer.flush().unwrap();
    assert_eq!(
        registry.query(ns.id(), [1; 32]).unwrap().phase,
        Phase::OutcomeUnknown
    );
    assert_eq!(kernel.count("submit"), 1);
    assert_eq!(kernel.count("close"), 1);
    assert!(registry.health().revoke_required);
    registry.propose(&ns, [1; 32], intent()).unwrap();
    writer.flush().unwrap();
    assert_eq!(kernel.count("submit"), 1);
}
#[test]
fn epoch_reuse_lock_payload_and_namespace_capacity_reject_before_allocation() {
    let temp = Temp::new();
    let limits = Limits {
        namespaces: 1,
        max_payload_bytes: 32,
        ..Limits::default()
    };
    let (registry, writer, ns, kernel) = ready(&temp.0, limits.clone());
    assert!(Registry::open(&temp.0, [2; 16], limits.clone(), Kernel::new(2)).is_err());
    assert!(registry.prepare_namespace([9; 16], [8; 16]).is_err());
    let mut oversized = intent();
    oversized.payload = vec![0; 33];
    assert!(registry.propose(&ns, [1; 32], oversized).is_err());
    assert_eq!(kernel.count("allocate"), 0);
    drop(writer);
    assert!(Registry::open(&temp.0, [1; 16], limits, Kernel::new(1)).is_err());
}

#[test]
fn sqlite_exclusive_writer_lock_cannot_block_urgent_allocated_cancel() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    registry.propose(&ns, [1; 32], intent()).unwrap();
    let blocker = rusqlite::Connection::open(&temp.0).unwrap();
    blocker.execute_batch("BEGIN EXCLUSIVE").unwrap();
    let barrier = Arc::new(std::sync::Barrier::new(2));
    writer.block_storage(barrier.clone());
    let storage = thread::spawn(move || writer.flush());
    barrier.wait();
    barrier.wait();
    thread::sleep(Duration::from_millis(20));
    assert!(!registry.health().persistence_failed);
    let (tx, rx) = std::sync::mpsc::channel();
    let urgent = registry.clone();
    let urgent_ns = ns.clone();
    let cancel = thread::spawn(move || {
        tx.send(urgent.cancel(&urgent_ns, [1; 32]).unwrap())
            .unwrap()
    });
    let pending = rx
        .recv_timeout(Duration::from_secs(1))
        .expect("cancel waited for SQLite lock");
    cancel.join().unwrap();
    assert_eq!(pending.phase, Phase::CancelPending);
    assert_eq!(kernel.count("close"), 1);
    assert_eq!(kernel.count("submit"), 0);
    blocker.execute_batch("COMMIT").unwrap();
    storage.join().unwrap().unwrap();
    assert!(registry
        .query(ns.id(), [1; 32])
        .unwrap()
        .key_cancelled_durable());
    assert_eq!(kernel.count("submit"), 0);
}

#[test]
fn read_only_history_never_dispatches_or_promotes_unfinished_work() {
    let path = Temp::new();
    let kernel = Kernel::new(1);
    let (registry, mut writer) =
        Registry::open(&path.0, [1; 16], Limits::default(), kernel.clone()).unwrap();
    let ns = registry.prepare_namespace([2; 16], [3; 16]).unwrap();
    writer.flush().unwrap();
    registry.propose(&ns, [4; 32], intent()).unwrap();
    writer.flush().unwrap();
    registry.cancel(&ns, [5; 32]).unwrap();
    writer.flush().unwrap();
    assert!(
        inspect(&path.0, [2; 16], [3; 16], [5; 32], Limits::default())
            .unwrap()
            .snapshot
            .unwrap()
            .key_cancelled_durable()
    );
    let before = fs::read(&path.0).unwrap();
    let calls = kernel.events.lock().unwrap().len();
    let inspected = inspect(&path.0, [2; 16], [3; 16], [4; 32], Limits::default()).unwrap();
    assert!(inspected.namespace_exists);
    assert_eq!(inspected.snapshot.unwrap().phase, Phase::OutcomeUnknown);
    assert!(inspect(&path.0, [9; 16], [3; 16], [4; 32], Limits::default()).is_err());
    assert!(
        inspect(&path.0, [2; 16], [3; 16], [9; 32], Limits::default())
            .unwrap()
            .snapshot
            .is_none()
    );
    assert!(
        !inspect(&path.0, [2; 16], [9; 16], [9; 32], Limits::default())
            .unwrap()
            .namespace_exists
    );
    assert_eq!(fs::read(&path.0).unwrap(), before);
    assert_eq!(kernel.events.lock().unwrap().len(), calls);
    drop(writer);
    drop(registry);
    assert_eq!(
        inspect(&path.0, [2; 16], [3; 16], [4; 32], Limits::default())
            .unwrap()
            .snapshot
            .unwrap()
            .phase,
        Phase::OutcomeUnknown
    );
    let absent = Temp::new();
    assert!(inspect(&absent.0, [2; 16], [3; 16], [4; 32], Limits::default()).is_err());
    assert!(!absent.0.exists());
}

#[test]
fn cancellation_reconciliation_is_atomic_durable_and_survives_retirement() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    registry.propose(&ns, [7; 32], intent()).unwrap();
    writer.flush().unwrap();
    let cancelled = registry.cancel(&ns, [7; 32]).unwrap();
    let id = cancelled.operation.unwrap();
    writer.flush().unwrap();
    assert!(!registry
        .query(ns.id(), [7; 32])
        .unwrap()
        .reconciled_durable());
    let marked = registry.reconcile(&ns, [7; 32], &id).unwrap();
    assert_eq!(marked.phase, Phase::CancelledDurable);
    assert_eq!(marked.revision, cancelled.revision + 1);
    assert!(!marked.reconciled_durable());
    assert_eq!(registry.reconcile(&ns, [7; 32], &id).unwrap(), marked);
    assert_eq!(registry.cancel(&ns, [7; 32]).unwrap(), marked);
    assert_eq!(registry.complete(&ns, [7; 32]).unwrap(), marked);
    registry.retire_namespace(&ns).unwrap();
    // The actual writer's normal stop path must flush the marker before exit.
    writer
        .run(Arc::new(AtomicBool::new(true)), Duration::from_millis(1))
        .unwrap();
    let calls = kernel.events.lock().unwrap().len();
    let historical = inspect(&temp.0, [2; 16], [3; 16], [7; 32], Limits::default())
        .unwrap()
        .snapshot
        .unwrap();
    assert!(historical.reconciled_durable());
    assert!(historical.key_cancelled_durable());
    assert_eq!(historical.operation, Some(id));
    assert_eq!(historical.closure, cancelled.closure);
    drop(registry);
    let (_restarted, _writer) =
        Registry::open(&temp.0, [2; 16], Limits::default(), kernel.clone()).unwrap();
    assert_eq!(kernel.events.lock().unwrap().len(), calls);
}

#[test]
fn cancellation_reconciliation_rejects_wrong_identity_and_missing_commit() {
    let temp = Temp::new();
    let (registry, mut writer, ns, _) = ready(&temp.0, Limits::default());
    let id = registry
        .propose(&ns, [7; 32], intent())
        .unwrap()
        .operation
        .unwrap();
    writer.flush().unwrap();
    registry.cancel(&ns, [7; 32]).unwrap();
    writer.flush().unwrap();
    let mut wrong = id;
    wrong.instance += 1;
    assert!(registry.reconcile(&ns, [7; 32], &wrong).is_err());
    registry.reconcile(&ns, [7; 32], &id).unwrap();
    writer.inject_failure();
    assert!(writer.flush().is_err());
    assert!(!registry
        .query(ns.id(), [7; 32])
        .unwrap()
        .reconciled_durable());
    let old = inspect(&temp.0, [2; 16], [3; 16], [7; 32], Limits::default())
        .unwrap()
        .snapshot
        .unwrap();
    assert!(old.key_cancelled_durable());
    assert!(!old.reconciled_durable());
}

#[test]
fn legacy_layout_preserves_completed_proof_but_never_promotes_cancelled_rows() {
    let temp = Temp::new();
    let (registry, mut writer, ns, kernel) = ready(&temp.0, Limits::default());
    for key in [[7; 32], [8; 32]] {
        registry.propose(&ns, key, intent()).unwrap();
        writer.flush().unwrap();
    }
    registry.complete(&ns, [7; 32]).unwrap();
    registry.cancel(&ns, [8; 32]).unwrap();
    writer.flush().unwrap();
    drop(writer);
    drop(registry);
    let db = rusqlite::Connection::open(&temp.0).unwrap();
    db.execute_batch("DROP TABLE reconciliations").unwrap();
    let records: Vec<(Vec<u8>, i64, i64, i64)> = db
        .prepare("SELECT key,revision,terminal,phase FROM records ORDER BY key")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
        .unwrap()
        .map(|r| r.unwrap())
        .collect();
    drop(db);
    let before = fs::read(&temp.0).unwrap();
    for (key, expected) in [([7; 32], true), ([8; 32], false)] {
        let row = inspect(&temp.0, [2; 16], [3; 16], key, Limits::default())
            .unwrap()
            .snapshot
            .unwrap();
        assert_eq!(row.reconciled_durable(), expected);
    }
    assert_eq!(fs::read(&temp.0).unwrap(), before);
    let calls = kernel.events.lock().unwrap().len();
    let (_registry, _writer) =
        Registry::open(&temp.0, [2; 16], Limits::default(), kernel.clone()).unwrap();
    let db = rusqlite::Connection::open(&temp.0).unwrap();
    let after: Vec<(Vec<u8>, i64, i64, i64)> = db
        .prepare("SELECT key,revision,terminal,phase FROM records ORDER BY key")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
        .unwrap()
        .map(|r| r.unwrap())
        .collect();
    assert_eq!(records, after);
    assert_eq!(kernel.events.lock().unwrap().len(), calls);
}

#[test]
fn reconciliation_audit_rejects_orphan_duplicate_wrong_revision_identity_and_phase() {
    for corruption in [
        "UPDATE reconciliations SET key=zeroblob(32)",
        "UPDATE reconciliations SET revision=revision+1",
        "UPDATE reconciliations SET operation=zeroblob(80)",
        "UPDATE reconciliations SET operation=zeroblob(81)",
        "DELETE FROM namespaces",
        "UPDATE records SET phase=6 WHERE key=x'0707070707070707070707070707070707070707070707070707070707070707'",
        "UPDATE records SET terminal=0 WHERE key=x'0707070707070707070707070707070707070707070707070707070707070707'",
        "ALTER TABLE reconciliations RENAME TO saved; CREATE TABLE reconciliations AS SELECT * FROM saved; INSERT INTO reconciliations SELECT * FROM saved; DROP TABLE saved",
    ] {
        let temp=Temp::new();
        let (registry,mut writer,ns,kernel)=ready(&temp.0,Limits::default());
        let id=registry.propose(&ns,[7;32],intent()).unwrap().operation.unwrap();
        writer.flush().unwrap();
        registry.cancel(&ns,[7;32]).unwrap();
        registry.cancel(&ns,[8;32]).unwrap();
        registry.reconcile(&ns,[7;32],&id).unwrap();
        writer.flush().unwrap();
        drop(writer); drop(registry);
        rusqlite::Connection::open(&temp.0).unwrap().execute_batch(corruption).unwrap();
        let before=fs::read(&temp.0).unwrap();
        assert!(inspect(&temp.0,[2;16],[3;16],[8;32],Limits::default()).is_err(),"{corruption}");
        assert_eq!(fs::read(&temp.0).unwrap(),before);
        assert!(Registry::open(&temp.0,[2;16],Limits::default(),kernel).is_err(),"{corruption}");
        assert_eq!(fs::read(&temp.0).unwrap(),before);
    }
}

#[test]
fn failed_marker_insert_rolls_back_the_terminal_revision_too() {
    let temp = Temp::new();
    let (registry, mut writer, ns, _) = ready(&temp.0, Limits::default());
    let id = registry
        .propose(&ns, [7; 32], intent())
        .unwrap()
        .operation
        .unwrap();
    writer.flush().unwrap();
    registry.cancel(&ns, [7; 32]).unwrap();
    writer.flush().unwrap();
    let old = registry.query(ns.id(), [7; 32]).unwrap();
    let db = rusqlite::Connection::open(&temp.0).unwrap();
    db.execute_batch("CREATE TRIGGER reject_marker BEFORE INSERT ON reconciliations BEGIN SELECT RAISE(ABORT,'marker failure'); END").unwrap();
    registry.reconcile(&ns, [7; 32], &id).unwrap();
    assert!(writer.flush().is_err());
    let row = inspect(&temp.0, [2; 16], [3; 16], [7; 32], Limits::default())
        .unwrap()
        .snapshot
        .unwrap();
    assert_eq!(row, old);
    assert_eq!(
        db.query_row("SELECT COUNT(*) FROM reconciliations", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
}

#[test]
fn allocated_cancel_proof_never_submits_and_control_exhaustion_never_claims_durability() {
    for full in [false, true] {
        let temp = Temp::new();
        let mut limits = Limits::default();
        if full {
            limits.pending_jobs = 2;
            limits.closure_jobs = 1;
        }
        let (registry, mut writer, ns, kernel) = ready(&temp.0, limits);
        let id = registry
            .propose(&ns, [7; 32], intent())
            .unwrap()
            .operation
            .unwrap();
        registry.cancel(&ns, [7; 32]).unwrap();
        let observed = registry.reconcile(&ns, [7; 32], &id).unwrap();
        assert!(!observed.reconciled_durable());
        assert_eq!(observed.persistence_failed, full);
        writer.flush().unwrap();
        assert_eq!(kernel.count("submit"), 0);
        let durable = inspect(&temp.0, [2; 16], [3; 16], [7; 32], Limits::default())
            .unwrap()
            .snapshot
            .unwrap();
        assert_eq!(durable.reconciled_durable(), !full);
        assert!(durable.key_cancelled_durable());
    }
}
