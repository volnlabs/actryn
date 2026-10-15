use anyhow::{ensure, Context, Result};
use std::sync::Mutex;
/// The callback must be bounded and nonblocking; close never waits for storage/provider work.
#[derive(Default)]
pub struct PublicationGate {
    closed: Mutex<bool>,
}
impl PublicationGate {
    pub fn close(&self) -> bool {
        let mut closed = self.closed.lock().unwrap_or_else(|p| p.into_inner());
        let first = !*closed;
        *closed = true;
        first
    }
    pub fn publish<T>(&self, f: impl FnOnce() -> T) -> Result<T> {
        let closed = self
            .closed
            .lock()
            .map_err(|_| anyhow::anyhow!("publication gate poisoned"))?;
        ensure!(!*closed, "publication context closed");
        Ok(f())
    }
}
pub struct BoundedOutput {
    data: Vec<u8>,
    limit: usize,
    overflow: bool,
}
impl BoundedOutput {
    pub fn new(limit: usize) -> Result<Self> {
        ensure!(limit > 0 && limit <= 65536, "invalid response bound");
        Ok(Self {
            data: Vec::new(),
            limit,
            overflow: false,
        })
    }
    pub fn push(&mut self, bytes: &[u8]) -> Result<()> {
        if self.overflow
            || self
                .data
                .len()
                .checked_add(bytes.len())
                .context("response size overflow")?
                > self.limit
        {
            self.overflow = true;
            self.data.clear();
            anyhow::bail!("response limit exceeded");
        }
        self.data.extend_from_slice(bytes);
        Ok(())
    }
    pub fn finish(self) -> Result<Vec<u8>> {
        ensure!(!self.overflow, "response discarded after overflow");
        Ok(self.data)
    }
}
