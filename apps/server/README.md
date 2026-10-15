# Actryn Server foundation

This crate implements the independent server launch/accounting path. It does not
establish D2 qualification by compilation or unit tests alone.

## Processes and local protocol

`actryn-launcher` runs as root and exclusively holds the containerd connection.
`actryn-serverd` runs as the configured service UID, never receives the engine
socket and owns a separate broker database. Both take an exclusive state lock
before recovery or socket replacement. Their configuration is the root-owned,
non-group/world-writable `/etc/actryn/server.json`:

```json
{
  "server_uid": 991,
  "operator_uid": 1000,
  "io_device": "254:0",
  "artifacts": {
    "sha256:<64 lowercase hex digits>": {
      "rootfs": "/var/lib/actryn/artifacts/<digest>/rootfs",
      "argv": ["/bin/agent"]
    }
  }
}
```

The root-owned artifact registry is a trusted installation input. The installer
must verify the OCI digest and extracted rootfs provenance before adding an entry;
the launcher does not pull images or infer image identity from a directory name.
Use the **whole disk** major:minor backing the rootfs for the fixed I/O policy.
The parent cgroup must have cpu, memory, pids and io controllers enabled.

Fixed sockets:

- `/run/actryn/launcher.sock`: root or configured server UID only.
- `/run/actryn-server/server.sock`: root or configured operator UID only.
- `/run/actryn/observer.sock`: real privileged observer, verified root peer.
- `/run/actryn/brokers/<generated-attempt>/broker.sock`: bind-mounted into only that
  attempt; host parent is service-private. Peer UID and actual peer cgroup are checked.

Messages use a four-byte big-endian length followed by UTF-8 JSON, at most 65,536
bytes, one request per connection. Operator and launcher requests are:

```json
{"op":"prepare","artifact_digest":"sha256:<digest>"}
{"op":"start","attempt_id":"<returned-id>"}
{"op":"stop","attempt_id":"<returned-id>"}
{"op":"inspect","attempt_id":"<returned-id>"}
{"op":"result","attempt_id":"<returned-id>","request_key":"index-1"}
```

Responses are `{"result":"ok","inspection":...}` or
`{"result":"error","message":"..."}`. Preparation creates a real stopped
containerd task, verifies process/cgroup/namespaces/mounts/device policy and
observer coverage, then retains its PID lifetime and cgroup inode. Start rechecks
that binding. There is no user-supplied OCI spec, path, hook, command, ID allocation
or runtime option. A failed/ambiguous task create remains charged until verified
cleanup. This implementation uses containerd-client 0.9.0's distinct task
Create/Get/Start calls, not `ctr tasks start`.

The `result` operation is available only on the server socket, to its authenticated
operator. It returns `{"result":"call_result","call":...,"value":...}` with the
original stored attested value, or null after cancellation/expiry. It never
allocates or resends work. Native result writes recheck cancellation fences and
the original request deadline at their publication point. Rust operator clients
use `protocol::request_as(path, installed_server_uid, request)`; the default
`protocol::request` requires a root helper peer.

The observer request/status types are in `src/observer.rs`. Registration precedes
task creation. Missing coverage, losses or changed epoch prevents launch. Later
observer loss is an explicit evidence gap and does not pretend installed isolation
has disappeared. Runtime termination is supervised by the launcher; packaging
must restart it and run recovery after a crash. A standalone killed launcher
cannot itself enforce an attempt wall-time deadline while it is absent.

## Broker and durable store

The per-attempt protocol accepts `call` with stable `request_key`, named `method`
and `input`, or `cancel`/`result` with that key. Attempt identity comes from the socket.
Supported methods are `diagnostic.echo`, `model.offline`, and `model.propose`.
Unknown methods reject with an application policy-denial reason.

```json
{"op":"call","request_key":"index-1","method":"model.offline","input":{"goal":"Index both wheels forward","observation_id":"obs-1"}}
```

The offline fixture returns a bounded 10/10 tick, 1,000 ms proposal. Its label is
`offline-fixture`; it is not a model-quality result. The live method uses only
OpenAI Responses, `gpt-5.4-mini-2026-03-17`, fixed structured output, no hosted tools,
no redirects/proxies/retries, 4,096 input text bytes, 1,024 output tokens and a
65,536-byte response cap. The broker binds observation/request identity itself.
Neither method dispatches a robot command. The integration layer must route that
proposal through authenticated Robot admission and the kernel gate.

For live calls, systemd must deliver `openai-api-key` to the **server service only**
at `/run/credentials/actryn-serverd.service/openai-api-key`. Missing credentials
reject before a dispatch reservation. No credentials are read by tests or sent
to the launcher/agent. A timeout, invalid/oversized/ambiguous provider response or
crash retains the external debit. Repeated calls cannot reset their finite call
and output-token budget. These token/request bounds are not an invoice-price
claim; the release must additionally pin and validate applicable provider costs.
A profile requiring an enforceable monetary ceiling must reject the live method
unless it supplies a verified provider-enforced cap; this implementation exposes
no invoice-ceiling guarantee.

The Store API provides SQLite FULL-synchronous intent transactions, prepared and
active capacity, retirement until reap, stable request keys, pre-dispatch durable
reservations, cancellation tombstones, terminal-wins state changes, conservative
restart recovery, bounded output and retained settled usage. `settle` is a trusted
connector operation: only verified terminal work may release its debit. Close a
`PublicationGate` before disk work on cancellation; its publishing callback must
be bounded and nonblocking. Recovery never starts or resends work.

Prepared, running and retiring sandboxes share the two live reservations; cleanup
does not free them early. The fixed preview defaults retain at most 128 attempt
histories (including capped stdout/stderr), 16 stable request keys per attempt and
64 denial records per attempt. History exhaustion rejects preparation; this crate
has no acknowledgement or deletion command that could forgive unresolved work.
These values must remain pinned with the installed release profile.

`Inspection` reports attempt state/outcome, calls and evidence gaps. Normal process
exit, cancellation, unknown outcomes and incomplete diagnostics remain distinct.
Raw capped stdout/stderr and truncation markers stay in the launcher-owned
attempt directory; controlled export/MCAP integration is a separate integration
surface. Successful log draining does not claim arbitrary-media durability.

## Verification

```sh
cargo test -p actryn-server
cargo clippy -p actryn-server --all-targets -- -D warnings
```

`tests/guest_launcher.py` is for the disposable pinned Debian VM **only**. It
requires real containerd and the real observer, writes its guest-only registry and
rootfs fixture, and exercises stopped preparation, execution, cleanup and replay
rejection. It accepts the path of the launcher binary. It must not run on an
operator workstation. Root's retained VM evidence is authoritative for its result.

`tests/guest_broker.py <launcher> <serverd>` installs test binaries under the
root-owned `/usr/local/libexec/actryn-test` so the service UID can traverse to them,
then compiles the static
`broker_agent.c` fixture and runs both native services. It checks the actual
sandbox's network denial, typed offline proposal, denied method accounting,
cancel-before-call tombstone, result lookup/suppression, peer rejection, and cleanup
of a forked descendant. Copy all three
fixture files together into the disposable VM before running it.

Not yet qualified by this crate's unit suite: full runtime negative-access and
resource-pressure tests, storage-failure/crash campaigns, complete evidence
export/replay, live-provider suitability and an independent installation.
