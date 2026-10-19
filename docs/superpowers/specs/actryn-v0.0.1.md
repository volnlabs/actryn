# Actryn v0.0.1 developer-preview specification

Approved 2026-10-16. Status: implementation in progress; not a qualified release.

Amended 2026-10-19 by the sole maintainer: use the
[solo release plan](../plans/2026-10-19-actryn-solo-preview.md). Utkarsh Maurya owns
release review/signing, provider credentials, evidence retention and the manual
fresh-install rehearsal. Independent A14 is deferred until another developer is
available. This does not relax any technical acceptance or authority contract.

## Product boundary

An external developer installs a supported Linux environment, prepares one isolated
OCI agent and one fixed `wheel.index_step.v1` skill, authorizes locally, runs typed
proposals through the actual kernel authority/serdev path, finishes or interrupts,
reconciles and inspects evidence. A credential-free offline demonstration and one
pinned live-model acceptance run are required. No physical actuation is supported.

The [execution plan](../plans/2026-10-16-actryn-v0.0.1.md) defines milestones M0-M4
and acceptance A01-A16. The two existing architecture contracts remain normative
for identity, grants, cancellation, normal finish, recovery, bounded resource
accounting, capture durability and gateway trust. This document narrows deployment
scope; it does not relax those contracts.

## Target and implementation

Debian 13 x86-64 server/development host, Debian 13 ARM64 QEMU `virt` robot guest,
and an external deterministic controller fixture over an emulated PL011 UART.
One UART is the console; a separate UART has an exclusive serdev child. Never map
a physical actuator/device into this profile. The fixture uses a separate
non-actuating device-identity namespace and labels all encoder data simulated.

Rust services/CLI/reference reducer and Python SDK use original Apache-2.0 code
(explicit user license decision 2026-10-16). The narrow C loadable module uses
GPL-2.0-only. This selects the architecture's C fallback for the Linux 6.12 preview;
it does not require a Rust kernel API backport or two production authority drivers.

Use maintained systemd/containerd/TLS/Protobuf/SQLite/MCAP facilities. The restricted
launcher uses containerd's separate task-create and task-start APIs; `ctr tasks
start` cannot provide the required intervening policy verification checkpoint.

The [software profile](../../../targets/qemu-arm64-fixture/1/profile.toml) contains
finite engineering policy values. They are not measured timing guarantees or
physical output limits. Exact image/kernel/configuration/compiler/runtime hashes
must be frozen and tested before release. Family names alone are not compatibility.

The [wire specification](../../../schemas/fixture-wire-v2.md) fixes cross-language
framing and semantics. The kernel UAPI is canonical under `kernel/include/uapi/`;
userspace bindings and ABI tests must detect drift. Unknown versions, unsupported
capabilities, stale identities and mismatched target tuples reject.

## Public behavior

- Python SDK: describe, observe, propose, query and cancel. Create a stable request
  handle before sending; timeout cannot replace that handle or repeat uncertain work.
- Operator CLI: doctor, local enroll/pair, attempt/instance prepare, grant issue,
  activate, start, inspect, cancel/revoke, reconcile, rearm, evidence export/replay.
  Pairing/installation/query/resume never grants authority or rearms.
- One fixed skill accepts bounded signed left/right tick deltas and finite duration,
  referencing a retained observation. It emits `WheelDutyPair`; it owns no grant table
  or raw transport. Target success and timely controller reconciliation are distinct.
- One active attempt and operation in the standard demonstration; finite prepared,
  active, retiring and unresolved external resources remain charged until settled.
- Evidence separates admission, transmission, controller facts, lifecycle and
  simulated/physical observation. Controller acknowledgement is not physical success.
- Hosted connector: OpenAI Responses `gpt-5.4-mini-2026-03-17`, approved structured
  schema and finite reservations; credentials remain in the broker. No automatic
  request retries, arbitrary URLs or provider-hosted tools.

## Promotion and limits

Software D0/D1, D2/D3 and the maintainer's personal fresh software installation
and recovery rehearsal are release requirements. Original independent A14 stays
DEFERRED and must not be reported PASS. Physical endpoint comparison/selection, qualified firmware,
physical D4 and robot-deployment D5 remain open; no physical target artifact ships.
Required signatures, live credentials, off-host evidence restoration and the
human maintainer's rehearsal remain release inputs. The same person may own
these duties. A dedicated encrypted release key may be established for this first
release; disposable fixture keys are never release identities.

Release claim, only after the required gates pass: **Qualified by the sole
maintainer; independent installation and physical qualification have not been
performed.** Use the same claim in release notes and the qualification bundle.

Server may promote independently after its own acceptance; the combined preview
requires the actual kernel/backend path. Build/test results do not imply publication.
No remote push, protected/default-branch merge or release publication is included
without separate authorization. Candidate completion requires every technical
acceptance gate, real target tests, the maintainer rehearsal, reviewed signatures
and tested evidence restoration. Independent installation is a later additive
qualification record for the exact tested release, never a retroactive claim.
