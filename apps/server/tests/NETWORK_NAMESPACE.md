# CREATED-task network namespace functional proof

`network_namespace.py` is a test-only trusted verifier, separate from agent
execution. Imports are inert. There is no public command that prepares or starts
work; `collect(prepared_reply, expected, ip_pin)` is called by a separately
reviewed Root guest owner between a known Prepare and any Launch. Its private
`--child FD` entry is only the parent's subprocess interface.

This implements the scoped interpretation recorded in
`artifacts/server-network-namespace-proposal01/root-interpretation.json`
(SHA256 `a1a3d201891dd8c3053cc2ee7cd3712f61c02dabcf6c7936832a039dd32947b0`).
It does not amend platform-release-contract row77, frozen predicate map03, the
runtime profile, or the existing agent evidence. Actual target execution is
**NOT_RUN**; the guest `ip` pin is still unobserved. D2-05 remains open until
actual evidence and Root's mapping; whole D2, physical qualification and A16
acceptance are not claimed.

## Inputs and owner responsibilities

`prepared_reply` is the unmodified installed CLI Prepare response. `expected`
comes from independent Root-reviewed inputs, not the returned report:

- `attempt`: 32 lowercase hex characters; `artifact`: `sha256:` digest.
- `binding`: exact parsed durable prepared binding (including boot, snapshot
  PID/start/cgroup and cgroup inode). It must have unambiguous Create identity.
- `proof_cgroup`: the exact Root-owned guest scope outside `/actryn` and every
  attempt cgroup. Both parent and helper must remain there.

The Root owner pins source files (this module plus `guest_observer_gap.py` and
its `guest_capacity.py` dependency), guest Python/ctr/dpkg tools, installed
package/config/boot/machine/kernel tuple, and the selected OCI/agent provenance.
It durably records the original Prepare, helper intent/result or exception,
stdout/stderr and known helper-scope closure. It exclusively owns the attempt;
no concurrent Start, service/config/route change or other admission is allowed.
Failures are preserved, never retried automatically. A failure/timeout authorizes
no Launch or repeated Prepare; Root separately reviews cleanup. This module
performs no SQL, credential access, Robot RPC, service action or cancellation.

After the task pidfd is opened, failures raise `ProofFailure`; the owner must
persist its JSON-compatible `evidence` before cleanup. It retains the partial
report and captured worker return code, stdout and stderr (hex, byte count,
SHA256 and explicit omitted-byte count). Retained stdout is capped at512KiB and
stderr at64KiB; a timeout has no known return code. These are post-capture limits,
so the finite enclosing memory limit is still required. Earlier admission
failures raise their original exception and have dispatched no worker.

`ip_pin` is mandatory; there is no default or configured pin. It has exactly:

```
{path: canonical /usr/bin/ip or /usr/sbin/ip,
 sha256: 64 lowercase hex,
 metadata: {dev,ino,mode,uid,gid,nlink,size,mtime_ns,ctime_ns},
 package: {name: iproute2, version: actual version, architecture: amd64}}
```

Root must first observe these public values in the selected guest. The executor
requires a root-owned protected canonical regular executable and protected root
ancestors, exact stable metadata/hash, exact `dpkg-query -W` package identity and
membership in `dpkg-query -L iproute2`, before and after the proof. These checks
associate the exact tool bytes with the observed package; they do not audit the
entire package manager or toolchain. Missing or changed pins reject before
opening the task pidfd or entering a namespace.

## Sequence, attribution and limits

The parent holds the original task pidfd until the last bookend. It checks the
exact containerd `CREATED` task, PID/start, cgroup path/inode, boot, netns
device/inode and empty regular application logs before the worker and after it.
The opened namespace FD is also checked against that identity immediately before
launch. Keeping a namespace FD is insufficient on its own: original-task death
rejects even if the namespace persists.

Only that netns FD is passed as an extra inherited descriptor; the pidfd stays
in the parent. The single-threaded worker calls `os.setns(fd, CLONE_NEWNET)` once,
checks unchanged PID/start/cgroup and all six other namespace identities, then
creates its AF_INET TCP socket. It makes exactly one numeric
`203.0.113.1:443` connect (no DNS) with a one-second timeout, requiring precisely
`ENETUNREACH`. Success, EPERM, unrelated errors, timeout and unknown outcomes fail.
The socket closes without being transferred to the agent.

Before and after, it retains complete raw UTF-8 JSON for four fixed read-only
commands, each beginning with the pinned absolute `ip -j -details`:

```
link show
address show
-4 route show table all
-6 route show table all
```

All dumps must succeed without stderr or truncation. Only `lo` with loopback
link type is admitted; addresses/routes must remain loopback-only with no
external interface, default route, gateway, encapsulation or nexthop. Empty
route/address inventories on a down loopback are allowed; nothing brings it up.
Both full decoded topologies must be equal. Raw dumps and unknown auxiliary
fields remain in the report; no evidence is rewritten to fit expectations.

Limits: whole collector30s, worker parent timeout15s/child alarm12s, each command
at most1s, each four-command dump4s, connect1s, each dump32KiB/256rows (addresses
at most16); worker stdout512KiB. Executable hashing is bounded32MiB. Root must
also impose a finite guest cgroup memory/tasks/runtime limit and retain the
actual host/guest helper closures. These are harness cutoffs, not WCET claims.

The helper remains in a distinct trusted cgroup, so its connect is not an agent
observer event. Do not inject it into `broker_evidence.validate_trace`, register
it as the agent, or claim agent-origin egress. Compose its report separately with
the existing selected-agent AF_INET socket EPERM, inherited-FD scan, zero-route
snapshot and allowed Unix-broker/denial evidence. The existing native proof
correctly continues to state that the agent made no external-connect attempt.

## Offline tests and primary API references

Run only the pure tests on a development host:

```
python3 -B -m unittest discover -s apps/server/tests -p test_network_namespace.py
```

Tests use synthetic records or mock every namespace/socket/collector action.
They never enter a namespace, open a network socket or run ip/ctr/dpkg.

- [Python 3.13 os.setns](https://docs.python.org/3.13/library/os.html#os.setns):
  a namespace FD with an explicit namespace type restricts the join.
- [Linux setns(2)](https://man7.org/linux/man-pages/man2/setns.2.html):
  namespace-FD joins affect the calling thread; the explicit network type rejects
  other namespace types. Necessary trusted Linux privilege must be provided by
  the Root proof scope, without adding privilege to the agent profile.
- [ip(8)](https://man7.org/linux/man-pages/man8/ip.8.html) documents JSON output;
  [ip-route(8)](https://man7.org/linux/man-pages/man8/ip-route.8.html) describes
  the explicit `table all` selection. Actual installed-tool output is still
  subject to the fixed pinned-guest preflight and strict parser.
