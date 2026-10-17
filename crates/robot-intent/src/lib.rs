//! Stable request identity and durable intent only. The kernel owns all live
//! eligibility, grants and controller dispatch. No userspace grant table exists.
mod store;
mod types;
mod writer;
use std::{
    collections::{BTreeMap, VecDeque},
    path::Path,
    sync::{Arc, Mutex},
};
pub use store::inspect;
pub use types::*;
pub use writer::Writer;
#[derive(Clone)]
pub struct Registry {
    shared: Arc<Shared>,
}
/// Issued only after authenticated attempt binding by the embedding manager.
/// Historical handles allow query/cancel but never reactivate a retired namespace.
#[derive(Clone)]
pub struct Namespace {
    shared: Arc<Shared>,
    id: NamespaceId,
}
impl Namespace {
    pub fn id(&self) -> NamespaceId {
        self.id
    }
    pub fn attempt(&self) -> [u8; 16] {
        lock(&self.shared).namespaces[&self.id].attempt
    }
    pub fn runtime_epoch(&self) -> [u8; 16] {
        lock(&self.shared).namespaces[&self.id].epoch
    }
    pub fn retired(&self) -> bool {
        lock(&self.shared).namespaces[&self.id].retired
    }
}
#[derive(Clone)]
struct NamespaceRecord {
    id: NamespaceId,
    attempt: [u8; 16],
    epoch: [u8; 16],
    revision: u64,
    ready: bool,
    retired: bool,
}
#[derive(Clone)]
struct Entry {
    snapshot: Snapshot,
    intent: Option<Intent>,
}
#[derive(Clone)]
enum Job {
    Namespace(NamespaceRecord),
    Key(Box<Entry>),
}
type NamespaceMap = BTreeMap<NamespaceId, NamespaceRecord>;
type EntryMap = BTreeMap<(NamespaceId, RequestKey), Entry>;
struct State {
    namespaces: NamespaceMap,
    entries: EntryMap,
    ordinary: VecDeque<Job>,
    control: VecDeque<Job>,
    pending: usize,
    fault: Option<Fault>,
    persistence_failed: bool,
}
struct Shared {
    state: Mutex<State>,
    limits: Limits,
    epoch: [u8; 16],
    authority: Arc<dyn Authority>,
}
fn lock(shared: &Shared) -> std::sync::MutexGuard<'_, State> {
    shared.state.lock().unwrap_or_else(|poison| {
        let mut s = poison.into_inner();
        s.fault = Some(Fault::Storage);
        s.persistence_failed = true;
        s
    })
}
fn enqueue(s: &mut State, limits: &Limits, job: Job, control: bool) -> bool {
    let maximum = limits.pending_jobs - if control { 0 } else { limits.closure_jobs };
    if s.pending >= maximum {
        return false;
    }
    if control {
        s.control.push_back(job);
    } else {
        s.ordinary.push_back(job);
    }
    s.pending += 1;
    true
}
impl Registry {
    /// Preparation only. Startup durably retires every old namespace and converts
    /// unfinished records to OUTCOME_UNKNOWN. Reusing a manager epoch is rejected.
    pub fn open(
        path: impl AsRef<Path>,
        epoch: [u8; 16],
        limits: Limits,
        authority: Arc<dyn Authority>,
    ) -> Result<(Self, Writer)> {
        if epoch == [0; 16]
            || limits.keys == 0
            || limits.keys > 65536
            || limits.cancellation_keys == 0
            || limits.cancellation_keys >= limits.keys
            || limits.namespaces == 0
            || limits.namespaces > 1024
            || limits.pending_jobs < 2
            || limits.pending_jobs > 4096
            || limits.closure_jobs == 0
            || limits.closure_jobs >= limits.pending_jobs
            || limits.max_payload_bytes == 0
            || limits.max_payload_bytes > 65536
            || limits.database_bytes < 262144
            || limits.database_bytes > 1_073_741_824
        {
            return Err(Error::Rejected("invalid finite registry limits/epoch"));
        }
        let (store, namespaces, entries) = store::Store::open(path.as_ref(), epoch, &limits)?;
        let shared = Arc::new(Shared {
            state: Mutex::new(State {
                namespaces,
                entries,
                ordinary: VecDeque::new(),
                control: VecDeque::new(),
                pending: 0,
                fault: None,
                persistence_failed: false,
            }),
            limits,
            epoch,
            authority,
        });
        Ok((
            Self {
                shared: shared.clone(),
            },
            Writer::new(shared, store),
        ))
    }
    /// Preparation queues namespace persistence; no operation may allocate before
    /// `namespace_ready` observes its durable publication.
    pub fn prepare_namespace(&self, attempt: [u8; 16], id: NamespaceId) -> Result<Namespace> {
        let mut s = lock(&self.shared);
        if attempt == [0; 16] || id == [0; 16] {
            return Err(Error::Rejected("zero namespace/attempt"));
        }
        if s.fault.is_some() {
            return Err(Error::Faulted);
        }
        if s.namespaces.contains_key(&id) {
            return Err(Error::Rejected("namespace cannot reopen"));
        }
        if s.namespaces.len() >= self.shared.limits.namespaces {
            return Err(Error::Capacity);
        }
        let ns = NamespaceRecord {
            id,
            attempt,
            epoch: self.shared.epoch,
            revision: 1,
            ready: false,
            retired: false,
        };
        if !enqueue(
            &mut s,
            &self.shared.limits,
            Job::Namespace(ns.clone()),
            false,
        ) {
            return Err(Error::Capacity);
        }
        s.namespaces.insert(id, ns);
        Ok(Namespace {
            shared: self.shared.clone(),
            id,
        })
    }
    pub fn lookup_namespace(&self, id: NamespaceId) -> Option<Namespace> {
        lock(&self.shared)
            .namespaces
            .contains_key(&id)
            .then(|| Namespace {
                shared: self.shared.clone(),
                id,
            })
    }
    pub fn namespace_ready(&self, namespace: &Namespace) -> bool {
        Arc::ptr_eq(&self.shared, &namespace.shared)
            && lock(&self.shared)
                .namespaces
                .get(&namespace.id)
                .is_some_and(|ns| ns.ready && !ns.retired && ns.epoch == self.shared.epoch)
    }
    pub fn query(&self, namespace: NamespaceId, key: RequestKey) -> Option<Snapshot> {
        lock(&self.shared)
            .entries
            .get(&(namespace, key))
            .map(|entry| entry.snapshot.clone())
    }
    pub fn query_operation(&self, operation: &OperationId) -> Option<Snapshot> {
        lock(&self.shared)
            .entries
            .values()
            .find(|entry| entry.snapshot.operation.as_ref() == Some(operation))
            .map(|entry| entry.snapshot.clone())
    }
    pub fn health(&self) -> Health {
        let s = lock(&self.shared);
        Health {
            admission_open: s.fault.is_none()
                && s.entries.len() < self.shared.limits.keys - self.shared.limits.cancellation_keys
                && s.pending < self.shared.limits.pending_jobs - self.shared.limits.closure_jobs,
            revoke_required: s.fault.is_some(),
            fault: s.fault,
            pending_jobs: s.pending,
            keys: s.entries.len(),
            namespaces: s.namespaces.len(),
            persistence_failed: s.persistence_failed,
        }
    }
    pub fn propose(
        &self,
        namespace: &Namespace,
        key: RequestKey,
        intent: Intent,
    ) -> Result<Snapshot> {
        if !Arc::ptr_eq(&self.shared, &namespace.shared) {
            return Err(Error::Rejected("foreign namespace handle"));
        }
        let mut s = lock(&self.shared);
        if let Some(entry) = s.entries.get(&(namespace.id, key)) {
            if entry.intent.as_ref().is_some_and(|old| old != &intent) {
                return Err(Error::Conflict);
            }
            return Ok(entry.snapshot.clone()); // lookup never allocates or resubmits
        }
        if s.fault.is_some() {
            return Err(Error::Faulted);
        }
        if !s
            .namespaces
            .get(&namespace.id)
            .is_some_and(|ns| ns.ready && !ns.retired && ns.epoch == self.shared.epoch)
        {
            return Err(Error::Rejected("namespace ineligible"));
        }
        if key == [0; 32]
            || intent.digest == [0; 32]
            || intent.configuration_digest == [0; 32]
            || intent.instance == 0
            || intent.grant == 0
            || intent.context_revision == 0
            || intent.deadline_ns == 0
            || intent.observation == 0
            || intent.payload.len() > self.shared.limits.max_payload_bytes
        {
            return Err(Error::Rejected("invalid bounded immutable intent"));
        }
        if s.entries.len() >= self.shared.limits.keys - self.shared.limits.cancellation_keys
            || s.pending >= self.shared.limits.pending_jobs - self.shared.limits.closure_jobs
        {
            return Err(Error::Capacity);
        }
        // Key/digest exists in a nondispatchable phase BEFORE the kernel allocates.
        let mut entry = Entry {
            snapshot: Snapshot {
                namespace: namespace.id,
                key,
                digest: Some(intent.digest),
                operation: None,
                revision: 1,
                durable_revision: 0,
                phase: Phase::PendingIntent,
                terminal: false,
                closure: Closure::NotRequested,
                persistence_failed: false,
                reconciliation_revision: None,
            },
            intent: Some(intent),
        };
        s.entries.insert((namespace.id, key), entry.clone());
        match self
            .shared
            .authority
            .allocate(entry.intent.as_ref().unwrap())
        {
            Ok(operation) => {
                let valid = operation.runtime_nonce == self.shared.epoch
                    && operation.device != [0; 16]
                    && operation.boot != 0
                    && operation.session != 0
                    && operation.operation != 0
                    && operation.stream != 0
                    && operation.grant == entry.intent.as_ref().unwrap().grant
                    && operation.instance == entry.intent.as_ref().unwrap().instance
                    && !s
                        .entries
                        .values()
                        .any(|other| other.snapshot.operation == Some(operation));
                entry.snapshot.operation = Some(operation);
                if !valid {
                    entry.snapshot.phase = Phase::OutcomeUnknown;
                    entry.snapshot.terminal = true;
                    entry.snapshot.closure = self.shared.authority.close(&operation).into();
                    s.fault = Some(Fault::AuthorityUnknown);
                }
            }
            Err(error) => {
                entry.snapshot.phase = if error == AuthorityError::Denied {
                    Phase::Rejected
                } else {
                    Phase::OutcomeUnknown
                };
                entry.snapshot.terminal = true;
                if error != AuthorityError::Denied {
                    s.fault = Some(Fault::AuthorityUnknown);
                }
            }
        }
        // The job slot was reserved before allocation; callbacks cannot reenter.
        assert!(enqueue(
            &mut s,
            &self.shared.limits,
            Job::Key(Box::new(entry.clone())),
            false
        ));
        s.entries.insert((namespace.id, key), entry.clone());
        Ok(entry.snapshot)
    }
    /// Sets the terminal fence and invokes urgent kernel close under the same
    /// ordering lock as submission. It NEVER touches/waits for storage.
    pub fn cancel(&self, namespace: &Namespace, key: RequestKey) -> Result<Snapshot> {
        if !Arc::ptr_eq(&self.shared, &namespace.shared) {
            return Err(Error::Rejected("foreign namespace handle"));
        }
        let mut s = lock(&self.shared);
        cancel_locked(&self.shared, &mut s, namespace.id, key)
    }
    pub fn cancel_operation(&self, operation: &OperationId) -> Result<Snapshot> {
        let mut s = lock(&self.shared);
        let (ns, key) = s
            .entries
            .iter()
            .find(|(_, e)| e.snapshot.operation.as_ref() == Some(operation))
            .map(|(id, _)| *id)
            .ok_or(Error::Rejected("unknown operation"))?;
        cancel_locked(&self.shared, &mut s, ns, key)
    }
    pub fn retire_namespace(&self, namespace: &Namespace) -> Result<()> {
        if !Arc::ptr_eq(&self.shared, &namespace.shared) {
            return Err(Error::Rejected("foreign namespace handle"));
        }
        let mut s = lock(&self.shared);
        retire_locked(&self.shared, &mut s, namespace.id);
        Ok(())
    }
    /// Records matched reconciliation without removing a cancellation fence.
    /// The trusted manager must first observe a matched, nonfaulted kernel
    /// reconciliation. This method neither contacts nor drives the authority.
    pub fn reconcile(
        &self,
        namespace: &Namespace,
        key: RequestKey,
        operation: &OperationId,
    ) -> Result<Snapshot> {
        if !Arc::ptr_eq(&self.shared, &namespace.shared) {
            return Err(Error::Rejected("foreign namespace handle"));
        }
        let mut s = lock(&self.shared);
        if s.fault.is_some() || s.persistence_failed {
            return Err(Error::Faulted);
        }
        let entry = s
            .entries
            .get_mut(&(namespace.id, key))
            .ok_or(Error::Rejected("absent key"))?;
        if entry.snapshot.operation.as_ref() != Some(operation) || entry.intent.is_none() {
            return Err(Error::Rejected("reconciliation identity mismatch"));
        }
        if entry.snapshot.phase == Phase::Completed
            || entry.snapshot.reconciliation_revision.is_some()
        {
            return Ok(entry.snapshot.clone());
        }
        let cancelled = matches!(
            entry.snapshot.phase,
            Phase::CancelPending | Phase::CancelledDurable
        );
        if !cancelled && entry.snapshot.phase != Phase::Submitted {
            return Err(Error::Rejected("operation not reconcilable"));
        }
        entry.snapshot.revision = entry
            .snapshot
            .revision
            .checked_add(1)
            .ok_or(Error::Faulted)?;
        entry.snapshot.terminal = true;
        if cancelled {
            entry.snapshot.reconciliation_revision = Some(entry.snapshot.revision);
        } else {
            entry.snapshot.phase = Phase::Completed;
        }
        let job = entry.clone();
        if !enqueue(&mut s, &self.shared.limits, Job::Key(Box::new(job)), true) {
            s.fault = Some(Fault::Queue);
            s.persistence_failed = true;
            s.entries
                .get_mut(&(namespace.id, key))
                .unwrap()
                .snapshot
                .persistence_failed = true;
        }
        Ok(s.entries[&(namespace.id, key)].snapshot.clone())
    }
    /// Records completion already established by the manager/kernel/controller.
    /// It neither dispatches, finishes nor reconciles an operation itself.
    pub fn complete(&self, namespace: &Namespace, key: RequestKey) -> Result<Snapshot> {
        if !Arc::ptr_eq(&self.shared, &namespace.shared) {
            return Err(Error::Rejected("foreign namespace handle"));
        }
        let mut s = lock(&self.shared);
        let entry = s
            .entries
            .get_mut(&(namespace.id, key))
            .ok_or(Error::Rejected("absent key"))?;
        if entry.snapshot.terminal {
            return Ok(entry.snapshot.clone());
        }
        if entry.snapshot.phase != Phase::Submitted {
            return Err(Error::Rejected("operation not submitted"));
        }
        entry.snapshot.revision = entry
            .snapshot
            .revision
            .checked_add(1)
            .ok_or(Error::Faulted)?;
        entry.snapshot.phase = Phase::Completed;
        entry.snapshot.terminal = true;
        let job = entry.clone();
        if !enqueue(
            &mut s,
            &self.shared.limits,
            Job::Key(Box::new(job.clone())),
            true,
        ) {
            s.fault = Some(Fault::Queue);
            s.persistence_failed = true;
            s.entries
                .get_mut(&(namespace.id, key))
                .unwrap()
                .snapshot
                .persistence_failed = true;
        }
        Ok(s.entries
            .get(&(namespace.id, key))
            .unwrap()
            .snapshot
            .clone())
    }
}
fn cancel_locked(
    shared: &Shared,
    s: &mut State,
    ns: NamespaceId,
    key: RequestKey,
) -> Result<Snapshot> {
    if key == [0; 32] || !s.namespaces.contains_key(&ns) {
        return Err(Error::Rejected("unknown namespace/zero key"));
    }
    if let Some(entry) = s.entries.get(&(ns, key)) {
        if matches!(
            entry.snapshot.phase,
            Phase::CancelPending | Phase::CancelledDurable | Phase::Completed
        ) {
            return Ok(entry.snapshot.clone());
        }
    } else if s.entries.len() >= shared.limits.keys {
        // No tombstone fence can be retained: retire namespace and close every
        // allocated operation before returning capacity failure; no delayed admit.
        s.fault = Some(Fault::Capacity);
        retire_locked(shared, s, ns);
        return Err(Error::Capacity);
    }
    let absent = !s.entries.contains_key(&(ns, key));
    let mut entry = s.entries.get(&(ns, key)).cloned().unwrap_or(Entry {
        snapshot: Snapshot {
            namespace: ns,
            key,
            digest: None,
            operation: None,
            revision: 0,
            durable_revision: 0,
            phase: Phase::CancelPending,
            terminal: true,
            closure: Closure::NotAllocated,
            persistence_failed: false,
            reconciliation_revision: None,
        },
        intent: None,
    });
    entry.snapshot.revision = entry
        .snapshot
        .revision
        .checked_add(1)
        .ok_or(Error::Faulted)?;
    entry.snapshot.phase = Phase::CancelPending;
    entry.snapshot.terminal = true;
    entry.snapshot.closure = entry
        .snapshot
        .operation
        .map_or(Closure::NotAllocated, |operation| {
            shared.authority.close(&operation).into()
        });
    if matches!(entry.snapshot.closure, Closure::Failed(_)) {
        s.fault = Some(Fault::AuthorityUnknown);
    }
    if !enqueue(s, &shared.limits, Job::Key(Box::new(entry.clone())), true) {
        entry.snapshot.persistence_failed = true;
        s.persistence_failed = true;
        s.fault = Some(Fault::Queue);
    }
    s.entries.insert((ns, key), entry.clone());
    if absent && entry.snapshot.persistence_failed {
        retire_locked(shared, s, ns);
    }
    Ok(s.entries.get(&(ns, key)).unwrap().snapshot.clone())
}
fn retire_locked(shared: &Shared, s: &mut State, id: NamespaceId) {
    let Some(ns) = s.namespaces.get_mut(&id) else {
        return;
    };
    if ns.retired {
        return;
    }
    ns.retired = true;
    ns.ready = false;
    let Some(revision) = ns.revision.checked_add(1) else {
        s.fault = Some(Fault::CounterExhausted);
        return;
    };
    ns.revision = revision;
    let job = ns.clone();
    let keys = s
        .entries
        .keys()
        .filter(|(ns, _)| *ns == id)
        .map(|(_, key)| *key)
        .collect::<Vec<_>>();
    for key in keys {
        let _ = cancel_locked(shared, s, id, key);
    }
    if !enqueue(s, &shared.limits, Job::Namespace(job), true) {
        s.persistence_failed = true;
        s.fault = Some(Fault::Queue);
    }
}
#[cfg(test)]
mod tests;
