import copy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import guest_freeze_crash as crash

from guest_freeze_crash import (CAMPAIGN, HISTORY, SignalSequence, expiry_inference, finalize_result, main, process_identity,
    json_file,parse_fixture,same_disk_restart,unit_state,validate_crash_capture,validate_history,validate_unknown,verify_phase_handoff,verify_raw_archive,wait_read)


class FreezeTests(unittest.TestCase):
    def cold_evidence(self):
        boot='22222222-2222-4222-8222-222222222222'
        fields='MainPID=0\nActiveState=inactive\nUnitFileState=disabled\nExecMainStartTimestampMonotonic=0\n'
        def reply(out):return dict(exit=0,stdout=out,stderr='',timeout=False,overflow=False,argv=[])
        queries={u:reply(fields) for u in ('actryn-robotd','actryn-gatewayd')}
        queries['boot-journal']=reply(json.dumps({'_BOOT_ID':boot.replace('-',''),
            '__CURSOR':'s=retained;i=1','__MONOTONIC_TIMESTAMP':'123'})+'\n')
        queries['unit-journal']=reply('')
        return dict(boot_id=boot,boot_id_after=boot,queries=queries)

    def test_cold_service_evidence_rejects_started_enabled_missing_or_uncertain_journal(self):
        good=self.cold_evidence();crash.validate_cold_services(good,good['boot_id'])
        changes=[lambda v:v.update(boot_id_after='another-boot'),
            lambda v:v['queries'].pop('boot-journal'),
            lambda v:v['queries']['boot-journal'].update(stdout=''),
            lambda v:v['queries']['boot-journal'].update(stdout='{}\n'),
            lambda v:v['queries']['boot-journal'].update(stdout='{}\n{}\n'),
            lambda v:v['queries']['boot-journal'].update(exit=1),
            lambda v:v['queries']['unit-journal'].update(timeout=True),
            lambda v:v['queries']['unit-journal'].update(overflow=True),
            lambda v:v['queries']['unit-journal'].update(stderr='journal unavailable'),
            lambda v:v['queries']['unit-journal'].update(stdout='{"UNIT":"actryn-robotd.service"}\n')]
        for unit in ('actryn-robotd','actryn-gatewayd'):
            for old,new in [('disabled','enabled'),('TimestampMonotonic=0','TimestampMonotonic=100'),
                            ('MainPID=0','MainPID=42'),('ActiveState=inactive','ActiveState=active'),
                            ('UnitFileState=disabled\n','')]:
                changes.append(lambda v,u=unit,a=old,b=new:v['queries'][u].update(
                    stdout=v['queries'][u]['stdout'].replace(a,b)))
        for change in changes:
            bad=copy.deepcopy(good);change(bad)
            with self.subTest(bad=bad),self.assertRaises(AssertionError):
                crash.validate_cold_services(bad,good['boot_id'])

    def test_guest_cold_queries_use_exact_boot_and_bounded_read_only_presence_checks(self):
        good=self.cold_evidence();responses=[good['queries'][name]
            for name in ('actryn-robotd','actryn-gatewayd','boot-journal','unit-journal')]
        seen=[]
        def run(argv,**kwargs):
            seen.append((argv,kwargs));r=responses[len(seen)-1]
            return SimpleNamespace(returncode=r['exit'],stdout=r['stdout'].encode(),stderr=b'')
        output=io.StringIO()
        with (patch('pathlib.Path.read_text',return_value=good['boot_id']+'\n'),
              patch('subprocess.run',side_effect=run),contextlib.redirect_stdout(output)):
            exec(crash.COLD_SERVICES,{})
        value=json.loads(output.getvalue());crash.validate_cold_services(value,good['boot_id'])
        self.assertEqual(len(seen),4)
        self.assertTrue(all(options=={'capture_output':True,'timeout':2} for _,options in seen))
        for argv,_ in seen[2:]:
            self.assertIn('--boot='+good['boot_id'].replace('-',''),argv)
            self.assertIn('--lines=1',argv)
            self.assertIn('--output-fields=_BOOT_ID,__MONOTONIC_TIMESTAMP',argv)
        self.assertEqual(seen[3][0][-2:],['--unit=actryn-robotd.service','--unit=actryn-gatewayd.service'])

    def test_cold_query_timeout_and_overflow_remain_evidence_not_empty_success(self):
        good=self.cold_evidence()
        for failure in ('timeout','overflow'):
            output=io.StringIO()
            if failure=='timeout':effect=subprocess.TimeoutExpired(['journalctl'],2,output=b'partial')
            else:effect=None
            with (patch('pathlib.Path.read_text',return_value=good['boot_id']+'\n'),
                  patch('subprocess.run',side_effect=effect,
                        return_value=SimpleNamespace(returncode=0,stdout=b'x'*65537,stderr=b'')),
                  contextlib.redirect_stdout(output)):
                exec(crash.COLD_SERVICES,{})
            value=json.loads(output.getvalue())
            self.assertTrue(all(q[failure] for q in value['queries'].values()))
            with self.assertRaisesRegex(AssertionError,'availability uncertain'):
                crash.validate_cold_services(value,good['boot_id'])

    def test_cold_archive_and_service_start_are_surrounded_by_fresh_checks(self):
        good=self.cold_evidence();boot=good['boot_id']
        units={u:dict(row.split('=',1) for row in good['queries'][u]['stdout'].splitlines())
               for u in ('actryn-robotd','actryn-gatewayd')}
        for fail_check in (None,1,2,3):
            with self.subTest(fail_check=fail_check),tempfile.TemporaryDirectory() as d:
                campaign=crash.CrashCampaign(SimpleNamespace(output=Path(d),ssh_key='/key',
                    ssh_port=26223,known_hosts='/known'));campaign.plan_sha256='frozen'
                order=[];count=0
                def remote(_campaign,program):
                    nonlocal count
                    if program==crash.GUEST_FACTS:
                        return {'units':units,'public_identity':{}}
                    self.assertEqual(program,crash.COLD_SERVICES);count+=1;order.append('cold')
                    value=copy.deepcopy(good)
                    if count==fail_check:value['queries']['unit-journal']['stdout']='prior activation\n'
                    return value
                def archive(_argv,**kwargs):
                    order.append('archive');kwargs['stdout'].write(b'preserved cold bytes')
                    return SimpleNamespace(returncode=0,stderr=b'')
                def history():order.append('history');return {}
                def start(*_args,**_kwargs):order.append('start');raise RuntimeError('stop after start boundary')
                campaign.history=history;campaign.run=start
                handoff={'plan_sha256':'frozen','guest':{'public_identity':{}},'prepared':{},
                    'operation':{'boot':3},'history':{},
                    'handle':{'attempt':'aa'*16,'namespace':'bb'*16,'key':'cc'*32}}
                with (patch('guest_freeze_crash.same_disk_restart'),patch('guest_freeze_crash.PinnedQemu'),
                      patch('guest_freeze_crash.remote_json',side_effect=remote),
                      patch('guest_freeze_crash.validate_guest'),patch('guest_freeze_crash.write_json'),
                      patch('guest_freeze_crash.subprocess.run',side_effect=archive),
                      patch('guest_freeze_crash.verify_raw_archive',return_value={}),
                      patch('guest_freeze_crash.validate_history'),patch('guest_freeze_crash.FixtureStatus') as fixture):
                    fixture.return_value.read.return_value=dict(boot=3,left=0,right=0,enabled=False)
                    with self.assertRaises((AssertionError,RuntimeError)):
                        campaign.inspect({'boot_id':'11111111-1111-4111-8111-111111111111','qemu':{},'fixture':{}},
                            {'boot_id':boot,'qemu':{}},{'handoff':handoff})
                expected={None:['cold','archive','cold','history','cold','start'],1:['cold'],
                    2:['cold','archive','cold'],3:['cold','archive','cold','history','cold']}[fail_check]
                self.assertEqual(order,expected)
                self.assertEqual((Path(d)/'cold-runtime.tar.gz').exists(),fail_check!=1)

    def test_prior_service_start_rejects_before_cold_archive(self):
        boot='22222222-2222-4222-8222-222222222222'
        facts={'units':{u:{'ActiveState':'inactive','MainPID':'0','UnitFileState':'disabled',
                          'ExecMainStartTimestampMonotonic':'100'}
                         for u in ('actryn-robotd','actryn-gatewayd')}}
        with tempfile.TemporaryDirectory() as d:
            campaign=crash.CrashCampaign(SimpleNamespace(output=Path(d),ssh_key='/key',
                ssh_port=26223,known_hosts='/known'))
            with (patch('guest_freeze_crash.same_disk_restart'),patch('guest_freeze_crash.PinnedQemu'),
                  patch('guest_freeze_crash.remote_json',return_value=facts),
                  patch('guest_freeze_crash.validate_guest'),patch('guest_freeze_crash.write_json'),
                  patch('guest_freeze_crash.subprocess.run',side_effect=AssertionError('archive reached')) as archive):
                with self.assertRaisesRegex(AssertionError,'cold service activation'):
                    campaign.inspect({'boot_id':'11111111-1111-4111-8111-111111111111','qemu':{}},
                                     {'boot_id':boot,'qemu':{}},{})
            archive.assert_not_called()
            self.assertFalse((Path(d)/'cold-runtime.tar.gz').exists())

    def test_enabled_service_rejects_before_preparation_or_signal(self):
        campaign=crash.CrashCampaign(SimpleNamespace(output=Path('/unused'),ssh_key='/key',
            ssh_port=26223,known_hosts='/known'))
        facts={'units':{'actryn-robotd':{'UnitFileState':'enabled'},
                        'actryn-gatewayd':{'UnitFileState':'disabled'}}}
        with (patch('guest_freeze_crash.PinnedQemu') as qemu,patch('guest_freeze_crash.FixtureStatus'),
              patch('guest_freeze_crash.remote_json',return_value=facts),
              patch('guest_freeze_crash.validate_guest'),patch('guest_freeze_crash.write_json'),
              patch.object(campaign,'setup') as setup):
            with self.assertRaisesRegex(AssertionError,'disabled before crash'):
                campaign.freeze({'qemu':{},'fixture':{},'boot_id':'original'})
        setup.assert_not_called();qemu.return_value.send.assert_not_called()

    def test_sdk_change_is_in_inspect_chain_before_output_or_ssh(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);tests=root/'apps/robotd/tests';tests.mkdir(parents=True)
            selected=tests/'guest_freeze_crash.py';selected.write_text('# selected harness\n')
            sdk=root/'sdk/python/actryn';sdk.mkdir(parents=True)
            for name in ('__init__.py','client.py','robot_v1_pb2.py'):(sdk/name).write_text('# original\n')
            original={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in [selected,*sdk.glob('*.py')]}
            (sdk/'client.py').write_text('# changed executed RPC implementation\n')
            binary=root/'binary';binary.write_bytes(b'pinned');digest=hashlib.sha256(binary.read_bytes()).hexdigest()
            rpc={k:str(binary) for k in ('cli','reader','ssh_key','known_hosts','ca','cert','key')}
            rpc.update(ssh_port=26223,tcp_port=27445,principal='existing',dns='robot.test',
                       pin='a'*64,manager_sha256='a'*64,gateway_sha256='a'*64,module_note_sha256='a'*64)
            plan={'allow_disposable_guest':True,'machine_id':'a'*32,
                'boot_id':'11111111-1111-4111-8111-111111111111','manifest_sha256':'b'*64,
                'rpc':rpc,'cli_sha256':digest,'reader_sha256':digest,
                'qemu':{'argv':['qemu','-chardev','socket,id=controller,path=/controller']},
                'fixture':{'controller_path':'/controller'}}
            (root/'plan.json').write_text(json.dumps(plan));(root/'restart.json').write_text('{}')
            def frozen_chain(_directory,_plan,_digest,current):
                # Production chain compares the full pin map; changes must be
                # visible before output creation and SharedSsh construction.
                for name,expected in current.items():
                    if name in original and expected!=original[name]:
                        raise AssertionError('changed executed SDK in frozen handoff')
                return {}
            argv=['guest_freeze_crash.py','inspect','--plan',str(root/'plan.json'),
                '--before',str(root/'before'),'--restart',str(root/'restart.json'),'--output',str(root/'output')]
            with (patch.object(sys,'argv',argv),patch.object(crash,'ROOT',root),
                  patch.object(crash,'__file__',str(selected)),
                  patch('guest_freeze_crash.verify_phase_handoff',side_effect=frozen_chain),
                  patch('guest_freeze_crash.SharedSsh',side_effect=AssertionError('SSH reached')) as ssh):
                with self.assertRaisesRegex(AssertionError,'changed executed SDK'):
                    main()
            ssh.assert_not_called();self.assertFalse((root/'output').exists())

    def fixture(self):
        h = SimpleNamespace(attempt=b'a'*16, namespace=b'n'*16, key=b'k'*32)
        op = dict(device=[1]*16, runtime_nonce=[2]*16, boot=3, session=4,
                  grant=5, instance=6, operation=7, stream=8)
        raw=(bytes([1])*16+bytes([2])*16+struct.pack('<6Q',3,4,5,6,7,8)).hex()
        rows = {'namespaces': [['6e'*16, '61'*16, '02'*16, 1, 0]],
                'records': [['6e'*16, '6b'*32, 2, 0, 3, raw]]}
        return h, op, rows

    def test_changed_or_missing_original_history_never_passes(self):
        h, op, before = self.fixture()
        validate_history(before,copy.deepcopy(before),h,op)
        for change in (lambda x: x['records'].clear(),
                       lambda x: x['namespaces'][0].__setitem__(1, 'ff'*16),
                       lambda x: x['records'][0].__setitem__(3, 1),
                       lambda x: x['records'][0].__setitem__(5, 'different-operation'),
                       lambda x: x['records'].append(x['records'][0])):
            after = copy.deepcopy(before); change(after)
            with self.assertRaises(AssertionError):
                validate_history(before, after, h, op)

    def test_history_unknown_requires_exact_identity_and_no_live_authority(self):
        h, op, _ = self.fixture()
        good = {'live_authority': False, 'snapshot': {'namespace':list(h.namespace), 'key':list(h.key),
            'operation':op, 'terminal':True, 'phase':'OutcomeUnknown', 'verdict':'OutcomeUnknown',
            'reconciled':False, 'cancellation_durable':False, 'persistence_failed':False}}
        validate_unknown(good, h, op)
        for change in (lambda v:v.update(live_authority=True),
                       lambda v:v['snapshot'].update(operation=dict(op, operation=9)),
                       lambda v:v['snapshot'].update(phase='Completed'),
                       lambda v:v['snapshot'].update(reconciled=True)):
            bad=copy.deepcopy(good);change(bad)
            with self.assertRaises(AssertionError):validate_unknown(bad,h,op)

    def test_kill_requires_confirmed_freeze_and_expiry_observation_and_never_retries(self):
        events=[]
        s=SignalSequence(lambda state:events.append(('guard',state)),
                         lambda sig:events.append(('signal',sig)),lambda *v:None)
        with self.assertRaises(AssertionError):s.kill({'source_timing_inference':True})
        s.freeze()
        with self.assertRaises(AssertionError):s.freeze()
        with self.assertRaises(AssertionError):s.kill({})
        s.kill({'source_timing_inference':True,'disabled_zero':True})
        with self.assertRaises(AssertionError):s.kill({'source_timing_inference':True,'disabled_zero':True})
        self.assertEqual(events,[('guard','running'),('signal',signal.SIGSTOP),
                                 ('guard','stopped'),('signal',signal.SIGKILL)])

    def test_changed_guard_and_failed_signal_cannot_select_another_pid_or_repeat(self):
        sent=[]
        def changed(_):raise AssertionError('identity changed')
        s=SignalSequence(changed, sent.append,lambda *v:None)
        with self.assertRaises(AssertionError):s.freeze()
        self.assertEqual(sent,[])
        def denied(sig):sent.append(sig);raise OSError('denied')
        s=SignalSequence(lambda _:None,denied,lambda *v:None)
        with self.assertRaises(OSError):s.freeze()
        with self.assertRaises(AssertionError):s.freeze()
        self.assertEqual(sent,[signal.SIGSTOP])

    def test_expiry_inference_never_claims_observed_fault_reason(self):
        _,op,_=self.fixture()
        before=dict(state='Active',boot=3,session=4,left=100,right=-100,enabled=True,now_ns=1_000_000_000,queued=0)
        after=dict(before,state='Faulted',left=0,right=0,enabled=False,now_ns=1_600_000_000)
        proof=expiry_inference(before,after,op)
        self.assertEqual(proof,{'source_timing_inference':True,'disabled_zero':True,
                               'fault_reason_observed':False,'elapsed_fixture_ns':600_000_000})
        for change in (dict(state='Active'),dict(boot=9),dict(enabled=True),dict(left=1),
                       dict(now_ns=1_100_000_000),dict(now_ns=4_000_000_000),dict(queued=32)):
            with self.assertRaises(AssertionError):expiry_inference(before,dict(after,**change),op)

    def archive(self,path,metadata_padding=0,change=lambda v:None):
        raw=b'raw original registry bytes'
        inventory={'files':{'intent.sqlite':{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}},
                   'bytes':len(raw),'padding':' '*metadata_padding}
        change(inventory)
        with tarfile.open(path,'w:gz') as a:
            for name,data in [('inventory.json',json.dumps(inventory).encode()),('runtime/intent.sqlite',raw)]:
                m=tarfile.TarInfo(name);m.size=len(data);a.addfile(m,io.BytesIO(data))

    def test_cold_archive_is_hash_verified_and_inventory_read_is_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'raw.tar.gz';self.archive(p);self.assertIn('intent.sqlite',verify_raw_archive(p)['files'])
            self.archive(p,change=lambda v:v['files']['intent.sqlite'].update(sha256='f'*64))
            with self.assertRaises(AssertionError):verify_raw_archive(p)
            self.archive(p,metadata_padding=1024*1024)
            with self.assertRaises(AssertionError):verify_raw_archive(p)

    def test_absolute_read_deadline_rejects_late_success(self):
        def late():time.sleep(.02);return True
        with self.assertRaises(AssertionError):wait_read(late,bool,.005)

    def test_new_boot_cannot_substitute_another_disk_or_reuse_invocation(self):
        before={'pid':12,'invocation_id':'old','argv':['qemu','-drive','file=retained.qcow2','-serial','file:old.log','-qmp','old.sock']}
        after=copy.deepcopy(before);after.update(pid=13,invocation_id='new');after['argv'][-1]='new.sock'
        same_disk_restart(before,after)
        for bad in (dict(after,pid=12),dict(after,invocation_id='old')):
            with self.assertRaises(AssertionError):same_disk_restart(before,bad)
        after['argv'][2]='file=other.qcow2'
        with self.assertRaises(AssertionError):same_disk_restart(before,after)

    def test_read_only_guest_history_program_retains_actual_sqlite_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'intent.sqlite'
            with contextlib.closing(sqlite3.connect(p)) as db, db:
                db.executescript('CREATE TABLE namespaces(id BLOB,attempt BLOB,epoch BLOB,revision INT,retired INT);'
                    'CREATE TABLE records(namespace BLOB,key BLOB,revision INT,terminal INT,phase INT,operation BLOB,intent BLOB,closure BLOB);')
                db.execute('INSERT INTO namespaces VALUES(?,?,?,?,?)',(b'n'*16,b'a'*16,b'e'*16,1,0))
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)',(b'n'*16,b'k'*32,2,0,3,b'o'*80,b'intent',b'c'*9))
            original=p.read_bytes()
            program=HISTORY.replace("'/var/lib/actryn-robot/runtime/intent.sqlite'",repr(str(p)))
            result=subprocess.run([sys.executable,'-B','-c',program],capture_output=True,timeout=2)
            self.assertEqual(result.returncode,0,result.stderr)
            value=json.loads(result.stdout);self.assertEqual(value['records'][0][3:5],[0,3])
            self.assertEqual(p.read_bytes(),original)
            self.assertFalse(p.with_name('intent.sqlite-journal').exists())

    def test_one_owned_child_really_stops_before_pidfd_kill(self):
        child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(10)'])
        fd=os.pidfd_open(child.pid);identity=process_identity(child.pid)
        def guard(state):
            actual=process_identity(child.pid);self.assertEqual(actual['start_ticks'],identity['start_ticks'])
            self.assertEqual(actual['state'] in ('T','t'),state=='stopped')
        try:
            sequence=SignalSequence(guard,lambda sig:signal.pidfd_send_signal(fd,sig),lambda *_:None)
            sequence.freeze();wait_read(lambda:process_identity(child.pid),lambda v:v['state']=='T',1)
            sequence.kill({'source_timing_inference':True,'disabled_zero':True})
            self.assertEqual(child.wait(timeout=2),-signal.SIGKILL)
        finally:
            os.close(fd)
            if child.poll() is None:child.kill();child.wait(timeout=2)

    def test_success_sentinel_requires_completed_hash_collection(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(CAMPAIGN,output=Path(d)):
            (Path(d)/'original.json').write_text('{}')
            finalize_result({'status':'PASS'})
            self.assertTrue((Path(d)/'phase-result.json').exists())
            value=json.loads((Path(d)/'phase-result.json').read_bytes())
            self.assertEqual(value['artifact_hashes_sha256'],hashlib.sha256((Path(d)/'artifact-hashes.json').read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory() as d,patch.dict(CAMPAIGN,output=Path(d)):
            (Path(d)/'original.json').write_text('{}')
            with patch('guest_freeze_crash.sha',side_effect=OSError('read failed')):
                with self.assertRaises(OSError):finalize_result({'status':'PASS'})
            self.assertFalse((Path(d)/'phase-result.json').exists())

    def test_crash_capture_cannot_claim_completion_or_second_dispatch(self):
        from test_gateway_capture import fixture
        decoded,handle,prepared,operation=fixture()
        decoded['records']=decoded['records'][:3]  # Proposal, actual allocation and START; no closure.
        handoff={'operation':operation,'prepared':prepared}
        proof=validate_crash_capture(decoded,handoff,handle)
        self.assertEqual(proof['accepted_proposals'],1)
        self.assertFalse(proof['execution_replay_eligible'])
        terminal=copy.deepcopy(decoded['records'][-1]);terminal['value']['kind']=0x30001
        terminal['value']['sequence']+=1
        decoded['records'].append(terminal)
        with self.assertRaises(AssertionError):validate_crash_capture(decoded,handoff,handle)
        decoded['records'].pop();decoded['records'].append(copy.deepcopy(decoded['records'][1]))
        with self.assertRaises(AssertionError):validate_crash_capture(decoded,handoff,handle)

    def handoff(self, directory):
        plan={'boot_id':'original-boot'};pins={'apps/robotd/tests/guest_freeze_crash.py':'a'*64}
        digest='b'*64
        handoff={'plan_sha256':digest,'handle':{'key':'original-key'}}
        values={'plan.json':plan,'source-pins.json':pins,'before-freeze.json':handoff,
                'handle.json':handoff['handle'],'fixture-closure.json':{'proof':{'disabled_zero':True}},
                'crashed.json':{'handoff':handoff,'fixture_proof':{'disabled_zero':True},
                    'signal_attempts':['SIGSTOP','SIGKILL'],'same_disk_restart_required':True,
                    'pure_instantaneous_powercut':False,'automatic_retry':False}}
        for name,value in values.items():(directory/name).write_text(json.dumps(value))
        with patch.dict(CAMPAIGN,output=directory):
            finalize_result({'status':'FROZEN_CRASH_COMPLETE','actual_inspection':'NOT_RUN',
                             'automatic_retry':False,'pure_instantaneous_powercut':False})
        return plan,digest,pins,values['crashed.json']

    def test_phase_handoff_verifies_crash_bytes_and_inventory_before_use(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);plan,digest,pins,crashed=self.handoff(p)
            self.assertEqual(verify_phase_handoff(p,plan,digest,pins),crashed)
            (p/'crashed.json').write_text(json.dumps(dict(crashed,signal_attempts=['SIGKILL'])))
            with self.assertRaises(AssertionError):verify_phase_handoff(p,plan,digest,pins)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);plan,digest,pins,_=self.handoff(p)
            inventory=json_file(p/'artifact-hashes.json',65536);inventory['crashed.json']='f'*64
            (p/'artifact-hashes.json').write_text(json.dumps(inventory))
            with self.assertRaises(AssertionError):verify_phase_handoff(p,plan,digest,pins)

    def test_phase_handoff_rejects_failure_missing_inputs_and_mixed_chain(self):
        for name,change in [('failure.json',{}),('before-freeze.json',{'plan_sha256':'c'*64}),
                            ('plan.json',{'boot_id':'another-boot'}),('source-pins.json',{'different':'f'*64}),
                            ('handle.json',{'key':'different'}),('fixture-closure.json',{'proof':{}})]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                p=Path(d);plan,digest,pins,_=self.handoff(p)
                (p/name).write_text(json.dumps(change))
                # Even a freshly hashed inventory cannot hide an inconsistent required chain.
                result=json_file(p/'phase-result.json',65536);result.pop('artifact_hashes_sha256')
                (p/'artifact-hashes.json').unlink();(p/'phase-result.json').unlink()
                with patch.dict(CAMPAIGN,output=p):finalize_result(result)
                with self.assertRaises(AssertionError):verify_phase_handoff(p,plan,digest,pins)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);plan,digest,pins,_=self.handoff(p);(p/'before-freeze.json').unlink()
            with self.assertRaises((AssertionError,FileNotFoundError)):verify_phase_handoff(p,plan,digest,pins)

    def test_phase_handoff_rejects_nonregular_and_oversized_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);plan,digest,pins,_=self.handoff(p)
            (p/'artifact-hashes.json').unlink();os.mkfifo(p/'artifact-hashes.json')
            with self.assertRaises(AssertionError):verify_phase_handoff(p,plan,digest,pins)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);plan,digest,pins,_=self.handoff(p)
            (p/'artifact-hashes.json').write_bytes(b' '*(1024*1024+1))
            with self.assertRaises(AssertionError):verify_phase_handoff(p,plan,digest,pins)

    def test_inspect_rejects_bad_handoff_before_output_or_ssh_open(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);binary=p/'binary';binary.write_bytes(b'pinned')
            digest=hashlib.sha256(binary.read_bytes()).hexdigest()
            rpc={k:str(binary) for k in ('cli','reader','ssh_key','known_hosts','ca','cert','key')}
            rpc.update(ssh_port=26223,tcp_port=27445,principal='existing',dns='robot.test',
                       pin='a'*64,manager_sha256='a'*64,gateway_sha256='a'*64,module_note_sha256='a'*64)
            plan={'allow_disposable_guest':True,'machine_id':'a'*32,
                  'boot_id':'11111111-1111-4111-8111-111111111111','manifest_sha256':'b'*64,
                  'rpc':rpc,'cli_sha256':digest,'reader_sha256':digest,
                  'qemu':{'argv':['qemu','-chardev','socket,id=controller,path=/controller']},
                  'fixture':{'controller_path':'/controller'}}
            (p/'plan.json').write_text(json.dumps(plan))
            argv=['guest_freeze_crash.py','inspect','--plan',str(p/'plan.json'),'--before',str(p/'before'),
                  '--restart',str(p/'restart.json'),'--output',str(p/'output')]
            with (patch.object(sys,'argv',argv),patch('guest_freeze_crash.verify_phase_handoff',
                    side_effect=AssertionError('tampered')) as verify,patch('guest_freeze_crash.SharedSsh') as ssh,
                    patch('guest_freeze_crash.CrashCampaign') as campaign):
                with self.assertRaisesRegex(AssertionError,'tampered'):main()
            verify.assert_called_once();ssh.assert_not_called();campaign.assert_not_called()
            self.assertFalse((p/'output').exists())

    def test_fixture_status_parser_preserves_origin_fields_and_rejects_ambiguous_frame(self):
        raw=b'state=Active boot=3 session=4 duties=(100, -100, true) encoders=[2, -2] queued=0 now_ns=123\n'
        value=parse_fixture(raw);self.assertEqual(value['boot'],3);self.assertEqual(value['encoders'],[2,-2])
        self.assertTrue(value['enabled'])
        for bad in (raw+raw,raw[:-1],b'OK\n',raw.replace(b'boot=3',b'boot=-1')):
            with self.assertRaises(AssertionError):parse_fixture(bad)

    def test_plan_read_rejects_symlink_fifo_and_oversize_before_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'plan';p.write_text('{}');self.assertEqual(json_file(p,2),{})
            link=Path(d)/'link';link.symlink_to(p)
            with self.assertRaises(OSError):json_file(link,2)
            fifo=Path(d)/'fifo';os.mkfifo(fifo)
            with self.assertRaises(AssertionError):json_file(fifo,2)
            p.write_text('{} ')
            with self.assertRaises(AssertionError):json_file(p,2)

    def test_current_manager11_owned_unit_is_accepted_and_unrelated_units_are_rejected(self):
        reply=SimpleNamespace(returncode=0,stdout=b'MainPID=42\nActiveState=active\n')
        for name in ('actryn-install-robot-vm01.service','actryn-install-robot-manager11-vm01.service'):
            with patch('guest_freeze_crash.subprocess.run',return_value=reply):
                try:value=unit_state(name)
                except AssertionError:value=None
                self.assertEqual(value,{'MainPID':'42','ActiveState':'active'})
        for name in ('actryn-preview-robot.service','unrelated.service','actryn-install-robot-manager12-vm01.service',
                     'actryn-install-robot-vm01.service;echo', '../actryn-install-robot-vm01.service'):
            with self.assertRaises(AssertionError):unit_state(name)


if __name__=='__main__':unittest.main()
