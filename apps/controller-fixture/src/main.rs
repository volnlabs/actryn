//! Native non-actuating peer for QEMU `-chardev socket,...,server=off`.
mod persistence;
use actryn_core::{Controller, State, SyntheticSink};
use fixture_wire::{Frame, Kind, Parser, ENCODED_LEN};
use persistence::PersistentState;
use std::{
    collections::VecDeque,
    env, fs,
    io::{self, Read, Write},
    os::unix::{
        fs::PermissionsExt,
        net::{UnixDatagram, UnixListener, UnixStream},
    },
    path::PathBuf,
    thread,
    time::{Duration, Instant},
};
const MAX_QUEUE: usize = 32;
const MAX_DELAY_NS: u64 = 2_000_000_000;
const FRAME_TIMEOUT_NS: u64 = 500_000_000;
struct Pending {
    bytes: [u8; ENCODED_LEN],
    offset: usize,
    at: u64,
    sync: bool,
}
impl Pending {
    fn write_to(&mut self, output: &mut impl Write) -> io::Result<bool> {
        let bytes = if self.sync {
            &[0][..]
        } else {
            &self.bytes[self.offset..]
        };
        let n = output.write(bytes)?;
        if n == 0 {
            return Err(io::ErrorKind::WriteZero.into());
        }
        if self.sync {
            self.sync = false;
        } else {
            self.offset += n;
        }
        Ok(self.offset == ENCODED_LEN)
    }
}
fn retire_output(queue: &mut VecDeque<Pending>, now: u64) {
    queue.clear();
    // A reset may abandon an already-written prefix. End it explicitly before
    // any new receipt; this byte is framing, not a delayed/droppable receipt.
    queue.push_back(Pending {
        bytes: [0; ENCODED_LEN],
        offset: ENCODED_LEN,
        at: now,
        sync: true,
    });
}
#[derive(Default)]
struct FaultControls {
    delay: u64,
    drop: usize,
    pause_rx_until: u64,
    last: Option<[u8; ENCODED_LEN]>,
}
fn enqueue(
    queue: &mut VecDeque<Pending>,
    f: Frame,
    now: u64,
    controls: &mut FaultControls,
) -> bool {
    let bytes = f.encode();
    if f.kind != Kind::Observation {
        controls.last = Some(bytes);
    }
    if f.kind != Kind::Observation && controls.drop > 0 {
        controls.drop -= 1;
        return true;
    }
    if queue.len() == MAX_QUEUE {
        return false;
    }
    queue.push_back(Pending {
        bytes,
        offset: 0,
        at: now.saturating_add(controls.delay),
        sync: f.kind == Kind::HelloAck,
    });
    true
}
fn main() {
    if let Err(e) = run() {
        eprintln!("controller-fixture inhibited: {e}");
        std::process::exit(1);
    }
}
fn argument_paths() -> io::Result<(PathBuf, PathBuf, PathBuf)> {
    let mut args = env::args().skip(1);
    let (mut socket, mut state, mut admin) = (None, None, None);
    while let Some(arg) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| io::Error::other("expected flag value"))?;
        let slot = match arg.as_str() {
            "--socket" => &mut socket,
            "--state" => &mut state,
            "--admin" => &mut admin,
            _ => {
                return Err(io::Error::other(
                    "usage: controller-fixture --socket PATH --state PATH --admin PATH",
                ))
            }
        };
        if slot.replace(PathBuf::from(value)).is_some() {
            return Err(io::Error::other("duplicate flag"));
        }
    }
    let result = (
        socket.ok_or_else(|| io::Error::other("missing --socket"))?,
        state.ok_or_else(|| io::Error::other("missing --state"))?,
        admin.ok_or_else(|| io::Error::other("missing --admin"))?,
    );
    if result.0 == result.1 || result.0 == result.2 || result.1 == result.2 {
        return Err(io::Error::other("paths must differ"));
    }
    Ok(result)
}
struct SocketPaths(Vec<PathBuf>);
impl Drop for SocketPaths {
    fn drop(&mut self) {
        for path in &self.0 {
            let _ = fs::remove_file(path);
        }
    }
}
fn bounded_number(text: Option<&str>, max: u64) -> Option<u64> {
    text?.parse().ok().filter(|n| *n <= max)
}
fn run() -> io::Result<()> {
    let (socket_path, state_path, admin_path) = argument_paths()?;
    let mut persistent = PersistentState::open(&state_path)?;
    // Never unlink an existing socket: it may belong to a running process.
    let listener = UnixListener::bind(&socket_path)?;
    let mut paths = SocketPaths(vec![socket_path.clone()]);
    fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600))?;
    listener.set_nonblocking(true)?;
    let admin = UnixDatagram::bind(&admin_path)?;
    paths.0.push(admin_path.clone());
    fs::set_permissions(&admin_path, fs::Permissions::from_mode(0o600))?;
    admin.set_nonblocking(true)?;
    let clock = Instant::now();
    let mut controller = Controller::new(persistent.device, persistent.boot, 0);
    let mut sink = SyntheticSink::default();
    let mut connection: Option<UnixStream> = None;
    let mut parser = Parser::default();
    let mut queue = VecDeque::with_capacity(MAX_QUEUE);
    let mut controls = FaultControls::default();
    let mut next_observation = 0;
    let mut partial_since: Option<u64> = None;
    eprintln!(
        "software fixture listening {}; boot {}; simulated encoder data only",
        socket_path.display(),
        persistent.boot
    );
    loop {
        let now = u64::try_from(clock.elapsed().as_nanos())
            .map_err(|_| io::Error::other("clock exhausted"))?;
        let mut disconnect = false;
        if partial_since.is_some_and(|start| now.saturating_sub(start) >= FRAME_TIMEOUT_NS) {
            parser.discard_until_delimiter();
            partial_since = None;
        }
        if let Some(fault) = controller.poll(now, &mut sink) {
            if connection.is_some() && !enqueue(&mut queue, fault, now, &mut controls) {
                disconnect = true;
            }
        }
        let mut command = [0u8; 128];
        match admin.recv_from(&mut command) {
            Ok((n, peer)) => {
                let command = if n == command.len() {
                    ""
                } else {
                    std::str::from_utf8(&command[..n]).unwrap_or("").trim()
                };
                let words: Vec<_> = command.split_whitespace().take(3).collect();
                let mut accepted = true;
                let mut status = None;
                match words.as_slice() {
                    ["delay", value] => {
                        if let Some(n) = bounded_number(Some(value), MAX_DELAY_NS) {
                            controls.delay = n;
                        } else { accepted = false; }
                    }
                    ["drop", value] => {
                        if let Some(n) = bounded_number(Some(value), MAX_QUEUE as u64) {
                            controls.drop = n as usize;
                        } else { accepted = false; }
                    }
                    ["pause-rx", value] => {
                        if let Some(n) = bounded_number(Some(value), MAX_DELAY_NS) {
                            controls.pause_rx_until = now.saturating_add(n);
                        } else { accepted = false; }
                    }
                    ["sink-fail"] => sink.fail_next = true,
                    ["restart"] => {
                        controller.transport_lost(now, &mut sink);
                        retire_output(&mut queue, now);
                        parser = Parser::default();
                        partial_since = None;
                        let boot = persistent.advance()?;
                        controller = Controller::new(persistent.device, boot, now);
                        controls.last = None;
                    }
                    ["replay"] => {
                        if let Some(bytes) = controls.last {
                            if queue.len() < MAX_QUEUE {
                                queue.push_back(Pending {bytes, offset: 0, at: now, sync: false});
                            } else { accepted = false; }
                        } else { accepted = false; }
                    }
                    ["status"] => status = Some(format!(
                        "state={:?} boot={} session={} duties={:?} encoders={:?} queued={} now_ns={}\n",
                        controller.state, controller.boot, controller.session, controller.duties(),
                        controller.encoders(), queue.len(), now)),
                    ["shutdown"] => {
                        controller.transport_lost(now, &mut sink);
                        return Ok(());
                    }
                    _ => accepted = false,
                }
                if let Some(path) = peer.as_pathname() {
                    let _ = admin.send_to(
                        status
                            .as_deref()
                            .unwrap_or(if accepted { "OK\n" } else { "ERROR\n" })
                            .as_bytes(),
                        path,
                    );
                }
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {}
            Err(e) => return Err(e),
        }
        match listener.accept() {
            Ok((stream, _)) => {
                if connection.is_none() {
                    stream.set_nonblocking(true)?;
                    connection = Some(stream);
                    parser = Parser::default();
                    partial_since = None;
                    next_observation = now.saturating_add(100_000_000);
                }
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {}
            Err(e) => return Err(e),
        }
        if let Some(stream) = connection.as_mut() {
            if now >= controls.pause_rx_until {
                let mut bytes = [0u8; 512];
                match stream.read(&mut bytes) {
                    Ok(0) => disconnect = true,
                    Ok(n) => {
                        for &byte in &bytes[..n] {
                            if byte == 0 {
                                partial_since = None;
                            } else if partial_since.is_none() {
                                partial_since = Some(now);
                            }
                            if let Some(Ok(frame)) = parser.push(byte) {
                                let reply = controller.handle(frame, now, &mut sink);
                                if !enqueue(&mut queue, reply, now, &mut controls) {
                                    disconnect = true;
                                    break;
                                }
                            }
                        }
                    }
                    Err(e) if e.kind() == io::ErrorKind::WouldBlock => {}
                    Err(_) => disconnect = true,
                }
            }
            if now >= next_observation && matches!(controller.state, State::Ready | State::Active) {
                let observation = controller.observation(now, &mut sink);
                if !enqueue(&mut queue, observation, now, &mut controls) {
                    disconnect = true;
                }
                next_observation = now.saturating_add(100_000_000);
            }
            if let Some(pending) = queue.front_mut() {
                if now >= pending.at {
                    match pending.write_to(stream) {
                        Ok(true) => {
                            queue.pop_front();
                        }
                        Ok(false) => {}
                        Err(e) if e.kind() == io::ErrorKind::WouldBlock => {}
                        Err(_) => disconnect = true,
                    }
                }
            }
        }
        if disconnect {
            controller.transport_lost(now, &mut sink);
            connection = None;
            parser = Parser::default();
            partial_since = None;
            queue.clear();
        }
        thread::sleep(Duration::from_millis(1));
    }
}

#[cfg(test)]
mod framing_tests {
    use super::*;
    struct ShortWriter {
        bytes: Vec<u8>,
        limit: usize,
        block: bool,
    }
    impl Write for ShortWriter {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if self.block {
                self.block = false;
                return Err(io::ErrorKind::WouldBlock.into());
            }
            let n = bytes.len().min(self.limit);
            self.bytes.extend_from_slice(&bytes[..n]);
            Ok(n)
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    #[test]
    fn restart_terminates_every_abandoned_prefix_before_fresh_ack() {
        let mut hello = Frame::new(Kind::HelloAck);
        hello.nonce = [8; 16];
        for cut in 1..ENCODED_LEN {
            let mut queue = VecDeque::new();
            let mut controls = FaultControls::default();
            let old = Frame::new(Kind::Observation).encode();
            let mut output = ShortWriter {
                bytes: vec![],
                limit: cut,
                block: false,
            };
            let mut pending = Pending {
                bytes: old,
                offset: 0,
                at: 0,
                sync: false,
            };
            assert!(!pending.write_to(&mut output).unwrap());
            assert_eq!(output.bytes.len(), cut);
            queue.push_back(pending);
            retire_output(&mut queue, 4);
            assert_eq!(queue.len(), 1);
            assert!(enqueue(&mut queue, hello, 4, &mut controls));
            output.limit = 3;
            output.block = true;
            assert_eq!(
                queue
                    .front_mut()
                    .unwrap()
                    .write_to(&mut output)
                    .unwrap_err()
                    .kind(),
                io::ErrorKind::WouldBlock
            );
            assert!(queue.front().unwrap().sync);
            while let Some(front) = queue.front_mut() {
                if front.write_to(&mut output).unwrap() {
                    queue.pop_front();
                }
            }
            assert_eq!(
                &output.bytes[cut..],
                [&[0, 0][..], &hello.encode()].concat()
            );
            let mut parser = Parser::default();
            let decoded: Vec<_> = output
                .bytes
                .into_iter()
                .filter_map(|b| parser.push(b))
                .filter_map(Result::ok)
                .collect();
            assert_eq!(decoded.last(), Some(&hello));
            if cut == ENCODED_LEN - 1 {
                // All old payload bytes were already sent: the reset delimiter
                // can finish that old frame, whose identity stays old.
                assert_eq!(decoded, vec![Frame::new(Kind::Observation), hello]);
            } else {
                assert_eq!(decoded, vec![hello]);
            }
        }
    }
}
