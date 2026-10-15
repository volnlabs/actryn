use actryn_observer::{Event, Request, Status, COVERAGE};
use anyhow::{bail, ensure, Context, Result};
use libbpf_rs::{MapCore, MapFlags, ObjectBuilder, RingBufferBuilder};
use serde_json::json;
use std::{
    cell::RefCell,
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::{
        fd::AsRawFd,
        unix::{
            fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
            net::{UnixListener, UnixStream},
        },
    },
    path::{Path, PathBuf},
    rc::Rc,
    sync::mpsc,
    time::Duration,
};

const SOCKET: &str = "/run/actryn/observer.sock";
const OBJECT: &str = "/usr/lib/actryn/observer.bpf.o";
const OUTPUT: &str = "/var/lib/actryn-observer";
const RETAINED_BYTES: usize = 16 * 1024 * 1024;
type Command = (Request, mpsc::SyncSender<Result<Status>>);

struct Registration {
    attempt: String,
    path: PathBuf,
    file: File,
    bytes: usize,
    local_lost: u64,
    final_status: Option<Status>,
}

fn trusted(path: &Path) -> Result<()> {
    for p in path.ancestors() {
        let m = fs::symlink_metadata(p)?;
        ensure!(
            m.uid() == 0 && m.mode() & 0o022 == 0 && !m.file_type().is_symlink(),
            "untrusted path {}",
            p.display()
        );
    }
    Ok(())
}

fn collector(commands: mpsc::Receiver<Command>, ready: mpsc::SyncSender<Result<()>>) -> Result<()> {
    ensure!(
        std::env::consts::ARCH == "x86_64"
            && fs::read_to_string("/proc/sys/kernel/osrelease")?.trim() == "6.12.111+deb13-amd64",
        "unsupported observer tuple"
    );
    trusted(Path::new(OBJECT))?;
    let boot = fs::read_to_string("/proc/sys/kernel/random/boot_id")?
        .trim()
        .to_owned();
    let epoch = fs::read_to_string("/proc/sys/kernel/random/uuid")?
        .trim()
        .to_owned();
    fs::create_dir_all(OUTPUT)?;
    trusted(Path::new(OUTPUT))?;
    let output = Path::new(OUTPUT).join(&epoch);
    fs::create_dir(&output)?;
    fs::set_permissions(&output, fs::Permissions::from_mode(0o700))?;
    let object = ObjectBuilder::default().open_file(OBJECT)?.load()?;
    let mut links = Vec::new();
    let mut programs = Vec::new();
    for program in object.progs_mut() {
        programs.push(program.name().to_string_lossy().into_owned());
        links.push(program.attach()?);
    }
    programs.sort();
    ensure!(
        programs == ["enter", "executed", "exited", "forked", "leave"],
        "incorrect fixed program set"
    );
    let targets = object
        .maps()
        .find(|m| m.name() == "targets")
        .context("targets map missing")?;
    let events = object
        .maps()
        .find(|m| m.name() == "events")
        .context("events map missing")?;
    let registrations = Rc::new(RefCell::new(BTreeMap::<u64, Registration>::new()));
    let callback_regs = registrations.clone();
    let callback_epoch = epoch.clone();
    let callback_boot = boot.clone();
    let malformed = Rc::new(RefCell::new(false));
    let callback_malformed = malformed.clone();
    let mut builder = RingBufferBuilder::new();
    builder.add(&events, move |bytes| {
        let Ok(event) = Event::decode(bytes) else {
            *callback_malformed.borrow_mut() = true;
            return 0;
        };
        let mut all = callback_regs.borrow_mut();
        if let Some(r) = all.get_mut(&event.cgroup_id) {
            let record = json!({"collector_epoch": callback_epoch, "boot_id": callback_boot,
                "attempt_id": r.attempt, "event": event});
            let mut bytes = serde_json::to_vec(&record).expect("serializable fixed event");
            bytes.push(b'\n');
            if bytes.len() > RETAINED_BYTES.saturating_sub(r.bytes) || r.local_lost != 0 {
                r.local_lost = r.local_lost.saturating_add(1);
            } else {
                r.bytes += bytes.len();
                if r.file.write_all(&bytes).is_err() {
                    r.local_lost = r.local_lost.saturating_add(1);
                }
            }
        } else {
            *callback_malformed.borrow_mut() = true;
        }
        0
    })?;
    let ring = builder.build()?;
    ready.send(Ok(()))?;
    loop {
        ring.poll(Duration::from_millis(10))?;
        for _ in 0..8 {
            let (request, reply) = match commands.try_recv() {
                Ok(c) => c,
                Err(mpsc::TryRecvError::Empty) => break,
                Err(mpsc::TryRecvError::Disconnected) => return Ok(()),
            };
            let result = (|| -> Result<Status> {
                request.validate(&boot)?;
                let key = request.cgroup_id.to_ne_bytes();
                let cg =
                    Path::new("/sys/fs/cgroup").join(request.cgroup_path.trim_start_matches('/'));
                let unknown_unregister = request.op == "unregister"
                    && !registrations.borrow().contains_key(&request.cgroup_id);
                if !unknown_unregister {
                    trusted(&cg)?;
                    ensure!(
                        fs::metadata(&cg)?.ino() == request.cgroup_id,
                        "cgroup identity changed"
                    );
                }
                if request.op == "register"
                    && !registrations.borrow().contains_key(&request.cgroup_id)
                {
                    ensure!(
                        registrations.borrow().len() < 8 && !*malformed.borrow(),
                        "collector capacity/health"
                    );
                    let path = output.join(format!("{}.jsonl", request.attempt_id));
                    let file = OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .mode(0o600)
                        .open(&path)?;
                    targets.update(&key, &[0; 16], MapFlags::NO_EXIST)?;
                    registrations.borrow_mut().insert(
                        request.cgroup_id,
                        Registration {
                            attempt: request.attempt_id.clone(),
                            path,
                            file,
                            bytes: 0,
                            local_lost: 0,
                            final_status: None,
                        },
                    );
                }
                if let Some(r) = registrations.borrow().get(&request.cgroup_id) {
                    ensure!(r.attempt == request.attempt_id, "cgroup already attributed");
                }
                let counts = targets.lookup(&key, MapFlags::ANY)?;
                let (sequence, lost) = match counts {
                    Some(ref bytes) if bytes.len() == 16 => (
                        u64::from_ne_bytes(bytes[..8].try_into().unwrap()),
                        u64::from_ne_bytes(bytes[8..].try_into().unwrap()),
                    ),
                    None => (0, 0),
                    _ => bail!("invalid source counters"),
                };
                let local_lost = registrations
                    .borrow()
                    .get(&request.cgroup_id)
                    .map_or(0, |r| r.local_lost);
                let lost = lost.saturating_add(local_lost);
                let mut status = Status {
                    ready: counts.is_some() && lost == 0 && !*malformed.borrow(),
                    collector_epoch: epoch.clone(),
                    coverage: COVERAGE.iter().map(|s| (*s).into()).collect(),
                    sequence,
                    lost,
                };
                if request.op == "unregister"
                    && registrations.borrow().contains_key(&request.cgroup_id)
                {
                    ensure!(
                        fs::read_to_string(cg.join("cgroup.events"))?
                            .lines()
                            .any(|line| line == "populated 0"),
                        "cgroup still populated"
                    );
                    if counts.is_some() {
                        targets.delete(&key)?;
                        ring.poll(Duration::ZERO)?;
                    }
                    {
                        let mut all = registrations.borrow_mut();
                        let registration = all.get_mut(&request.cgroup_id).unwrap();
                        if let Some(previous) = &registration.final_status {
                            status = previous.clone();
                        } else {
                            status.lost = status
                                .lost
                                .saturating_add(registration.local_lost.saturating_sub(local_lost));
                            status.ready &= status.lost == 0;
                            registration.final_status = Some(status.clone());
                        }
                        registration.file.flush()?;
                        registration.file.sync_all()?;
                        let mut summary = OpenOptions::new()
                            .write(true)
                            .create(true)
                            .truncate(true)
                            .custom_flags(libc::O_NOFOLLOW)
                            .mode(0o600)
                            .open(registration.path.with_extension("summary.json"))?;
                        serde_json::to_writer(
                            &mut summary,
                            &json!({"status": status,
                            "retained_bytes": registration.bytes, "local_lost": registration.local_lost,
                            "durability": "JSONL synced at unregister; no complete-episode claim"}),
                        )?;
                        summary.sync_all()?;
                        File::open(&output)?.sync_all()?;
                    }
                    registrations.borrow_mut().remove(&request.cgroup_id);
                }
                Ok(status)
            })();
            let _ = reply.send(result);
        }
    }
}

fn exchange(mut stream: UnixStream, sender: &mpsc::SyncSender<Command>) -> Result<()> {
    let mut cred: libc::ucred = unsafe { std::mem::zeroed() };
    let mut len = size_of::<libc::ucred>() as libc::socklen_t;
    ensure!(
        unsafe {
            libc::getsockopt(
                stream.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_PEERCRED,
                (&mut cred as *mut libc::ucred).cast(),
                &mut len,
            )
        } == 0
            && cred.uid == 0,
        "root launcher peer required"
    );
    stream.set_read_timeout(Some(Duration::from_millis(250)))?;
    stream.set_write_timeout(Some(Duration::from_millis(250)))?;
    let mut header = [0; 4];
    stream.read_exact(&mut header)?;
    let len = u32::from_be_bytes(header) as usize;
    ensure!((1..=65536).contains(&len), "invalid frame size");
    let mut data = vec![0; len];
    stream.read_exact(&mut data)?;
    let request = serde_json::from_slice(&data)?;
    let (reply, result) = mpsc::sync_channel(1);
    sender
        .try_send((request, reply))
        .context("collector unavailable or busy")?;
    let status = result
        .recv_timeout(Duration::from_millis(500))
        .context("collector stalled")??;
    let bytes = serde_json::to_vec(&status)?;
    stream.write_all(&(bytes.len() as u32).to_be_bytes())?;
    stream.write_all(&bytes)?;
    Ok(())
}

fn main() -> Result<()> {
    ensure!(
        unsafe { libc::geteuid() } == 0 && std::env::args_os().count() == 1,
        "run the installed observer as root, with no arguments"
    );
    let (send, receive) = mpsc::sync_channel(8);
    let (ready, wait) = mpsc::sync_channel(1);
    let failure = ready.clone();
    std::thread::spawn(move || {
        if let Err(error) = collector(receive, ready) {
            eprintln!("collector stopped: {error:#}");
            let _ = failure.try_send(Err(error));
        }
    });
    wait.recv_timeout(Duration::from_secs(10))
        .context("collector startup failed")??;
    fs::create_dir_all("/run/actryn")?;
    trusted(Path::new("/run/actryn"))?;
    let socket = UnixListener::bind(SOCKET)?;
    fs::set_permissions(SOCKET, fs::Permissions::from_mode(0o600))?;
    for stream in socket.incoming() {
        if let Err(error) = exchange(stream?, &send) {
            eprintln!("observer request rejected: {error:#}");
        }
    }
    Ok(())
}
