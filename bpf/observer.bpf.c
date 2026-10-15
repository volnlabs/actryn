// SPDX-License-Identifier: GPL-2.0-only
// Fixed Debian 13 x86-64 tracepoint ABI; this object is diagnostic, not enforcement.
#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>
#include <asm/unistd.h>

struct counters { __u64 sequence, lost; };
struct event {
    __u64 monotonic_ns, cgroup_id, pid_tgid, sequence;
    __s64 result;
    __u32 related_pid, kind;
    __s32 syscall;
    __u32 reserved;
    char comm[16];
};
_Static_assert(sizeof(struct event) == 72, "observer ABI");
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 8);
    __type(key, __u64);
    __type(value, struct counters);
} targets SEC(".maps");
struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 20);
} events SEC(".maps");

static __always_inline int emit(__u32 kind, __s32 syscall, __s64 result, __u32 related)
{
    __u64 cgroup = bpf_get_current_cgroup_id();
    struct counters *count = bpf_map_lookup_elem(&targets, &cgroup);
    if (!count)
        return 0;
    __u64 sequence = __sync_fetch_and_add(&count->sequence, 1) + 1;
    struct event *e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        __sync_fetch_and_add(&count->lost, 1);
        return 0;
    }
    e->monotonic_ns = bpf_ktime_get_ns();
    e->cgroup_id = cgroup;
    e->pid_tgid = bpf_get_current_pid_tgid();
    e->sequence = sequence;
    e->result = result;
    e->related_pid = related;
    e->kind = kind;
    e->syscall = syscall;
    e->reserved = 0;
    bpf_get_current_comm(e->comm, sizeof(e->comm));
    bpf_ringbuf_submit(e, 0);
    return 0;
}
static __always_inline int selected(long id)
{
    return id == __NR_openat || id == __NR_connect || id == __NR_bpf ||
        id == __NR_perf_event_open || id == __NR_mount || id == __NR_unshare || id == __NR_setns;
}
struct enter_ctx { __u64 common; long id; unsigned long args[6]; };
struct exit_ctx { __u64 common; long id; long ret; };
struct fork_ctx { __u64 common; char parent_comm[16]; int parent_pid; char child_comm[16]; int child_pid; };
struct exec_ctx { __u64 common; __u32 filename; int pid; int old_pid; };
SEC("tracepoint/raw_syscalls/sys_enter")
int enter(struct enter_ctx *ctx) { return selected(ctx->id) ? emit(1, ctx->id, 0, 0) : 0; }
SEC("tracepoint/raw_syscalls/sys_exit")
int leave(struct exit_ctx *ctx) { return selected(ctx->id) ? emit(2, ctx->id, ctx->ret, 0) : 0; }
SEC("tracepoint/sched/sched_process_fork")
int forked(struct fork_ctx *ctx) { return emit(3, -1, 0, ctx->child_pid); }
SEC("tracepoint/sched/sched_process_exec")
int executed(struct exec_ctx *ctx) { return emit(4, -1, 0, ctx->old_pid); }
SEC("tracepoint/sched/sched_process_exit")
int exited(void *ctx) { return emit(5, -1, 0, 0); }
char LICENSE[] SEC("license") = "GPL";
