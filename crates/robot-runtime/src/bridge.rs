use authority_client::{AuthorityDevice, Opcode, Request, Role, Status};
use robot_intent::{Authority, AuthorityError, CloseAck, Intent, OperationId};
use std::{
    io,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        RwLock,
    },
};
pub(crate) struct Bridge {
    pub admin: AuthorityDevice,
    pub runtime: RwLock<Option<AuthorityDevice>>,
    pub acquisition: RwLock<Option<AuthorityDevice>>,
    pub enabled: AtomicBool,
    pub session_deadline: AtomicU64,
}
fn classify(e: io::Error) -> AuthorityError {
    match e.raw_os_error() {
        Some(
            libc::EPERM
            | libc::EINVAL
            | libc::ESTALE
            | libc::EBUSY
            | libc::EEXIST
            | libc::EOVERFLOW,
        ) => AuthorityError::Denied,
        _ => AuthorityError::OutcomeUnknown,
    }
}
pub(crate) fn identity(s: &Status) -> OperationId {
    OperationId {
        device: s.device_identity,
        boot: s.controller_boot,
        session: s.controller_session,
        runtime_nonce: s.runtime_nonce,
        grant: s.grant,
        instance: s.instance,
        operation: s.operation,
        stream: s.stream,
    }
}
pub(crate) fn matches(s: &Status, id: &OperationId) -> bool {
    s.device_identity == id.device
        && s.controller_boot == id.boot
        && s.controller_session == id.session
        && s.runtime_nonce == id.runtime_nonce
        && s.grant == id.grant
        && s.operation == id.operation
        && s.stream == id.stream
}
impl Bridge {
    pub fn runtime_request(&self, r: &mut Request) -> io::Result<()> {
        self.runtime
            .read()
            .unwrap()
            .as_ref()
            .ok_or_else(|| io::Error::other("runtime retired"))?
            .request(r)
    }
    pub fn bind_runtime(&self) -> io::Result<()> {
        let runtime = AuthorityDevice::bind(Role::Runtime)?;
        let acquisition = AuthorityDevice::bind(Role::Acquisition)?;
        *self.runtime.write().unwrap() = Some(runtime);
        *self.acquisition.write().unwrap() = Some(acquisition);
        Ok(())
    }
    pub fn release_runtime(&self) {
        *self.acquisition.write().unwrap() = None;
        *self.runtime.write().unwrap() = None;
    }
    fn live(&self, intent: &Intent) -> Result<(), AuthorityError> {
        let now = authority_client::boottime_ns().map_err(classify)?;
        if !self.enabled.load(Ordering::Acquire)
            || now >= self.session_deadline.load(Ordering::Acquire)
            || now >= intent.deadline_ns
        {
            return Err(AuthorityError::Denied);
        }
        Ok(())
    }
    pub fn revoke(&self) -> io::Result<()> {
        self.enabled.store(false, Ordering::Release);
        let s = self.admin.status()?;
        if s.flags & 8 == 0 {
            return Ok(());
        }
        let mut r = Request::new(Opcode::Revoke);
        r.runtime_nonce = s.runtime_nonce;
        r.grant = s.grant;
        self.admin.request(&mut r)
    }
}
fn intent_request(op: Opcode, intent: &Intent, nonce: [u8; 16]) -> Request {
    let mut r = Request::new(op);
    r.runtime_nonce = nonce;
    r.grant = intent.grant;
    r.instance = intent.instance;
    r.deadline_ns = intent.deadline_ns;
    r.observation = intent.observation;
    r.context_revision = intent.context_revision;
    r.digest = intent.digest;
    r
}
impl Authority for Bridge {
    fn allocate(&self, intent: &Intent) -> Result<OperationId, AuthorityError> {
        self.live(intent)?;
        let s = self.admin.status().map_err(classify)?;
        let mut r = intent_request(Opcode::Allocate, intent, s.runtime_nonce);
        self.runtime_request(&mut r).map_err(classify)?;
        let after = self.admin.status().map_err(classify)?;
        let id = identity(&after);
        if id.operation != r.operation
            || id.stream != r.stream
            || id.runtime_nonce != r.runtime_nonce
        {
            let _ = self.revoke();
            return Err(AuthorityError::OutcomeUnknown);
        }
        Ok(id)
    }
    fn submit(&self, id: &OperationId, intent: &Intent) -> Result<(), AuthorityError> {
        self.live(intent)?;
        let mut r = intent_request(Opcode::Start, intent, id.runtime_nonce);
        r.operation = id.operation;
        r.stream = id.stream;
        self.runtime_request(&mut r).map_err(classify)
    }
    fn close(&self, id: &OperationId) -> Result<CloseAck, AuthorityError> {
        let s = self.admin.status().map_err(classify)?;
        if !matches(&s, id) {
            return Err(AuthorityError::Denied);
        }
        let mut r = Request::operation_identity(Opcode::Cancel, &s);
        self.admin.request(&mut r).map_err(classify)?;
        Ok(CloseAck::LocallyClosed {
            transition: self.admin.status().map_err(classify)?.transaction,
        })
    }
}
