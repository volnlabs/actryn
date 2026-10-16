"""A04: explicit SIGSTOP, independent fixture closure observation, then SIGKILL.

No VM launch, enrollment, automatic repair or proposal retry. The operator owns
the same-disk restart between the two explicitly invoked phases.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shlex
import signal
import socket
import stat
import struct
import subprocess
import tarfile
import tempfile
import time
import uuid

from failure_paths import OneProposal
from gateway_campaign import GatewayCampaign, acknowledged_running
from guest import CAMPAIGN, ROOT, RequestHandle, phase, write_json
from source_gap import no_effect, sha
from ssh_campaign import SharedSsh


def require(value, reason):
    if not value:
        raise AssertionError(reason)


def operation_blob(operation):
    return (bytes(operation['device']) + bytes(operation['runtime_nonce']) + struct.pack('<6Q',
        *(operation[k] for k in ('boot', 'session', 'grant', 'instance', 'operation', 'stream')))).hex()

def validate_history(before, after, handle, operation):
    require(before == after, 'raw historical rows changed or new work appeared')
    namespaces, records = after['namespaces'], after['records']
    ns, key = handle.namespace.hex(), handle.key.hex()
    owner = [r for r in namespaces if r[0] == ns]
    rows = [r for r in records if r[0] == ns and r[1] == key]
    require(len(owner) == len(rows) == 1 and owner[0][1] == handle.attempt.hex(), 'original history missing/ambiguous')
    row = rows[0]
    require(row[2] > 0 and row[3] == 0 and row[4] in (2, 3)
            and row[5] == operation_blob(operation), 'durable unfinished operation was not retained')

def validate_unknown(report, handle, operation):
    s = report['snapshot']
    require(report['live_authority'] is False and s is not None
            and s['namespace'] == list(handle.namespace) and s['key'] == list(handle.key)
            and s['operation'] == operation and s['phase'] == s['verdict'] == 'OutcomeUnknown'
            and s['terminal'] is True and s['reconciled'] is False
            and s['cancellation_durable'] is False and s['persistence_failed'] is False,
            'historical UNKNOWN changed identity or regained authority')

def expiry_inference(before, after, operation):
    elapsed = after['now_ns'] - before['now_ns']
    require(before['state'] == 'Active' and before['enabled'] is True
            and before['left'] != 0 and before['right'] != 0
            and after['state'] == 'Faulted' and after['enabled'] is False
            and after['left'] == after['right'] == 0
            and all(s['boot'] == operation['boot'] and s['session'] == operation['session']
                    and 0 <= s['queued'] < 32 for s in (before, after))
            and 500_000_000 <= elapsed <= 2_000_000_000,
            'no bounded same-session external disabled-zero observation')
    return dict(source_timing_inference=True, disabled_zero=True,
                fault_reason_observed=False, elapsed_fixture_ns=elapsed)

class SignalSequence:
    def __init__(self, guard, send, record):
        self.guard, self.send, self.record = guard, send, record
        self.freeze_attempted = self.frozen = self.kill_attempted = False

    def freeze(self):
        require(not self.freeze_attempted, 'SIGSTOP/guard cannot be retried')
        self.freeze_attempted = True
        self.guard('running')
        self.record('sigstop-intent', dict(automatic_retry=False))
        self.send(signal.SIGSTOP)
        self.frozen = True

    def kill(self, proof):
        require(self.frozen and not self.kill_attempted and proof.get('source_timing_inference') is True
                and proof.get('disabled_zero') is True, 'kill requires original freeze and closure proof')
        self.kill_attempted = True
        self.guard('stopped')
        self.record('sigkill-intent', dict(automatic_retry=False))
        self.send(signal.SIGKILL)


def wait_read(call, predicate, seconds):
    deadline = time.monotonic() + seconds
    while True:
        require(time.monotonic() < deadline, 'absolute read deadline')
        value = call()
        require(time.monotonic() < deadline, 'absolute read deadline')
        if predicate(value):
            return value
        time.sleep(.01)


def process_identity(pid):
    root = Path('/proc', str(pid))
    fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
    return dict(pid=pid, start_ticks=int(fields[19]), state=fields[0],
                argv=[s.decode() for s in (root / 'cmdline').read_bytes().split(b'\0') if s])


def socket_inodes(pid):
    paths=list(Path('/proc',str(pid),'fd').iterdir());require(len(paths)<=256,'QEMU FD capacity')
    values=[]
    for p in paths:
        try:link=os.readlink(p)
        except FileNotFoundError:continue
        if re.fullmatch(r'socket:\[[0-9]+\]',link):values.append(link)
    require(values,'no retained QEMU socket descriptors')
    return sorted(values)


def read_file(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode),'regular JSON input required')
        raw=stream.read(limit+1)
    require(len(raw)<=limit,'JSON input capacity')
    return raw


def json_file(path,limit):
    return json.loads(read_file(path,limit))


def unit_state(unit):
    require(re.fullmatch(r'actryn-install-robot-(?:manager11-)?vm[0-9]+\.service', unit), 'not a supported owned installation VM unit')
    p = subprocess.run(['systemctl', '--user', 'show', unit,
        '--property=MainPID,InvocationID,ActiveState,TasksMax,MemoryMax,Restart'], capture_output=True, timeout=2)
    require(p.returncode == 0 and len(p.stdout) <= 8192, 'host VM unit read failed')
    return dict(line.split('=', 1) for line in p.stdout.decode().splitlines())


class PinnedQemu:
    def __init__(self, expected):
        self.expected = expected
        self.fd = os.pidfd_open(expected['pid'])
        try:
            require(sha(Path('/proc', str(expected['pid']), 'exe')) == expected['exe_sha256'], 'host QEMU executable mismatch')
            self.executable = Path('/proc',str(expected['pid']),'exe').stat()
            self.guard('running')
        except BaseException:
            os.close(self.fd)
            raise

    def guard(self, state):
        e = self.expected
        require(not select.select([self.fd], [], [], 0)[0], 'original QEMU exited')
        actual = process_identity(e['pid']); unit = unit_state(e['unit'])
        executable=Path('/proc',str(e['pid']),'exe').stat()
        require(actual['start_ticks'] == e['start_ticks'] and actual['argv'] == e['argv']
                and all(getattr(executable,k)==getattr(self.executable,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'))
                and actual['argv'][0] == '/usr/bin/qemu-system-aarch64'
                and actual['argv'][actual['argv'].index('-name') + 1] == 'actryn-install-robot'
                and unit['MainPID'] == str(e['pid']) and unit['InvocationID'] == e['invocation_id']
                and unit['ActiveState'] == 'active' and unit['Restart'] == 'no'
                and unit['TasksMax'] == '256' and unit['MemoryMax'] == '3221225472', 'owned QEMU lifetime changed')
        states = [(p / 'stat').read_text().rsplit(')', 1)[1].split()[0]
                  for p in Path('/proc', str(e['pid']), 'task').iterdir()]
        require(states and (all(s in ('T', 't') for s in states) if state == 'stopped'
                else all(s not in (('Z','X') if state=='waiting' else ('T','t','Z','X')) for s in states)), 'QEMU stop/running state mismatch')
        actual['task_states']=states
        return actual

    def send(self, sig):
        signal.pidfd_send_signal(self.fd, sig, None, 0)

    def close(self):
        os.close(self.fd)


def parse_fixture(raw):
    m = re.fullmatch(rb'state=(Inhibited|Ready|Active|Faulted) boot=(\d+) session=(\d+) '
        rb'duties=\((-?\d+), (-?\d+), (true|false)\) encoders=\[(-?\d+), (-?\d+)\] '
        rb'queued=(\d+) now_ns=(\d+)\n', raw)
    require(m is not None, 'fixture status format changed')
    a=m.groups()
    return dict(state=a[0].decode(),boot=int(a[1]),session=int(a[2]),left=int(a[3]),right=int(a[4]),
                enabled=a[5]==b'true',encoders=[int(a[6]),int(a[7])],queued=int(a[8]),now_ns=int(a[9]))


class FixtureStatus:
    def __init__(self, expected):
        self.expected = expected
        e=expected; identity=process_identity(e['pid'])
        require(identity['start_ticks']==e['start_ticks'] and sha(Path('/proc',str(e['pid']),'exe'))==e['exe_sha256']
                and identity['argv'][identity['argv'].index('--admin')+1]==e['admin_path']
                and identity['argv'][identity['argv'].index('--socket')+1]==e['controller_path'], 'native fixture pin mismatch')
        self.argv = identity['argv']

    def read(self):
        e=self.expected; identity=process_identity(e['pid'])
        require(identity['start_ticks']==e['start_ticks'] and identity['argv']==self.argv, 'fixture process changed')
        with tempfile.TemporaryDirectory(prefix='actryn-a04-status-') as root, socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as s:
            s.settimeout(.3);s.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1)
            s.bind(str(Path(root)/'status.sock'));s.connect(e['admin_path']);s.send(b'status')
            raw, ancillary, flags, _ = s.recvmsg(1024,socket.CMSG_SPACE(12))
            credentials=[struct.unpack('3i',data) for level,kind,data in ancillary
                         if level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS]
            require(not flags & (socket.MSG_TRUNC|socket.MSG_CTRUNC) and len(credentials)==1
                    and credentials[0][0]==e['pid'] and credentials[0][1]==os.getuid(), 'fixture status origin/truncation')
            return parse_fixture(raw)


def same_disk_restart(before, after):
    def normalized(argv):
        result=list(argv)
        for i in range(1,len(result)):
            if result[i-1]=='-qmp' or result[i-1]=='-serial' and result[i].startswith('file:'):
                result[i]='PRESERVED_NEW_DIAGNOSTIC_PATH'
        return result
    require(before['pid'] != after['pid'] and before['invocation_id'] != after['invocation_id']
            and normalized(before['argv']) == normalized(after['argv']), 'not the same retained-disk boot tuple')


# Both programs run only through the existing bounded SSH transport. No identity
# private directory is included: runtime contains intent, binding and capture data.
GUEST_FACTS = '''import hashlib,json,os,pathlib,re,subprocess
p=pathlib.Path('/opt/actryn/robot/current').resolve();raw=(p.parent/'manifest.json').read_bytes()
units={};executables={}
for u in ('actryn-robotd','actryn-gatewayd'):
 r=subprocess.run(['systemctl','show','--property=MainPID,ActiveState',u],capture_output=True,timeout=2);assert r.returncode==0
 units[u]=dict(v.split('=',1) for v in r.stdout.decode().splitlines())
 pid=int(units[u]['MainPID'])
 if pid>1:
  exe=pathlib.Path('/proc',str(pid),'exe');executables[u]=dict(path=str(exe.resolve()),sha256=hashlib.sha256(exe.read_bytes()).hexdigest())
n=pathlib.Path('/sys/module/actryn_authority/notes/.note.gnu.build-id')
i=pathlib.Path('/var/lib/actryn-robot/identity');active=json.loads((i/'active.json').read_bytes());assert re.fullmatch('[a-f0-9]{32}',active['generation'])
identity=dict(active=active,ca_sha256=hashlib.sha256((i/active['generation']/'ca.pem').read_bytes()).hexdigest(),certificate_sha256=hashlib.sha256((i/active['generation']/'certificate.pem').read_bytes()).hexdigest(),policy_sha256=hashlib.sha256(pathlib.Path('/var/lib/actryn-robot/policy.json').read_bytes()).hexdigest())
print(json.dumps(dict(machine_id=pathlib.Path('/etc/machine-id').read_text().strip(),boot_id=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),arch=os.uname().machine,kernel=os.uname().release,compatible=pathlib.Path('/proc/device-tree/compatible').read_bytes().hex(),manifest_sha256=hashlib.sha256(raw).hexdigest(),slot=str(p),module_note_sha256=hashlib.sha256(n.read_bytes()).hexdigest() if n.exists() else None,units=units,executables=executables,public_identity=identity)))
'''
HISTORY = '''import contextlib,json,pathlib,sqlite3
p=pathlib.Path('/var/lib/actryn-robot/runtime/intent.sqlite')
try:
 with contextlib.closing(sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True,timeout=.2)) as d:
  d.execute('PRAGMA query_only=ON')
  d.execute('BEGIN')
  a=list(d.execute('SELECT lower(hex(id)),lower(hex(attempt)),lower(hex(epoch)),revision,retired FROM namespaces ORDER BY id'))
  b=list(d.execute('SELECT lower(hex(namespace)),lower(hex(key)),revision,terminal,phase,lower(hex(operation)),lower(hex(intent)),lower(hex(closure)) FROM records ORDER BY namespace,key'))
  assert len(a)<=16 and len(b)<=256
  print(json.dumps(dict(namespaces=a,records=b)))
except sqlite3.Error as e:
 print(json.dumps(dict(sqlite_error=str(e),sqlite_errorcode=getattr(e,'sqlite_errorcode',None),read_only=True,repair_attempted=False)))
'''
RAW_CAPTURE = '''import hashlib,io,json,pathlib,stat,sys,tarfile
root=pathlib.Path('/var/lib/actryn-robot/runtime');assert root.is_dir() and not root.is_symlink()
allpaths=list(root.rglob('*'));assert len(allpaths)<=4096 and not any(p.is_symlink() for p in allpaths)
paths=sorted(p for p in allpaths if not p.is_dir());assert len(paths)<=2048
total=0;items={}
for p in paths:
 s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=32*1024*1024
 raw=p.read_bytes();total+=len(raw);assert total<=256*1024*1024
 items[str(p.relative_to(root))]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as tar:
 raw=json.dumps(dict(files=items,bytes=total),sort_keys=True).encode();m=tarfile.TarInfo('inventory.json');m.size=len(raw);m.mode=0o600;tar.addfile(m,io.BytesIO(raw))
 for p in paths:
  name=str(p.relative_to(root));raw=p.read_bytes();assert len(raw)==items[name]['bytes'] and hashlib.sha256(raw).hexdigest()==items[name]['sha256']
  m=tarfile.TarInfo('runtime/'+name);m.size=len(raw);m.mode=0o600;tar.addfile(m,io.BytesIO(raw))
'''


def remote_json(campaign, program):
    raw=campaign.run('python3 -B -E -s -c '+shlex.quote(program),timeout=15)
    require(len(raw)<=4*1024*1024,'read-only response capacity')
    return json.loads(raw)


def validate_guest(actual, plan, boot):
    require(actual['machine_id']==plan['machine_id'] and actual['boot_id']==boot
        and actual['arch']=='aarch64' and actual['kernel']=='6.12.111+deb13-arm64'
        and bytes.fromhex(actual['compatible']).startswith(b'linux,dummy-virt\0')
        and actual['manifest_sha256']==plan['manifest_sha256']
        and actual['slot']=='/opt/actryn/robot/releases/'+plan['manifest_sha256']+'/payload'
        and actual['public_identity']['active']['generation']==plan['identity_generation']
        and actual['public_identity']['active']['dns_name']==plan['rpc']['dns']
        and actual['module_note_sha256']==plan['rpc']['module_note_sha256'], 'wrong installed guest/boot/module')
    for unit,key in (('actryn-robotd','manager_sha256'),('actryn-gatewayd','gateway_sha256')):
        if unit in actual['executables']:
            require(actual['executables'][unit]==dict(path=actual['slot']+'/bin/'+unit,sha256=plan['rpc'][key]), 'loaded binary differs from installed tuple')


def durable_record(name, value):
    data=json.dumps(value,indent=2).encode()+b'\n'
    with (CAMPAIGN['output']/name).open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    fd=os.open(CAMPAIGN['output'],os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def finalize_result(result):
    output=CAMPAIGN['output']
    durable_record('artifact-hashes.json',{str(p.relative_to(output)):sha(p)
        for p in sorted(output.rglob('*')) if p.is_file() and p.name not in ('artifact-hashes.json','phase-result.json')})
    durable_record('phase-result.json',dict(result,artifact_hashes_sha256=sha(output/'artifact-hashes.json')))


def validate_crash_capture(decoded, handoff, handle):
    from gateway_campaign import execution_counts
    from failure_paths import operation_id
    op=handoff['operation']
    require(decoded['format']=='actryn-failure-capture-1' and decoded['attempt']==list(handle.attempt)
        and decoded['configuration_digest']==handoff['prepared']['configuration_digest']
        and decoded['policy']=='MetadataOnly' and decoded['volatile_tail_unknown'] is True
        and decoded['execution_replay_eligible'] is False,'wrong crash capture/replay boundary')
    require(len(decoded['sources'])==len(decoded['frontiers'])==2,'capture producer inventory')
    # A genuine crash can leave an unsynced MCAP and a hot checkpoint journal.
    # The pinned production reader reports/excludes these; neither is repaired
    # in the source. Other corruption/source faults cannot establish this case.
    require(all(isinstance(s,str) and (s.startswith('private SQLite rollback after READONLY_ROLLBACK (776);')
        or s=='uncommitted/unsupported raw recording remnants retained') for s in decoded['issues']), 'unexpected recorder fault')
    for source,frontier in zip(decoded['sources'],decoded['frontiers']):
        require(not source['missing_record_ordinals'] and not source['source_gap_record_ordinals']
            and frontier['gap_count']==0 and frontier['durable']==frontier['read']
            and source['last_record_ordinal']==source['durable_frontier'],'unsupported durable prefix')
    events=[r['value'] for r in decoded['records'] if r['origin']=='Kernel' and r['kind']=='Transition']
    require(events and all(b['sequence']==a['sequence']+1 for a,b in zip(events,events[1:]))
        and len({v['status']['events_lost'] for v in events})==1
        and not any(r['kind']=='SourceGap' for r in decoded['records']),'independent continuity fault')
    allocations=[v for v in events if v['kind']==0x1000e]
    starts=[v for v in events if v['kind']==0x10007]
    require(len(allocations)==len(starts)==1 and operation_id(allocations[0]['status'])==op
        and operation_id(starts[0]['status'])==op
        and not any(v['kind'] in (0x30001,0x30002,0x2000a) for v in events), 'not one unfinished allocation/START')
    proposals,samples=execution_counts(decoded['records'],handle,op)
    return dict(accepted_proposals=proposals,sample_requests=samples,
        raw_remnants=decoded['raw_remnants'],issues=decoded['issues'],volatile_tail_unknown=True,
        execution_replay_eligible=False)


def verify_raw_archive(path):
    with tarfile.open(path,'r:gz') as archive:
        members=[];size_sum=0
        for m in archive:
            require(len(members)<2049 and m.isfile() and m.size<=(1024*1024 if m.name=='inventory.json' else 32*1024*1024),'raw member capacity/type')
            size_sum+=m.size;require(size_sum<=257*1024*1024,'raw archive total capacity')
            members.append(m)
        require(members,'empty raw inventory')
        require(len({m.name for m in members})==len(members) and all(m.isfile() for m in members),'raw aliases/nonregular entry')
        inventory=json.load(archive.extractfile('inventory.json'));items=inventory['files']
        require(len(items)+1==len(members) and inventory['bytes']<=256*1024*1024,'raw byte capacity')
        total=0
        for m in members:
            name=Path(m.name);require(not name.is_absolute() and '..' not in name.parts
                and name.as_posix()==m.name,'raw path traversal/alias')
            if m.name=='inventory.json':continue
            require(m.name.startswith('runtime/') and m.size<=32*1024*1024,'raw file capacity/path')
            key=m.name[len('runtime/'):];expected=items[key];raw=archive.extractfile(m).read();total+=len(raw)
            require(len(raw)==expected['bytes']==m.size and hashlib.sha256(raw).hexdigest()==expected['sha256'],'raw file integrity')
        require(total==inventory['bytes'] and 'intent.sqlite' in items,'raw registry absent/size mismatch')
        return inventory


class CrashCampaign(GatewayCampaign):
    def history(self):
        value=remote_json(self,HISTORY)
        write_json('history-'+str(self.local_calls)+'.json',value)
        require('sqlite_error' not in value,'read-only registry unavailable; preserve journal, never repair in place')
        return value

    def freeze(self,plan):
        qemu=PinnedQemu(plan['qemu'])  # Open/pin before setup can grant anything.
        sequence=SignalSequence(qemu.guard,qemu.send,lambda label,value:write_json(label+'.json',value))
        setup_started=False
        try:
            fixture=FixtureStatus(plan['fixture'])
            facts=remote_json(self,GUEST_FACTS);validate_guest(facts,plan,plan['boot_id'])
            write_json('original-guest.json',facts)
            setup_started=True;self.setup();self.activate()
            with self.connection() as rpc:
                observation=rpc.observe(self.handle.attempt,self.handle.namespace)
                call=OneProposal(rpc,self.handle,observation)
                self.start_checked(rpc,self.handle,call)
                result=call.finish();operation=self.confirm_running(rpc,result)
                wait_read(fixture.read,lambda v:v['state']=='Active' and v['enabled']
                          and v['left']!=0 and v['right']!=0,1)
                query=rpc.query(self.handle);description=rpc.describe()
                require(acknowledged_running(self.handle,result,query,description)==operation
                    and query['snapshot']['durable_revision']==query['snapshot']['revision']>0,
                    'missing durable original RUNNING identity')
                history=self.history();validate_history(history,history,self.handle,operation)
                handoff=dict(plan_sha256=self.plan_sha256,handle=json.loads((self.args.output/'handle.json').read_bytes()),
                    prepared=self.prepared,operation=operation,history=history,query=query,description=description,
                    proposal_result=result,guest=facts,kind='SIGSTOP-then-SIGKILL; not instantaneous powercut')
                durable_record('before-freeze.json',handoff)
                before=fixture.read();sockets=socket_inodes(plan['qemu']['pid'])
                require(before['state']=='Active' and before['enabled'] and before['boot']==operation['boot']
                    and before['session']==operation['session'],'original fixture no longer active')
                sequence.freeze()
                stopped=wait_read(lambda:qemu.guard('waiting'),lambda d:all(s in ('T','t') for s in d['task_states']),1)
                require(socket_inodes(plan['qemu']['pid'])==sockets,'QEMU socket descriptors changed before freeze')
                write_json('qemu-all-threads-frozen.json',stopped)
                def status():
                    qemu.guard('stopped')  # All threads and owned socket remain frozen, process alive.
                    require(socket_inodes(plan['qemu']['pid'])==sockets,'QEMU socket descriptors not retained')
                    value=fixture.read();write_json('fixture-last-status.json',value);return value
                after=wait_read(status,lambda v:v['state']=='Faulted' and v['now_ns']-before['now_ns']>=500_000_000,1.8)
                proof=expiry_inference(before,after,operation)
                durable_record('fixture-closure.json',dict(before=before,after=after,proof=proof,
                    last_observed_controller_receipt_ns=description['runtime']['kernel']['controller_ns'],
                    last_applied_absolute_expiry_unavailable=True,max_sample_ms=500,
                    pinned_qemu_chardev=plan['fixture']['controller_path'],retained_socket_inodes=sockets,
                    observation='socket/process retained; fault reason unavailable; source/timing inference only'))
                sequence.kill(proof)
                require(select.select([qemu.fd],[],[],3)[0],'original QEMU death not confirmed')
                dead=wait_read(lambda:unit_state(plan['qemu']['unit']),lambda v:v['MainPID']=='0'
                    and v['ActiveState'] in ('inactive','failed'),3)
                write_json('original-host-unit-ended.json',dead)
                durable_record('crashed.json',dict(handoff=handoff,fixture_proof=proof,
                    signal_attempts=['SIGSTOP','SIGKILL'],same_disk_restart_required=True,
                    pure_instantaneous_powercut=False,automatic_retry=False))
        except BaseException:
            write_json('interruption-state.json',dict(freeze_attempted=sequence.freeze_attempted,
                kill_attempted=sequence.kill_attempted,no_automatic_sigcont_or_repeated_signal=True))
            if setup_started and not sequence.freeze_attempted:
                try:self.local('revoke',label='failure-one-revoke',closure=True)
                except BaseException as error:write_json('cleanup-unknown.json',dict(error=repr(error),automatic_retry=False))
            raise
        finally:qemu.close()


    def inspect(self,plan,restart,before):
        require(restart['boot_id']!=plan['boot_id'] and str(uuid.UUID(restart['boot_id']))==restart['boot_id'], 'new actual boot required')
        same_disk_restart(plan['qemu'],restart['qemu'])
        qemu=PinnedQemu(restart['qemu'])
        try:
            facts=remote_json(self,GUEST_FACTS);validate_guest(facts,plan,restart['boot_id'])
            require(all(v['ActiveState']=='inactive' and v['MainPID']=='0' for v in facts['units'].values()),'normal services already opened retained state')
            write_json('cold-boot.json',facts)
            path=self.args.output/'cold-runtime.tar.gz'
            with path.open('xb') as output:
                p=subprocess.run(self.ssh+['python3 -B -E -s -c '+shlex.quote(RAW_CAPTURE)],stdout=output,stderr=subprocess.PIPE,timeout=45)
                output.flush();os.fsync(output.fileno())
            write_json('cold-runtime-process.json',dict(exit=p.returncode,stderr=p.stderr[:8192].decode(errors='replace')))
            require(p.returncode==0,'raw DB/journal/capture preservation failed')
            inventory=verify_raw_archive(path);write_json('cold-runtime-inventory.json',inventory)
            handoff=before['handoff'];require(handoff['plan_sha256']==self.plan_sha256,'wrong original handoff plan')
            require(facts['public_identity']==handoff['guest']['public_identity'],'retained public identity/policy changed')
            self.handle=RequestHandle(*(bytes.fromhex(handoff['handle'][k]) for k in ('attempt','namespace','key')))
            self.prepared=handoff['prepared'];operation=handoff['operation']
            fixture=FixtureStatus(plan['fixture']);external=fixture.read()
            require(external['boot']==operation['boot'] and external['left']==external['right']==0
                and not external['enabled'],'external controller restarted or restored output')
            write_json('same-external-fixture-afterboot.json',external)
            history=self.history();validate_history(handoff['history'],history,self.handle,operation)
            write_json('one-explicit-service-start-intent.json',dict(units=['actryn-robotd','actryn-gatewayd'],automatic_retry=False))
            raw=self.run('systemctl start actryn-robotd.service actryn-gatewayd.service',timeout=40)
            write_json('one-explicit-service-start-reply.json',dict(stdout=raw.decode(errors='replace')))
            def ready():
                try:return self.local('describe',label='new-boot-describe')
                except (OSError,subprocess.SubprocessError,RuntimeError):return None
            initial=wait_read(ready,bool,10);no_effect(initial)
            loaded=remote_json(self,GUEST_FACTS);validate_guest(loaded,plan,restart['boot_id'])
            require(len(loaded['executables'])==2,'both installed services did not start')
            write_json('loaded-afterboot.json',loaded)
            require(initial['runtime']['prepared'] is None and initial['runtime']['health']['inhibited'], 'authority restored on reboot')
            require(self.epoch.hex()!=handoff['handle']['robot_epoch'],'runtime epoch reused')
            for index in range(3):
                with self.connection() as rpc:
                    d=rpc.describe();no_effect(d)
                    require(d['runtime']['prepared'] is None and d['runtime']['health']['inhibited'],'automatic preparation/authority')
                    report=rpc.query(self.handle);validate_unknown(report,self.handle,operation)
                    write_json('historical-query-'+str(index)+'.json',report)
            validate_history(history,self.history(),self.handle,operation)
            # Re-pair the pinned same identity for reads; never re-Propose.
            a=self.args
            self.cli('pair','--endpoint',f'127.0.0.1:{a.tcp_port}','--dns',a.dns,'--pin',a.pin,
                '--ca',a.ca,'--cert',a.cert,'--key',a.key,'--out',str(a.output/'pair.json'))
            durable_record('handle.json',handoff['handle'])
            self.cli('export','--pair',str(a.output/'pair.json'),'--cert',a.cert,'--key',a.key,
                '--handle',str(a.output/'handle.json'),'--out',str(a.output/'evidence'),timeout=120)
            env=dict(os.environ,ACTRYN_TEST_CAPTURE=str(a.output/'evidence/capture'),ACTRYN_TEST_CAPTURE_REPORT=str(a.output/'decoded.json'))
            p=subprocess.run([str(a.reader),'--exact','decode_retired_campaign_capture','--ignored','--nocapture'],env=env,capture_output=True,timeout=30)
            write_json('reader.json',dict(exit=p.returncode,stdout=p.stdout[:65536].decode(errors='replace'),stderr=p.stderr[:65536].decode(errors='replace')))
            require(p.returncode==0,'pinned production reader failed')
            proof=validate_crash_capture(json_file(a.output/'decoded.json',4*1024*1024),handoff,self.handle)
            final=self.local('describe',label='final-no-automatic-work');no_effect(final)
            require(final['runtime']['prepared'] is None and final['runtime']['health']['inhibited'],'authority returned during inspection/export')
            validate_history(history,self.history(),self.handle,operation)
            self.inspection_result=dict(status='PASS',test='A04 freeze-then-crash',proof=proof,
                raw_registry_physical_phase='retained unfinished; read-only API projects UNKNOWN',
                fixture_closure=before['fixture_proof'],automatic_mutation_retries=0,physical_acceptance=False)
        finally:qemu.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('freeze','inspect'))
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--before',type=Path)
    parser.add_argument('--restart',type=Path)
    options=parser.parse_args()
    raw=read_file(options.plan,131072);plan=json.loads(raw)
    require(plan['allow_disposable_guest'] is True and re.fullmatch('[0-9a-f]{32}',plan['machine_id'])
        and str(uuid.UUID(plan['boot_id']))==plan['boot_id'] and re.fullmatch('[0-9a-f]{64}',plan['manifest_sha256']), 'explicit disposable target pins required')
    rpc=plan['rpc']
    fields={'ssh_port','tcp_port','cli','reader','ssh_key','known_hosts','ca','cert','key','principal','dns','pin',
        'manager_sha256','gateway_sha256','module_note_sha256'}
    require(set(rpc)==fields and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',rpc['principal']), 'existing RPC input fields/principal')
    require(all(Path(rpc[k]).is_absolute() for k in ('cli','reader','ssh_key','known_hosts','ca','cert','key')), 'absolute existing host paths required')
    for k in ('pin','manager_sha256','gateway_sha256','module_note_sha256'):
        require(re.fullmatch('[0-9a-f]{64}',rpc[k]),'SHA256 pin')
    require(sha(rpc['cli'])==plan['cli_sha256'] and sha(rpc['reader'])==plan['reader_sha256'], 'host CLI/reader changed')
    require(plan['qemu']['argv'][plan['qemu']['argv'].index('-chardev')+1]
        =='socket,id=controller,path='+plan['fixture']['controller_path'],'QEMU does not use pinned native fixture socket')
    os.umask(0o077);options.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    CAMPAIGN['output']=options.output.resolve();CAMPAIGN['started']=time.monotonic()
    for path in (options.plan,Path(__file__)):
        require(path.is_file() and not path.is_symlink(),'regular plan/source required')
    args=argparse.Namespace(**rpc,output=CAMPAIGN['output'],mode='freeze-then-crash')
    args.cli=Path(args.cli);args.reader=Path(args.reader)
    campaign=CrashCampaign(args);campaign.plan_sha256=hashlib.sha256(raw).hexdigest()
    def cutoff(*_):raise TimeoutError('absolute harness phase cutoff; no retry')
    old_handler=signal.signal(signal.SIGALRM,cutoff)
    signal.setitimer(signal.ITIMER_REAL,90 if options.phase=='freeze' else 240)
    try:
        durable_record('plan.json',plan)
        write_json('source-pins.json',{str(p.relative_to(ROOT)):sha(p) for p in
            sorted(Path(__file__).parent.glob('*.py'))})
        with SharedSsh(campaign.ssh,args.output) as connection:
            campaign.ssh=connection.command
            if options.phase=='freeze':
                require(options.before is None and options.restart is None,'freeze has no restart inputs')
                phase('A04 explicitly frozen QEMU then crash; not instantaneous powercut')
                campaign.freeze(plan)
            else:
                require(options.before is not None and options.restart is not None,'reviewed before/restart handoff required')
                completed=json_file(options.before/'phase-result.json',65536)
                require(completed['status']=='FROZEN_CRASH_COMPLETE' and not (options.before/'failure.json').exists(),'original phase failed or incomplete')
                restart=json_file(options.restart,131072)
                before=json_file(options.before/'crashed.json',8*1024*1024)
                durable_record('restart-handoff.json',restart)
                campaign.inspect(plan,restart,before)
        # Shared SSH cleanup and hash collection must finish inside the failure
        # boundary before the final success sentinel is written.
        finalize_result(dict(status='FROZEN_CRASH_COMPLETE',actual_inspection='NOT_RUN',
            automatic_retry=False,pure_instantaneous_powercut=False) if options.phase=='freeze' else campaign.inspection_result)
    except BaseException as error:
        write_json('failure.json',dict(phase=CAMPAIGN['phase'],error=repr(error),automatic_retry=False,
            no_automatic_restart_or_sigcont=True,action='preserve output, original VM disk and fixture; root reviews state'))
        try:
            write_json('failure-artifact-hashes.json',{str(p.relative_to(args.output)):sha(p)
                for p in sorted(args.output.rglob('*')) if p.is_file() and p.name!='failure-artifact-hashes.json'})
        except BaseException as error:
            write_json('failure-hash-collection-unknown.json',dict(error=repr(error)))
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old_handler)


if __name__=='__main__':main()
