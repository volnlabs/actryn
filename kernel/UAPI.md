# Authority UAPI v1

The canonical header is `include/uapi/linux/actryn_authority.h`. The dedicated
serdev child compatible is **`actryn,fixture-v2`**. The production interface has
no raw-byte write operation. All numbers use the native little-endian ARM64
ABI; controller wire encoding is separately little-endian and never a struct cast.

`actryn_request` and `actryn_status` are each 192 bytes, aligned to 8;
`actryn_event` is 216 bytes. Rust clients use `#[repr(C)]` with exact-width
integers and assert sizes/offsets. Ioctls are REQUEST `0xc0c04101`, STATUS
`0x80c04102`. Request success copies allocated identities back before return;
the status query is non-admitting and reports current identities and frontiers.
An interrupted request does not withdraw a previously accepted close.

Open separate file descriptions for ADMIN, RUNTIME, ACQUISITION, EVENTS and
issue BIND with the chosen role. Admin binding requires initial-namespace
CAP_SYS_ADMIN. Runtime/acquisition registration binds the calling process's
thread-group leader and credentials, not the descriptor or numeric PID.
Transferred/forked runtime descriptors cannot command. The manager installs its
exec-denying seccomp filter before runtime binding. The gateway receives no FD.
The kernel retains the credential object and leader `self_exec_id`; credential
replacement or successful exec invalidates owner liveness before subsequent
dispatch and on the watchdog pass. The kernel does not inspect BPF filter
instructions to prove exec denial. The guest selftest installs and exercises
that required startup filter.

Workflow: ADMIN HANDSHAKE then REARM; ADMIN GRANT sets a nonzero instance and
finite deadline; RUNTIME ACTIVATE consumes that instance/grant. ACQUISITION
OBSERVE retains a nonzero observation/context revision plus acquisition bounds
and validity. RUNTIME ALLOCATE (opcode 14) allocates a nonreused operation/stream
and immutable envelope without sending any UART frame. The manager durably binds
that returned identity, then START echoes it and queues the non-actuating START.
CANCEL also retires allocated-but-not-started identities. SAMPLE binds
the current epoch/grant/operation/stream, observation and strictly increasing
sequence, finite deadline and typed duties. FINISH/CANCEL close the operation;
REVOKE closes the grant. Status distinguishes local closing, reconciliation and
fault. A matched barrier releases the group; a late receipt cannot clear faults.
RECOVER is administrator-only and starts fresh inhibited reconciliation before
explicit REARM. If a fault abandoned a transmitted prefix, recovery waits until
its original host cutoff before emitting a COBS delimiter and a fresh HELLO;
the delimiter must not complete a still-valid old sample. HEALTH supplies a
finite recorder-health horizon. SAMPLE expiry must also fit the health and
observation-age horizons. Revocation retires grant authorization even when no
operation is outstanding; another ACTIVATE requires a new explicit GRANT.

All unused/reserved fields and unsupported flags reject. Identity-dependent
commands must echo `runtime_nonce` and current grant/operation/stream. Deadlines
are CLOCK_BOOTTIME absolute nanoseconds, with equality expired. Observation
context revision is fixed at 1 in the preview. The software profile caps duties
at 200 permille, grants at 60 s, operations at 10 s and samples at 500 ms.

Events are bounded diagnostics, not durable storage. Overflow latches evidence
loss and inhibits further ordinary dispatch. A consuming EVENTS FD reads whole
records; the manager must persist them and separately track durable intent.
The simulator's reported encoder/output facts never establish physical motion.
Event kind namespaces are REQUEST `0x10000 | opcode`, WIRE
`0x20000 | wire_kind`, CLOSURE `0x30000 | reason`. Status flag bits are
HANDSHAKEN=1, TX_STARTED=2, AWAITING=4 and GRANT_AUTHORIZED=8. A handshake wait must require
HANDSHAKEN before REARM; REARM completes only on READY plus its baseline event.
