# Additional owner lifetime cases

This test-only client supplements `owner-exit`, which covers a single-threaded
process. Both target cases passed in `artifacts/kernel-module16-owner01` on
the exact ARM kernel with module SHA-256
`a49fd1a48bbdc39447a78fc0b0714e2e713c34f4fe25c11e989a790778291112`.
Leader 3342 exited while thread 3343 survived; a separate case reused the reaped
owner's numeric PID 3388 through one `clone3(set_tid)` call. The old descriptor's
HEALTH and ACTIVATE requests returned EPERM, with UNKNOWN and identity retained.
These are software fixture results, not physical qualification. It reuses the existing
adversarial suite's fixed authority setup and target guard by including that C
source with its entry point renamed. It does not load/unload the module, reset
the fixture, or change production limits.

Build in the exact ARM64 guest, outside any PID namespace or container:

```sh
cc -std=c11 -Wall -Wextra -Werror -pthread \
  kernel/tests/authority_owner_lifetime.c -o authority-owner-lifetime
```

Each case requires its own fresh inhibited fixture and ordinary module
unload/reload, with manager/gateway services stopped. Preserve environment,
module/source hashes, boot identity, stdout/stderr, exit status and dmesg in a
new labeled directory. Stop after any failure; never retry into the same result.
The parent has a twenty-second alarm; child processes have fifteen-second
alarms. These are harness bounds, not kernel latency claims.

```sh
./authority-owner-lifetime leader-exit
./authority-owner-lifetime pid-reuse
```

`leader-exit` first verifies that a sibling thread can refresh the live owner's
health. The leader then calls `pthread_exit`, while the sibling and a transferred
runtime file description in the parent remain open. The sibling joins the
leader to establish its termination, records the still-live TGID and distinct
TID, and requires HEALTH and ACTIVATE through the retained runtime description
to fail with EPERM. Both processes check owner-loss closure, UNKNOWN and the
original operation identity. The sibling checks closure before releasing its
own runtime descriptor.

`pid-reuse` reaps the original owner while retaining its runtime descriptor,
requires OWNER_LOST/UNKNOWN, then calls `clone3(set_tid)` once to create a new
thread group with the original numeric TGID. It verifies the existing PID
namespace has no parent after successful authority setup has established
initial-user-namespace administrative privilege. No new PID namespace is
created. Both the clone return value and the replacement's PID/TID must equal
the original TGID. The replacement's HEALTH and ACTIVATE requests through the
old descriptor must fail with EPERM; terminal state and identity must remain
unchanged. Failure of `clone3`, including unavailable checkpoint/restore
capability or a PID collision, prints NOT_RUN and exits 77. It is not a PASS and
does not fall back to PID churn or namespace aliases.

Both modes require the grant-authorized, pending-transmit and handshake flags
to be clear after owner loss, with device/controller identity, instance, operation identity,
runtime nonce and last-applied duties retained. They do not infer a controller
disable receipt or qualify physical motion. A new explicit registration is
outside these tests; it is not prohibited by the old descriptor's rejection.

The host-only `--selftest` mode checks the terminal predicate with fourteen
counterexamples. It bypasses the ARM guard solely for those in-memory checks
and never opens the device. Host success is not either target lifetime result.
