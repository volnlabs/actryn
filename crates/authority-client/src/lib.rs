//! Fixed UAPI v1 client. The kernel remains the authority; this crate owns no grant table.
use serde::Serialize;
use std::{
    fs::{File, OpenOptions},
    io,
    os::{fd::AsRawFd, unix::fs::OpenOptionsExt},
};

#[cfg(not(all(
    target_endian = "little",
    target_pointer_width = "64",
    target_os = "linux"
)))]
compile_error!("Actryn UAPI v1 requires 64-bit little-endian Linux");

pub const VERSION: u32 = 1;
pub const DEVICE: &str = "/dev/actryn-authority";
const REQUEST_IOCTL: libc::c_ulong = 0xc0c04101;
const STATUS_IOCTL: libc::c_ulong = 0x80c04102;

#[repr(u32)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Role {
    Admin = 1,
    Runtime = 2,
    Acquisition = 3,
    Events = 4,
}
#[repr(u32)]
#[derive(Clone, Copy, Debug)]
pub enum Opcode {
    Bind = 1,
    Handshake,
    Rearm,
    Grant,
    Activate,
    Observe,
    Start,
    Sample,
    Finish,
    Cancel,
    Revoke,
    Recover,
    Health,
    Allocate,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Serialize)]
pub struct Request {
    pub version: u32,
    pub opcode: u32,
    pub flags: u32,
    pub role: u32,
    pub runtime_nonce: [u8; 16],
    pub grant: u64,
    pub instance: u64,
    pub operation: u64,
    pub stream: u64,
    pub sequence: u64,
    pub transaction: u64,
    pub deadline_ns: u64,
    pub observation: u64,
    pub acquired_earliest_ns: u64,
    pub acquired_latest_ns: u64,
    pub valid_until_ns: u64,
    pub context_revision: u64,
    pub left_permille: i32,
    pub right_permille: i32,
    pub reason: u32,
    pub reserved0: u32,
    pub digest: [u8; 32],
    pub reserved: [u8; 16],
}
impl Request {
    pub fn new(opcode: Opcode) -> Self {
        Self {
            version: VERSION,
            opcode: opcode as u32,
            ..Self::default()
        }
    }
    /// Common operation fields for SAMPLE/FINISH/CANCEL. START additionally needs
    /// the immutable allocation fields retained in the durable intent.
    pub fn operation_identity(opcode: Opcode, status: &Status) -> Self {
        Self {
            runtime_nonce: status.runtime_nonce,
            grant: status.grant,
            operation: status.operation,
            stream: status.stream,
            ..Self::new(opcode)
        }
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Serialize)]
pub struct Status {
    pub version: u32,
    pub state: u32,
    pub operation_state: u32,
    pub reserved0: u32,
    pub runtime_nonce: [u8; 16],
    pub device_identity: [u8; 16],
    pub controller_boot: u64,
    pub controller_session: u64,
    pub grant: u64,
    pub instance: u64,
    pub operation: u64,
    pub stream: u64,
    pub sequence: u64,
    pub transaction: u64,
    pub deadline_ns: u64,
    pub now_ns: u64,
    pub observation: u64,
    pub context_revision: u64,
    pub controller_ns: u64,
    pub left_encoder: i64,
    pub right_encoder: i64,
    pub left_permille: i32,
    pub right_permille: i32,
    pub reason: u32,
    pub events_lost: u32,
    pub flags: u32,
    pub reserved1: u32,
}
impl Status {
    pub fn validate(&self) -> io::Result<()> {
        if self.version != VERSION
            || self.reserved0 != 0
            || self.reserved1 != 0
            || self.state > 5
            || self.operation_state > 6
            || self.reason > 9
            || self.flags & !15 != 0
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "unsupported authority status",
            ));
        }
        Ok(())
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Serialize)]
pub struct Event {
    pub sequence: u64,
    pub captured_ns: u64,
    pub kind: u32,
    pub reserved: u32,
    pub status: Status,
}

const _: () = {
    assert!(size_of::<Request>() == 192 && align_of::<Request>() == 8);
    assert!(size_of::<Status>() == 192 && align_of::<Status>() == 8);
    assert!(size_of::<Event>() == 216);
    assert!(std::mem::offset_of!(Request, digest) == 144);
    assert!(std::mem::offset_of!(Status, left_encoder) == 152);
    assert!(std::mem::offset_of!(Event, status) == 24);
};

pub struct AuthorityDevice {
    file: File,
    role: Role,
}
impl AuthorityDevice {
    /// Runtime callers install the exec-denying seccomp filter before binding.
    pub fn bind(role: Role) -> io::Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .write(role != Role::Events)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(DEVICE)?;
        let device = Self { file, role };
        let mut request = Request::new(Opcode::Bind);
        request.role = role as u32;
        device.request(&mut request)?;
        Ok(device)
    }
    /// A failed/interrupted ioctl may have taken effect. Query or close; never retry
    /// an uncertain allocation/start as a new operation.
    pub fn request(&self, request: &mut Request) -> io::Result<()> {
        let result = unsafe {
            libc::ioctl(
                self.file.as_raw_fd(),
                REQUEST_IOCTL,
                request as *mut Request,
            )
        };
        if result < 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }
    pub fn status(&self) -> io::Result<Status> {
        let mut status = Status::default();
        let result = unsafe {
            libc::ioctl(
                self.file.as_raw_fd(),
                STATUS_IOCTL,
                &mut status as *mut Status,
            )
        };
        if result < 0 {
            return Err(io::Error::last_os_error());
        }
        status.validate()?;
        Ok(status)
    }
    pub fn read_event(&self) -> io::Result<Event> {
        if self.role != Role::Events {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "events binding required",
            ));
        }
        let mut event = Event::default();
        let result = unsafe {
            libc::read(
                self.file.as_raw_fd(),
                (&mut event as *mut Event).cast(),
                size_of::<Event>(),
            )
        };
        if result < 0 {
            return Err(io::Error::last_os_error());
        }
        if result as usize != size_of::<Event>() || event.reserved != 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "incomplete authority event",
            ));
        }
        event.status.validate()?;
        Ok(event)
    }
    pub fn wait_event(&self, timeout_ms: u16) -> io::Result<bool> {
        let mut poll = libc::pollfd {
            fd: self.file.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        let result = unsafe { libc::poll(&mut poll, 1, timeout_ms.into()) };
        if result < 0 {
            return Err(io::Error::last_os_error());
        }
        if poll.revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0 {
            return Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "authority event source unavailable",
            ));
        }
        Ok(poll.revents & libc::POLLIN != 0)
    }
}

pub fn boottime_ns() -> io::Result<u64> {
    let mut ts = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    if unsafe { libc::clock_gettime(libc::CLOCK_BOOTTIME, &mut ts) } != 0 {
        return Err(io::Error::last_os_error());
    }
    u64::try_from(ts.tv_sec)
        .ok()
        .and_then(|s| s.checked_mul(1_000_000_000))
        .and_then(|s| s.checked_add(ts.tv_nsec as u64))
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "boot clock overflow"))
}

/// Install before runtime binding. Existing and future threads cannot execute a
/// new image; the kernel also checks the registered task/credential lifetime.
pub fn deny_exec() -> io::Result<()> {
    #[cfg(target_arch = "x86_64")]
    let arch = 0xc000003e;
    #[cfg(target_arch = "aarch64")]
    let arch = 0xc00000b7;
    #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
    compile_error!("seccomp profile supports only x86-64 and ARM64");
    let stmt = |code, k| libc::sock_filter {
        code,
        jt: 0,
        jf: 0,
        k,
    };
    let eq = |k, jt, jf| libc::sock_filter {
        code: 0x15,
        jt,
        jf,
        k,
    };
    let filters = [
        stmt(0x20, 4),
        eq(arch, 1, 0),
        stmt(0x06, 0x80000000),
        stmt(0x20, 0),
        // x32 shares the x86-64 audit architecture; reject its alternate syscall table.
        libc::sock_filter {
            code: 0x45,
            jt: 0,
            jf: 1,
            k: 0x40000000,
        },
        stmt(0x06, 0x00050000 | libc::EPERM as u32),
        eq(libc::SYS_execve as u32, 0, 1),
        stmt(0x06, 0x00050000 | libc::EPERM as u32),
        eq(libc::SYS_execveat as u32, 0, 1),
        stmt(0x06, 0x00050000 | libc::EPERM as u32),
        stmt(0x06, 0x7fff0000),
    ];
    let prog = libc::sock_fprog {
        len: filters.len() as u16,
        filter: filters.as_ptr().cast_mut(),
    };
    if unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let result = unsafe { libc::syscall(libc::SYS_seccomp, 1, 1, &prog) };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }
    if result != 0 {
        return Err(io::Error::other("seccomp thread synchronization failed"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn no_request_fields_are_accidentally_reused() {
        let s = Status {
            runtime_nonce: [9; 16],
            grant: 3,
            instance: 5,
            operation: 7,
            stream: 11,
            sequence: 99,
            deadline_ns: 500,
            left_permille: 200,
            ..Status::default()
        };
        let r = Request::operation_identity(Opcode::Cancel, &s);
        assert_eq!((r.grant, r.instance, r.operation, r.stream), (3, 0, 7, 11));
        assert_eq!(
            (
                r.version,
                r.opcode,
                r.sequence,
                r.deadline_ns,
                r.left_permille
            ),
            (1, 10, 0, 0, 0)
        );
        assert_eq!(r.digest, [0; 32]);
        assert_eq!(r.reserved, [0; 16]);
    }
    #[test]
    fn unsupported_kernel_status_is_not_accepted() {
        let mut s = Status {
            version: VERSION,
            ..Status::default()
        };
        s.validate().unwrap();
        s.reserved1 = 1;
        assert!(s.validate().is_err());
        s.reserved1 = 0;
        s.operation_state = 7;
        assert!(s.validate().is_err());
        s.operation_state = 0;
        s.flags = 8;
        s.validate().unwrap();
        s.flags = 16;
        assert!(s.validate().is_err());
        s.flags = 0;
        s.reason = 10;
        assert!(s.validate().is_err());
        assert!(boottime_ns().unwrap() > 0);
    }
    #[test]
    fn exec_filter_rejects_both_entrypoints_in_an_isolated_child() {
        let child = unsafe { libc::fork() };
        assert!(child >= 0);
        if child == 0 {
            if deny_exec().is_err() {
                unsafe { libc::_exit(1) }
            }
            let path = c"/bin/true";
            let argv = [path.as_ptr(), std::ptr::null()];
            let env = [std::ptr::null::<libc::c_char>()];
            let a = unsafe { libc::execve(path.as_ptr(), argv.as_ptr(), env.as_ptr()) };
            if a != -1 || unsafe { *libc::__errno_location() } != libc::EPERM {
                unsafe { libc::_exit(2) }
            }
            let b = unsafe {
                libc::syscall(
                    libc::SYS_execveat,
                    libc::AT_FDCWD,
                    path.as_ptr(),
                    argv.as_ptr(),
                    env.as_ptr(),
                    0,
                )
            };
            if b != -1 || unsafe { *libc::__errno_location() } != libc::EPERM {
                unsafe { libc::_exit(3) }
            }
            #[cfg(target_arch = "x86_64")]
            {
                let x32 = unsafe {
                    libc::syscall(0x40000208_i64, path.as_ptr(), argv.as_ptr(), env.as_ptr())
                };
                if x32 != -1 || unsafe { *libc::__errno_location() } != libc::EPERM {
                    unsafe { libc::_exit(4) }
                }
            }
            unsafe { libc::_exit(0) }
        }
        let mut status = 0;
        assert_eq!(unsafe { libc::waitpid(child, &mut status, 0) }, child);
        assert!(libc::WIFEXITED(status));
        assert_eq!(libc::WEXITSTATUS(status), 0);
    }
}
