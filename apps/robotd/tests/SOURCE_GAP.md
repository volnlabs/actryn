# A11: actual kernel event omission

`source_gap.py` is an opt-in campaign for the pinned, disposable AArch64 QEMU
Robot guest (`6.12.111+deb13-arm64`). It uses the installed production manager,
authority module, controller fixture, CLI and Python SDK. It never issues a
grant, activates a preparation, proposes an operation, or permits nonzero
outputs. This is software evidence, not physical qualification.

The campaign requires an existing enrolled identity and authorized workload
certificate; it does not enroll or replace either. Supply the locally reviewed
device leaf pin, loaded manager SHA256 and loaded module build-ID note SHA256.
Use a new output directory and schedule exclusive guest ownership with the
other acceptance campaigns. Do not launch it against a live robot.

The procedure is deliberately narrow:

1. Inspect the guest, binaries and no-authority status. Recover and rearm once.
   Pair through the pinned TLS endpoint, retain a fresh attempt/namespace/key,
   and prepare locally under an authenticated workload session. Wait for healthy
   preparation and at least one durable kernel event.
2. A guest-local helper opens the trusted-root, non-exclusive `EVENTS` role and
   pins the manager with `pidfd_open`. It sends `SIGSTOP`, verifies every manager
   thread is stopped, performs exactly one nonblocking 216-byte event read, and
   closes that FD. A local `finally` sends `SIGCONT` exactly once, including when
   the read or validation fails. The requested total pause limit is 500 ms;
   exceeding it fails the campaign. Raw bytes and timing are persisted after
   resume in `/var/tmp/actryn-a11-<random>/omission.json`.
3. Poll read-only status for an unhealthy event stream, inhibited authority and
   `SourceGap`. Retire once, recover once, and export the retired capture through
   the production CLI. Decode its actual checkpoint/MCAP bytes using the
   production `evidence::Recorder::recover` reader.
4. Require one durable `SourceGap` with the original runtime epoch, exact external
   sequence `previous -> stolen -> observed`, unchanged cumulative loss, original
   event timestamp, and zero grant/operation/output status. Require contiguous
   recorder ordinals around that external gap, the kernel source fault frontier,
   no checkpoint/remnant errors, and execution replay ineligibility. Independent
   clock or recorder pending-age faults also fail this campaign.

The driver has a shared 256-entry event FIFO; the fixture normally emits one
observation every 100 ms. A nominal overflow therefore takes more than 25.6 s,
which would also cross the manager's clock and evidence deadlines. This test
instead omits one actual event through the existing read API, with no new
production injection command. It does **not** establish FIFO-overflow behavior,
scheduler latency bounds, physical effects, or complete execution replay.
The recorded pause interval runs from the STOP request through the successful
CONT syscall; thread-stop and read timestamps are retained separately. It is
not a scheduler or signal-delivery latency guarantee. Subsequent successful
read-only manager status is required before retirement/recovery can complete.

Build the host reader and run the local checks first:

```sh
cargo test --locked --offline -p actryn-robotd --all-targets
cargo build --locked --offline -p actryn-robotd --example source_gap_reader
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/robotd/tests -p test_source_gap.py -v
```

After explicit guest handoff, supply the existing reviewed paths and hashes:

```sh
python3 apps/robotd/tests/source_gap.py \
  --ssh-port 26221 --tcp-port 27443 \
  --ssh-key .cache/qemu/id_ed25519 --known-hosts .cache/qemu/known_hosts \
  --ca "$A11_CA" --cert "$A11_CERT" --key "$A11_KEY" \
  --principal "$A11_PRINCIPAL" --dns robot.test --pin "$A11_DEVICE_LEAF_SHA256" \
  --manager-sha256 "$A11_MANAGER_SHA256" --module-note-sha256 "$A11_MODULE_NOTE_SHA256" \
  --cli target/debug/actryn --reader target/debug/examples/source_gap_reader \
  --output artifacts/robot-source-gap-01
```

Every mutation is sent once. Lost replies remain explicitly unknown and fail the
campaign; only status and the same retained helper artifact are subsequently
read. If resume is unconfirmed, the campaign stops further mutations. A killed
helper (`SIGKILL`), guest failure, or host failure cannot be covered by its
`finally`; an operator must inspect the retained state before any next action.
No timeout, freshness or durability threshold is widened. The outputs retain
phase timings, source/binary pins, raw status and event bytes, full decoded fault
metadata, capture hashes and failure details. An incomplete capture is a failed
result, never filled in from the stolen event. A fresh numbered campaign is
required after reviewing any failure; this harness does not retry mutations.
