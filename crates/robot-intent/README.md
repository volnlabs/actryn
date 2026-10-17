# Robot request-key intent registry

This crate durably binds an authenticated attempt-scoped request key to one
immutable intent and kernel-allocated operation epoch. It implements the request
identity/cancellation portion of the platform contract. It owns no effective
grant table, writes no controller frames and cannot grant/rearm authority.

The embedding manager authenticates principal/attempt bindings before issuing a
`Namespace` handle or permitting historical queries/cancellation. Agent request
fields cannot select another principal, attempt, runtime nonce or operation ID.
The SDK's stable request handle exists before any proposal leaves the agent.

## Manager integration

Implement `Authority` using the real kernel UAPI:

- `allocate(&Intent)` reserves non-dispatchable operation/stream IDs using the
  non-UART ALLOCATE path. It must never START or write a task frame.
- `submit(&OperationId, &Intent)` performs fresh kernel admission, including the
  live grant, namespace/instance, context/observation and absolute deadline checks.
  It returns without waiting for UART completion or controller reconciliation.
- `close(&OperationId)` invokes the existing urgent allocated-operation close
  path, including cancellation before START. `CloseAck::Requested` and
  `LocallyClosed { transition }` remain distinct facts. Neither is reconciliation.

Callbacks are short synchronous calls, made under the registry ordering mutex.
They must not touch storage, wait for UART/reconciliation, or reenter this crate.
The kernel retains the sole effective authority and its own serialization order.
The registry mutex is not a kernel authority mutex.

During startup/preparation:

1. Call `Registry::open(path, runtime_nonce, limits, Arc<dyn Authority>)`. Supply
   the actual fresh kernel runtime nonce after handshake/registration. This is a
   preparation call that may wait for storage; it never resumes old authority.
2. Call `prepare_namespace(attempt, namespace_id)`. Both IDs come from the trusted
   manager's authenticated attempt association. Preparation queues persistence;
   run `writer.flush()` on the storage thread and require `namespace_ready()`
   before allowing proposals. It grants no control permission.
3. Run `Writer::run(stop, interval)` on a dedicated storage thread, or call
   `Writer::flush()` there periodically. Do not flush or join that thread from an
   urgent cancellation/revocation path. Poll `Registry::health()` independently;
   `revoke_required` asks the manager to use its existing urgent global close path.

`propose(&Namespace, key, Intent)` first reserves bounded key/job capacity and
records the immutable key/digest in a non-dispatchable phase. It then obtains the
complete `OperationId` tuple from the kernel. The tuple contains device identity,
boot/session, runtime nonce, grant, instance, operation and stream; mismatched,
zero or reused allocation identity faults rather than substituting IDs.

The returned `Snapshot` is an **internal pending result** and may contain allocated
IDs before their binding is durable. A network response must preserve that pending
meaning and stable request handle; it must not claim durable binding/admission
from this return. Wait/query for the actual durable revision and resulting phase
before reporting stronger facts. The writer commits the complete intent outside
the mutex, then reacquires it and rechecks revision, terminal fence, namespace,
epoch and registry health before synchronous kernel `submit`. That callback
performs the fresh live eligibility checks. Sample dispatch inside the resulting
operation has no per-sample registry fsync.

All immutable fields are retained: digest, configuration digest, instance/grant,
context revision, deadline, observation and bounded typed-skill payload. Same-key
same-intent calls only return the existing record; they never enqueue, allocate or
resubmit. Changed digest or any changed immutable field returns `Conflict`. Query
by namespace/key or complete operation ID is read-only and non-admitting.

## Cancellation and durability

`cancel(&Namespace, key)` and `cancel_operation(&OperationId)` use the same short
ordering mutex as submission. They set the terminal fence and call urgent kernel
close immediately for an allocated operation **before** queuing storage work.
Thus cancellation either fences the final submit check, or follows submission and
closes those exact allocated IDs. A blocked SQLite writer cannot hold this mutex.

Absent-key cancellation consumes reserved key capacity and retains a tombstone
fence before returning. A delayed proposal cannot allocate while that tombstone
is pending. It has no original digest to compare; all later proposals resolve to
its terminal cancellation rather than binding new work.

Cancellation returns `Phase::CancelPending` until the tombstone transaction is
committed. Only `Snapshot::key_cancelled_durable()` establishes
`KEY_CANCELLED_DURABLE`. `Closure` separately reports kernel close requested,
locally closed, not allocated, or failed/unknown. Durable identity closure never
proves downstream reconciliation or physical stopping. Lost acknowledgements are
resolved by query, without another admission attempt. Repeated cancellation shares
the existing pending/durable fence and does not relabel the kernel close reason.

SQLite applies monotonic revisions in one transaction and never replaces a
terminal record with nonterminal work, even if delayed work carries a higher
revision. An old intent/status commit cannot overwrite a cancellation tombstone.
Storage failure preserves existing durable terminal facts, marks unsettled work
unknown or cancellation-pending with `persistence_failed`, urgently closes known
unsettled operation IDs, retires namespaces and denies new effects. A failed
cancellation commit never becomes a successful durable cancellation response.

`complete()` is an internal manager report for completion already established via
the kernel/controller lifecycle. It neither finishes nor reconciles control by
itself. A cancellation fence wins over a later completion report. Terminal
bindings/tombstones are retained; they are not reused for another operation.

`reconcile(namespace, key, operation)` records a trusted manager's matched kernel
reconciliation. It verifies the complete stored operation identity and queues a
reserved control transaction; it never dispatches work. Submitted work becomes
`Completed`. Cancelled work keeps its cancellation phase and closure, advances
its revision, and gains a marker in the additive `reconciliations` table. Each
marker contains the namespace, key, exact terminal revision and 80-byte operation
identity; the marker and record revision commit atomically. Repeats are
idempotent. Public reconciliation credit requires that exact revision to be
durable, with no persistence failure. A durable terminal `Completed` row already
records manager-established reconciliation, including in the original format.
Neither representation invents a task verdict or physical stopping evidence.

The optional table retains at most one marker per existing key under the same
key count and database byte limits. Startup and historical inspection audit all
markers for duplicate/orphan, revision/identity and eligible-phase mismatches;
invalid proof rejects the read/open. Opening an old format-1 database adds only
the empty table, with no reconciliation backfill or rewrite of legacy terminal
records. A missing table or marker never credits an allocated cancellation.
Historical inspection does not create the table. Old readers ignore the additive
table and remain conservative about cancellation reconciliation; this is a file
format property, not qualification of a software downgrade. Normal fresh-epoch
startup still retires namespaces and marks unfinished work unknown, never
resubmitting it. Preserve evidence before any managed software transition.

## Finite policy and persistence

Default limits are engineering policy, not timing guarantees:

| Resource | Default |
|---|---:|
| All retained key rows, including history and tombstones | 1,024 |
| Key slots reserved for absent-key cancellation | 64 |
| All retained namespace rows, including retired history | 16 |
| Persistence jobs, including the worker's in-flight job | 128 |
| Job slots reserved for cancellation/retirement/completion | 32 |
| Immutable typed-skill payload | 4,096 bytes/key |
| SQLite main database quota | 16 MiB |

Pending job count is not released when the worker starts waiting for storage;
submission-status persistence reuses its existing job reservation. Ordinary
exhaustion rejects new proposals before kernel allocation and preserves active
work. Existing allocated cancellation invokes urgent close even when no further
persistence slot can be obtained. If an absent tombstone cannot retain its key or
persistence reservation, the namespace is retired and every allocated operation
in it is urgently closed. No delayed proposal may pass that retired namespace.
Insufficient persistence is reported as pending/failed, never durable success.

The registry uses pinned `rusqlite` 0.40.2 with bundled native SQLite, FULL
synchronization, DELETE journaling, 4 KiB pages and in-memory temporary storage.
Its main-file `max_page_count` quota is finite and verified on reopen. The quota
is not a total filesystem/block quota: rollback journal, lock file and filesystem
metadata add bounded storage overhead. Epoch-history rows also consume that DB
quota. Exhaustion requires explicit servicing; there is no eviction, automatic
repair, truncation or deletion of cancellation history. Preserve the database and
its namespace/epoch history across manager/image restarts.

An exclusive OS lock prevents two registry writers opening the same path. Do not
rename/delete the lock or database to reset it, copy it to a competing manager,
or use distinct aliases for the same database. The selected local filesystem
must honor SQLite/lock/fsync contracts; arbitrary media failure is not covered.

## Restart and historical access

Every successful open inserts a fresh never-before-used manager epoch, durably
retires old namespaces and converts unfinished records to `OutcomeUnknown` before
exposing the registry. Reusing an epoch or reopening a namespace ID rejects.
Cancelled durable tombstones and other terminal records retain their facts.
A lost uncommitted tail cannot recover authority: the retired namespace and fresh
runtime epoch prevent delayed work from becoming eligible even if its cancellation
commit was lost. No recovered record is automatically allocated, submitted or
resent under a new key.

`lookup_namespace()` returns a historical capability with `id`, `attempt`,
`runtime_epoch` and `retired` accessors; it cannot activate or prepare that
namespace. The manager must authorize historical query/cancel above this API.
Kernel rejection of old IDs is not interpreted as downstream reconciliation.

## Verification

```sh
cargo test -p robot-intent
cargo clippy -p robot-intent --all-targets -- -D warnings
cargo fmt -p robot-intent -- --check
```

Tests use real SQLite files and independent expected event order. They cover
paused persistence, a second connection holding SQLite's exclusive lock, cancel
between commit and the fresh final check, cancellation after submission, lost
ID/ack responses, reversed persistence order and terminal precedence, changed
intent retries, finite key/job reserves, namespace retirement, storage failure,
unknown submission, acknowledged-tombstone preservation and fresh-epoch restart.
The terminal-wins predicate was observed failing before implementation, then
passes alongside the real transaction and interleaving tests.

These callback fixtures do not establish actual kernel/UART behavior. Production
ioctl wiring, process-death integration, power-cut durability, manager credentials,
controller reconciliation and physical qualification remain separate evidence.

`inspect(path, attempt, namespace, key, limits)` opens SQLite read-only with zero
busy wait, validates the bounded supported format, and distinguishes a missing
namespace from an absent key. It accepts no Authority callback. Unfinished
records are projected as `OutcomeUnknown` without writing a new revision,
resending or restoring authority; terminal durable tombstones remain terminal.
The embedding manager must authenticate the principal/attempt association using
its retained preparation binding before exposing this historical route.
