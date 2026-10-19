"""Synthetic evidence only: never execute broker_agent on the host."""
import copy
import hashlib
import io
import json
import tarfile
import unittest

import broker_evidence as proof
from test_guest_capacity import complete_export, rehash


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sync_stdout(data):
    """Keep export hashes valid so negative cases reach semantic checks."""
    d = next(v['content'] for v in data['bundle']['artifacts'] if v['name'] == 'stdout')
    raw = data['stdout']
    d.update(retained_bytes=len(raw), retained_sha256='sha256:'+hashlib.sha256(raw).hexdigest(),
             tail=raw[-2048:].hex(), tail_omitted_bytes=max(0, len(raw)-2048))
    rehash(data['bundle'])


def sync_trace(data, rows):
    data['trace_raw'] = b''.join(encode(v)+b'\n' for v in rows)
    data['summary']['retained_bytes'] = len(data['trace_raw'])


def evidence():
    bundle, attempt, _, binding, inspection, logs, summary, _, _ = complete_export()
    agent = b'not-an-executed-binary: synthetic hash-bound source fixture'
    layer = io.BytesIO()
    with tarfile.open(fileobj=layer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, data, mode in [('bin/agent', agent, 0o555),
                                 ('etc/actryn/input.json', b'{}', 0o444),
                                 ('etc/actryn/input.schema.json', b'{}', 0o444)]:
            member = tarfile.TarInfo(name); member.size = len(data); member.mode = mode
            archive.addfile(member, io.BytesIO(data))
    layer = layer.getvalue()
    def descriptor(data, media):
        return dict(digest='sha256:' + hashlib.sha256(data).hexdigest(), size=len(data), mediaType=media)
    config = encode(dict(architecture='amd64', os='linux',
                         config={'Entrypoint': ['/bin/agent'], 'User': '65532:65532', 'WorkingDir': '/tmp',
                                 'Labels': {'org.actryn.profile': 'offline-preview-v1'}},
                         rootfs={'type': 'layers', 'diff_ids': ['sha256:' + hashlib.sha256(layer).hexdigest()]}))
    manifest = encode(dict(schemaVersion=2, mediaType='application/vnd.oci.image.manifest.v1+json',
                           config=descriptor(config, 'application/vnd.oci.image.config.v1+json'),
                           layers=[descriptor(layer, 'application/vnd.oci.image.layer.v1.tar')]))
    artifact = 'sha256:' + hashlib.sha256(manifest).hexdigest()
    expected = dict(attempt=attempt, artifact=artifact, agent_sha256=hashlib.sha256(agent).hexdigest())
    value = dict(attempt_id=attempt, request_key='offline-1', origin='server_attested',
                 request_digest='sha256:' + 'd'*64, deadline_ms=492288, model='offline-fixture',
                 robot_handle=None, trusted_robot_observation=None, observation_digest=None,
                 lineage_digest=None, agent_observation_reference='fixture-obs-1',
                 output=dict(left_delta_ticks=10, right_delta_ticks=10, duration_ms=1000))
    call = dict(inspection['calls'][0], request_key='offline-1')
    tombstone = dict(call, id='e'*32, request_key='cancel-first', state='cancelled', deadline_ms=0)
    denial = dict(request_key='denied-1', method='admin.grant', reason='method_not_allowed')
    inspection.update(calls=[call, tombstone], denials=[denial])
    records = [dict(event='sandbox_identity', pid=1, tid=1, uid=65532, gid=65532)]
    records.append(dict(event='sandbox_fds', enumeration_fd=3, entries=6, other_fds=3,
                        extra_fds=0, stdio_sockets=0, stdin_closed=0, errors=0, close_result=0))
    for case, syscall, error in [('socket_inet', 41, 1), ('bpf', 321, 1),
                                  ('perf_event_open', 298, 1), ('unshare', 272, 1), ('setns', 308, 1), ('mount', 165, 1),
                                  ('containerd_path', 257, 2), ('credential_path', 257, 2),
                                  ('devmem_path', 257, 2), ('root_readonly', 257, 30)]:
        records.append(dict(event='sandbox_probe', case=case, syscall=syscall, result=-1, errno=error))
    replies = [('offline_call', {'result': 'ok', 'value': value}),
               ('offline_result', {'result': 'ok', 'value': {'call': dict(call, publication_closed=False), 'value': value}}),
               ('forbidden_method', {'result': 'error', 'reason': 'policy_denied: method_not_allowed'}),
               ('cancel_absent', {'result': 'ok', 'value': {'stage': 'KEY_CANCELLED_DURABLE'}}),
               ('call_closed', {'result': 'error', 'reason': 'publication context closed'})]
    records.extend(dict(event='broker_probe', case=case, reply=reply) for case, reply in replies)
    logs['stdout'] = b''.join(encode(v)+b'\n' for v in records) + b'BROKER_ACCEPTANCE_PASS child=2\n'
    for item in bundle['artifacts']:
        name, content = item['name'], item['content']
        if name == 'attempt': content['artifact_digest'] = artifact
        if name == 'broker':
            content.update(calls=inspection['calls'], policy_denials=[denial], policy_denials_retained=1)
        if name in logs:
            data = logs[name]
            content.update(retained_bytes=len(data), retained_sha256='sha256:'+hashlib.sha256(data).hexdigest(),
                           tail=data[-2048:].hex(), tail_omitted_bytes=max(0,len(data)-2048))
    inspection['attempt']['artifact_digest'] = artifact
    prepared = copy.deepcopy(inspection['attempt']); prepared.update(state='prepared', outcome='pending')
    parent = binding['snapshot']['pid']; child = parent+1
    events = [dict(kind=4, syscall=-1, result=0)]
    for result in [3, -2, -2, -2, -30]:
        events += [dict(kind=1, syscall=257, result=0), dict(kind=2, syscall=257, result=result)]
    for _ in range(5):
        events += [dict(kind=1, syscall=42, result=0), dict(kind=2, syscall=42, result=0)]
    # Rejected syscalls can have exit-only traces: seccomp runs before sys_enter.
    events += [dict(kind=2, syscall=321, result=-1), dict(kind=3, syscall=-1, result=0, related_pid=child),
               dict(kind=5, syscall=-1, result=0, pid=child, tid=child), dict(kind=5, syscall=-1, result=0)]
    trace = []
    for sequence, event in enumerate(events, 1):
        e = dict(sequence=sequence, monotonic_ns=100+sequence, pid=parent, tid=parent,
                 cgroup_id=binding['cgroup_id'], origin='linux.tracepoint', related_pid=0,
                 classification='observed'); e.update(event)
        trace.append(dict(attempt_id=attempt, boot_id=binding['boot_id'],
                          collector_epoch=binding['observer']['collector_epoch'], event=e))
    trace = b''.join(encode(v)+b'\n' for v in trace)
    summary.update(retained_bytes=len(trace), local_lost=0)
    summary['status']['sequence'] = len(events)
    next(v['content'] for v in bundle['artifacts'] if v['name']=='runtime_facts')['observer']['sequence'] = len(events)
    rehash(bundle)
    return dict(stdout=logs['stdout'], stderr=b'', bundle=bundle, inspection=inspection,
                prepared=prepared, summary=summary, trace_raw=trace, expected=expected,
                manifest_raw=manifest, config_raw=config, layer_raw=layer)


class BrokerEvidenceTests(unittest.TestCase):
    def test_reaped_launcher_cancel_view_cannot_replace_broker_status(self):
        data = evidence()
        launcher = copy.deepcopy(data['inspection'])
        launcher.update(calls=[], denials=[])
        # The two stores set Start deadlines independently; retain both values.
        data['inspection']['attempt']['deadline_ms'] -= 52
        with self.assertRaisesRegex(AssertionError, 'broker evidence incomplete or changed'):
            proof.validate(**dict(data, inspection=launcher))
        proof.validate(**data)
        self.assertEqual(launcher['calls'], [])
        self.assertEqual(launcher['denials'], [])
        self.assertEqual(launcher['attempt']['deadline_ms'] -
                         data['inspection']['attempt']['deadline_ms'], 52)

    def test_complete_source_denials_and_exit_only_seccomp_trace(self):
        result = proof.validate(**evidence())
        self.assertEqual(result['syscall_denials'], 10)
        self.assertEqual(result['broker_cases'], 5)
        self.assertEqual(result['seccomp_enter_absence'], 'not_policy_origin_proof')

    def test_stdout_missing_duplicate_reordered_wrong_errno_false_pass(self):
        for label in ('missing', 'duplicate', 'reorder', 'errno', 'setns_ebadf', 'success', 'namespace', 'bool_pid', 'child', 'missing_marker'):
            data = evidence(); lines = data['stdout'].splitlines()
            if label == 'missing': lines.pop(1)
            elif label == 'duplicate': lines.insert(2, lines[1])
            elif label == 'reorder': lines[1], lines[2] = lines[2], lines[1]
            elif label == 'errno': lines[2] = lines[2].replace(b'"errno":1', b'"errno":2')
            elif label == 'setns_ebadf': lines[6] = lines[6].replace(b'"errno":1', b'"errno":9')
            elif label == 'success': lines[2] = lines[2].replace(b'"result":-1', b'"result":3')
            elif label == 'namespace': lines[0] = lines[0].replace(b'"pid":1', b'"pid":2')
            elif label == 'bool_pid': lines[0] = lines[0].replace(b'"pid":1', b'"pid":true')
            elif label == 'child': lines[-1] = b'BROKER_ACCEPTANCE_PASS child=1'
            else: lines.pop()
            data['stdout'] = b'\n'.join(lines)+b'\n'
            sync_stdout(data)
            with self.subTest(label=label), self.assertRaises(AssertionError): proof.validate(**data)

    def test_structured_broker_replies_and_denial_are_not_substrings(self):
        for label in ('allowed', 'denial', 'closed', 'export_denial', 'duplicate_denial', 'duplicate_json'):
            data = evidence()
            if label == 'allowed': data['stdout'] = data['stdout'].replace(b'"left_delta_ticks":10', b'"left_delta_ticks":11')
            elif label == 'denial': data['stdout'] = data['stdout'].replace(b'policy_denied: method_not_allowed', b'something policy_denied')
            elif label == 'closed': data['stdout'] = data['stdout'].replace(b'publication context closed', b'request already dispatched')
            elif label == 'duplicate_json': data['stdout'] = data['stdout'].replace(b'"event":"sandbox_identity"', b'"event":"wrong","event":"sandbox_identity"')
            else:
                broker = next(x['content'] for x in data['bundle']['artifacts'] if x['name']=='broker')
                broker['policy_denials'] = [] if label=='export_denial' else broker['policy_denials']*2
                rehash(data['bundle'])
            sync_stdout(data)
            with self.subTest(label=label), self.assertRaises(AssertionError): proof.validate(**data)

    def test_attempt_OCI_agent_and_binding_cannot_be_replayed(self):
        for label in ('attempt','artifact','agent','layer','prepared','binding','epoch','cgroup'):
            data = evidence()
            if label in ('attempt','artifact','agent'):
                key = {'attempt':'attempt','artifact':'artifact','agent':'agent_sha256'}[label]
                data['expected'][key] = ('sha256:' if key=='artifact' else '')+'f'*(32 if key=='attempt' else 64)
            elif label == 'layer': data['layer_raw'] += b'x'
            elif label == 'prepared': data['prepared']['state']='running'
            elif label == 'binding': data['prepared']['binding']=data['prepared']['binding'].replace('46207','46208')
            else:
                rows = [json.loads(v) for v in data['trace_raw'].splitlines()]
                if label=='epoch': rows[0]['collector_epoch']='wrong'
                else: rows[0]['event']['cgroup_id']+=1
                sync_trace(data, rows)
            with self.subTest(label=label), self.assertRaises(AssertionError): proof.validate(**data)

    def test_missing_lossy_incomplete_trace_or_wrong_open_connect_denial_rejected(self):
        for label in ('missing','duplicate','lost','exec','fork','open','connect','stderr'):
            data=evidence(); rows=[json.loads(v) for v in data['trace_raw'].splitlines()]
            if label=='missing':rows.pop()
            elif label=='duplicate':rows[-1]=rows[0]
            elif label=='lost':data['summary']['local_lost']=1
            elif label=='exec':rows[0]['event']['kind']=5
            elif label=='fork':rows[-3]['event']['related_pid']=0
            elif label=='open':rows[2]['event']['result']=-1
            elif label=='connect':rows[10]['event']['result']=-1
            else:data['stderr']=b'unexpected'
            if label not in ('lost','stderr'):sync_trace(data, rows)
            with self.subTest(label=label),self.assertRaises(AssertionError):proof.validate(**data)

    def test_no_seccomp_enter_records_is_supported_not_a_false_failure(self):
        data=evidence();rows=[json.loads(v) for v in data['trace_raw'].splitlines()]
        rows=[v for v in rows if v['event']['syscall']!=321]
        for i,v in enumerate(rows,1):v['event']['sequence']=i
        data['trace_raw']=b''.join(encode(v)+b'\n' for v in rows);data['summary']['status']['sequence']=len(rows);data['summary']['retained_bytes']=len(data['trace_raw'])
        next(x['content'] for x in data['bundle']['artifacts'] if x['name']=='runtime_facts')['observer']['sequence']=len(rows)
        rehash(data['bundle']);proof.validate(**data)

    def test_inherited_fds_are_not_hidden_by_topology_or_socket_denial(self):
        for key, value in [('extra_fds', 1), ('stdio_sockets', 1), ('other_fds', 4),
                           ('errors', 1), ('entries', 4097), ('enumeration_fd', 0),
                           ('close_result', -1), ('stdin_closed', True)]:
            data = evidence(); lines = data['stdout'].splitlines(); record = json.loads(lines[1])
            record[key] = value; lines[1] = encode(record); data['stdout'] = b'\n'.join(lines)+b'\n'
            sync_stdout(data)
            with self.subTest(key=key), self.assertRaises(AssertionError): proof.validate(**data)

    def test_closed_stdin_only_is_supported_with_its_fresh_open_control(self):
        data = evidence(); lines=data['stdout'].splitlines(); record=json.loads(lines[1])
        record.update(stdin_closed=1, enumeration_fd=0, other_fds=2, entries=5)
        lines[1]=encode(record); data['stdout']=b'\n'.join(lines)+b'\n';sync_stdout(data)
        rows=[json.loads(v) for v in data['trace_raw'].splitlines()]
        rows[2]['event']['result']=0;sync_trace(data, rows)
        proof.validate(**data)

    def test_bool_trace_kind_and_success_result_are_not_integers(self):
        for syscall, kind, field, value in [(257,1,'kind',True),(42,2,'result',False)]:
            data=evidence(); rows=[json.loads(v) for v in data['trace_raw'].splitlines()]
            row=next(v for v in rows if v['event']['syscall']==syscall and v['event']['kind']==kind)
            row['event'][field]=value;sync_trace(data, rows)
            with self.subTest(field=field),self.assertRaises(AssertionError):
                proof.validate_trace(data['trace_raw'], json.loads(data['prepared']['binding']),
                                     data['expected']['attempt'], data['summary'], [3,-2,-2,-2,-30])


if __name__=='__main__':unittest.main()
