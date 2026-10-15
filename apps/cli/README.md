# Actryn CLI

`actryn` is the native JSON CLI for the installed v0.0.1 server and robot services.
Run `actryn --help` for the complete command list. Each invocation makes at most
one operation request; it never retries a mutation or implicitly grants/rearms.
An error report exits nonzero. Installation belongs to release packaging.

Build with `cargo build -p actryn-cli --bin actryn --locked`. The CLI uses the same
bounded protobuf and TLS implementation as the robot daemon/gateway. Local server
RPC uses its native bounded JSON framing.

## Server

Run these on the server as its configured operator (or root):

```sh
actryn server prepare --artifact sha256:REVIEWED_DIGEST
actryn server launch --attempt ATTEMPT_ID
actryn server status --attempt ATTEMPT_ID
actryn server result --attempt ATTEMPT_ID --key REQUEST_KEY
actryn server cancel --attempt ATTEMPT_ID
actryn server export --attempt ATTEMPT_ID --out evidence.json
```

`prepare` returns the generated attempt ID; `launch` starts that prepared attempt.
The artifact digest must already be in the root-controlled allowlist. Result
lookup never calls the model again and respects closed publication. Export
retrieves a finite diagnostic JSON bundle, including available resource counters,
log tails/hashes, broker metadata and observer loss metadata. It validates the
attempt identity and 60 KiB bound, then creates a new mode-0600 file with fsync.
An existing destination is never overwritten. The bundle explicitly says it is
not execution replay evidence. There is no caller-selected helper filesystem path.

With the launcher and broker stopped, root imports the reviewed offline OCI layout:

```sh
actryn server import --layout image-layout --digest sha256:REVIEWED_DIGEST
actryn server discard-incomplete --digest sha256:INCOMPLETE_DIGEST
```

Import verifies the manifest, blobs, fixed files and artifact policy before adding
the digest to the allowlist. `discard-incomplete` removes only that digest's
incomplete import; it cannot remove a complete installed artifact.

The server socket is fixed at `/run/actryn-server/server.sock`; the CLI verifies
its peer UID against the root-protected `/etc/actryn/server.json`. The service
account is allocated during installation, not assumed to have a fixed numeric UID.

## Robot enrollment and pairing

Local robot commands run on the robot as its configured operator or root. They
use `/run/actryn-robot/operator.sock` and verify the daemon peer is root. Local
cancel, revoke and retire use the reserved `/run/actryn-robot/closure.sock` route.

```sh
actryn robot doctor
actryn robot enroll-request --dns robot.example
# Have the public CSR signed by the chosen CA, then install the public chain:
actryn robot enroll-install --cert device.pem --ca ca.pem
actryn robot install-principal --epoch ROBOT_EPOCH --principal developer \
  --pin CLIENT_LEAF_SHA256 --can-propose
```

`describe`, `status` and `doctor` report current daemon state. `doctor` adds the
client's compiled protocol/UAPI versions; it does not invent hardware test results.
Enrollment keeps the device private key in the daemon. The device leaf-certificate
SHA-256 reported by enrollment/Describe is distinct from the CSR's SPKI SHA-256.
Principal installation is an explicit local decision to trust a client leaf pin;
omitting `--can-propose` creates read-only access. Revoke it locally with
`robot revoke-principal --epoch ROBOT_EPOCH --principal developer`.

On the client, use the operator-reviewed **device leaf DER SHA-256**:

```sh
mkdir -m 700 session
actryn robot pair --endpoint 192.0.2.10:7443 --dns robot.example \
  --pin DEVICE_LEAF_SHA256 --ca ca.pem --cert client.pem --key client.key \
  --out session/pair.json
```

The endpoint is a numeric IP:port (IPv6 uses brackets). DNS is the separate
certificate identity. Pairing verifies TLS 1.3, CA chain, DNS, ALPN, mutual client
authentication and the explicit device leaf pin before sending Describe. It saves
only the public endpoint, DNS, CA, device pin and returned robot epoch. Client
private keys are never copied into pairing state or sent to a launcher/agent.
Supply the protected key file on each network command. Pairing issues no authority.

## One operation and recovery

Use the server's generated attempt ID. Save a fresh handle **before** proposing:

```sh
actryn robot handle --pair session/pair.json --attempt ATTEMPT_ID \
  --out session/operation.json
# On the robot, with that handle file and a recent authenticated client session:
actryn robot rearm --epoch ROBOT_EPOCH
actryn robot prepare --handle session/operation.json --principal developer
actryn robot grant --epoch ROBOT_EPOCH --duration-ms 30000
actryn robot activate --epoch ROBOT_EPOCH
# On the client:
actryn robot observe --pair session/pair.json --cert client.pem --key client.key \
  --handle session/operation.json
actryn robot propose --pair session/pair.json --cert client.pem --key client.key \
  --handle session/operation.json --observation OBSERVATION_ID \
  --parent-digest PARENT_DIGEST --left 1 --right 1 --duration-ms 1000
actryn robot query --pair session/pair.json --cert client.pem --key client.key \
  --handle session/operation.json
# On the robot after terminal controller evidence:
actryn robot reconcile --epoch ROBOT_EPOCH
```

Supply the SHA-256 parent digest of the proposal input you are recording as
provenance, and use a fresh authenticated observation. Neither value issues authority. The fixed skill is bounded by
the reviewed profile; the CLI accepts only typed integer deltas and duration.
Grant duration is bounded at 60 seconds and the daemon enforces the remaining
session/preparation/authority lifetime. Local epoch-based commands accept
`--pair FILE` instead of `--epoch HEX` when the pairing file is present locally.

A second operation under the same still-valid grant needs a fresh handle key,
the same attempt and namespace (`robot handle --namespace NAMESPACE ...`), a fresh
observation, and successful reconciliation of the first operation. Creating that
file does not authorize the second operation.

Before opening the proposal connection, the CLI locks the handle, stores the
exact typed proposal and changes its state to `proposal_attempted`, then fsyncs
both file and directory. Competing submissions cannot both win. The CLI refuses
to propose from that handle again, including after connection failure. Do not
copy a handle to evade this protection. A response loss after mutation transmission
returns `outcome_unknown: true`; keep the handle and inspect/cancel it rather than
creating a replacement operation.

```sh
actryn robot cancel --pair session/pair.json --cert client.pem --key client.key \
  --handle session/operation.json
# Offline operator closure is also available on the robot:
actryn robot cancel --local --handle session/operation.json --epoch ROBOT_EPOCH
actryn robot query --local --handle session/operation.json --epoch ROBOT_EPOCH
actryn robot revoke --epoch ROBOT_EPOCH
actryn robot recover --epoch ROBOT_EPOCH
actryn robot retire --epoch ROBOT_EPOCH
```

Cancellation durably closes the local handle before transmission and works before
any proposal reply or operation ID. A failed cancel does not establish remote
cancellation; query the same key and use explicit local closure if required.
`outcome_unknown` describes this invocation, not the outcome of an earlier proposal.
The retained handle state remains visible in remote query/cancel output.

After daemon epoch retirement, network query/cancel/export first discovers the
current epoch using Describe on the same pinned TLS connection, then accesses the
original immutable handle namespace/attempt/key. This does not change the pairing
or handle file. Proposal and observation retain their selected epoch and cannot
revive an old binding. A changed device certificate requires explicit pairing into
a new file with the newly reviewed pin. Historical cancellation reports do not
imply live authority. Recovery, rearm, grant and activation remain explicit actions.

After retiring the namespace and recovering to an inhibited state, export its
retained capture using any handle from that namespace:

```sh
actryn robot export --pair session/pair.json --cert client.pem --key client.key \
  --handle session/operation.json --out evidence
# Or on the robot:
actryn robot export --local --handle session/operation.json --out evidence
```

Export creates a private directory, verifies each bounded file's SHA-256 and
keeps `INCOMPLETE.json` until all bytes and the manifest are durable. An existing
destination is never overwritten. The exported capture preserves unknown tails
and does not claim execution replay eligibility or physical qualification.

## File and transport bounds

State files and output directories must belong to the caller or root. State,
handle locks and private keys must not be readable/writable by other users; output
directories must not be group/world-writable. File reads reject symlinks and
nonregular files. JSON state is capped at 64 KiB, private keys at 8 KiB and
certificate inputs at 24 KiB. RPC frames are capped at 64 KiB; each transport stage
has a 10-second deadline. No CLI secret bytes appear in arguments or JSON output.
The supplied private-key filename is an argument, not the key contents.

## Verification

`cargo test -p actryn-cli --locked` tests durable single-submission handles,
cancellation races, malformed/symlinked state, unknown mutation replies, response
identity, argument bounds, and real in-memory mutual TLS with CA/DNS/pin rejection.
`cargo clippy -p actryn-cli --all-targets --locked -- -D warnings` checks the crate.

`tests/guest_server.py /usr/local/bin/actryn` exercises the installed server CLI as
its configured nonroot operator in the disposable pinned Debian guest. It requires
the reviewed server broker fixture and active packaged services. It prepares,
starts, looks up the offline result, cancels, verifies result suppression, exports
and verifies hashes/bounds/ownership, and rejects overwrite. This test creates and
closes a fresh attempt; it is not a physical qualification test.
