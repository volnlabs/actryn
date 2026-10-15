//! Deterministic software reference only. This is neither production kernel authority
//! nor independent proof of its safety. Every transition takes an explicit clock.
use fixture_wire::{Frame, Kind, Status};

pub const MAX_DUTY: i32 = 200;
pub const MAX_OPERATION_NS: u64 = 10_000_000_000;
pub const MAX_SAMPLE_NS: u64 = 500_000_000;
pub const MAX_SLEW_CREDIT_NS: u64 = 100_000_000;
pub const SLEW_PER_SECOND: u64 = 1000;
pub const CONTEXT: u64 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum State {
    Inhibited,
    Ready,
    Active,
    Faulted,
}
pub trait Sink {
    fn update(&mut self, left: i32, right: i32, enabled: bool) -> Result<(), Status>;
}
#[derive(Default, Debug)]
pub struct SyntheticSink {
    pub left: i32,
    pub right: i32,
    pub enabled: bool,
    pub updates: u64,
    pub fail_next: bool,
}
impl Sink for SyntheticSink {
    fn update(&mut self, left: i32, right: i32, enabled: bool) -> Result<(), Status> {
        self.updates += 1;
        if std::mem::take(&mut self.fail_next) {
            return Err(Status::SinkUnknown);
        }
        self.left = left;
        self.right = right;
        self.enabled = enabled;
        Ok(())
    }
}
#[derive(Debug)]
pub struct Controller {
    pub state: State,
    pub device: [u8; 16],
    pub boot: u64,
    pub session: u64,
    nonce: [u8; 16],
    handshaken: bool,
    grant: u64,
    op_high: u64,
    stream_high: u64,
    tx_high: u64,
    active: Option<Frame>,
    started: Option<Frame>,
    sample: Option<(Frame, Frame)>,
    close: Option<(Frame, Frame)>,
    left: i32,
    right: i32,
    enabled: bool,
    applied_at: u64,
    now: u64,
    ticks: [i64; 2],
    fraction: [i128; 2],
    observation_sequence: u64,
}
impl Controller {
    pub fn new(device: [u8; 16], boot: u64, now: u64) -> Self {
        Self {
            state: State::Inhibited,
            device,
            boot,
            session: 0,
            nonce: [0; 16],
            handshaken: false,
            grant: 0,
            op_high: 0,
            stream_high: 0,
            tx_high: 0,
            active: None,
            started: None,
            sample: None,
            close: None,
            left: 0,
            right: 0,
            enabled: false,
            applied_at: now,
            now,
            ticks: [0; 2],
            fraction: [0; 2],
            observation_sequence: 0,
        }
    }
    pub fn duties(&self) -> (i32, i32, bool) {
        (self.left, self.right, self.enabled)
    }
    pub fn encoders(&self) -> [i64; 2] {
        self.ticks
    }
    fn response(&self, request: Frame, kind: Kind, status: Status, now: u64) -> Frame {
        Frame {
            kind,
            device: self.device,
            boot: self.boot,
            session: self.session,
            nonce: self.nonce,
            controller_ns: now,
            left: self.left,
            right: self.right,
            encoder_left: self.ticks[0],
            encoder_right: self.ticks[1],
            status,
            ..request
        }
    }
    fn fault(&mut self, request: Frame, status: Status, now: u64, sink: &mut impl Sink) -> Frame {
        let disabled = sink.update(0, 0, false).is_ok();
        self.state = State::Faulted;
        self.handshaken = false;
        self.active = None;
        self.sample = None;
        self.enabled = false;
        self.left = 0;
        self.right = 0;
        self.response(
            request,
            Kind::Fault,
            if disabled {
                status
            } else {
                Status::SinkUnknown
            },
            now,
        )
    }
    fn expiry(&self) -> Option<u64> {
        self.active.map(|op| {
            self.sample
                .map_or(op.expiry_ns, |(s, _)| s.expiry_ns.min(op.expiry_ns))
        })
    }
    /// Poll independently of transport progress; equality expires. Integration stops
    /// at the original expiry even if the caller polls late.
    pub fn poll(&mut self, now: u64, sink: &mut impl Sink) -> Option<Frame> {
        let request = self.active.unwrap_or_else(|| Frame::new(Kind::Fault));
        if now < self.now {
            return Some(self.fault(request, Status::Protocol, self.now, sink));
        }
        let end = self.expiry().map_or(now, |deadline| now.min(deadline));
        if self.enabled {
            for (i, duty) in [self.left, self.right].into_iter().enumerate() {
                let total = self.fraction[i] + duty as i128 * end.saturating_sub(self.now) as i128;
                let increment = total / 1_000_000_000;
                let Some(ticks) = (self.ticks[i] as i128)
                    .checked_add(increment)
                    .and_then(|v| i64::try_from(v).ok())
                else {
                    return Some(self.fault(request, Status::Limit, now, sink));
                };
                self.ticks[i] = ticks;
                self.fraction[i] = total % 1_000_000_000;
            }
        }
        self.now = now;
        if self.expiry().is_some_and(|deadline| now >= deadline) {
            return Some(self.fault(request, Status::Expired, now, sink));
        }
        None
    }
    fn epoch(&self, f: &Frame) -> bool {
        f.device == self.device
            && f.boot == self.boot
            && f.session == self.session
            && f.nonce == self.nonce
            && self.handshaken
    }
    fn canonical(f: &Frame) -> bool {
        f.controller_ns == 0
            && f.encoder_left == 0
            && f.encoder_right == 0
            && f.status == Status::Ok
            && match f.kind {
                Kind::Hello => {
                    f.device == [0; 16]
                        && f.boot == 0
                        && f.session == 0
                        && f.nonce != [0; 16]
                        && f.grant == 0
                        && f.operation == 0
                        && f.stream == 0
                        && f.sequence == 0
                        && f.transaction != 0
                        && f.expiry_ns == 0
                        && f.left == 0
                        && f.right == 0
                        && f.context == 0
                }
                Kind::Rearm => {
                    f.grant == 0
                        && f.operation == 0
                        && f.stream == 0
                        && f.sequence == 0
                        && f.transaction != 0
                        && f.expiry_ns == 0
                        && f.left == 0
                        && f.right == 0
                        && f.context == CONTEXT
                }
                Kind::Start => {
                    f.grant != 0
                        && f.operation != 0
                        && f.stream != 0
                        && f.sequence == 0
                        && f.transaction != 0
                        && f.expiry_ns != 0
                        && f.left == 0
                        && f.right == 0
                        && f.context == CONTEXT
                }
                Kind::Sample => {
                    f.grant != 0
                        && f.operation != 0
                        && f.stream != 0
                        && f.sequence != 0
                        && f.transaction != 0
                        && f.expiry_ns != 0
                        && f.context == CONTEXT
                }
                Kind::Quiesce => {
                    f.grant != 0
                        && f.operation != 0
                        && f.stream != 0
                        && f.sequence == 0
                        && f.transaction != 0
                        && f.expiry_ns == 0
                        && f.left == 0
                        && f.right == 0
                        && f.context == CONTEXT
                }
                _ => false,
            }
    }
    pub fn handle(&mut self, f: Frame, now: u64, sink: &mut impl Sink) -> Frame {
        if let Some(fault) = self.poll(now, sink) {
            return fault;
        }
        if !Self::canonical(&f) {
            return self.response(f, Kind::Fault, Status::Protocol, now);
        }
        if f.kind == Kind::Hello {
            if matches!(self.state, State::Active | State::Ready) {
                return self.response(f, Kind::Fault, Status::Busy, now);
            }
            let Some(session) = self.session.checked_add(1) else {
                return self.fault(f, Status::Persistence, now, sink);
            };
            self.session = session;
            self.nonce = f.nonce;
            self.handshaken = true;
            self.state = State::Inhibited;
            self.grant = 0;
            self.op_high = 0;
            self.stream_high = 0;
            self.tx_high = f.transaction;
            self.close = None;
            self.sample = None;
            self.observation_sequence = 0;
            return self.response(f, Kind::HelloAck, Status::Inhibited, now);
        }
        if !self.epoch(&f) {
            return self.response(f, Kind::Fault, Status::Stale, now);
        }
        if f.kind == Kind::Start && self.active == Some(f) {
            return self.started.unwrap();
        }
        if let Some((original, receipt)) = self.close {
            if f.kind == Kind::Quiesce && f == original {
                return receipt;
            }
        }
        if let Some((original, receipt)) = self.sample {
            if f.kind == Kind::Sample && f.sequence == original.sequence {
                return if f == original {
                    receipt
                } else {
                    self.response(f, Kind::Fault, Status::Protocol, now)
                };
            }
        }
        if f.transaction <= self.tx_high {
            return self.response(f, Kind::Fault, Status::Stale, now);
        }
        if f.kind == Kind::Rearm {
            if self.state != State::Inhibited {
                return self.response(f, Kind::Fault, Status::Inhibited, now);
            }
            if sink.update(0, 0, false).is_err() {
                return self.fault(f, Status::SinkUnknown, now, sink);
            }
            self.left = 0;
            self.right = 0;
            self.enabled = false;
            self.applied_at = now;
            self.state = State::Ready;
            self.tx_high = f.transaction;
            return self.response(f, Kind::Baseline, Status::Ok, now);
        }
        if matches!(self.state, State::Inhibited | State::Faulted) {
            return self.response(f, Kind::Fault, Status::Inhibited, now);
        }
        if f.grant < self.grant {
            return self.response(f, Kind::Fault, Status::Stale, now);
        }
        match f.kind {
            Kind::Start => {
                if self.state == State::Active {
                    return self.response(f, Kind::Fault, Status::Busy, now);
                }
                if f.operation <= self.op_high || f.stream <= self.stream_high {
                    return self.response(f, Kind::Fault, Status::Stale, now);
                }
                if f.expiry_ns <= now {
                    return self.fault(f, Status::Expired, now, sink);
                }
                if f.expiry_ns - now > MAX_OPERATION_NS {
                    return self.response(f, Kind::Fault, Status::Limit, now);
                }
                self.op_high = f.operation;
                self.stream_high = f.stream;
                self.grant = f.grant;
                self.tx_high = f.transaction;
                self.active = Some(f);
                self.sample = None;
                self.close = None;
                self.state = State::Active;
                let receipt = self.response(f, Kind::Started, Status::Ok, now);
                self.started = Some(receipt);
                receipt
            }
            Kind::Sample => {
                let Some(op) = self.active else {
                    return self.response(f, Kind::Fault, Status::Stale, now);
                };
                if f.operation != op.operation
                    || f.stream != op.stream
                    || f.grant != op.grant
                    || self
                        .sample
                        .is_some_and(|(old, _)| f.sequence <= old.sequence)
                {
                    return self.response(f, Kind::Fault, Status::Stale, now);
                }
                if f.expiry_ns <= now {
                    return self.fault(f, Status::Expired, now, sink);
                }
                if f.expiry_ns > op.expiry_ns || f.expiry_ns - now > MAX_SAMPLE_NS {
                    return self.response(f, Kind::Fault, Status::Limit, now);
                }
                let credit = now.saturating_sub(self.applied_at).min(MAX_SLEW_CREDIT_NS);
                let allowed = (credit as u128 * SLEW_PER_SECOND as u128 / 1_000_000_000) as i64;
                if [f.left, f.right]
                    .into_iter()
                    .any(|v| !(-MAX_DUTY..=MAX_DUTY).contains(&v))
                    || (f.left as i64 - self.left as i64).abs() > allowed
                    || (f.right as i64 - self.right as i64).abs() > allowed
                {
                    return self.response(f, Kind::Fault, Status::Limit, now);
                }
                if sink.update(f.left, f.right, true).is_err() {
                    return self.fault(f, Status::SinkUnknown, now, sink);
                }
                self.left = f.left;
                self.right = f.right;
                self.enabled = true;
                self.applied_at = now;
                self.tx_high = f.transaction;
                let receipt = self.response(f, Kind::SampleApplied, Status::Ok, now);
                self.sample = Some((f, receipt));
                receipt
            }
            Kind::Quiesce => {
                if let Some(op) = self.active {
                    if f.operation != op.operation || f.stream != op.stream || f.grant != op.grant {
                        return self.response(f, Kind::Fault, Status::Busy, now);
                    }
                } else if f.operation <= self.op_high || f.stream <= self.stream_high {
                    return self.response(f, Kind::Fault, Status::Stale, now);
                }
                if sink.update(0, 0, false).is_err() {
                    return self.fault(f, Status::SinkUnknown, now, sink);
                }
                self.op_high = f.operation;
                self.stream_high = f.stream;
                self.grant = f.grant;
                self.tx_high = f.transaction;
                self.active = None;
                self.sample = None;
                self.left = 0;
                self.right = 0;
                self.enabled = false;
                self.applied_at = now;
                self.state = State::Ready;
                let receipt = self.response(f, Kind::Quiesced, Status::Ok, now);
                self.close = Some((f, receipt));
                receipt
            }
            _ => self.response(f, Kind::Fault, Status::Protocol, now),
        }
    }
    pub fn observation(&mut self, now: u64, sink: &mut impl Sink) -> Frame {
        if let Some(fault) = self.poll(now, sink) {
            return fault;
        }
        let Some(sequence) = self.observation_sequence.checked_add(1) else {
            return self.fault(Frame::new(Kind::Observation), Status::Limit, now, sink);
        };
        self.observation_sequence = sequence;
        let mut f = self.active.unwrap_or_else(|| Frame::new(Kind::Observation));
        f.sequence = sequence;
        f.transaction = 0;
        f.expiry_ns = 0;
        f.context = CONTEXT;
        self.response(
            f,
            Kind::Observation,
            if matches!(self.state, State::Ready | State::Active) {
                Status::Ok
            } else {
                Status::Inhibited
            },
            now,
        )
    }
    pub fn transport_lost(&mut self, now: u64, sink: &mut impl Sink) -> Frame {
        self.poll(now, sink);
        self.fault(
            self.active.unwrap_or_else(|| Frame::new(Kind::Fault)),
            Status::Inhibited,
            now,
            sink,
        )
    }
}
