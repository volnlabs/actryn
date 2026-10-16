# Robot manager and encrypted relay

`actryn-robotd` embeds the reviewed `wheel.index_step.v1` runtime and binds the
actual Linux authority device. It refuses startup without that device. This
preview supports only the pinned, non-actuating ARM64 QEMU fixture.

The manager runs as root with the shipped systemd restrictions. A root-owned
`/etc/actryn/robot.json` selects `operator_uid` and a distinct nonzero `gateway_uid`.
The operator owns the two mode-0600 sockets under `/run/actryn-robot`: ordinary
administration and reserved closure. The gateway owns the control and relay
sockets, but cannot read `/var/lib/actryn-robot` or open the authority device.
Install the gateway account using `packaging/sysusers.d/robot.conf`, then use
the shipped manager/gateway units; arbitrary service credentials are unsupported.

The gateway forwards encrypted streams from TCP 7443. TLS 1.3 mutual
authentication terminates in the manager. Only a process registered through its
Unix peer credentials and retained pidfd may relay requests. Its exit, heartbeat
loss or replacement closes associated authority. The gateway never supplies an
authenticated principal name or receives the device key.

Local enrollment creates a private key and CSR. An offline site issuer signs the
CSR; local installation verifies the chain, DNS identity and matching key while
inhibited. The operator pins the device leaf fingerprint and installs permitted
workload certificate fingerprints with local principal names/scopes. Principal
revocation takes effect before its durable write. Revoked names remain retired.
Certificate rotation retires established sessions and never rearms a device.
Clock rollback or lost clock-checkpoint progress closes authority.

A normal checkpoint that finishes after the previous 10-second durability
deadline retains its successfully written wall floor and completion evidence,
but latches the clock unhealthy before publishing the new progress timestamp.
This remains true if the watchdog was delayed too. Later normal writes cannot
restore clock health; explicit local recovery is required. The historical idle
checkpoint timeouts remain unattributed: their retained logs do not distinguish
scheduling, writer-lock delay or storage latency.

Use the `actryn robot` commands for enrollment, pairing, preparation, rearm,
grant, activation, query, cancellation, reconciliation, retirement and recovery.
Authenticate the installed workload principal before local preparation. A
prepared binding retains that session's original deadline, attempt and namespace;
reconnect and credential renewal cannot extend it. The ordinary remote methods
are describe, observe, propose, query, cancel and evidence read. All other
methods require the protected local operator transport.

Three shared ordinary request slots each permit at most 64 KiB. Two independent
closure slots permit 4 KiB each. There are eight remote connections, two concurrent
TLS handshakes, four request slots per principal and 128 retained principal slots.
One maintenance worker serializes preparation/enrollment/admission; revocation
has a separate persistence slot and urgent closure never waits for that writer.
One export worker bounds capture reads. The native runtime independently bounds
intents, recording bytes, age and active/staged/retiring work.

## Evidence export

After retirement and explicit recovery have released the capture writer:

```sh
actryn robot export --local --handle operation.json --out evidence-directory
# Or use --pair pairing.json --cert workload.pem --key workload.key.
```

The manager authenticates the retained namespace before reading its capture.
Exports include that key's historical inspection, immutable binding, raw MCAP
batches and checkpoint database. They exclude device/workload keys and the global
intent database. Reads hold the existing capture lifetime lock and reject active
writers, unexpected files, symlinks, hard links and out-of-bounds offsets. Limits
are 8192 files and 64 MiB per capture, 32 entries per manifest page and 16 KiB per
chunk. The CLI creates a new private directory, verifies all file hashes and
retains `INCOMPLETE.json` on failure; it never overwrites a previous export.

Raw remnants and an unknown volatile tail remain evidence of uncertainty.
Metadata-only capture does not qualify for execution replay. A matched controller
receipt is software evidence, not independent physical displacement evidence.

## Validation

Host checks: `cargo test -p actryn-robotd -p robot-rpc -p actryn-cli` and strict
Clippy. `tests/guest.py` is an opt-in test against the exact guest/module/fixture
and installed services, using disposable test-only issuer material. It retains
campaign phases, failures and observations. It does not load a host module,
attach a physical controller or automatically retry failed mutations.
Actual campaign results and remaining release gates are recorded in
`docs/development/progress.md`; the presence of this test is not a passing run.
