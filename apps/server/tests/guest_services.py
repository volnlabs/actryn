#!/usr/bin/env python3
"""Disposable pinned Debian VM only. Run guest_broker.py first to install its reviewed fixture."""
import fcntl,grp,hashlib,json,os,pathlib,pwd,shutil,signal,sqlite3,subprocess,sys,time
from guest_launcher import rpc,wait_for,socket_ready

def systemctl(*args):
    subprocess.run(['systemctl',*args],check=True)

def pid(unit):
    return int(subprocess.check_output(['systemctl','show','-p','MainPID','--value',unit]))

def read_inspection(attempt):
    try:
        result=rpc({'op':'inspect','attempt_id':attempt},'/run/actryn-server/server.sock')
        return result.get('inspection')
    except (OSError,AssertionError):return None

def new_attempt():
    config=json.loads(pathlib.Path('/etc/actryn/server.json').read_text())
    artifact=next(iter(config['artifacts']))
    response=rpc({'op':'prepare','artifact_digest':artifact},'/run/actryn-server/server.sock')
    assert response['result']=='ok',response
    attempt=response['inspection']['attempt']['id']
    started=rpc({'op':'start','attempt_id':attempt},'/run/actryn-server/server.sock')
    assert started['result']=='ok',started
    output=pathlib.Path('/var/lib/actryn-server')/attempt/'stdout.log'
    wait_for(lambda:b'BROKER_ACCEPTANCE_PASS' in output.read_bytes(),15)
    return attempt

def verify_retired_export(attempt,unknown_owner=None):
    def retired():
        inspection=read_inspection(attempt)
        return inspection and inspection['attempt']['state']=='reaped'
    wait_for(retired,30)
    assert not pathlib.Path('/sys/fs/cgroup/actryn',attempt).exists()
    response=rpc({'op':'export','attempt_id':attempt},'/run/actryn-server/server.sock')
    assert response['result']=='evidence',response
    bundle=response['bundle'];assert not bundle['execution_replay_eligible']
    assert len(json.dumps(bundle,separators=(',',':'),ensure_ascii=False).encode())<=60*1024
    artifacts={item['name']:item for item in bundle['artifacts']}
    if unknown_owner=='broker':
        assert artifacts['broker']['content']['attempt_outcome']=='unknown','broker crash lost uncertain outcome'
    if unknown_owner=='launcher':
        assert artifacts['attempt']['content']['outcome']=='unknown','launcher crash lost uncertain outcome'
    for item in artifacts.values():
        encoded=json.dumps(item['content'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        assert item['bytes']==len(encoded),item['name']
        assert item['sha256']=='sha256:'+hashlib.sha256(encoded).hexdigest(),item['name']
    counters=artifacts['runtime_facts']['content']['resources']['counters']
    assert int(counters['memory.peak'])>0,counters
    assert 'oom_kill ' in counters['memory.events'],counters
    assert 'usage_usec ' in counters['cpu.stat'],counters
    assert artifacts['runtime_facts']['content']['observer']['collector_epoch']
    log=artifacts['stdout']['content'];raw=(pathlib.Path('/var/lib/actryn-server')/attempt/'stdout.log').read_bytes()
    assert log['retained_bytes']==len(raw) and log['retained_sha256']=='sha256:'+hashlib.sha256(raw).hexdigest()
    assert bytes.fromhex(log['tail'])==raw[-2048:]
    assert raw.count(b'BROKER_ACCEPTANCE_PASS')==1,'restart repeated agent work'
    assert artifacts['broker']['content']['policy_denials'][0]['reason']=='method_not_allowed'
    assert rpc({'op':'result','attempt_id':attempt,'request_key':'offline-1'},'/run/actryn-server/server.sock')['value'] is None
    pathlib.Path('/root',f'actryn-export-{attempt}.json').write_text(json.dumps(bundle,indent=2))
    operator="""import json,socket,struct,sys
with socket.socket(socket.AF_UNIX) as s:
    s.settimeout(15);s.connect('/run/actryn-server/server.sock')
    data=json.dumps({'op':'export','attempt_id':sys.argv[1]}).encode()
    s.sendall(struct.pack('!I',len(data))+data)
    def read(n):
        data=b''
        while len(data)<n:
            part=s.recv(n-len(data));assert part;data+=part
        return data
    length=struct.unpack('!I',read(4))[0];assert length<=65536
    assert json.loads(read(length))['result']=='evidence'
print('OPERATOR_EXPORT_PASS')
"""
    assert subprocess.check_output(['python3','-c',operator,attempt],user=1000,group=1000,extra_groups=[]).strip()==b'OPERATOR_EXPORT_PASS'

assert os.geteuid()==0
assert pathlib.Path('/var/lib/actryn-broker-test-rootfs/bin/agent').exists(),'run guest_broker.py first'
packaging=pathlib.Path(sys.argv[3]).resolve()
for unit in ['actryn-serverd.service','actryn-launcher.service']:
    subprocess.run(['systemctl','stop',unit],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
locks=[]
for path in ['/var/lib/actryn-server/launcher.lock','/var/lib/actryn-server/broker/server.lock']:
    lock=open(path,'r+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(lock)
config_path=pathlib.Path('/etc/actryn/server.json');config=json.loads(config_path.read_text())
old_uid=config['server_uid']
def validate_account():
    try:account=pwd.getpwnam('actryn-server')
    except KeyError:return None
    group=grp.getgrnam('actryn-server')
    assert account.pw_uid not in [0,config['operator_uid']] and account.pw_gid==group.gr_gid
    assert (account.pw_dir,account.pw_shell)==('/nonexistent','/usr/sbin/nologin'),'unsafe existing service account'
    assert pwd.getpwuid(account.pw_uid).pw_name==account.pw_name and grp.getgrgid(group.gr_gid).gr_name==group.gr_name,'numeric account alias'
    assert set(os.getgrouplist(account.pw_name,account.pw_gid))=={account.pw_gid},'unexpected supplementary service groups'
    assert set(group.gr_mem)<={'actryn-server'},'unexpected members of service group'
    return account
validate_account()
pathlib.Path('/etc/sysusers.d').mkdir(exist_ok=True)
sysusers=pathlib.Path('/etc/sysusers.d/actryn-server.conf')
shutil.copyfile(packaging/'sysusers.d/server.conf',sysusers)
subprocess.run(['systemd-sysusers',str(sysusers)],check=True)
account=validate_account();assert account
# Migrate only the earlier native fixture's inactive accounting files, never unrelated identities.
for db_path in ['/var/lib/actryn-server/launcher.sqlite','/var/lib/actryn-server/broker/state.sqlite']:
    database=sqlite3.connect(f'file:{db_path}?mode=ro',uri=True)
    try:
        assert database.execute("SELECT count(*) FROM attempts WHERE state!='reaped'").fetchone()[0]==0,'active accounting prevents identity migration'
    finally:database.close()
broker_state=pathlib.Path('/var/lib/actryn-server/broker')
for path in broker_state.iterdir():
    assert path.name in ['server.lock','state.sqlite','state.sqlite-wal','state.sqlite-shm'],'unknown broker state file'
    assert not path.is_symlink() and path.is_file() and path.stat().st_uid in [old_uid,account.pw_uid],'unexpected broker state owner/type'
    os.chown(path,account.pw_uid,account.pw_gid)
os.chown(broker_state,account.pw_uid,account.pw_gid)
config['server_uid']=account.pw_uid
replacement=config_path.with_suffix('.json.packaging');replacement.write_text(json.dumps(config));replacement.chmod(0o644);replacement.replace(config_path)
for lock in locks:lock.close()
for source,destination in [(sys.argv[1],'/usr/bin/actryn-launcher'),(sys.argv[2],'/usr/bin/actryn-serverd')]:
    shutil.copyfile(source,destination);pathlib.Path(destination).chmod(0o755)
for name in ['actryn-launcher.service','actryn-serverd.service']:
    shutil.copyfile(packaging/'systemd'/name,pathlib.Path('/etc/systemd/system')/name)
tmpfile=pathlib.Path('/etc/tmpfiles.d/actryn-server.conf')
shutil.copyfile(packaging/'tmpfiles.d/server.conf',tmpfile)
subprocess.run(['systemd-tmpfiles','--create',str(tmpfile)],check=True)
systemctl('daemon-reload')
subprocess.run(['systemd-analyze','verify','/etc/systemd/system/actryn-launcher.service','/etc/systemd/system/actryn-serverd.service'],check=True)
reset=subprocess.run(['systemctl','reset-failed','actryn-launcher.service','actryn-serverd.service'],capture_output=True,text=True)
assert reset.returncode==0 or (reset.stderr.strip() and all('not loaded' in line.lower() for line in reset.stderr.splitlines())),reset.stderr
systemctl('start','actryn-serverd.service')
wait_for(lambda:socket_ready('/run/actryn-server/server.sock'),15)
service_status=pathlib.Path(f'/proc/{pid("actryn-serverd.service")}/status').read_text()
assert 'CapEff:\t0000000000000000' in service_status and 'NoNewPrivs:\t1' in service_status
attempts=[]
for victim in ['actryn-serverd.service','actryn-launcher.service']:
    attempt=new_attempt();attempts.append(attempt)
    previous=pid(victim);os.kill(previous,signal.SIGKILL)
    wait_for(lambda:pid(victim)>0 and pid(victim)!=previous,30)
    verify_retired_export(attempt,'broker' if victim=='actryn-serverd.service' else 'launcher')
    if victim=='actryn-launcher.service':
        bundle=rpc({'op':'export','attempt_id':attempt},'/run/actryn-server/server.sock')['bundle']
        assert any(item['reason']=='log_incomplete' for item in bundle['omissions']),bundle
attempt=new_attempt();attempts.append(attempt)
systemctl('stop','actryn-serverd.service')
systemctl('start','actryn-serverd.service')
wait_for(lambda:socket_ready('/run/actryn-server/server.sock'),15)
verify_retired_export(attempt)
print(json.dumps({'test':'packaged-services-crash-recovery-and-evidence','status':'PASS','attempts':attempts}))
