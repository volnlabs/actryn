use super::*;
use std::{
    sync::atomic::{AtomicBool, Ordering},
    thread,
    time::Duration,
};
pub struct Writer {
    shared: Arc<Shared>,
    pub(crate) store: store::Store,
    failed: bool,
    #[cfg(test)]
    pub(crate) after_persist: Option<Arc<std::sync::Barrier>>,
}
impl Writer {
    pub(crate) fn new(shared: Arc<Shared>, store: store::Store) -> Self {
        Self {
            shared,
            store,
            failed: false,
            #[cfg(test)]
            after_persist: None,
        }
    }
    /// One finite pass. All SQLite work occurs outside the registry ordering lock.
    pub fn flush(&mut self) -> Result<usize> {
        if self.failed {
            return Err(Error::Faulted);
        }
        let mut count = 0;
        for _ in 0..self.shared.limits.pending_jobs {
            let (job, parent) = {
                let mut s = lock(&self.shared);
                let Some(job) = s.control.pop_front().or_else(|| s.ordinary.pop_front()) else {
                    break;
                };
                let parent = match &job {
                    Job::Key(e) => s.namespaces.get(&e.snapshot.namespace).cloned(),
                    _ => None,
                };
                (job, parent)
            };
            let persisted = match self
                .store
                .persist(&job, parent.as_ref(), &self.shared.limits)
            {
                Ok(entry) => entry,
                Err(error) => {
                    self.fail();
                    return Err(error);
                }
            };
            #[cfg(test)]
            if let Some(barrier) = self.after_persist.take() {
                barrier.wait();
                barrier.wait();
            }
            let mut s = lock(&self.shared);
            let mut reused = false;
            match &job {
                Job::Namespace(ns) => {
                    if let Some(current) = s.namespaces.get_mut(&ns.id) {
                        if current.revision == ns.revision
                            && !current.retired
                            && current.epoch == self.shared.epoch
                        {
                            current.ready = true;
                        }
                    }
                }
                Job::Key(job_entry) => {
                    let durable =
                        persisted.ok_or(Error::Rejected("missing durable key after commit"))?;
                    let id = (job_entry.snapshot.namespace, job_entry.snapshot.key);
                    let ns_live = s
                        .namespaces
                        .get(&id.0)
                        .is_some_and(|ns| ns.ready && !ns.retired && ns.epoch == self.shared.epoch);
                    let healthy = s.fault.is_none();
                    if let Some(current) = s.entries.get_mut(&id) {
                        current.snapshot.durable_revision = current
                            .snapshot
                            .durable_revision
                            .max(durable.snapshot.durable_revision);
                        if durable.snapshot.terminal
                            && durable.snapshot.revision >= current.snapshot.revision
                        {
                            current.snapshot = durable.snapshot;
                        } else if current.snapshot.revision == job_entry.snapshot.revision
                            && !current.snapshot.terminal
                            && job_entry.snapshot.phase == Phase::PendingIntent
                            && durable.snapshot.revision == current.snapshot.revision
                        {
                            current.snapshot.phase = Phase::IntentDurable;
                            if ns_live && healthy {
                                let operation = current
                                    .snapshot
                                    .operation
                                    .ok_or(Error::Rejected("missing allocated operation"))?;
                                let submitted = self
                                    .shared
                                    .authority
                                    .submit(&operation, current.intent.as_ref().unwrap());
                                current.snapshot.revision = current
                                    .snapshot
                                    .revision
                                    .checked_add(1)
                                    .ok_or(Error::Faulted)?;
                                match submitted {
                                    Ok(()) => current.snapshot.phase = Phase::Submitted,
                                    Err(error) => {
                                        current.snapshot.phase = if error == AuthorityError::Denied
                                        {
                                            Phase::Rejected
                                        } else {
                                            Phase::OutcomeUnknown
                                        };
                                        current.snapshot.terminal = true;
                                        current.snapshot.closure =
                                            self.shared.authority.close(&operation).into();
                                    }
                                }
                                let next = current.clone();
                                if submitted.is_err_and(|e| e != AuthorityError::Denied)
                                    || matches!(next.snapshot.closure, Closure::Failed(_))
                                {
                                    s.fault = Some(Fault::AuthorityUnknown);
                                }
                                // Reuse the consumed job reservation for status persistence.
                                if next.snapshot.terminal {
                                    s.control.push_back(Job::Key(Box::new(next)));
                                } else {
                                    s.ordinary.push_back(Job::Key(Box::new(next)));
                                }
                                reused = true;
                            }
                        }
                    }
                }
            }
            if !reused {
                s.pending -= 1;
            }
            count += 1;
        }
        Ok(count)
    }
    fn fail(&mut self) {
        self.failed = true;
        let mut s = lock(&self.shared);
        s.fault = Some(Fault::Storage);
        s.persistence_failed = true;
        for entry in s.entries.values_mut() {
            if entry.snapshot.terminal && entry.snapshot.durable_revision >= entry.snapshot.revision
            {
                continue; // a later storage failure cannot erase an established terminal fact
            }
            entry.snapshot.persistence_failed = true;
            if let Some(operation) = entry.snapshot.operation {
                entry.snapshot.closure = self.shared.authority.close(&operation).into();
            }
            if !entry.snapshot.terminal {
                entry.snapshot.phase = Phase::OutcomeUnknown;
                entry.snapshot.terminal = true;
                entry.snapshot.revision = entry.snapshot.revision.saturating_add(1);
            }
        }
        for ns in s.namespaces.values_mut() {
            ns.ready = false;
            ns.retired = true;
        }
    }
    /// Caller-owned storage thread. Stopping/joining is not an urgent close path.
    pub fn run(mut self, stop: Arc<AtomicBool>, interval: Duration) -> Result<()> {
        if interval.is_zero() || interval > Duration::from_secs(1) {
            return Err(Error::Rejected("invalid writer polling interval"));
        }
        while !stop.load(Ordering::Acquire) {
            self.flush()?;
            thread::sleep(interval);
        }
        self.flush()?;
        Ok(())
    }
    #[cfg(test)]
    pub(crate) fn block_storage(&mut self, barrier: Arc<std::sync::Barrier>) {
        self.store.block = Some(barrier);
    }
    #[cfg(test)]
    pub(crate) fn inject_failure(&mut self) {
        self.store.fail = true;
    }
}
impl Drop for Writer {
    fn drop(&mut self) {
        let mut s = lock(&self.shared);
        if s.fault.is_none() {
            s.fault = Some(Fault::WriterStopped);
        }
    }
}
