# Actryn developer preview in progress

Actryn is the product under the **VolnLabs** organisation. The proposed product repository is `volnlabs/actryn`, with **Actryn Server** and **Actryn Robot** as its main components.

The first release includes a narrow custom Linux authority component. Its actual
QEMU UART tests and the server, runtime and developer tools are under integration;
the combined release acceptance gates are not yet complete.

The approved [v0.0.1 developer-preview specification](docs/superpowers/specs/actryn-v0.0.1.md)
and [execution plan](docs/superpowers/plans/2026-10-16-actryn-v0.0.1.md) define the
current implementation scope. See the [progress ledger](docs/development/progress.md)
for actual verification. The preview is software-only; physical activation is unavailable.

Developer entry points: [installed offline workflow](packaging/release/README.md),
[CLI](apps/cli/README.md), and [Python SDK](sdk/python/README.md).

- [Complete offline architecture field guide](docs/actryn-architecture-guide.html) — beginner Linux/kernel explanations, decisions, failure walkthroughs, glossary and embedded specifications.
- [System architecture, repositories, CLI, kernel/userspace boundary and distribution](docs/superpowers/specs/architecture.md)
- [Pinned source review, extraction map and selective adoption decisions](docs/research/2026-10-13-source-review.md)
- [Kernel/controller contract](docs/architecture/kernel-controller-contract.md) — cancellation/normal completion, fixture wire v2, native endpoint conformance and recovery.
- [Platform/release contract](docs/architecture/platform-release-contract.md) — request-key cancellation, broker/preparation reservations, launch, evidence and independent release promotions.
- [Review remediation and remaining validation gates](docs/reviews/2026-10-13-review-remediation.md).
- [Independent cross-reference against the full product brief](docs/reviews/2026-10-13-post-patch-brief-review.md) — historical findings against preserved targets, all 40 problems, project dispositions and all 15 research references; subsequent corrections are in the remediation record.
- [Historical independent review and coverage of all 40 problems](docs/reviews/2026-10-13-independent-architecture-review.md) — includes project and 15-paper inventories with explicit evidence limits; links preserve the pre-patch baseline.

Selected source organization: one initial `actryn` monorepo with userspace/SDK/CLI, portable Rust core, `kernel/`, `firmware/` and `targets/` boundaries. Server, robot and target artifacts promote independently. An unprivileged network gateway relays end-to-end authenticated traffic to the trusted manager; it receives no actuator authority. Shared Rust kernel integration remains conditional on the exact target build/lifetime gate. Reference checkouts, when present under `ref/`, are local inspection inputs excluded from Git.

Historical reviews and preserved baselines retain the previous product name, Voln.

Original userspace code uses [Apache-2.0](LICENSE). The Linux authority module,
kernel tests and observer BPF code use [GPL-2.0-only](LICENSES/GPL-2.0-only.txt),
as identified by their source headers. Third-party dependencies retain their own
licenses; release bundles include their notices and corresponding kernel source.
