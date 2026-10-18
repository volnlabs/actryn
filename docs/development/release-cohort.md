# Release cohort and case evidence

Read-only source/evidence reconciliation at checkpoint `b85e1bf`, 2026-10-18.
This additive map closes no whole D2 or A01–A16 row. It records selected bytes,
actual case evidence and the specific work still needed to make a release claim.
The [approved matrix](../superpowers/plans/2026-10-16-actryn-v0.0.1.md#acceptance-matrix),
[D2 contract](../superpowers/specs/architecture.md) and
[platform profile rules](../architecture/platform-release-contract.md) remain authoritative.
All hashes below are SHA-256. Artifact links refer to retained, ignored local
evidence; pushing this document does not back up those files.

## Selected artifacts, not a homogeneous build

The installed Server is disposable TEST manifest
`f32f1c85ff58095034d7b82f80e59454fac826b83760f7013a585a27025c54ad`, with payload
`c7db8cdb7784f0b6e63a9e5e7f5de55740e269076da3c81072d7eda67b881097`.
Its unsigned reference is `fbfc394a2e710cadf738596830dcfc1b7f778e99b8a1336d85a9bf2a64547c78`.
The 27-entry [component map](../../artifacts/server-device-policy-package01/component-map.json)
is `51d45112d30e6d74c2e8ebfc91810b90f35b2f44b89d60f335ffe7da057f78f0`.
Only the launcher executable and its unit changed from the preceding Server package;
the other 25 payload bytes, modes and licenses were preserved.

| Server payload | Selected hash | Build origin / boundary |
|---|---|---|
| `bin/actryn-launcher` | `17a0d39250fb67c20b3397ddeeb5201cbd0f650426e06a12bcae918362996b24` | `14afd962b9bea0986a4507230c2dd5710c52dca9`; integrated as `2e93ccd` |
| `units/actryn-launcher.service` | `778d4698d09a94b8a94a6d4981a39fd324ec6d42bf7c2191aee8d9e41a4f9acb` | Same source; adds launcher `CAP_BPF` |
| `bin/actryn-serverd` | `afef317ba581fe2feedf24bd46c244c17fdbd5aacf4b75dd62058a64a93ada5b` | `8d6e71df39738fe742421348e6c16d68d1cbb727` |
| `bin/actryn` | `f5840d33b5ffff7b9de58cf32581299fb25289c186ba38f1ede69a1f9c42443c` | `544c3824a486097ca30b66b56220a148d9bbd742`; importer correction |
| `bin/actryn-observer` | `bf2b4d2214940722c8ac3e5f11c67321787834126a0bdb7c787cc76f88537a7c` | `770c87915b329e4c597cc298f4cc02ad74fcc157`; reused binary |
| `lib/observer.bpf.o` | `13c4882895fb92567c34abdc1a77a0c00b184cbe61e7af621f3547c9887b734d` | Original build receipt unavailable; later byte-identical matching build at `c72bfe0` is separately retained |
| `bin/controller-fixture` | `d1176146f8b56f21d644bc75c2b9fe686d342b0d8f09ca61532e726276013842` | `2ec9da05bce8f14caff50ad79d0eab9ca67b5600`; reused binary |
| `share/agent/offline-oci.tar` | `8f0656fc10fb7b78e4667f16ce0efa9d9eaf8c8ec84559fbf35408276b35b928` | Packaged offline artifact; distinct from imported capacity-diagnostic and D2 test artifacts |

The installed Robot is disposable TEST manifest
`d77a269823b55ba8fe2541be15b3202651489fdd3c784cab69cd242821a2f012`, with payload
`3ddf8ff34ea418b16813c522718beb85da7c02c7aebc40fa6d4daeec5c276367`.
Its unsigned reference is `dadd347413b23833d1272bbdf0c45b0e46259b5e8bdd3e40dcc0a907eedbca6a`.
The 17-entry [component map](../../artifacts/robot-reconciliation-package01/component-map.json)
is `80ca5934debfd7ad2dec6bc4baad5ad497ca07dd218083ae4066549cfd76bd9c`.

| Installed Robot payload | Selected hash | Build origin |
|---|---|---|
| `bin/actryn-robotd` | `e36d5b2857bfa85b9042d529246b0b173c9cc4cac8c7686c3a6bf047a2ce372a` | `8d6e71df39738fe742421348e6c16d68d1cbb727` |
| `bin/actryn` | `4102e793c48fc43767680ed3c9cf4ffd2f8512171271e3340ab2632090fd1fc5` | `544c3824a486097ca30b66b56220a148d9bbd742` |
| `bin/actryn-gatewayd` | `8705d2ca43ec18440a8328e1cb24b0de12ed7858c2960548809d516b0f12822f` | `a47623935380d37310154fbfa0d8ce7a4294f53f` |
| `module/actryn_authority.ko` | `a49fd1a48bbdc39447a78fc0b0714e2e713c34f4fe25c11e989a790778291112` | Module16, source `d3f48e8694faac2ae4f360e8d4d010824d50ec0a` |

Both roles select profile `6b9f174af8b018e0cf95bfd282ed52b5385d364ebe7e372d54ce6a91d1d99be8`
and build inputs `60ec99a5d032831a94c36036555a2c9b1b969fa3f2e9436293d521459f0e1831`.
The Robot DTB is `b7a13e2f87dccf996274d65e91603b988b4d170bfa3ca9f2610f173d0dcc2011`.
These identities do not establish current package/provider equality on every test disk.

**Final Robot package: UNSELECTED.** Installed d77/dadd retains INSTALL.md
`a0a5e4ee942146bfa60e7274a324ed26b7284c7defd12e1597e0ec6ef2fcc153`
and notices `d651b22f850ba8c1c40390a407835838cdf4aff50e5d56e7bfac0b0a32bd89b9`.
The separately reviewed alternatives are INSTALL.md
`c8b5f4a7e47e06b198b511bdd8c9ba9dae35018f078afc32bfbf629c08890add`
and notices02 `98ec4b48f120976337d35ff57ea16e4b56b18c9c10406a237206c401d410a985`.
`c8b5…` is a document hash, not a package manifest. Before selecting a final
Robot candidate, merge those two selected assets with the dadd runtime deliberately,
verify all 17 entries/modes/licenses and the remaining 15 entries byte-identical,
and record the new manifest/payload and source-material references. This merge
has not been performed here. The older `878732d8…` unsigned cohort has older
runtime binaries and cannot stand in for that selection. Neither TEST signature
nor a notices-text check supplies release qualification or custodian approval.

## Source-impact boundaries

The following comparisons read retained source archives, without rebuilding or
using a current branch as a substitute for a component's build source.

| Comparison | Concrete result | Permitted use / remaining work |
|---|---|---|
| Server `8d6e71d` archive `79acc8689f9eef8098be5ca4ba0911e0e5285cfa9e2ac34375f73a4d55732831` → launcher `14afd962` archive `270cda4667aea8206012a35c2395f4f705e9448e86a25f9e230d679f91ce7d03` | Within Server production source, Server Cargo.toml, robot-rpc, Cargo.lock and service units, only `bpf/device_policy.insns`, `src/{device_policy,launcher,lib,policy}.rs` and the launcher unit differ. | The final delta is fixed-filter installation after paused task creation, direct/effective MULTI inventory verification before Start, and loader capability. Host instruction/interpreter and binding regressions plus actual D2 filter evidence cover that delta; they do not re-execute every older sandbox case. |
| Historical launcher `d58dd102` archive `515c8a0d4d1186a09f503a02811a7ee3052f6707438921c37dd664457d7093ab` → `14afd962` | Server source additionally changes `artifact.rs`, `robot.rs`, `service.rs`; Cargo.lock also differs. | Do not call the entire old→new build a device-only change. Reuse importer, credential/settlement and final-filter receipts separately; review the applicable dependency/link closure for each older claim. Unrelated workspace changes are not automatically linked code. |
| Manager11 `02779a0e` archive `e6b4cbecc216a5169a2de20b693c7162691a34642003f286dd24563a1d364747` → Robot `8d6e71d` archive `fbe3e0f227c1579ad00e8d15cdae0e2b76b851d973e13b5f804c4d00aadef085` | In the compared daemon, runtime, intent, evidence, authority-client, RPC and lockfile scope, production changes are intent `src/{lib,store,types}.rs` and runtime `src/{lib,reconciliation,types}.rs`; tests/READMEs also differ. The other named scopes match. | Durable legacy Completed remains reconciliation proof with OutcomeUnknown task verdict; allocated cancellation needs an exact operation/revision marker, queued before writer stop and credited only durably. Missing/corrupt/legacy cancellation proof stays uncredited. Old-reader conservatism is not general downgrade qualification. |

Source archives: [Server 8d6](../../artifacts/server-reconciliation-build01/source-8d6e71d.tar),
[launcher14](../../artifacts/server-device-policy-build01/source.tar),
[launcher d58](../../artifacts/release-source-materials01/sources/actryn-d58dd10235d906644027a973dfd297d7841a492c.tar),
[manager11](../../artifacts/release-source-materials01/sources/actryn-02779a0e36e6a587eceaa7daa0229393bb93906d.tar),
[Robot 8d6](../../artifacts/robot-reconciliation-build02/source-8d6e71d.tar).
The Robot build review checks 363 source leaves, 28 allocated sections and 147
target imports; the ARM CLI ABI receipt checks 136 imports. Launcher build checks
31 allocated sections and 154 historical target imports, followed by fresh four-provider
readback before installation. These are static/build facts, not behavioral tests.

## Case-level reuse and remaining predicates

| Required scope | Evidence that can be mapped | Boundary still requiring an explicit disposition |
|---|---|---|
| D2 existing-device denial and memory pressure | **Two-case composite only:** f32/launcher17a0, existing char1:7 with allowed/absent controls, open results3,-2,-1, 177 loss-free records, fresh max18/oom1/oom_kill1 and natural137; all 27 cold payload/policy files subsequently verified. | Original run05 is FAILED; normal capture05 NOT_RUN. The corrected offline validator and separate custody establish these cases without a new attempt. Trace attribution combines fixed probe/node/control evidence, not a device-policy-origin event. |
| Other D2 isolation, attribution, method policy, cleanup/export | Historical `server-services-guest05.log`/`-unknown.log`, installed Server receipts, `server-a08-pressure-run11`, and `observer-installed-01` supply separate scopes. Selected observer/BPF and serverd retain their own origins. | Map every [profile rule](../architecture/platform-release-contract.md) to actual controls, prepared snapshots and negative/cleanup evidence. Check the launcher/dependency delta above; do not transfer all older claims solely because package filenames match. Whole D2 remains `OPEN_FINAL_COHORT_RECONCILIATION_REQUIRED`. |
| A01/A03 | Manager11 lifecycle03: two natural completions under one grant, reconciliation before reuse; module16 stale/replay cases. | Older manager execution is not execution of e36. Bind the reviewed reconciliation delta and its tests/actual settlement separately; no combined-two-operation claim from the one-operation combined demo. |
| A02/A09 | Replyloss02: initial reply withheld and durable cancellation; contention04: allocated closure during 611 ms SQLite lock, zero STARTs; registry race tests remain separate. | Manager10/module16 evidence. SQLite contention is not fsync-stall, EIO or media-power-loss proof. Current command/front-end coverage is separate below. |
| A04/A05/A08 | Existing crash/unknown-history evidence, pressure-run11 allocation/reclaim cases, and final existing-handle cleanup with e36/afef: four historical settlements preserve OutcomeUnknown; exact raw cancellation markers and 22/21 Server,16/21 Robot,zero-debit custody. | Finalize-run01 stays FAILED at recorder-inclusive cutoff; its consumed abort remains unknown and must never be resent. Separate cleanup does not create task success or a whole-campaign PASS. Package drift during the interval must not be silently described as exact original-cohort execution. |
| A06/A07/A15 | Unchanged module16 aggregate: 16 actual ARM cases and 17 cases each in plain/lockdep/KASAN/KCSAN, including retained FD, leader exit, genuine PID reuse and concurrent closure. | Reuse exact module/source/config receipt; no blanket diagnostic rebuild. Mocked serdev byte offsets and PM/shutdown callbacks do not prove physical UART or real-platform suspend/poweroff behavior. |
| A10 | Traffic03 corrected unchanged-capture analysis; lifetime09 gateway replacement/retained-FD, local offline recovery and export. | Preserve earlier failures, uncertain negative reply and the capture-prefix boundary. Zero SAMPLE records are not applied-motion proof. Bind manager11→e36 delta. |
| A11 | Actual source80→82 gap and hot-journal committed-prefix recovery. | Preserve raw remnant/unknown tail and read/queued/durable distinctions. Metadata-only capture intentionally remains execution-replay-ineligible. |
| A12 | Fresh installation/interruption tests; current f32 cold stage/activate/resume and startup02; d77 update/startup/history custody. | Final Robot 17-entry merge and final manifest selection remain open. Runtime-only qualification Restart=no drop-ins are recorded test configuration, not the packaged Restart=on-failure policy. |
| A13/A14/A16 | Live-policy/missing-credential controls; observer overhead/loss evidence; failed production pilot07 and accepted diagnostic8 retained independently. | Authorized live-provider run, independent developer installation, production authority pilots and frozen comparison remain open. Diagnostic8 is an instrumented non-reproduction, not a fix, comparison or WCET proof. |

The latest Server case leaves 24/23 Server rows,16/21 Robot records and zero
debits; separate failure custody, cold stop and cold integrity preserve all old
rows and 374 entries. Do not substitute the earlier cleanup's 22/21 counts for
this later state. All failed records and unperformed stages retain their status.

## ARM CLI coverage to bind

The selected `4102…` CLI has actual installed `robot describe` and `robot recover`
execution in the d77 startup/update receipts, plus the static ABI result above.
The startup capability-parser failure is preserved; its retained known Recover
reply and ready proof are not another startup invocation. Earlier CLI doctor and
manager11 lifecycle use older binaries: the lifecycle harness calls CLI `pair`,
`handle`, `cancel`, `query` and `export`, while most authority commands use direct
RPC/SDK. API behavior is therefore not automatically proof of every CLI route.

No selected-4102 target acceptance receipt is bound here for the following routes:

- `robot prepare`, `grant`, `rearm`, `activate`, `observe`, `propose`, `reconcile`,
  `revoke`, `retire` — the central CLI-only operation lifecycle remains uncovered.
- `robot pair`, `handle`, `query`, `cancel`, `export`, `doctor`/`status` — retain
  older CLI evidence, then establish exact command/RPC dependency source equality
  or add only the missing selected-binary checks.
- `robot enroll-request`, `enroll-install`, `install-principal`, `revoke-principal`
  — older installed enrollment/RPC receipts are not selected-CLI evidence.

This is an explicit coverage gap in this map, not an assertion that every command
has failed or that no other saved receipt exists. Resolve it by attaching exact
receipt/binary bindings or a source-equality review first; only genuinely uncovered
routes need new execution. [CLI dispatch](../../apps/cli/src/command.rs) defines
these names; there is no separate `robot execute` or `authorise` command to invent.

## Hash-bound receipt index

These are existing records, not new acceptance results. Earlier package/build
records saying target NOT_RUN remain historical; later actual receipts supplement
them without rewriting them.

| Receipt | SHA-256 |
|---|---|
| [Launcher build](../../artifacts/server-device-policy-build01/provenance.json) | `fd7c18d41c2fbad01d119d58d3efee3b04dcaabe7b7c46f33199b82153b85193` |
| [Serverd build](../../artifacts/server-reconciliation-build01/provenance.json) | `39150625840f9a85875fc7017c9a11e28434c865b597506a56c9304ac518a539` |
| [Robot build review](../../artifacts/robot-reconciliation-root-review01/result.json) | `72c37e7ee8a3df6d19dc2b4a95206e651e014152027920ac7ffe8e4701a6964a` |
| [ARM CLI ABI](../../artifacts/arm-cli-runtime-collection01/abi/result.json) | `080fd43f46d218449ad6d79c5c2141e684736ec0de7827b5f75708488cbed67a` |
| [Device-policy host checks](../../artifacts/server-device-policy-root-tests01/verification.json) | `2e0fb58ecf830e9932c4877867fd82ab8e43b42710bdf34c2089264453d56b49` |
| [D2 corrected offline review](../../artifacts/server-diagnosis-thread-exits-regression01/review.json) | `ad5269e4afebe064d8033aa1871d42a4ebd2fcec54826128b210c1562e05b7d0` |
| [D2 two-case composite](../../artifacts/server-device-policy-composite-cases01/result.json) | `b66f7bb4516443854b4c222b4b69a76d19eebb423ecfa148607bcb04801d993c` |
| [Current Server cold integrity](../../artifacts/server-device-policy-cold-integrity-owner01/result.json) | `d94805cb2ba5bad6ee999ae15df10b971f4984bee1292e7dc3bcd9b4fc484507` |
| [Manager11 lifecycle03](../../artifacts/robot-manager11-lifecycle03/result.json) | `296fcc3762d692f38c1934753a79577cc54bfb28c0fb42256aee86a5ee21a4df` |
| [Replyloss02](../../artifacts/robot-a02-replyloss-02/result.json) | `b6744e8bdd9a0d54ec973dc19cbe579ffa06cb102d2054e651910f73c83f02d4` |
| [Contention04](../../artifacts/robot-a09-contention-04/result.json) | `59c49b6b9c1eac0d6b2173a278f7519721e8a4d0f4970e218ddcdf200cbc9927` |
| [Lifetime09](../../artifacts/robot-a10-lifetime-09/result.json) | `730b8fa965f8b714c1ba6ed25662c61faaa7535ae308dc10e6f5f88119db989f` |
| [Pressure-run11 capture validation](../../artifacts/server-a08-pressure-run11/capture-validated.json) | `92875b5c76811026708b67c025c54db14f3b3fe6d50c0b2228ee92301caaf840` |
| [Existing-handle cleanup review](../../artifacts/robot-retained-debit-finalize-cleanup-actual-review01/review.json) | `19223fd1dd083fcf8e56321c02bc830f9a70274f68385a1ede55db8a77b757c6` |
| [Module16 acceptance aggregate](../../artifacts/kernel-module16-acceptance01/manifest.json) | `00120810d6e385e32fe4d915852fbed819b9182cbf013aee668538dcb8d9a298` |
| [Selected Robot startup/parser review](../../artifacts/reconciliation-robot-startup01/parser-review.json) | `f34be51899457fbf245bcb74a85a210fa795aaec2bb80e9e5e6574d8a44304a8` |
| [Installed Robot package inspection](../../artifacts/robot-qualification-package-inspection01/capture.json) | `f774c54897482e119be5b52b2ce587dd906643c8950c655929e1df9f97ce02a7` |

Robot package inspection matches nine of ten pins: Expat remains2.9 against
pinned2.8.3. That limits exact installed-Robot cohort equality and says nothing
about the separate A16 disk. Its full package/provider baseline requires its own
binding. Final selection must also retain build/link/source-material and notice
provenance, genuine release-signing inputs and external A13/A14 evidence. No row
in this document is a whole-release PASS, physical qualification or CI result.
