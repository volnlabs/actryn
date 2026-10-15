# Pinned preview OCI agent

The offline preview asset is an OCI Image Layout 1.0.0 using the OCI image-spec
v1.1.1 manifest/config/layer formats. It contains one uncompressed USTAR layer with
exactly `bin/agent`, `etc/actryn/input.json` and `etc/actryn/input.schema.json`.
The rootfs directories required by the fixed sandbox are created by the importer.
The image configuration fixes `/bin/agent`, UID/GID 65532, `/tmp`, and the
`offline-preview-v1` broker profile. The broker independently permits only
`model.offline` and `diagnostic.echo` for this profile. Installing credentials on
the server does not grant this artifact live-model access.

The agent sends one bounded `model.offline` request through the existing
per-attempt Unix socket. It validates the broker-attested response and emits a
JSON proposal for `wheel.index_step.v1`, without issuing authority. Its stable
request key is `preview-1`; the packaged input is credential-free. The input's
`offline-preview-reference` is diagnostic provenance, not a robot observation or
permission to move. The external workflow must acquire a fresh robot observation
and explicitly authorize locally. The agent keeps its attempt alive for 60 seconds
after output, within the launcher ceiling, so an operator can inspect the broker
result before publication closes. It never retries a request.

## Build

Use the release workspace lock and Rust 1.92.0. The supported server architecture
is Linux amd64; the resulting agent is a static ELF without an interpreter.

```sh
CARGO_BUILD_JOBS=1 RUSTFLAGS="-C target-feature=+crt-static -C debuginfo=0 -C strip=symbols --remap-path-prefix=$PWD=/actryn" \
  cargo build --locked --release --target x86_64-unknown-linux-gnu -p actryn-preview-agent
python3 packaging/agent/build_oci.py \
  --agent target/x86_64-unknown-linux-gnu/release/actryn-preview-agent \
  --out offline-preview.oci
```

The builder prints the actual manifest digest. It uses Python's maintained
`tarfile` USTAR writer, fixes ordering/modes/UID/GID/timestamps, and rejects dynamic
ELFs. The OCI manifest covers the image configuration and layer; the layer covers
the agent, input and schema. Packaging is byte-identical for identical input
bytes. Cross-machine compiler reproducibility is not claimed by that packaging test.
There is no network pull, mutable tag resolution or shell command inside the agent.

The software guest campaign `oci-preview-guest01.log` used:

- Manifest: `sha256:c3013959f5cca4a2275fa5f26de6f030dcc011241dbbe5961993a406e2e53d45`
- Static agent: `sha256:5632516582d0ea2d192e838044a302925fbcd3267f6cd6f6e5aa1e275d5f9ca1`

Those are evidence pins for that build, not universal hashes for later source changes.

## Separately pinned live profile

`live-preview-v1` permits only `model.propose` and `diagnostic.echo`; it does not
permit the offline model method. The same static client reads the digest-bound
`mode: live` input, sends one request, and accepts only the pinned
`gpt-5.4-mini-2026-03-17` result. Generate the policy description with the exact
server release that will import and run the artifact:

```sh
actryn-artifact describe-live-policy > live-policy.json
python3 packaging/agent/build_oci.py \
  --agent target/x86_64-unknown-linux-gnu/release/actryn-preview-agent \
  --profile live-preview-v1 --live-policy live-policy.json --out live-preview.oci
```

The OCI configuration includes the fixed model and server policy SHA-256. Import,
prepare and start reject a different policy, even if the image itself has a valid
content digest. The policy covers the OpenAI Responses endpoint, model snapshot,
prompt, strict target schema, explicit `reasoning.effort: none`, output-token and
transport limits. The supported reasoning setting is documented in the
[official model reference](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
It is a latency choice, not a guarantee of response time or Robot freshness.

Only the server reads the fixed systemd `openai-api-key` credential. An operator
must install the protected credential and the documented service drop-in before
live inference. The image, agent, launcher and OCI metadata contain no credential.
The client has no direct network access, and the broker uses one fixed HTTPS
destination without proxies, redirects, hosted tools or retries. Requests have a
30-second transport deadline, 64 KiB response limit and 1,024 output-token ceiling;
the durable broker additionally bounds calls, concurrent jobs and retained bytes.
These are token/call/byte limits, not an invoice ceiling. Unknown external outcomes
retain their reservations, and cancellation suppresses late output.

The supplied `live-preview-reference` remains diagnostic input, not trusted Robot
sensor evidence. The combined workflow must acquire and retain an actual Robot
observation before inference and keep its original one-second freshness limit.
No delayed model result may substitute or silently refresh that observation.

`guest_live_acceptance.py OCI_DIR DIGEST --expect missing-credential` verifies the
installed real sandbox fails closed without a provider credential and performs no
external debit. `--expect completed` requires an operator-installed credential and
makes one real provider call; it never substitutes a fixture result or retries a
failed/unknown call. The harness preserves and reports the attempt and result.
Neither a successful model proposal nor a software fixture qualifies physical motion.

The missing-credential campaign `oci-live-missing-credential-guest01.log` passed
with manifest `sha256:a16322353bf2af48ecbc2d0fac50ce19ddacd3d3138283b6d739efa7e4559c89`,
static agent `sha256:64a3c208a94616dc161b5adb73909b79bad76e831810ef7ab55e52e4615294a9`,
and model policy `sha256:af9412c8b9c37edc8e9aaeb4d4aec098bb787748f6e8142592814874e7eaf7c5`.
No live provider success is claimed by that test. `oci-preview-guest02.log` also
passed the offline workflow with the updated server and the earlier offline pin.

## Install and approve

The release installer must supply a root-owned OCI directory whose path ancestors
are not writable by other users, the expected digest from verified release
metadata, and a root-owned `/etc/actryn/server.json` with the allocated service UID,
operator UID and actual cgroup I/O device. Initial `artifacts` may be empty before
import. The state and broker directories/account must already exist. The installer
owns their setup and service supervision.

Stop both server services before importing. The importer obtains their lifetime
locks and its own exclusive import lock; running services prevent approval changes.

```sh
systemctl stop actryn-serverd actryn-launcher
actryn-artifact import --layout /root/offline-preview.oci --digest sha256:EXPECTED_MANIFEST
systemctl start actryn-serverd
actryn server prepare --artifact sha256:EXPECTED_MANIFEST
```

Import requires root and the explicit expected manifest digest. It verifies the
index, every referenced SHA-256/size, supported architecture/configuration, and the
layer contents. Maintained `tar` 0.4.46 parses raw entries; the importer writes only
three exact allowlisted paths with `create_new` and `O_NOFOLLOW`. Links, special
files, duplicates, extension/sparse records, traversal, arbitrary paths, multiple
layers, compressed layers and image-selected runtime configuration are rejected.
No image hooks, environment variables, mounts or entrypoint arguments become
launcher authority.

Each layer is at most 16 MiB, the ELF at most 8 MiB, input at most 4 KiB and schema
at most 8 KiB. There are at most eight installed/incomplete registry slots and one
importer. The registry retains both verified OCI blobs and the expanded fixed
rootfs, for a conservative bound below 256 MiB across eight slots, plus small
metadata. Extra unreferenced source blobs are not copied. The release profile does
not support arbitrary OCI images.

Files/directories are fsynced, sealed against unprivileged writes, completed with
a marker and atomically renamed under `/var/lib/actryn-artifacts/SHA256`. The
root-controlled approval map is replaced only after complete validation. Repeating
an identical complete import verifies it and is idempotent. Prepare and start
both compare the installed file set and contents with the digest-bound OCI layer.
An arbitrary rootfs directory and a syntactically valid invented digest no longer
pass launch validation. Trusted root can replace the program itself; this remains
a trusted-Linux/administrator boundary, not hostile-root isolation.

## Interrupted import

An interrupted `.incomplete-SHA256` slot is never launchable and still consumes
capacity. A complete slot whose approval update was interrupted is retained but
cannot be launched until its digest is present in the approval map. No active
artifact is evicted to make room. With services stopped, explicitly discard only
the unfinished staging/config temporary file for that digest:

```sh
actryn-artifact discard-incomplete --digest sha256:EXPECTED_MANIFEST
actryn-artifact import --layout /root/offline-preview.oci --digest sha256:EXPECTED_MANIFEST
```

The recovery command accepts no path, never removes the installed slot, and does
not modify the active approval map. A malformed or altered installed slot remains
an operator-visible failure; it is never silently overwritten.

## Tests and evidence

`cargo test -p actryn-server -p actryn-preview-agent --locked` covers digest/size
mismatches, malformed or oversized layers, links/duplicates/unapproved paths,
incomplete slots/capacity, content tampering, profile tool denial, typed agent
input/replies and prevention of a second local submission. Broker durable accounting
remains authoritative after process or host loss; the agent's tmpfs marker alone
is not durable host-restart storage.

`python3 packaging/agent/test_build_oci.py` checks deterministic content-addressed
packaging and rejects an ELF interpreter. `guest_acceptance.py OCI_DIR DIGEST` is
for the disposable installed Debian server guest with the imported binaries and
stopped services and an already-valid approval map. It preserves approval and attempt history,
checks wrong-pin rejection, idempotence, lifetime-lock denial, tamper-before-start
rejection, incomplete-slot cleanup, the real isolated broker proposal, cancellation, result suppression and
cgroup cleanup. It requires the native CLI at `/usr/local/bin/actryn` and configured
operator UID 1000. Software fixture success does not qualify physical actuation.

Existing server guest fixtures now package their static test entrypoints through
`guest_artifact.py`. Supply importer/builder paths as extra arguments, or install
`/usr/bin/actryn-artifact` and `/usr/share/actryn/agent/build_oci.py` with its two JSON
assets. Fresh disposable fixture state is required; numeric UID991 there remains
a test-only placeholder, not the packaged service identity.

Primary sources:
[OCI layout v1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/image-layout.md),
[OCI manifest v1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/manifest.md),
[tar 0.4.46 raw entries](https://docs.rs/tar/0.4.46/tar/struct.Entries.html#method.raw).
