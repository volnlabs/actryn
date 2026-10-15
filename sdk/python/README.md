# Actryn Python SDK

Install the pinned package into a virtual environment: `python -m pip install .`.
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
# Persist handle.json() before the first request if the application needs recovery.
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

Run `PYTHONPATH=sdk/python python3 -m unittest discover -s sdk/python/tests -v`
from the repository root. These codec/timeout tests use local socket pairs;
end-to-end mTLS and Robot acceptance require the running manager and fixture.
