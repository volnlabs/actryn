use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{fs, path::Path};

pub const MEMORY_MAX: u64 = 268_435_456;
pub const PIDS_MAX: u64 = 64;
pub const CPU_MAX: &str = "50000 100000";
pub const IO_RATE: u64 = 1_048_576;
pub const IO_OPS: u64 = 128;
pub const CONTAINER_UID: u32 = 65532;

pub fn fixed_spec(rootfs: &str, broker: &str, cgroup: &str, argv: &[String]) -> Value {
    let architecture = if cfg!(target_arch = "aarch64") {
        "SCMP_ARCH_AARCH64"
    } else {
        "SCMP_ARCH_X86_64"
    };
    let allow = [
        "read",
        "write",
        "readv",
        "writev",
        "pread64",
        "pwrite64",
        "close",
        "close_range",
        "fstat",
        "newfstatat",
        "stat",
        "lstat",
        "statx",
        "lseek",
        "mmap",
        "mprotect",
        "munmap",
        "mremap",
        "madvise",
        "brk",
        "rt_sigaction",
        "rt_sigprocmask",
        "rt_sigreturn",
        "sigaltstack",
        "ioctl",
        "access",
        "faccessat",
        "faccessat2",
        "pipe",
        "pipe2",
        "select",
        "pselect6",
        "poll",
        "ppoll",
        "dup",
        "dup2",
        "dup3",
        "fcntl",
        "getpid",
        "getppid",
        "gettid",
        "getuid",
        "geteuid",
        "getgid",
        "getegid",
        "getgroups",
        "uname",
        "getcwd",
        "chdir",
        "fchdir",
        "open",
        "openat",
        "creat",
        "readlink",
        "readlinkat",
        "getdents",
        "getdents64",
        "mkdir",
        "mkdirat",
        "unlink",
        "unlinkat",
        "rename",
        "renameat",
        "renameat2",
        "fsync",
        "fdatasync",
        "ftruncate",
        "truncate",
        "fchmod",
        "chmod",
        "umask",
        "utimensat",
        "fstatfs",
        "statfs",
        "clock_gettime",
        "clock_getres",
        "clock_nanosleep",
        "nanosleep",
        "gettimeofday",
        "times",
        "getrusage",
        "getrlimit",
        "prlimit64",
        "futex",
        "set_robust_list",
        "get_robust_list",
        "set_tid_address",
        "rseq",
        "arch_prctl",
        "sched_getaffinity",
        "sched_yield",
        "execve",
        "execveat",
        "fork",
        "vfork",
        "wait4",
        "waitid",
        "exit",
        "exit_group",
        "kill",
        "tgkill",
        "restart_syscall",
        "getrandom",
        "connect",
        "getsockopt",
        "setsockopt",
        "getsockname",
        "getpeername",
        "sendto",
        "recvfrom",
        "sendmsg",
        "recvmsg",
        "shutdown",
        "epoll_create1",
        "epoll_ctl",
        "epoll_wait",
        "epoll_pwait",
        "eventfd2",
        "socketpair",
    ];
    json!({"ociVersion":"1.0.2","root":{"path":rootfs,"readonly":true},
        "process":{"terminal":false,"user":{"uid":CONTAINER_UID,"gid":CONTAINER_UID,"additionalGids":[]},
            "args":argv,"env":["PATH=/usr/bin:/bin","HOME=/tmp","LANG=C.UTF-8","ACTRYN_BROKER=/run/actryn-broker/broker.sock"],"cwd":"/tmp",
            "noNewPrivileges":true,"capabilities":{"bounding":[],"effective":[],"inheritable":[],"permitted":[],"ambient":[]},
            "rlimits":[{"type":"RLIMIT_NOFILE","hard":128,"soft":128},{"type":"RLIMIT_CORE","hard":0,"soft":0}]},
        "hostname":"actryn-agent","mounts":[
            {"destination":"/proc","type":"proc","source":"proc","options":["nosuid","noexec","nodev"]},
            {"destination":"/dev","type":"tmpfs","source":"tmpfs","options":["nosuid","noexec","strictatime","mode=755","size=65536"]},
            {"destination":"/tmp","type":"tmpfs","source":"tmpfs","options":["nosuid","nodev","noexec","mode=1777","size=16777216"]},
            {"destination":"/run/actryn-broker","type":"bind","source":broker,"options":["rbind","ro","nosuid","nodev","noexec"]}],
        "linux":{"cgroupsPath":cgroup,"rootfsPropagation":"private",
            "namespaces":[{"type":"pid"},{"type":"mount"},{"type":"ipc"},{"type":"uts"},{"type":"network"},{"type":"cgroup"}],
            "devices":[
                {"path":"/dev/null","type":"c","major":1,"minor":3,"fileMode":438,"uid":0,"gid":0},
                {"path":"/dev/zero","type":"c","major":1,"minor":5,"fileMode":438,"uid":0,"gid":0},
                {"path":"/dev/random","type":"c","major":1,"minor":8,"fileMode":438,"uid":0,"gid":0},
                {"path":"/dev/urandom","type":"c","major":1,"minor":9,"fileMode":438,"uid":0,"gid":0}],
            "resources":{"memory":{"limit":MEMORY_MAX,"swap":MEMORY_MAX},"pids":{"limit":PIDS_MAX},"cpu":{"quota":50000,"period":100000},
                "devices":[{"allow":false,"access":"rwm"},{"allow":true,"type":"c","major":1,"minor":3,"access":"rw"},
                    {"allow":true,"type":"c","major":1,"minor":5,"access":"rw"},{"allow":true,"type":"c","major":1,"minor":8,"access":"rw"},{"allow":true,"type":"c","major":1,"minor":9,"access":"rw"}]},
            "maskedPaths":["/proc/kcore","/proc/keys","/proc/timer_list","/proc/sched_debug","/sys/firmware"],
            "readonlyPaths":["/proc/sys","/proc/sysrq-trigger","/proc/irq","/proc/bus"],
            "seccomp":{"defaultAction":"SCMP_ACT_ERRNO","defaultErrnoRet":1,"architectures":[architecture],"syscalls":[
                {"names":allow.as_slice(),"action":"SCMP_ACT_ALLOW"},
                {"names":["socket"],"action":"SCMP_ACT_ALLOW","args":[{"index":0,"value":1,"op":"SCMP_CMP_EQ"}]},
                {"names":["clone"],"action":"SCMP_ACT_ALLOW","args":[{"index":0,"value":2114060288_u64,"valueTwo":0,"op":"SCMP_CMP_MASKED_EQ"}]},
                {"names":["clone3"],"action":"SCMP_ACT_ERRNO","errnoRet":38}]}}})
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Snapshot {
    pub pid: u32,
    pub start_ticks: u64,
    pub cgroup: String,
    pub uid: u32,
    pub gid: u32,
    pub capabilities: u64,
    pub no_new_privileges: bool,
    pub seccomp_mode: u32,
    pub private_namespaces: bool,
    pub network_routes: usize,
    pub memory_max: u64,
    pub pids_max: u64,
    pub cpu_max: String,
    pub io_max: String,
    pub device_programs: Vec<u32>,
    #[serde(default)]
    pub device_programs_direct: Vec<u32>,
    #[serde(default)]
    pub device_attach_flags: u32,
    pub unexpected_mounts: Vec<String>,
    pub root_readonly: bool,
}
pub fn verify_snapshot(s: &Snapshot, pid: u32, cgroup: &str, io_device: &str) -> Result<()> {
    ensure!(
        s.pid == pid && s.start_ticks > 0 && s.cgroup == cgroup,
        "wrong task lifetime/cgroup"
    );
    ensure!(
        s.uid == CONTAINER_UID
            && s.gid == CONTAINER_UID
            && s.capabilities == 0
            && s.no_new_privileges
            && s.seccomp_mode == 2,
        "process restrictions missing"
    );
    ensure!(
        s.private_namespaces && s.network_routes == 0,
        "namespace/network isolation missing"
    );
    ensure!(
        s.memory_max == MEMORY_MAX && s.pids_max == PIDS_MAX && s.cpu_max.trim() == CPU_MAX,
        "cgroup limits missing"
    );
    ensure!(
        s.io_max.lines().any(|line| {
            let fields: Vec<_> = line.split_whitespace().collect();
            fields.first() == Some(&io_device)
                && ["rbps=1048576", "wbps=1048576", "riops=128", "wiops=128"]
                    .iter()
                    .all(|value| fields.contains(value))
        }),
        "I/O limit missing"
    );
    ensure!(
        !s.device_programs.is_empty()
            && !s.device_programs_direct.is_empty()
            && s.device_attach_flags == 2
            && s.device_programs.iter().all(|id| *id > 0)
            && s.device_programs_direct.iter().all(|id| *id > 0),
        "device enforcement not installed"
    );
    ensure!(
        s.root_readonly && s.unexpected_mounts.is_empty(),
        "unexpected/writable host mounts"
    );
    Ok(())
}
fn number(path: impl AsRef<Path>) -> Result<u64> {
    Ok(fs::read_to_string(path)?.trim().parse()?)
}
pub fn snapshot(pid: u32, cgroup: &str, cgroup_dir: &Path) -> Result<Snapshot> {
    let proc = std::path::PathBuf::from(format!("/proc/{pid}"));
    let status = fs::read_to_string(proc.join("status"))?;
    let field = |name: &str| -> Result<&str> {
        status
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .map(str::trim)
            .context("missing process status field")
    };
    let process_cgroup = fs::read_to_string(proc.join("cgroup"))?
        .lines()
        .find_map(|line| line.strip_prefix("0::"))
        .context("not cgroup v2")?
        .to_string();
    ensure!(
        process_cgroup == cgroup,
        "runtime placed task in wrong cgroup"
    );
    let stat = fs::read_to_string(proc.join("stat"))?;
    let start_ticks = stat
        .rsplit_once(") ")
        .context("bad proc stat")?
        .1
        .split_whitespace()
        .nth(19)
        .context("missing process lifetime")?
        .parse()?;
    let mut private_namespaces = true;
    for namespace in ["pid", "mnt", "ipc", "uts", "net", "cgroup"] {
        private_namespaces &= fs::read_link(proc.join(format!("ns/{namespace}")))?
            != fs::read_link(format!("/proc/self/ns/{namespace}"))?;
    }
    let ipv4 = fs::read_to_string(proc.join("net/route"))?
        .lines()
        .skip(1)
        .filter(|line| !line.trim().is_empty())
        .count();
    // IPv6 loopback routes do not provide external connectivity.
    let ipv6 = fs::read_to_string(proc.join("net/ipv6_route"))?
        .lines()
        .filter(|line| line.split_whitespace().last() != Some("lo"))
        .count();
    let mounts = fs::read_to_string(proc.join("mountinfo"))?;
    let allow = [
        "/",
        "/proc",
        "/dev",
        "/tmp",
        "/run/actryn-broker",
        "/proc/kcore",
        "/proc/keys",
        "/proc/timer_list",
        "/proc/sched_debug",
        "/sys/firmware",
        "/proc/sys",
        "/proc/sysrq-trigger",
        "/proc/irq",
        "/proc/bus",
    ];
    let mut unexpected = vec![];
    let mut root_readonly = false;
    for line in mounts.lines() {
        let fields: Vec<_> = line.split_whitespace().collect();
        ensure!(fields.len() > 6, "malformed mount inventory");
        if fields[4] == "/" {
            root_readonly = fields[5].split(',').any(|v| v == "ro");
        }
        if !allow.contains(&fields[4]) {
            unexpected.push(fields[4].to_string());
        }
    }
    let mut capabilities = 0;
    for name in ["CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:"] {
        capabilities |= u64::from_str_radix(field(name)?, 16)?;
    }
    let direct = crate::device_policy::programs(cgroup_dir, false)?;
    let effective = crate::device_policy::programs(cgroup_dir, true)?;
    Ok(Snapshot {
        pid,
        start_ticks,
        cgroup: process_cgroup,
        uid: field("Uid:")?
            .split_whitespace()
            .next()
            .context("uid missing")?
            .parse()?,
        gid: field("Gid:")?
            .split_whitespace()
            .next()
            .context("gid missing")?
            .parse()?,
        capabilities,
        no_new_privileges: field("NoNewPrivs:")? == "1",
        seccomp_mode: field("Seccomp:")?.parse()?,
        private_namespaces,
        network_routes: ipv4 + ipv6,
        memory_max: number(cgroup_dir.join("memory.max"))?,
        pids_max: number(cgroup_dir.join("pids.max"))?,
        cpu_max: fs::read_to_string(cgroup_dir.join("cpu.max"))?,
        io_max: fs::read_to_string(cgroup_dir.join("io.max"))?,
        device_programs: effective.ids,
        device_programs_direct: direct.ids,
        device_attach_flags: direct.attach_flags,
        unexpected_mounts: unexpected,
        root_readonly,
    })
}
