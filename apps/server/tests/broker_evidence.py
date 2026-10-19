"""Pure, fixed-profile broker-probe evidence checks. No guest or process actions."""
import hashlib
import io
import json
import re
import tarfile

import guest_capacity as common

PROBES = [('socket_inet', 41, 1), ('bpf', 321, 1), ('perf_event_open', 298, 1),
          ('unshare', 272, 1), ('setns', 308, 1), ('mount', 165, 1), ('containerd_path', 257, 2),
          ('credential_path', 257, 2), ('devmem_path', 257, 2), ('root_readonly', 257, None)]
BROKER_CASES = ['offline_call', 'offline_result', 'forbidden_method', 'cancel_absent', 'call_closed']
DENIAL = {'request_key': 'denied-1', 'method': 'admin.grant', 'reason': 'method_not_allowed'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            assert key not in value, 'duplicate JSON key'
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(AssertionError('nonfinite JSON')))
    except (ValueError, UnicodeError) as error:
        raise AssertionError('invalid JSON evidence') from error


def check_oci(manifest_raw, config_raw, layer_raw, artifact, agent_sha256):
    """The three regular members from build_oci.py, read in memory, never extracted."""
    assert re.fullmatch('sha256:[0-9a-f]{64}', artifact)
    assert re.fullmatch('[0-9a-f]{64}', agent_sha256)
    assert len(manifest_raw) <= 65536 and len(config_raw) <= 65536 and len(layer_raw) <= 16*1024**2
    manifest, config = strict_json(manifest_raw), strict_json(config_raw)
    assert digest(manifest_raw) == artifact
    assert set(manifest) == {'schemaVersion', 'mediaType', 'config', 'layers'} and manifest['schemaVersion'] == 2
    assert manifest['mediaType'] == 'application/vnd.oci.image.manifest.v1+json' and len(manifest['layers']) == 1
    for descriptor, data, media in [(manifest['config'], config_raw, 'config.v1+json'),
                                    (manifest['layers'][0], layer_raw, 'layer.v1.tar')]:
        assert descriptor == {'digest': digest(data), 'size': len(data),
                              'mediaType': 'application/vnd.oci.image.' + media}
    assert config == dict(architecture='amd64', os='linux',
                         config={'Entrypoint': ['/bin/agent'], 'User': '65532:65532', 'WorkingDir': '/tmp',
                                 'Labels': {'org.actryn.profile': 'offline-preview-v1'}},
                         rootfs={'type': 'layers', 'diff_ids': [digest(layer_raw)]})
    try:
        with tarfile.open(fileobj=io.BytesIO(layer_raw), mode='r:') as archive:
            members = archive.getmembers()
            assert len(members) == 3 and [m.name for m in members] == [
                'bin/agent', 'etc/actryn/input.json', 'etc/actryn/input.schema.json']
            for member, mode, limit in zip(members, (0o555, 0o444, 0o444), (8*1024**2, 4096, 8192)):
                assert member.isreg() and member.mode == mode and member.uid == member.gid == member.mtime == 0
                assert 0 < member.size <= limit and not member.pax_headers
                stream = archive.extractfile(member); assert stream is not None
                data = stream.read(limit + 1); assert len(data) == member.size
                if member.name == 'bin/agent': assert hashlib.sha256(data).hexdigest() == agent_sha256
                else: assert isinstance(strict_json(data), dict)
    except (tarfile.TarError, OSError) as error:
        raise AssertionError('invalid fixed OCI layer') from error


def agent_records(stdout, attempt):
    assert 0 < len(stdout) <= 1024*1024 and stdout.endswith(b'\n')
    lines = stdout.splitlines(); assert len(lines) == 18 and all(len(line) <= 65536 for line in lines)
    records = [strict_json(line) for line in lines[:-1]]
    assert records[0] == dict(event='sandbox_identity', pid=1, tid=1, uid=65532, gid=65532)
    assert all(type(records[0][k]) is int for k in ('pid', 'tid', 'uid', 'gid'))
    fds = records[1]
    assert set(fds) == {'event', 'enumeration_fd', 'entries', 'other_fds', 'extra_fds',
                        'stdio_sockets', 'stdin_closed', 'errors', 'close_result'}
    assert fds['event'] == 'sandbox_fds' and all(type(v) is int for k,v in fds.items() if k != 'event')
    assert fds['stdin_closed'] in (0, 1) and fds['enumeration_fd'] == (0 if fds['stdin_closed'] else 3)
    assert fds['other_fds'] == 3-fds['stdin_closed'] and fds['other_fds']+1 <= fds['entries'] <= 4096
    assert fds['extra_fds'] == fds['stdio_sockets'] == fds['errors'] == fds['close_result'] == 0
    for value, (case, syscall, error) in zip(records[2:12], PROBES):
        assert set(value) == {'event', 'case', 'syscall', 'result', 'errno'}
        assert value['event'] == 'sandbox_probe' and value['case'] == case
        assert type(value['syscall']) is int and value['syscall'] == syscall
        assert type(value['result']) is int and value['result'] == -1 and type(value['errno']) is int
        assert value['errno'] == error if error is not None else value['errno'] in (13, 30)
    replies = []
    for value, case in zip(records[12:], BROKER_CASES):
        assert set(value) == {'event', 'case', 'reply'} and value['event'] == 'broker_probe' and value['case'] == case
        assert isinstance(value['reply'], dict); replies.append(value['reply'])
    first = replies[0]; assert set(first) == {'result', 'value'} and first['result'] == 'ok'
    value = first['value']
    assert set(value) == {'attempt_id', 'request_key', 'request_digest', 'deadline_ms', 'origin', 'model',
                          'robot_handle', 'trusted_robot_observation', 'observation_digest', 'lineage_digest',
                          'agent_observation_reference', 'output'}
    assert value['attempt_id'] == attempt and value['request_key'] == 'offline-1'
    assert value['origin'] == 'server_attested' and value['model'] == 'offline-fixture'
    assert value['agent_observation_reference'] == 'fixture-obs-1'
    assert value['robot_handle'] is value['trusted_robot_observation'] is value['observation_digest'] is value['lineage_digest'] is None
    assert re.fullmatch('sha256:[0-9a-f]{64}', value['request_digest']) and type(value['deadline_ms']) is int and value['deadline_ms'] > 0
    assert value['output'] == dict(left_delta_ticks=10, right_delta_ticks=10, duration_ms=1000)
    result = replies[1]; assert set(result) == {'result', 'value'} and result['result'] == 'ok'
    assert set(result['value']) == {'call', 'value'} and result['value']['value'] == value
    call = result['value']['call']; assert set(call) == {'id', 'request_key', 'state', 'publication_closed', 'consumed_tokens', 'deadline_ms'}
    assert re.fullmatch('[0-9a-f]{32}', call['id']) and call['request_key'] == 'offline-1' and call['state'] == 'settled'
    assert call['publication_closed'] is False and type(call['consumed_tokens']) is int and call['consumed_tokens'] == 0
    assert type(call['deadline_ms']) is int and call['deadline_ms'] == value['deadline_ms']
    assert replies[2] == {'result': 'error', 'reason': 'policy_denied: method_not_allowed'}
    assert replies[3] == {'result': 'ok', 'value': {'stage': 'KEY_CANCELLED_DURABLE'}}
    assert replies[4] == {'result': 'error', 'reason': 'publication context closed'}
    marker = re.fullmatch(rb'BROKER_ACCEPTANCE_PASS child=([1-9][0-9]{0,9})', lines[-1])
    assert marker and int(marker[1]) > 1
    return records, call


def validate_trace(raw, binding, attempt, summary, open_results):
    assert 0 < len(raw) <= 16*1024**2 and raw.endswith(b'\n')
    rows = [strict_json(line) for line in raw.splitlines()]
    assert 0 < len(rows) <= 32768
    assert sorted(v['event']['sequence'] for v in rows) == list(range(1, len(rows)+1))
    common.observer_health(summary['status'], binding['observer'])
    assert summary['status']['sequence'] == len(rows) and summary['local_lost'] == 0 and summary['retained_bytes'] == len(raw)
    for row in rows:
        e = row['event']
        assert row['attempt_id'] == attempt and row['boot_id'] == binding['boot_id']
        assert row['collector_epoch'] == binding['observer']['collector_epoch']
        assert e['cgroup_id'] == binding['cgroup_id'] and e['origin'] == 'linux.tracepoint'
        assert all(type(e[k]) is int for k in ('kind', 'syscall', 'result', 'pid', 'tid',
                                               'related_pid', 'cgroup_id', 'sequence', 'monotonic_ns'))
        assert 1 <= e['kind'] <= 5 and -1 <= e['syscall'] < 2**31 and -2**63 <= e['result'] < 2**63
        assert 0 < e['pid'] < 2**32 and 0 < e['tid'] < 2**32 and 0 <= e['related_pid'] < 2**32
        assert 0 < e['cgroup_id'] < 2**64 and e['sequence'] > 0 and 0 <= e['monotonic_ns'] < 2**64
    rows.sort(key=lambda v: v['event']['sequence']); parent = binding['snapshot']['pid']
    execs = [v['event']['sequence'] for v in rows if v['event']['kind'] == 4 and v['event']['pid'] == v['event']['tid'] == parent]
    assert execs, 'agent leader exec not observed'
    observed = [v['event'] for v in rows if v['event']['pid'] == v['event']['tid'] == parent and v['event']['sequence'] > execs[-1]]
    for syscall, results in [(257, open_results), (42, [0]*5)]:
        events = [e for e in observed if e['syscall'] == syscall]
        assert len(events) == 2*len(results) and [e['kind'] for e in events] == [1, 2]*len(results)
        assert [e['result'] for e in events if e['kind'] == 2] == results
        assert [e['monotonic_ns'] for e in events] == sorted(e['monotonic_ns'] for e in events)
    # __secure_computing runs before trace_sys_enter in upstream v6.12.111.
    # Denied calls may have no enter (or an exit-only record); absence is NOT
    # policy-origin attribution. Socket41 is not selected by this observer.
    blocked = [e for e in observed if e['syscall'] in (321, 298, 272, 308, 165)]
    assert all(e['result'] == -1 for e in blocked if e['kind'] == 2)
    forks = [e for e in observed if e['kind'] == 3]
    assert len(forks) == 1 and forks[0]['related_pid'] > 1 and forks[0]['related_pid'] != parent
    child = forks[0]['related_pid']
    assert any(v['event']['kind'] == 5 and v['event']['pid'] == v['event']['tid'] == child
               and v['event']['sequence'] > forks[0]['sequence'] for v in rows)
    assert any(e['kind'] == 5 and e['sequence'] > forks[0]['sequence'] for e in observed)
    return len(rows)


def validate(stdout, stderr, bundle, inspection, prepared, summary, trace_raw, expected,
             manifest_raw, config_raw, layer_raw):
    """Root supplies pinned expected identity, actual prepared reply and retained raw files.

    This never opens SQLite, starts a process, imports an image or contacts a guest.
    Installed package/boot/provider bookends remain the owner's separate obligation.
    """
    assert set(expected) == {'attempt', 'artifact', 'agent_sha256'}
    attempt, artifact = expected['attempt'], expected['artifact']
    assert re.fullmatch('[0-9a-f]{32}', attempt) and stderr == b''
    check_oci(manifest_raw, config_raw, layer_raw, artifact, expected['agent_sha256'])
    records, call = agent_records(stdout, attempt)
    assert prepared['id'] == attempt and prepared['artifact_digest'] == artifact and prepared['state'] == 'prepared' and prepared['outcome'] == 'pending'
    binding = strict_json(prepared['binding'])
    common.validate_export(bundle, attempt, artifact, binding, inspection,
                           {'stdout': stdout, 'stderr': stderr}, summary, len(trace_raw), True,
                           agent_check=lambda logs, _: agent_records(logs['stdout'], attempt),
                           expected_denials=[DENIAL])
    contents = {e['name']: e['content'] for e in bundle['artifacts']}
    broker = contents['broker']
    assert broker['classification'] == 'broker_application_policy_and_delegated_accounting'
    assert broker['attempt_state'] == 'reaped' and broker['attempt_outcome'] == 'cancelled' and broker['evidence_gaps'] == []
    assert broker['policy_denials'] == inspection['denials'] == [DENIAL]
    assert broker['policy_denials_retained'] == 1 and inspection['denials_omitted'] == 0
    assert broker['calls'] == inspection['calls'] and len(broker['calls']) == 2
    offline, cancelled = broker['calls']
    assert offline == dict(call, publication_closed=True)
    assert cancelled['request_key'] == 'cancel-first' and cancelled['state'] == 'cancelled' and cancelled['publication_closed'] is True
    assert re.fullmatch('[0-9a-f]{32}', cancelled['id']) and cancelled['id'] != call['id']
    assert type(cancelled['consumed_tokens']) is type(cancelled['deadline_ms']) is int and cancelled['consumed_tokens'] == cancelled['deadline_ms'] == 0
    count = validate_trace(trace_raw, binding, attempt, summary,
                           [records[1]['enumeration_fd'], *[-v['errno'] for v in records[8:12]]])
    return dict(attempt=attempt, artifact=artifact, agent_sha256=expected['agent_sha256'],
                syscall_denials=10, broker_cases=5, trace_records=count,
                inherited_fds='source_probe_no_extra_fds_or_stdio_sockets_before_broker_creation',
                agent_output='untrusted_but_bound_to_selected_OCI_and_export',
                denial_origin='broker_policy_record_only_for_admin.grant',
                seccomp_enter_absence='not_policy_origin_proof',
                network='AF_INET_socket_denied_and_zero_routes_no_external_connect_attempt')
