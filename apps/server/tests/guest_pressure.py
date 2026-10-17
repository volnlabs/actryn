#!/usr/bin/env python3
"""Opt-in, instrumented A08 server workload; no Robot or provider calls."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import struct
import subprocess
import threading
import time
import uuid
import guest_capacity as common

CONTROL = Path('/run/actryn/a08-pressure')
require = common.require


def validate_fault_events(raw, mode, attempt, pid, start, end):
    require(len(raw) <= 8192 and raw.endswith(b'\n') and 0 < end-start <= 10_000_000_000,
            'fault event bound or lease')
    rows = [line.split() for line in raw.decode('ascii').splitlines()]
    require(1 <= len(rows) <= (1 if mode == 'A' else 64), 'fault count')
    for row in rows:
        require(len(row) == 5 and start <= int(row[0]) < end
                and int(row[1]) == pid and row[2] == mode
                and int(row[3]) == (28 if mode == 'A' else 16)
                and row[4] == '/run/actryn/brokers/' + attempt, 'fault target/errno/lease changed')


def validate_reclaim(stores, attempt, directory_exists, children, cgroup_exists):
    require(set(stores) == {'launcher', 'broker'}
            and all(rows.get(attempt) == 'retiring' for rows in stores.values())
            and directory_exists and children == [] and not cgroup_exists,
            'reclaim failure did not retain both debits and only the empty broker directory')


class FaultControl:
    """One fixed ten-second control; removing it never retries the failed mutation."""
    def __init__(self, campaign, mode, active, target='0'*32):
        require(mode in ('A', 'R') and all(re.fullmatch('[0-9a-f]{32}', v) for v in (active,target))
                and active != target and (mode != 'A' or target == '0'*32), 'fault identity')
        self.campaign, self.mode, self.active, self.target = campaign, mode, active, target

    def __enter__(self):
        self.start = time.monotonic_ns(); self.end = self.start + 10_000_000_000
        # O_EXCL also rejects an existing symlink; trusted setup has already checked parents.
        fd = os.open(CONTROL/'control', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(f'1 {self.mode} {self.start} {self.end} {self.active} {self.target}\n')
        self.inode=(CONTROL/'control').lstat().st_ino
        self.timer=threading.Timer(10,self.release); self.timer.daemon=True
        try:
            self.timer.start()
            self.campaign.record('fault-armed', {'mode':self.mode, 'active':self.active,
                                 'target':self.target, 'start_ns':self.start, 'end_ns':self.end})
        except BaseException:
            self.timer.cancel()
            if self.timer.ident is not None: self.timer.join(.2)
            self.release(); raise
        return self

    def __exit__(self, kind, value, traceback):
        # Do not delete latched identity, events, attempts, logs, or imported artifacts.
        self.timer.cancel(); self.timer.join(.2); self.release()
        self.campaign.record('fault-removed', {'mode':self.mode, 'removed_ns':time.monotonic_ns(),
                             'lease_end_ns':self.end, 'exception':repr(value) if value else None})

    def release(self):
        try:
            if (CONTROL/'control').lstat().st_ino==self.inode: (CONTROL/'control').unlink()
        except FileNotFoundError: pass

    def assert_live(self):
        require(time.monotonic_ns() < self.end, 'fault expired before required observation')

    def events(self, offset, attempt, pid):
        raw = common.read_bounded(CONTROL/'events', 8192)[offset:]
        validate_fault_events(raw, self.mode, attempt, pid, self.start, self.end)
        self.campaign.record('fault-events', {'mode':self.mode, 'attempt':attempt,
                             'raw':raw.decode('ascii'), 'sha256':hashlib.sha256(raw).hexdigest()})

def read_broker_accounting(attempt, path=Path('/var/lib/actryn-server/broker/state.sqlite')):
    """Read existing rows only; the inspection API intentionally omits reservation metadata."""
    require(re.fullmatch('[0-9a-f]{32}',attempt), 'accounting attempt identity')
    require(stat.S_ISREG(path.lstat().st_mode), 'nonregular accounting database')
    with contextlib.closing(sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        deadline=time.monotonic()+1
        db.set_progress_handler(lambda:time.monotonic()>=deadline,1000)
        rows=[dict(row) for row in db.execute('''SELECT id,attempt_id,request_key,digest,state,
            request_bytes,response_capacity,token_reserved,consumed_tokens,deadline_ms,
            publication_closed,length(output) AS output_bytes FROM calls
            WHERE attempt_id=? ORDER BY rowid LIMIT 13''',(attempt,))]
    require(len(rows)<=12, 'unexpected accounting row capacity')
    return rows


def validate_pressure(raw, inspection, accounting):
    require = common.require
    require(len(raw) <= 32768 and raw.endswith(b'\n'), 'bounded complete pressure output')
    rows = [json.loads(v) for v in raw.splitlines()]
    require(len(rows) == 14 and rows[-1] == {'event':'pressure_ready','calls':12,'cancels':1}, 'incomplete workload')
    calls = [v for v in rows if v['event'] == 'pressure_call']
    cancels = [v for v in rows if v['event'] == 'pressure_cancel']
    require(len(calls) == 12 and len(cancels) == 1 and all(v.get('writes') == 1 for v in rows[:-1]), 'request count/retry')
    expected = {f'base-{n}' for n in range(4)} | {f'burst-{n}' for n in range(8)}
    require({v['key'] for v in calls} == expected, 'missing or duplicated key')
    denied, unknown = 0, 0
    denied_keys=set()
    for row in calls:
        key = row['key']
        if key.startswith('base-'):
            reply = row.get('reply', {})
            require(reply.get('result') == 'ok', 'baseline call failed')
            value = reply['value']
            require(value['attempt_id'] == inspection['attempt']['id'] and value['request_key'] == key
                    and value['origin'] == 'server_attested' and value['output'] == {'index':int(key[-1])},
                    'baseline identity/output changed')
        elif row.get('unknown') == 'eof_after_send' and 'reply' not in row:
            unknown += 1
        else:
            require(row.get('reply') == {'result':'error','reason':'attempt call budget exhausted'},
                    'burst success or unrelated failure')
            denied += 1
            denied_keys.add(key)
    require(denied >= 1 and denied + unknown == 8, 'no actual approved-call budget refusal')
    require(cancels[0] == {'event':'pressure_cancel','key':'base-0','writes':1,
                          'reply':{'result':'ok','value':{'stage':'KEY_CANCELLED_DURABLE'}}}, 'reserved cancel unconfirmed')
    require(inspection['robot_binding'] is None and not inspection['robot_requests']
            and not inspection['denials'] and inspection['denials_omitted'] == 0
            and not inspection['evidence_gaps'], 'unexpected Robot/policy/gap')
    stored = inspection['calls']
    base_keys={f'base-{n}' for n in range(4)}
    require(4<=len(stored)<=12 and len({v['request_key'] for v in stored})==len(stored)
            and len({v['id'] for v in stored})==len(stored)
            and base_keys <= {v['request_key'] for v in stored} <= expected, 'extra or missing broker key')
    require(len(accounting)==len(stored) and len({v['request_key'] for v in accounting})==len(accounting),
            'accounting row mismatch')
    by_key={v['request_key']:v for v in accounting}
    require(set(by_key)=={v['request_key'] for v in stored}, 'accounting key mismatch')
    tombstones=set(by_key)-base_keys
    require(denied_keys<=tombstones, 'confirmed budget denial missing durable tombstone')
    for call in stored:
        key=call['request_key']; row=by_key[key]
        require(re.fullmatch('[0-9a-f]{32}',row['id']) and row['attempt_id']==inspection['attempt']['id']
                and row['publication_closed'] in (0,1)
                and all(row[field]==call[field] for field in ('id','state','consumed_tokens','deadline_ms'))
                and bool(row['publication_closed']) is call['publication_closed'], 'accounting inspection mismatch')
        if key in base_keys:
            request=json.dumps({'method':'diagnostic.echo','input':{'index':int(key[-1])}},sort_keys=True,separators=(',',':')).encode()
            require(row['digest']=='sha256:'+hashlib.sha256(request).hexdigest()
                    and row['request_bytes']==len(request) and row['response_capacity']==65536
                    and row['token_reserved']==1024 and row['state']=='settled'
                    and row['consumed_tokens']==0 and row['deadline_ms']>0, 'unexpected approved call reservation')
            require(row['output_bytes'] is None if row['publication_closed'] else
                    type(row['output_bytes']) is int and 0<row['output_bytes']<=65536, 'approved call output accounting')
        else:
            require(row['digest'] is None and row['state']=='cancelled' and row['publication_closed']==1
                    and row['output_bytes'] is None and all(row[field]==0 for field in
                    ('request_bytes','response_capacity','token_reserved','consumed_tokens','deadline_ms')),
                    'burst key is not a closed zero-reservation tombstone')
    require(next(v for v in stored if v['request_key'] == 'base-0')['publication_closed'] is True,
            'cancelled publication remains open')
    return {'approved_calls':4,'burst_requests':8,'budget_refusals':denied,'closed_burst_tombstones':len(tombstones),
            'uncertain_replies_preserved':unknown,'reserved_cancel_durable':True}


def validate_failed_preparation(bundle, attempt, artifact, inspection, summary, trace_size):
    """B fails before output/task creation; expected missing logs remain explicit."""
    require(bundle['schema'] == 'actryn.server.evidence.v1' and bundle['attempt_id'] == attempt
            and bundle['execution_replay_eligible'] is False
            and bundle['omissions'] == [dict(artifact=v, reason='retained_log_unavailable', omitted_records=1)
                                       for v in ('stdout','stderr')], 'failed preparation omissions')
    entries=bundle['artifacts']
    require(len(entries)==3 and {v['name'] for v in entries} == {'attempt','runtime_binding','runtime_facts'},
            'failed preparation evidence inventory')
    for item in entries:
        raw=json.dumps(item['content'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        require(item['bytes']==len(raw) and item['sha256']=='sha256:'+hashlib.sha256(raw).hexdigest(),
                'failed preparation artifact hash')
    content={v['name']:v['content'] for v in entries}
    terminal=content['attempt']; current=inspection['attempt']; binding=content['runtime_binding']
    require(terminal['id']==current['id']==attempt and terminal['artifact_digest']==current['artifact_digest']==artifact
            and terminal['state']==current['state']=='reaped' and terminal['outcome']==current['outcome']=='cancelled'
            and terminal['binding'] is None and json.loads(current['binding'])==binding
            and binding['snapshot'] is None and binding['ambiguous_create'] is False and binding['cgroup_id']>0,
            'failed preparation durable identity/creation boundary')
    require(not inspection['calls'] and not inspection['denials'] and not inspection['evidence_gaps']
            and inspection['denials_omitted']==0 and inspection['robot_binding'] is None
            and not inspection['robot_requests'], 'failed preparation has unexpected work')
    require(str(uuid.UUID(binding['boot_id']))==binding['boot_id'], 'failed preparation boot')
    initial=binding['observer']; facts=content['runtime_facts']
    common.observer_health(initial, initial)
    require(facts['observer_health_unavailable'] is False, 'failed preparation observer unavailable')
    common.observer_health(facts['observer'], initial)
    common.observer_health(summary['status'], facts['observer'])
    require(summary['local_lost']==0 and summary['retained_bytes']==trace_size<=16*1024*1024,
            'failed preparation observer loss')
    resources=facts['resources']
    require(resources['classification']=='observed_cgroup_v2_counters'
            and resources['stage']=='after_descendants_empty_before_runtime_delete'
            and resources['unavailable']==[] and set(resources['counters'])==common.COUNTERS
            and resources['counters']['pids.current'].strip()=='0', 'failed preparation resource evidence')


class Campaign(common.Campaign):
    def __init__(self, output, artifact, launcher_pid):
        super().__init__(output, artifact)
        self.launcher_pid=launcher_pid
        self.results={key:'NOT_RUN' for key in ('approved_call_pressure','allocation_failure','reclaim_failure')}

    def helper(self, operation, attempt):
        require(operation in ('inspect','export') and re.fullmatch('[0-9a-f]{32}', attempt), 'read-only helper request')
        request={'op':operation, 'attempt_id':attempt}
        self.record('helper-intent', request)
        # No mutation and no retries. Fixed socket, finite frame and absolute deadline.
        deadline=time.monotonic()+3
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3); client.connect('/run/actryn/launcher.sock')
            _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            require(uid==0, 'launcher peer UID')
            raw=json.dumps(request).encode(); client.sendall(struct.pack('!I',len(raw))+raw)
            def read(size):
                result=b''
                while len(result)<size:
                    left=deadline-time.monotonic(); require(left>0, 'helper reply deadline')
                    client.settimeout(left); part=client.recv(size-len(result)); require(part, 'helper reply EOF')
                    result+=part
                return result
            size,=struct.unpack('!I',read(4)); require(size<=65536, 'helper frame cap')
            reply=json.loads(read(size))
        self.record('helper-reply',reply)
        return reply

    def stable(self, identity):
        inspection=self.status(identity[0]); common.active_identity(inspection,identity)
        require(json.loads(inspection['attempt']['binding'])==self.bindings[identity[0]], 'active binding changed')
        fields=Path(f'/proc/{identity[1]}/stat').read_text().rsplit(')',1)[1].split()
        require(int(fields[19])==identity[2], 'active process replaced')
        raw=common.read_bounded(Path('/var/lib/actryn-server',identity[0],'stdout.log'),32768)
        require(raw==self.active_stdout.setdefault(identity[0],raw), 'active output changed')
        accounting=read_broker_accounting(identity[0])
        self.record('pressure-accounting',{'attempt':identity[0],'rows':accounting})
        report=validate_pressure(raw,inspection,accounting)
        self.record('active-stable',{'identity':identity,'pressure':report,'stdout_sha256':hashlib.sha256(raw).hexdigest()})
        return report

    def export_failed(self, attempt):
        inspection=self.helper('inspect',attempt)['inspection']
        bundle=self.helper('export',attempt)['bundle']
        binding=json.loads(inspection['attempt']['binding']); epoch=binding['observer']['collector_epoch']
        require(str(uuid.UUID(epoch))==epoch, 'failed preparation collector path')
        trace=Path('/var/lib/actryn-observer',epoch,attempt+'.jsonl')
        raw=common.read_bounded(trace,16*1024*1024)
        summary=json.loads(common.read_bounded(trace.with_suffix('.summary.json'),4096))
        validate_failed_preparation(bundle,attempt,self.artifact,inspection,summary,len(raw))
        require(not Path('/sys/fs/cgroup/actryn',attempt).exists()
                and not Path('/run/actryn/brokers',attempt).exists()
                and not Path('/var/lib/actryn-server',attempt).exists(), 'failed allocation left created runtime')
        self.record('failed-allocation-export-verified', {'attempt':attempt, 'summary':summary,
                    'observer_trace_sha256':hashlib.sha256(raw).hexdigest(), 'missing_logs_expected':True})

    def retired_launcher_only(self, attempt):
        deadline=time.monotonic()+20
        while True:
            state=self.stores()
            require(attempt not in state['broker'] and state['launcher'].get(attempt) in ('retiring','reaped'),
                    'failed preparation unexpectedly adopted or not closed')
            if state['launcher'][attempt]=='reaped':
                self.record('failed-preparation-retired',{'attempt':attempt,'stores':state}); return
            require(time.monotonic()<deadline,{'allocation_cleanup_unknown':attempt,'stores':state})
            time.sleep(.1)

    def run(self):
        before=self.stores()
        require(all(state=='reaped' for rows in before.values() for state in rows.values()), 'outstanding attempts')
        require(all(len(rows)<=124 for rows in before.values()), 'four retained attempt slots required')
        require(not any((CONTROL/name).exists() for name in ('control','latched','events')), 'fault fixture already consumed')
        self.record('initial-stores',before)
        first=self.prepare()
        launched=self.cli('launch','--attempt',first)['inspection']
        snapshot=json.loads(launched['attempt']['binding'])['snapshot']
        identity=(first,snapshot['pid'],snapshot['start_ticks'])
        deadline=time.monotonic()+12
        while True:
            raw=common.read_bounded(Path('/var/lib/actryn-server',first,'stdout.log'),32768)
            if b'"event":"pressure_ready"' in raw and raw.endswith(b'\n'): break
            require(time.monotonic()<deadline,'pressure workload did not complete'); time.sleep(.05)
        self.results['approved_call_pressure']={'status':'OBSERVED_PENDING_FINAL_EVIDENCE',**self.stable(identity)}
        self.record('approved-call-pressure',self.results['approved_call_pressure'])

        with FaultControl(self,'A',first) as fault:
            reply=self.cli('prepare','--artifact',self.artifact,rejected=True)  # One Prepare only.
            failed=common.read_bounded(CONTROL/'latched',33).decode().rstrip('\n')
            require(re.fullmatch('[0-9a-f]{32}',failed) and failed not in self.known, 'latched allocation identity')
            common.capacity_rejection(reply,f'prepare failed; attempt {failed}')
            require('No space left on device (os error 28)' in reply['message'], 'wrong allocation failure')
            fault.assert_live(); fault.events(0,failed,self.launcher_pid)
        self.retired_launcher_only(failed)
        self.export_failed(failed); self.stable(identity)
        self.results['allocation_failure']={'status':'PASS','attempt':failed,'errno':'ENOSPC','injections':1}
        self.record('allocation-failure',self.results['allocation_failure'])

        staged=self.prepare(); offset=len(common.read_bounded(CONTROL/'events',8192))
        with FaultControl(self,'R',first,staged) as fault:
            self.cancel_sent.add(staged)  # Even an unknown reply must never cause another Cancel.
            reply=self.cli('cancel','--attempt',staged,rejected=True)
            common.capacity_rejection(reply,'Device or resource busy (os error 16)')
            fault.assert_live()
            directory=Path('/run/actryn/brokers',staged)
            state=self.stores()
            validate_reclaim(state,staged,directory.is_dir(),sorted(v.name for v in directory.iterdir()),
                             Path('/sys/fs/cgroup/actryn',staged).exists())
            self.record('reclaim-charged',{'attempt':staged,'stores':state,'directory':str(directory)})
            common.capacity_rejection(self.cli('prepare','--artifact',self.artifact,rejected=True),
                                      'preparation capacity exhausted')
            require(self.stores()==state,'refused preparation created accounting')
            self.stable(identity); fault.assert_live(); fault.events(offset,staged,self.launcher_pid)
        self.retired(staged)
        require(not Path('/run/actryn/brokers',staged).exists(),'reclaim did not converge after control removal')
        replacement=self.prepare()  # Fresh identity, never retries the failed Prepare.
        self.cancel(replacement); self.retired(replacement); self.stable(identity)
        self.results['reclaim_failure']={'status':'OBSERVED_PENDING_FINAL_EVIDENCE','attempt':staged,'errno':'EBUSY',
                    'replacement':replacement,'cleanup_mutation_retries':0}
        self.record('reclaim-failure',self.results['reclaim_failure'])
        self.cancel(first); self.retired(first)
        def check_pressure(logs,inspection):
            accounting=read_broker_accounting(first)
            self.record('final-pressure-accounting',{'attempt':first,'rows':accounting})
            validate_pressure(logs['stdout'],inspection,accounting)
            require(not logs['stderr'] and all(v['publication_closed'] is True for v in inspection['calls']),
                    'final pressure output/publication')
        for attempt in self.known:
            self.export(attempt,check_pressure if attempt==first else None)
        self.results['approved_call_pressure']['status']='PASS'
        self.results['reclaim_failure']['status']='PASS'
        after=self.stores()
        for name,rows in before.items():
            expected=set(self.known)|({failed} if name=='launcher' else set())
            require(set(after[name])-set(rows)==expected and all(v=='reaped' for v in after[name].values())
                    and all(after[name][k]==v for k,v in rows.items()),'history/accounting changed')
        self.record('PASS',{'phases':self.results,'stores':after,'active_identity':identity,
                    'instrumented_production_path':True,'unchanged_installed_unit_qualification':False,
                    'heap_oom_tested':False,'complete_A08':False,'physical_acceptance':False})


def main():
    import pressure_fixture
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact',required=True)
    parser.add_argument('--agent-sha256',required=True)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--fixture-record',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    require(re.fullmatch('sha256:[0-9a-f]{64}',args.artifact),'artifact digest')
    require(re.fullmatch('[0-9a-f]{64}',args.agent_sha256),'agent binary digest')
    pins=pressure_fixture.preflight(args.manifest)
    record=json.loads(pressure_fixture.protected_file(args.fixture_record,65536))
    pressure_fixture.verify_instrumented(record,pins)
    agent=Path('/var/lib/actryn-artifacts',args.artifact[7:],'rootfs/bin/agent')
    require(hashlib.sha256(pressure_fixture.protected_file(agent,8*1024*1024)).hexdigest()==args.agent_sha256,
            'approved fixture agent bytes differ from reviewed build')
    os.umask(0o077); args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    run=Campaign(args.output,args.artifact,pins['services']['actryn-launcher']['pid'])
    run.record('campaign',{'manifest':args.manifest,'artifact':args.artifact,'agent_sha256':args.agent_sha256,'pins':pins,
               'fixture':record,'source_sha256':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                    for name in ('guest_pressure.py','guest_capacity.py','pressure_fixture.py','pressure_agent.c','directory_fault.c')}})
    try:
        run.run()
    except BaseException as error:
        run.record('FAILED',{'error':repr(error),'phases':run.results,'known_attempts':run.known,
                   'cancel_already_attempted':sorted(run.cancel_sent),'automatic_retry':False})
        # FaultControl finally removed the control. No retry even after uncertain cancellation.
        require(not (CONTROL/'control').exists(),'fault control remains; separate cleanup review required')
        try: run.record('failure-stores',run.stores())
        except BaseException as readback: run.record('failure-readback-unavailable',{'error':repr(readback)})
        for attempt in reversed(run.known):
            try: run.cancel(attempt); run.retired(attempt)
            except BaseException as cleanup: run.record('cleanup-unconfirmed',{'attempt':attempt,'error':repr(cleanup)})
        raise


if __name__=='__main__': main()
