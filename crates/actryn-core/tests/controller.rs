use actryn_core::{Controller, State, SyntheticSink};
use fixture_wire::{Frame, Kind, Status};
const MS: u64 = 1_000_000;
fn setup() -> (Controller, SyntheticSink, Frame) {
    let mut c = Controller::new(*b"SIM-ACTRYN-00001", 1, 0);
    let mut sink = SyntheticSink::default();
    let mut hello = Frame::new(Kind::Hello);
    hello.nonce = [9; 16];
    hello.transaction = 1;
    let ack = c.handle(hello, 0, &mut sink);
    assert_eq!((ack.kind, ack.session), (Kind::HelloAck, 1));
    let mut command = Frame::new(Kind::Rearm);
    command.device = ack.device;
    command.boot = ack.boot;
    command.session = ack.session;
    command.nonce = ack.nonce;
    command.transaction = 2;
    command.context = 1;
    assert_eq!(c.handle(command, 0, &mut sink).kind, Kind::Baseline);
    command.kind = Kind::Start;
    command.grant = 1;
    command.operation = 1;
    command.stream = 1;
    command.transaction = 3;
    command.expiry_ns = 1000 * MS;
    (c, sink, command)
}
fn sample(mut op: Frame) -> Frame {
    op.kind = Kind::Sample;
    op.sequence = 1;
    op.transaction = 4;
    op.left = 100;
    op.right = -100;
    op.expiry_ns = 500 * MS;
    op
}
fn close(mut op: Frame, tx: u64) -> Frame {
    op.kind = Kind::Quiesce;
    op.sequence = 0;
    op.transaction = tx;
    op.expiry_ns = 0;
    op
}
#[test]
fn exact_started_duplicate_keeps_original_time() {
    let (mut c, mut sink, op) = setup();
    let first = c.handle(op, 10 * MS, &mut sink);
    assert_eq!(first.kind, Kind::Started);
    assert_eq!(c.handle(op, 20 * MS, &mut sink), first);
}
#[test]
fn applied_duplicate_is_not_reapplied_or_renewed() {
    let (mut c, mut sink, op) = setup();
    c.handle(op, 0, &mut sink);
    let s = sample(op);
    let receipt = c.handle(s, 100 * MS, &mut sink);
    assert_eq!(receipt.kind, Kind::SampleApplied);
    assert_eq!(sink.updates, 2);
    assert_eq!(c.handle(s, 200 * MS, &mut sink), receipt);
    assert_eq!(sink.updates, 2);
    let mut changed = s;
    changed.right = 0;
    assert_eq!(
        c.handle(changed, 200 * MS, &mut sink).status,
        Status::Protocol
    );
    assert_eq!(c.poll(500 * MS, &mut sink).unwrap().status, Status::Expired);
    assert_eq!(c.encoders(), [40, -40]);
    assert_eq!(c.duties(), (0, 0, false));
    assert_eq!(c.state, State::Faulted);
    assert_ne!(c.handle(s, 501 * MS, &mut sink).kind, Kind::SampleApplied);
}
#[test]
fn finish_cancel_and_retire_before_start() {
    let (mut c, mut sink, mut op) = setup();
    let q = close(op, 4);
    let closed = c.handle(q, 0, &mut sink);
    assert_eq!(closed.kind, Kind::Quiesced);
    assert_eq!(c.handle(q, MS, &mut sink), closed);
    assert_eq!(c.handle(op, MS, &mut sink).status, Status::Stale);
    for id in 2..=3 {
        op.operation = id;
        op.stream = id;
        op.transaction = id * 3;
        op.expiry_ns = 1000 * MS;
        assert_eq!(c.handle(op, id * 100 * MS, &mut sink).kind, Kind::Started);
        assert_eq!(
            c.handle(close(op, id * 3 + 1), id * 100 * MS + 50 * MS, &mut sink)
                .kind,
            Kind::Quiesced
        );
        assert_eq!(c.state, State::Ready);
    }
}
#[test]
fn envelope_deadline_epoch_and_unknown_sink() {
    let (mut c, mut sink, op) = setup();
    c.handle(op, 0, &mut sink);
    let mut s = sample(op);
    s.left = i32::MIN;
    assert_eq!(c.handle(s, 100 * MS, &mut sink).status, Status::Limit);
    s = sample(op);
    assert_eq!(c.handle(s, 99 * MS, &mut sink).status, Status::Protocol); // clock regressed
    assert_eq!(c.state, State::Faulted);
    let (mut c, mut sink, op) = setup();
    c.handle(op, 0, &mut sink);
    s = sample(op);
    s.left = 101;
    assert_eq!(c.handle(s, 100 * MS, &mut sink).status, Status::Limit);
    s = sample(op);
    s.expiry_ns = 100 * MS;
    assert_eq!(c.handle(s, 100 * MS, &mut sink).status, Status::Expired);
    s = sample(op);
    s.boot += 1;
    assert_eq!(c.handle(s, 100 * MS, &mut sink).status, Status::Stale);
    s = sample(op);
    s.encoder_left = 1;
    assert_eq!(c.handle(s, 100 * MS, &mut sink).status, Status::Protocol);
    assert_eq!(c.state, State::Faulted);
    let (mut c, mut sink, op) = setup();
    c.handle(op, 0, &mut sink);
    sink.fail_next = true;
    let failure = c.handle(sample(op), 100 * MS, &mut sink);
    assert_eq!(
        (failure.kind, failure.status),
        (Kind::Fault, Status::SinkUnknown)
    );
    assert_eq!(c.state, State::Faulted);
    assert_ne!(c.handle(op, 200 * MS, &mut sink).kind, Kind::Started);
}
#[test]
fn host_loss_and_restart_require_fresh_handshake_rearm() {
    let (mut c, mut sink, op) = setup();
    c.handle(op, 0, &mut sink);
    c.handle(sample(op), 100 * MS, &mut sink);
    c.transport_lost(200 * MS, &mut sink);
    assert_eq!(c.duties(), (0, 0, false));
    let mut restarted = Controller::new(c.device, 2, 0);
    assert_ne!(
        restarted.handle(sample(op), 100 * MS, &mut sink).kind,
        Kind::SampleApplied
    );
    let mut h = Frame::new(Kind::Hello);
    h.nonce = [9; 16];
    h.transaction = 1;
    let ack = c.handle(h, 200 * MS, &mut sink);
    assert_eq!(ack.session, 2);
    assert_eq!(c.handle(op, 201 * MS, &mut sink).status, Status::Stale);
}
#[test]
fn operation_expiry_and_quiesce_must_match_complete_identity() {
    let (mut c, mut sink, op) = setup();
    c.handle(op, 0, &mut sink);
    let mut q = close(op, 5);
    q.operation = 2;
    assert_eq!(c.handle(q, MS, &mut sink).status, Status::Busy);
    assert_eq!(c.state, State::Active);
    assert_eq!(
        c.poll(1000 * MS, &mut sink).unwrap().status,
        Status::Expired
    );
    assert_eq!(c.state, State::Faulted);
}

#[test]
fn finite_horizons_slew_credit_and_counter_exhaustion() {
    let (mut c, mut sink, mut op) = setup();
    op.expiry_ns = 2_000 * MS;
    assert_eq!(c.handle(op, 0, &mut sink).kind, Kind::Started);
    let mut s = sample(op);
    s.left = 200;
    s.expiry_ns = 1200 * MS;
    assert_eq!(c.handle(s, 1000 * MS, &mut sink).status, Status::Limit);
    s.left = 100;
    s.right = 100;
    s.expiry_ns = 1501 * MS;
    assert_eq!(c.handle(s, 1000 * MS, &mut sink).status, Status::Limit);
    s.expiry_ns = 1500 * MS;
    s.sequence = u64::MAX;
    assert_eq!(c.handle(s, 1000 * MS, &mut sink).kind, Kind::SampleApplied);
    s.sequence = 1;
    s.transaction = 5;
    assert_eq!(c.handle(s, 1100 * MS, &mut sink).status, Status::Stale);
    s.sequence = 0;
    assert_eq!(c.handle(s, 1100 * MS, &mut sink).status, Status::Protocol);
    let first = c.observation(1100 * MS, &mut sink);
    let second = c.observation(1100 * MS, &mut sink);
    assert_eq!(second.sequence, first.sequence + 1);
    assert_eq!(second.context, 1);
    c.transport_lost(1100 * MS, &mut sink);
    c.session = u64::MAX;
    let mut h = Frame::new(Kind::Hello);
    h.nonce = [1; 16];
    h.transaction = 1;
    assert_eq!(
        c.handle(h, 1100 * MS, &mut sink).status,
        Status::Persistence
    );
    assert_eq!(c.session, u64::MAX);
    assert_eq!(c.state, State::Faulted);
}

#[test]
fn disabled_ready_accepts_fresh_hello_but_retires_old_commands() {
    let (mut c, mut sink, old_start) = setup();
    let old_sample = sample(old_start);
    let mut hello = Frame::new(Kind::Hello);
    hello.nonce = [8; 16];
    hello.transaction = 1;
    let before = sink.updates;
    let ack = c.handle(hello, MS, &mut sink);
    assert_eq!(
        (ack.kind, ack.status, ack.session, ack.nonce),
        (Kind::HelloAck, Status::Inhibited, 2, [8; 16])
    );
    assert_eq!(
        sink.updates,
        before + 1,
        "READY must confirm disabled-zero through its sink"
    );
    assert_eq!(c.state, State::Inhibited);
    assert_eq!(c.duties(), (0, 0, false));
    assert_eq!(c.handle(old_start, 2 * MS, &mut sink).status, Status::Stale);
    assert_eq!(
        c.handle(old_sample, 2 * MS, &mut sink).status,
        Status::Stale
    );
    let mut fresh_start = old_start;
    fresh_start.session = ack.session;
    fresh_start.nonce = ack.nonce;
    assert_eq!(
        c.handle(fresh_start, 3 * MS, &mut sink).status,
        Status::Inhibited
    );
    let mut rearm = Frame::new(Kind::Rearm);
    rearm.device = ack.device;
    rearm.boot = ack.boot;
    rearm.session = ack.session;
    rearm.nonce = ack.nonce;
    rearm.transaction = 2;
    rearm.context = 1;
    assert_eq!(c.handle(rearm, 4 * MS, &mut sink).kind, Kind::Baseline);
    assert_eq!(c.handle(old_start, 5 * MS, &mut sink).status, Status::Stale);
    assert_eq!(
        c.handle(old_sample, 5 * MS, &mut sink).status,
        Status::Stale
    );
    assert_eq!(c.handle(fresh_start, 5 * MS, &mut sink).kind, Kind::Started);
}

#[test]
fn ready_hello_sink_failure_is_unknown_and_cannot_publish_a_session() {
    let (mut c, mut sink, old_start) = setup();
    let mut hello = Frame::new(Kind::Hello);
    hello.nonce = [8; 16];
    hello.transaction = 1;
    sink.fail_next = true;
    let result = c.handle(hello, MS, &mut sink);
    assert_eq!(
        (result.kind, result.status),
        (Kind::Fault, Status::SinkUnknown)
    );
    assert_eq!(c.session, old_start.session);
    assert_eq!(c.state, State::Faulted);
    assert_ne!(c.handle(old_start, 2 * MS, &mut sink).kind, Kind::Started);
}

#[test]
fn hello_cannot_replace_an_active_session_even_before_first_output() {
    let (mut c, mut sink, old_start) = setup();
    assert_eq!(c.handle(old_start, 0, &mut sink).kind, Kind::Started);
    let before = sink.updates;
    let mut hello = Frame::new(Kind::Hello);
    hello.nonce = [8; 16];
    hello.transaction = 1;
    assert_eq!(c.handle(hello, MS, &mut sink).status, Status::Busy);
    assert_eq!(c.session, old_start.session);
    assert_eq!(c.state, State::Active);
    assert_eq!(sink.updates, before);
    assert_eq!(
        c.handle(sample(old_start), 100 * MS, &mut sink).kind,
        Kind::SampleApplied
    );
    assert_eq!(c.handle(hello, 101 * MS, &mut sink).status, Status::Busy);
    assert_eq!(c.duties(), (100, -100, true));
}

#[test]
fn quiesced_ready_can_retire_session_without_replaying_old_receipts() {
    let (mut c, mut sink, op) = setup();
    c.handle(op, 0, &mut sink);
    let applied = sample(op);
    c.handle(applied, 100 * MS, &mut sink);
    let quiesce = close(op, 5);
    assert_eq!(c.handle(quiesce, 200 * MS, &mut sink).kind, Kind::Quiesced);
    assert_eq!(c.state, State::Ready);
    let mut hello = Frame::new(Kind::Hello);
    hello.nonce = [8; 16];
    hello.transaction = 1;
    assert_eq!(c.handle(hello, 201 * MS, &mut sink).kind, Kind::HelloAck);
    for old in [op, applied, quiesce] {
        assert_eq!(c.handle(old, 202 * MS, &mut sink).status, Status::Stale);
    }
    assert_eq!(c.state, State::Inhibited);
    assert_eq!(c.duties(), (0, 0, false));
}
