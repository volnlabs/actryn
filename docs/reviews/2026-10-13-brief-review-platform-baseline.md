# Platform, evidence and release contract

Status: **selected V1 design; unimplemented and unqualified**. This contract closes platform choices raised by the [independent review](../reviews/2026-10-13-independent-architecture-review.md), especially platform S1–S6 and architecture findings 7/9/10/12/13. It supplements the [system architecture](../superpowers/specs/2026-10-13-volnlabs-system-architecture.md). Names and CLI examples are proposed interfaces. Target versions, hardware and numerical physical limits remain required release inputs; missing inputs fail preflight.

## 1. Executable artifacts and identity

V1 supports an **untrusted OCI agent on the server proposing calls to reviewed fixed native skills on the robot**. Generated robot-local code, runtime skill loading and user-provided kernel programs are unsupported V1 execution classes.

Two immutable objects are distinct:

- Agent artifact: OCI digest, entrypoint, configuration/schema digest, approved broker tools and sandbox profile.
- Skill configuration: release-built skill ID, configuration digest, endpoint-contract revision and permitted typed parameters. Its code ships with `voln-robotd`; installation grants no motion authority.

The restricted launcher originates tenant/job/attempt IDs and binds them to artifact, sandbox, cgroup lifetime, host boot and process lifetimes. `attempt prepare` reserves this identity and a stopped verified sandbox before grant issuance; `attempt start` rechecks the binding before executing the agent. Fork/exec stays within that attempt. Agents cannot override this association through request fields. `voln-serverd` binds its per-attempt broker channel to that record and authenticates to the robot with a scoped workload credential. The robot independently authorizes that principal, creates a fresh local skill instance, and binds it to an operator-issued grant for the prepared attempt. The operator may prepare several instances for an attempt; every instance has one immutable skill/configuration identity and fresh mutable state owned by `voln-robotd`. The ordinary agent API cannot prepare/activate instances or issue grants.

Fixed skill routines run as bounded native tasks inside `voln-robotd`; they neither own the effective grant table nor write raw controller bytes. Kernel admission remains mandatory. A new server process or robot-manager lifetime creates new instances; recovered state is diagnostic history, not a resumed grant. The kernel session owner is the registered initial thread-group leader; its exit revokes task authority even if other threads or duplicated descriptors survive. Exact kernel lifetime implementation belongs to the robot contract.

The restrained wheel profile excludes active stabilization/holding claims. Independently progressing controller expiry/protection survives task loss; its electrical response still requires qualification. Future balancing/holding endpoints need their own independently surviving control contract.

The trusted inference broker originates a context binding attempt, inference request ID, observation IDs/content digests, calibration/clock revisions and skill/configuration. It binds the returned tool proposal to a stable parent request key; the first robot proposal supplies that key/digest, and the robot allocates/durably binds its operation ID before any effect. The broker appends the returned ID without rebinding the original key/context. Key-based retries resolve the same record. Context closes on cancellation, expiry or replacement; tool proposals cannot substitute a newer observation ID. Robot admission still checks locally retained observation validity. Direct agent model calls, when later supported, carry `agent_declared` lineage. Broker records are `server_attested`, not proof the model attended to an image or protection against a compromised server. Learned diagnoses remain separate from observed failures.

## 2. One server sandbox and launch order

Use containerd through its supported API with a restricted launcher. Select one tested OCI runtime/configuration tuple. The launcher accepts declarative approved profiles, never arbitrary host commands, mounts, hooks or runtime options.

Launch order is contractual:

1. Allocate identity and a dedicated cgroup lifetime; reserve attribution before task creation. Prepare immutable image/rootfs and per-attempt broker socket; close all other inherited descriptors.
2. Configure namespaces, mount/device allowlists, UID/capabilities, seccomp, resource limits and network isolation. Attach required enforcement and attribution; record installed identities and coverage.
3. Create the runtime task without executing image/application code. Trusted runtime setup is separately identified. Reject image-supplied hooks and unapproved runtime extensions.
4. Verify task/cgroup binding, policy presence and required collector readiness, then invoke task start. Any preceding failure destroys the prepared task and revokes credentials.

The runtime's create/start boundary and early-process attribution require source/integration tests on the selected version. A backend that cannot establish this order is unsupported. Descendants cannot migrate cgroups, acquire host capabilities or access the container engine. Cleanup revokes the attempt broker/credential and kills/reaps its complete cgroup before releasing the identity record.

The initial `server-restricted` profile has no routable network interface. External inference/tools go through the per-attempt Unix broker socket, exposing named approved operations rather than caller-selected URLs. The broker holds provider credentials outside the sandbox and applies destination/request limits. Arbitrary direct egress is unsupported in this profile.

| Rule | Enforcement / installation check | Evidence and exact limit |
|---|---|---|
| Host files, credentials and management sockets unavailable | Mount allowlist, separate identity, dropped capabilities, no inherited handles; inspect prepared mounts/FDs and negative fixture | Attributed syscall failure plus installed-policy snapshot. `ENOENT`/`EACCES` alone is not a policy-attributed denial. |
| Only minimal approved character devices | Device allowlist plus restricted `/dev`; inspect policy and try a deliberately mounted forbidden dummy device in the test profile | Kernel-observed failed open and policy inventory. Stock device policy supplies no assumed per-denial audit event. |
| No direct external/controller network | Isolated network namespace, no external route or inherited network socket; inspect topology and negative connect test | Failed connect, topology and broker records; do not infer which policy caused an arbitrary network error. |
| Privileged kernel/process operations unavailable | Dropped capabilities and architecture-specific seccomp rules for `bpf`, `perf_event_open`, mount and namespace-changing operations | Fixed reviewed BPF observer records entry/return for selected syscalls; distinguish filter configuration from an enforcement-origin denial event. |
| Bounded CPU/memory/PIDs/I/O | Required explicit cgroup limits; read back effective values | Trusted counters, pressure and process events. Correlation does not establish that one request caused all host pressure. |
| Only allowed broker methods/resources | Broker binds authenticated channel to prepared attempt and checks its fixed method/resource policy before any effect | Broker-origin `policy_denied` with rule/request/attempt identity is an attributable application denial, not a kernel denial. An agent cannot choose a new URL or administrator method. |

Profile acceptance records allowed control cases and violations, immediate fork/exec, unrelated errors of the same syscall, enforcement-install failure and reader loss. Custom BPF-LSM policy, ActPlane and Actime are optional later profiles; their installed version/path must earn a separate denial coverage claim. No argv-based kill is labelled pre-effect denial.

Loss of required enforcement closes launches, quarantines affected broker channels and terminates affected attempts; it cannot undo prior effects. Diagnostic-reader loss preserves enforcement, marks evidence incomplete and closes new diagnostic-profile launches. Existing server attempts may finish under installed isolation with incomplete reports; robot delegation follows its finite grant/evidence policy. Trace loss counters and unavailable hooks remain visible.

## 3. Durable intent, recorder health and replay

Before first possible dispatch, persist operation ID, client request key/digest, instance/grant/context and immutable configuration in the local intent database. Dispatch only after a successful durable commit and fresh live checks. Storage failure rejects new operations. After recovery, unfinished intents are `OUTCOME_UNKNOWN`; neither database restoration nor a retry silently resends them.

For each producer, retain three distinct frontiers:

- `read`: copied from the producer into bounded recorder memory.
- `queued`: accepted into a bounded persistence batch; still volatile.
- `durable`: required files flushed/synced and their checkpoint committed to the database.

The writer orders recording-file persistence before committing the checkpoint; recovery excludes unsupported checkpoints/tails from authoritative results, preserves raw remnants for diagnosis and reports the gap. Storage durability means the selected stack honored its tested flush contract, not survival of arbitrary media failure. The recorder authenticates source channels and assigns origin labels; agent payloads cannot claim kernel/controller origin. A hash proves content identity, not trustworthy authorship.

The robot profile must supply maximum volatile bytes/records, maximum age since durable progress, heartbeat interval and maximum permitted continuation after health loss. These are required finite inputs, not inferred from queue capacity. A trusted writer reports its durable frontier separately from reader acknowledgement. Reader alive with writer stalled therefore exhausts the age/budget. Repeated heartbeats with an unchanged frontier do not establish progress while required records are pending.

Crossing either bound closes new experimental admission **and revokes existing experimental streams** through the normal urgent path. No arbitrary continuation is authorized by a healthy read cursor. Kernel/controller protection never waits for fsync; reserve transition-event capacity and still expose overflow. Continuous sample dispatch is asynchronous inside an already durable operation; it has no per-sample fsync. A crash can lose its tail, including the final loss marker. Unfinished intents, producer/session changes and last durable frontiers expose that uncertainty; successful control does not imply a complete episode.

Each attempt has a capture manifest: profile/configuration digests; producer identities and clock domains/error bounds; requested and actually retained streams; payload-versus-metadata policy; sequence ranges/gaps; durable frontiers; interventions; retention/redaction; and replay eligibility with missing reasons. Server and robot retain their own authoritative portions; export links them without converting remote claims into local facts.

Metadata-only is the default and supports inspection. Recorded-input/model-output replay requires retained observations, configurations, responses and execution/intervention events for the requested interval; a hash of missing content fails eligibility. Partial intervals can be replayed only with explicit boundaries and unknowns. Fresh inference reproduction is a separate experiment. Replay runs under a no-device/no-live-credential profile with no command-service route. MCAP, OpenTelemetry and Rerun remain format/export/viewer integrations; none owns completeness or durability policy.

## 4. Enrollment, scopes and recovery

Enrollment is local-only while inhibited. On the robot's protected administrative Unix socket, `voln device enroll request` creates a device key and outputs a CSR plus fingerprint. An operator checks that fingerprint on the physical/local console, signs it with the site's offline issuer workflow, then uses `voln device enroll install` locally to install the certificate and selected site trust root. There is no unauthenticated network enrollment endpoint. `voln device pair` verifies that enrolled device fingerprint and site chain before recording the connection.

Use an established X.509/mTLS implementation. Separate certificate scopes for deployment, attempt proposal, observation/readout and operator grant/rearm; the site's issuance policy prevents deployment identities requesting operator scopes. Local policy maps authenticated principals to ceilings; a valid certificate is not a grant. Proposed credential defaults: device certificate 30 days, operator session 8 hours, workload/deployment certificate 5 minutes. These are administrative design defaults, not physical response bounds. Workload certificates require renewal through the authorized issuer; offline expiry never extends automatically.

On connection, validate certificate time and local revocation state; derive a remaining session deadline on the robot clock. Session/grant lifetime cannot exceed credential/delegation validity. Credential renewal authenticates future requests; it neither extends an issued grant nor revives an expired one. Clock uncertainty or rollback closes new authorization and inhibits affected task authority. Local revocation immediately closes that principal's sessions and revokes its grants. A disconnected robot cannot instantly learn a remote revocation; short-lived delegation bounds this exposure. Site policy may shorten it.

Rotate keys through authenticated issuer approval plus local installation of new trust material while inhibited. Reconnect, rotation and re-enrollment never rearm. Lost/compromised administrator credentials require physical/local privileged recovery: inhibit, reconcile, retire all grants/sessions, replace trust roots/keys as appropriate and explicitly rearm under the new identity. Lost robot keys require re-enrollment, never identity copying from a process checkpoint. Decommissioning revokes credentials and removes local secrets only after required evidence export/retention.

## 5. Immutable releases and useful demonstrations

Keep `voln`, `voln-linux` and `voln-targets`. A signed immutable promotion manifest pins component/image/package digests; RPC/UAPI/features; exact kernel build/config/module; wire vectors and firmware; target hardware, policy/calibration; dependency/weight licenses and notices; build provenance; and exact conformance/qualification evidence. Missing or incompatible required entries fail preflight. CI consumes these artifacts, never sibling moving branches.

The same release system has independent eligibility: a server manifest can promote after its own isolation/report/cleanup checks without robot qualification. A robot manifest pins a compatible server RPC range but keeps its exact qualified local tuple. A server update cannot silently update kernel, firmware or robot policy. Regression checks reconstruct manifests, reject deliberate mismatches, and exercise supported client upgrades/downgrades against a fixed robot tuple.

Trusted-stack updates require inhibition, downstream reconciliation and recovery access before staging. Activate only the complete compatible tuple; power interruption leaves an inhibited recoverable installation. Firmware recovery follows the actual target mechanism. Reverting software creates fresh epochs/instances and reconciles; it cannot restore grants or reverse motion. Preserve evidence before schema migration; unsupported downgrade is rejected, not attempted destructively.

Two proposed operator stories define scope:

1. **Server diagnosis:** install, `voln doctor --role server`, `voln attempt prepare <agent-digest> --profile server-restricted`, then `voln attempt start <prepared-attempt>` without a robot grant. A multimodal batch exceeds its memory budget while a child attempts forbidden host-device access and an unauthorized broker method. `voln attempt inspect` distinguishes resource facts, failed OS access, broker-attributed denial, missing evidence and model/tool context; `voln evidence export <attempt-id>` retains the report; cleanup leaves no descendants/credentials. Repeat with an unrelated open failure to prevent false denial claims.
2. **Repeated robot experiment:** install/doctor/enroll/pair; prepare the server attempt before local skill instance/grant/activation; acquire an encoder-indexed restrained-wheel observation; let the agent propose one bounded index step through a fixed skill; independently judge displacement using retained encoder/instrument readings. First cancel normally and inspect reconciliation; that terminalizes the operation without rearming or reviving it. Then exercise a separate delayed-agent run through grant expiry: observe `FAULT_LATCHED`, perform `voln robot reconcile` under authorized recovery, explicitly `voln robot rearm`, issue/activate a fresh grant and run a new operation. Deliver the old response and show rejection. Rearm alone never authorizes that new operation. This is the engineering fixture; the buyer demonstration adds a selected robot's repeated visual alignment task with independently measured final position. Its endpoint/task acceptance must be chosen before claiming customer usefulness.

An operator other than the author repeats both on a second installation, measuring install, diagnosis and recovery effort. Hosted provider/model identity remains unselected; recordings can support software fixtures but cannot stand in for a live task-success benchmark.

Adoption order is standard facility → supported public API → narrow adapter → extracted source/fork. Extraction requires a semantic gap, pinned unit/license, retained assumptions, regression tests and named patch owner. These contracts customize the surrounding machinery without importing whole frameworks or copying maintained APIs unnecessarily.

Validation still required: selected-runtime launch ordering and policy tests, persistence/crash fixtures, credential recovery, release reconstruction, model suitability and all target/physical measurements. This document resolves design choices; it is not evidence that those checks passed.
