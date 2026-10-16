# Actryn Python SDK

For an installed Server bundle, use the shipped SDK and wheel without network
access. Run as the developer in a new writable working directory; Python 3.13
and the tuple's exact `python3-venv` prerequisite must already be installed:

```sh
set -e
test ! -e .venv
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps \
  /opt/actryn/server/current/share/wheels/protobuf-7.36.1-py3-none-any.whl
export PYTHONPATH=/opt/actryn/server/current/share/sdk
.venv/bin/python -c 'from actryn import Client, RequestHandle'
```

These assets belong to the **server** role; the Robot payload does not ship the
SDK or a wheel. Use the installed Server as the SDK client or separately provision
the reviewed SDK/dependency artifacts on a client. Never run pip inside an
immutable release slot. The installed guide is
`/opt/actryn/server/current/share/docs/INSTALL.md`.

For **source development**, from `sdk/python` in a checkout, create a virtual
environment and run `python -m pip install .`. That build requires
`setuptools==82.0.0` and `protobuf==7.36.1` from a separately provisioned package
source; it is not the offline installed-bundle procedure.
Generated Protobuf code is from `libprotoc 36.1`; the runtime is pinned to
`protobuf 7.36.1`. Regenerate from the repository root with:

```sh
protoc -I schemas --python_out=sdk/python/actryn schemas/robot-v1.proto
```

The client requires a site trust root, a scoped workload certificate/key, the
paired device certificate fingerprint and its DNS identity. It validates the
site chain, hostname, TLS 1.3, ALPN and exact paired fingerprint. Obtain the
fingerprint through local enrollment/pairing; never learn it from an untrusted
network response and then call that pairing.

```python
from actryn import Client, RequestHandle

# Values come from the operator's prepared attempt/namespace, not a model reply.
handle = RequestHandle.create(attempt_id_bytes, namespace_bytes)
# Durably persist handle.json() before proposing; retain it through uncertainty.
with Client(host, server_name="robot.example", ca="site-ca.pem",
            certificate="workload.pem", key="workload.key",
            paired_fingerprint=locally_verified_sha256) as robot:
    observation = robot.observe(handle.attempt, handle.namespace)
    receipt = robot.propose(handle, observation_id=observation["id"],
                            left_delta_ticks=5, right_delta_ticks=5,
                            duration_ms=1000, parent_digest=retained_proposal_digest)
    state = robot.query(handle)
    cancellation = robot.cancel(handle)
```

`propose` is admission, not completion. Read inspection fields for durability,
closure, task verdict and reconciliation separately. `OutcomeUnknown` means a
request or reply may have been delivered: reconnect and query the original
handle. The SDK never automatically retries, replaces the key or rearms.
`cancel` accepts that handle before any operation ID has arrived. Ordinary
transport loss is not confirmation of cancellation. Historical lookup reports
retired/uncertain outcomes; it never restarts an operation.

One Client supports sequential calls on one connection; do not share it across
threads. It retains no background renewal or retries. Close/reconnect explicitly
when the session expires. A credential renewal does not extend an existing grant.

After local retirement/recovery releases the capture writer,
`robot.evidence_read(handle)` lists a page of retained capture filenames, sizes
and SHA-256 hashes; `file="...", offset=N` reads a bounded hexadecimal chunk.
Listing pages use the returned `next_offset`. Reads preserve the original
principal/attempt/namespace and never resume work. For a complete verified local
directory export use `actryn robot export`; an unknown volatile tail and
metadata-only replay restrictions remain explicit in its manifest.

Run `PYTHONPATH=sdk/python python3 -m unittest discover -s sdk/python/tests -v`
from the repository root. These codec/timeout tests use local socket pairs;
end-to-end mTLS and Robot acceptance require the running manager and fixture.
