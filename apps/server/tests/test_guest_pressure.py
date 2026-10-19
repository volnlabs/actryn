import copy
import contextlib
import json
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import guest_pressure as campaign
from test_guest_capacity import complete_export, rehash


def fixture():
    attempt = 'a' * 32
    rows = []
    calls = []
    for n in range(4):
        key = f'base-{n}'
        rows.append(dict(event='pressure_call', key=key, writes=1,
                         reply={'result': 'ok', 'value': {'attempt_id': attempt,
                                'request_key': key, 'origin': 'server_attested',
                                'output': {'index': n}}}))
        calls.append(dict(id=f'{n+1:032x}',request_key=key, state='settled', consumed_tokens=0,deadline_ms=100,
                          publication_closed=(n == 0)))
    for n in range(8):
        rows.append(dict(event='pressure_call', key=f'burst-{n}', writes=1,
                         reply={'result': 'error', 'reason': 'attempt call budget exhausted'}))
        calls.append(dict(id=f'{n+5:032x}',request_key=f'burst-{n}',state='cancelled',consumed_tokens=0,
                          deadline_ms=0,publication_closed=True))
    rows.append(dict(event='pressure_cancel', key='base-0', writes=1,
                     reply={'result': 'ok', 'value': {'stage': 'KEY_CANCELLED_DURABLE'}}))
    rows.append(dict(event='pressure_ready', calls=12, cancels=1))
    inspection = dict(attempt={'id': attempt, 'state': 'running', 'outcome': 'pending'},
                      calls=calls, robot_binding=None, robot_requests=[], denials=[],
                      denials_omitted=0, evidence_gaps=[])
    return rows, inspection


def accounting(inspection):
    digests=['a17cf07a90115e5630c582f3ce4e8d828dde70fe9e67c17b6a1e49785dd7aea2',
             'd90243d394ba5ff60254bc05cfd841de44199c361e8dca66b6d709b168280626',
             'b7c197e244cb3f77fff3e2baf5fdcf48d87e148524f44135e4c3e74f95e7c891',
             'b0802de7f56c1a54911ccc63e21d0d9bc682a17e3be7a9657f5fdc2d23a82ee1']
    return [dict(call,attempt_id=inspection['attempt']['id'],publication_closed=int(call['publication_closed']),
                 digest='sha256:'+digests[int(call['request_key'][-1])] if call['request_key'].startswith('base-') else None,
                 request_bytes=48 if call['request_key'].startswith('base-') else 0,
                 response_capacity=65536 if call['request_key'].startswith('base-') else 0,
                 token_reserved=1024 if call['request_key'].startswith('base-') else 0,
                 output_bytes=None if call['publication_closed'] else 100) for call in inspection['calls']]


class PressureTests(unittest.TestCase):
    def failed_preparation(self):
        bundle, attempt, artifact, binding, inspection, _, summary, size, _ = complete_export(False)
        binding['snapshot'] = None; inspection['attempt']['binding'] = json.dumps(binding)
        bundle['artifacts'] = [v for v in bundle['artifacts'] if v['name'] in
                               ('attempt','runtime_binding','runtime_facts')]
        next(v for v in bundle['artifacts'] if v['name']=='runtime_binding')['content'] = binding
        bundle['omissions'] = [dict(artifact=v, reason='retained_log_unavailable', omitted_records=1)
                               for v in ('stdout','stderr')]
        rehash(bundle)
        return [bundle, attempt, artifact, inspection, summary, size]

    def test_failed_allocation_requires_durable_identity_no_created_task_and_full_resources(self):
        campaign.validate_failed_preparation(*self.failed_preparation())
        for fault in ('missing','snapshot','observer','loss','omission','debit','hash','terminal'):
            args=self.failed_preparation(); bundle=args[0]; inspection=args[3]
            content={v['name']:v['content'] for v in bundle['artifacts']}
            if fault=='missing':bundle['artifacts'].pop()
            elif fault=='snapshot':content['runtime_binding']['snapshot']={'pid':5}
            elif fault=='observer':content['runtime_facts']['observer_health_unavailable']=True
            elif fault=='loss':args[4]['local_lost']=1
            elif fault=='omission':bundle['omissions'][0]['reason']='unknown'
            elif fault=='debit':inspection['calls']=[{}]
            elif fault=='terminal':inspection['attempt']['state']='retiring'
            rehash(bundle)
            if fault=='hash':bundle['artifacts'][0]['sha256']='sha256:'+'0'*64
            with self.subTest(fault=fault), self.assertRaises((AssertionError,KeyError)):
                campaign.validate_failed_preparation(*args)

    def test_fault_events_bind_errno_identity_pid_and_finite_lease(self):
        event = b'101 42 A 28 /run/actryn/brokers/' + b'b'*32 + b'\n'
        campaign.validate_fault_events(event, 'A', 'b'*32, 42, 100, 200)
        for bad in (event+event, event.replace(b' A 28 ', b' A 16 '),
                    event.replace(b'42', b'43'), event.replace(b'101', b'201'),
                    event.replace(b'b'*32,b'a'*32), event.replace(b'101',b'99')):
            with self.assertRaises(AssertionError):
                campaign.validate_fault_events(bad, 'A', 'b'*32, 42, 100, 200)

    def test_reclaim_capacity_requires_both_stores_and_preserved_empty_directory(self):
        stores = {'launcher':{'c'*32:'retiring'}, 'broker':{'c'*32:'retiring'}}
        campaign.validate_reclaim(stores, 'c'*32, True, [], False)
        for bad, exists, children, cgroup in (
                ({'launcher':{'c'*32:'reaped'},'broker':{'c'*32:'retiring'}}, True, [], False),
                (stores, False, [], False), (stores, True, ['broker.sock'], False),
                (stores, True, [], True)):
            with self.assertRaises(AssertionError):
                campaign.validate_reclaim(bad, 'c'*32, exists, children, cgroup)

    def test_failed_preparation_only_polls_existing_identity_until_reaped(self):
        run=campaign.Campaign(Path('/unused'),'unused',42)
        run.record=unittest.mock.Mock(); run.cli=unittest.mock.Mock()
        run.stores=unittest.mock.Mock(side_effect=[{'launcher':{'b'*32:'retiring'},'broker':{}},
                                                 {'launcher':{'b'*32:'reaped'},'broker':{}}])
        with patch.object(campaign.time,'sleep'):run.retired_launcher_only('b'*32)
        self.assertEqual(run.cli.call_count,0)
        run.stores=unittest.mock.Mock(return_value={'launcher':{'b'*32:'reaped'},'broker':{'b'*32:'prepared'}})
        with self.assertRaises(AssertionError):run.retired_launcher_only('b'*32)

    def test_fault_control_is_removed_on_failure_without_history_deletion_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'latched').write_text('retained identity')
            run=unittest.mock.Mock()
            with patch.object(campaign, 'CONTROL', root):
                with self.assertRaisesRegex(RuntimeError, 'single mutation failed'):
                    with campaign.FaultControl(run, 'R', 'a'*32, 'b'*32):
                        self.assertTrue((root/'control').exists())
                        raise RuntimeError('single mutation failed')
            self.assertFalse((root/'control').exists())
            self.assertEqual((root/'latched').read_text(), 'retained identity')
            self.assertEqual(run.cli.call_count, 0)

    def test_fault_control_setup_record_failure_also_disarms(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); run=unittest.mock.Mock()
            run.record.side_effect=OSError('record unavailable')
            with patch.object(campaign,'CONTROL',root), self.assertRaises(OSError):
                with campaign.FaultControl(run,'R','a'*32,'b'*32): self.fail('entered failed control')
            self.assertFalse((root/'control').exists())

    def test_shared_export_validator_keeps_hash_and_health_checks_for_pressure_agent(self):
        args=list(complete_export()); rows,pressure=fixture(); attempt=args[1]
        for row in rows[:4]:row['reply']['value']['attempt_id']=attempt
        for call in pressure['calls']:call['publication_closed']=True
        args[4]['calls']=pressure['calls']
        raw=b'\n'.join(json.dumps(row).encode() for row in rows)+b'\n'
        args[5]['stdout']=raw
        content={v['name']:v['content'] for v in args[0]['artifacts']}
        content['broker']['calls']=pressure['calls']
        content['stdout'].update(retained_bytes=len(raw),retained_sha256='sha256:'+campaign.hashlib.sha256(raw).hexdigest(),
                                 tail=raw[-2048:].hex(),tail_omitted_bytes=max(0,len(raw)-2048))
        rehash(args[0])
        check=lambda logs,inspection: campaign.validate_pressure(logs['stdout'],inspection,accounting(inspection))
        campaign.common.validate_export(*args,agent_check=check)
        content['runtime_facts']['observer_health_unavailable']=True; rehash(args[0])
        with self.assertRaises(AssertionError):campaign.common.validate_export(*args,agent_check=check)

    def validate(self, rows, inspection, stored=None):
        return campaign.validate_pressure(b'\n'.join(json.dumps(v).encode() for v in rows)+b'\n', inspection,
                                          accounting(inspection) if stored is None else stored)

    def test_finite_valid_calls_and_denials_pass(self):
        rows, inspection = fixture()
        self.validate(rows, inspection)

    def test_cancelled_denial_keys_are_not_approved_call_reservations(self):
        # Run09: four settled base calls, four budget-denial tombstones, four EOFs.
        rows, inspection = fixture()
        admitted={'burst-2','burst-7','burst-4','burst-3'}
        inspection['calls']=[call for call in inspection['calls'] if call['request_key'].startswith('base-') or call['request_key'] in admitted]
        for row in rows[4:12]:
            if row['key'] not in admitted:
                row.pop('reply'); row['unknown']='eof_after_send'
        self.validate(rows,inspection)

    def test_retained_run09_accounting_validates_without_promoting_failed_campaign(self):
        retained=json.loads((Path(__file__).parent/'fixtures/pressure-call-accounting.json').read_bytes())
        fields=('id','request_key','state','consumed_tokens','deadline_ms')
        inspection=fixture()[1]
        inspection['attempt']['id']=retained['attempt']
        inspection['calls']=[dict({key:row[key] for key in fields},publication_closed=bool(row['publication_closed']))
                             for row in retained['calls']]
        result=campaign.validate_pressure(retained['stdout'].encode(),inspection,retained['calls'])
        self.assertEqual(result['approved_calls'],4)
        self.assertEqual(result['closed_burst_tombstones'],4)
        self.assertEqual(result['uncertain_replies_preserved'],4)

    def test_active_accounting_is_retained_before_validator_failure(self):
        attempt='a'*32;run=campaign.Campaign(Path('/unused'),'unused',42)
        binding={'snapshot':{'pid':42,'start_ticks':7}}
        run.bindings[attempt]=binding
        inspection={'attempt':{'id':attempt,'state':'running','outcome':'pending','binding':json.dumps(binding)}}
        run.status=unittest.mock.Mock(return_value=inspection)
        labels=[];run.record=unittest.mock.Mock(side_effect=lambda label,value:labels.append(label))
        def reject(*args):
            self.assertEqual(labels,['pressure-accounting'])
            raise AssertionError('retain raw accounting on failure')
        with patch.object(campaign.Path,'read_text',return_value='process) '+' '.join(['0']*19+['7'])), \
             patch.object(campaign.common,'read_bounded',return_value=b'unchanged'), \
             patch.object(campaign,'read_broker_accounting',return_value=[{'raw':'retained'}]) as read, \
             patch.object(campaign,'validate_pressure',side_effect=reject):
            with self.assertRaisesRegex(AssertionError,'retain raw accounting'):run.stable((attempt,42,7))
        read.assert_called_once_with(attempt)
        run.record.assert_called_once_with('pressure-accounting',{'attempt':attempt,'rows':[{'raw':'retained'}]})

    def test_burst_tombstones_cannot_hide_reservations_missing_denials_or_unrelated_keys(self):
        for fault in ('missing','duplicate','unrelated','id','attempt','digest','state','closed','output',
                      'request_bytes','response_capacity','token_reserved','consumed_tokens','deadline_ms'):
            rows,inspection=fixture();stored=accounting(inspection)
            target=stored[4]
            if fault=='missing':
                inspection['calls'].pop(4);stored.pop(4)
            elif fault=='duplicate':stored.append(copy.deepcopy(target))
            elif fault=='unrelated':
                target['request_key']=inspection['calls'][4]['request_key']='unrelated'
            elif fault=='id':target['id']=stored[0]['id']
            elif fault=='attempt':target['attempt_id']='b'*32
            elif fault=='digest':target['digest']='sha256:'+'1'*64
            elif fault=='state':target['state']=inspection['calls'][4]['state']='settled'
            elif fault=='closed':target['publication_closed']=0;inspection['calls'][4]['publication_closed']=False
            elif fault=='output':target['output_bytes']=1
            else:
                target[fault]=1
                if fault in ('consumed_tokens','deadline_ms'):inspection['calls'][4][fault]=1
            with self.subTest(fault=fault),self.assertRaises(AssertionError):self.validate(rows,inspection,stored)

    def test_broker_accounting_reader_uses_existing_readonly_database_and_exact_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.sqlite';rows,inspection=fixture();stored=accounting(inspection)
            with contextlib.closing(sqlite3.connect(path)) as db, db:
                # The actual production calls schema; no invented digest/non-null constraint.
                db.execute('''CREATE TABLE attempts (id TEXT PRIMARY KEY,artifact_digest TEXT NOT NULL,
                    state TEXT NOT NULL,deadline_ms INTEGER NOT NULL,binding TEXT,outcome TEXT NOT NULL DEFAULT 'pending')''')
                db.execute('''CREATE TABLE calls (id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL REFERENCES attempts(id),
                    request_key TEXT NOT NULL,digest TEXT,state TEXT NOT NULL,
                    request_bytes INTEGER NOT NULL DEFAULT 0,response_capacity INTEGER NOT NULL DEFAULT 0,
                    token_reserved INTEGER NOT NULL DEFAULT 0,consumed_tokens INTEGER NOT NULL DEFAULT 0,
                    deadline_ms INTEGER NOT NULL DEFAULT 0,publication_closed INTEGER NOT NULL DEFAULT 0,
                    output BLOB,UNIQUE(attempt_id,request_key))''')
                for row in stored:
                    data=dict(row);size=data.pop('output_bytes');data['output']=b'x'*size if size is not None else None
                    db.execute('INSERT INTO calls('+','.join(data)+') VALUES('+','.join('?' for _ in data)+')',tuple(data.values()))
                db.execute("INSERT INTO calls(id,attempt_id,request_key,state) VALUES('other','other','other','cancelled')")
            before=path.read_bytes();names=set(Path(directory).iterdir())
            self.assertEqual(campaign.read_broker_accounting(inspection['attempt']['id'],path),stored)
            self.assertEqual(path.read_bytes(),before);self.assertEqual(set(Path(directory).iterdir()),names)
            absent=Path(directory)/'absent'
            with self.assertRaises(FileNotFoundError):campaign.read_broker_accounting(inspection['attempt']['id'],absent)
            self.assertFalse(absent.exists())
            link=Path(directory)/'link';link.symlink_to(path)
            with self.assertRaises(AssertionError):campaign.read_broker_accounting(inspection['attempt']['id'],link)
            with contextlib.closing(sqlite3.connect(path)) as db, db:
                db.execute("INSERT INTO calls(id,attempt_id,request_key,state) VALUES('extra',?,'extra','cancelled')",(inspection['attempt']['id'],))
            with self.assertRaisesRegex(AssertionError,'row capacity'):campaign.read_broker_accounting(inspection['attempt']['id'],path)

    def test_rehashed_unrelated_failures_missing_requests_or_extra_debits_cannot_pass(self):
        for fault in ('success', 'unrelated', 'missing', 'duplicate', 'resend', 'uncancelled',
                      'extra_debit', 'robot', 'gap', 'identity'):
            with self.subTest(fault=fault):
                rows, inspection = fixture()
                if fault == 'success': rows[4]['reply'] = {'result': 'ok', 'value': {}}
                elif fault == 'unrelated': rows[4]['reply']['reason'] = 'database corrupt'
                elif fault == 'missing': del rows[4]
                elif fault == 'duplicate': rows[5] = copy.deepcopy(rows[4])
                elif fault == 'resend': rows[4]['writes'] = 2
                elif fault == 'uncancelled': inspection['calls'][0]['publication_closed'] = False
                elif fault == 'extra_debit': inspection['calls'].append(dict(inspection['calls'][0]))
                elif fault == 'robot': inspection['robot_requests'] = [{}]
                elif fault == 'gap': inspection['evidence_gaps'] = ['unknown']
                elif fault == 'identity': rows[0]['reply']['value']['attempt_id'] = 'b' * 32
                with self.assertRaises(AssertionError): self.validate(rows, inspection)

    def test_transport_uncertainty_needs_a_complete_single_send_and_real_budget_denial(self):
        rows, inspection = fixture()
        rows[4].pop('reply'); rows[4]['unknown'] = 'eof_after_send'
        self.validate(rows, inspection)
        for v in rows[4:12]:
            v.pop('reply', None); v['unknown'] = 'eof_after_send'
        with self.assertRaises(AssertionError): self.validate(rows, inspection)

    def test_actual_agent_sends_bounded_unique_requests_once_over_unix_sockets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'agent'
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-DACTRYN_PRESSURE_HOST_TEST', '-o', str(binary),
                            str(Path(__file__).with_name('pressure_agent.c'))], check=True, timeout=15)
            accepted, errors, listeners, threads = [], [], [], []
            for endpoint in ('broker.sock', 'closure.sock'):
                listener = socket.socket(socket.AF_UNIX); listener.bind(str(root / endpoint))
                listener.listen(16); listener.settimeout(3); listeners.append(listener)
                def serve(server=listener, count=(12 if endpoint == 'broker.sock' else 1)):
                    try:
                        for _ in range(count):
                            with server.accept()[0] as conn:
                                conn.settimeout(2)
                                def read(size):
                                    data = b''
                                    while len(data) < size:
                                        part = conn.recv(size-len(data)); assert part
                                        data += part
                                    return data
                                size, = struct.unpack('!I', read(4)); assert size < 4096
                                value = json.loads(read(size)); accepted.append(value)
                                key = value['request_key']
                                if value['op'] == 'cancel': reply = {'result':'ok','value':{'stage':'KEY_CANCELLED_DURABLE'}}
                                elif key.startswith('base-'): reply = {'result':'ok','value':{'attempt_id':'a'*32,'request_key':key,'origin':'server_attested','output':value['input']}}
                                else: reply = {'result':'error','reason':'attempt call budget exhausted'}
                                body = json.dumps(reply).encode(); conn.sendall(struct.pack('!I',len(body))+body)
                    except BaseException as error: errors.append(error)
                thread = threading.Thread(target=serve); thread.start(); threads.append(thread)
            try:
                run = subprocess.run([str(binary), str(root)], capture_output=True, timeout=8)
            finally:
                for t in threads: t.join(timeout=4)
                for listener in listeners: listener.close()
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(len(accepted), 13)
            self.assertFalse(errors)
            self.assertEqual(sum(v['op']=='cancel' for v in accepted), 1)
            self.assertEqual({v['request_key'] for v in accepted},
                             {f'base-{n}' for n in range(4)} | {f'burst-{n}' for n in range(8)})
            self.assertTrue(all(v['method']=='diagnostic.echo' for v in accepted if v['op']=='call'))
            inspection=fixture()[1]
            campaign.validate_pressure(run.stdout,inspection,accounting(inspection))


if __name__ == '__main__': unittest.main()
