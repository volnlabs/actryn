#!/usr/bin/env python3
"""Real disposable installed server guest; explicit fresh imported OCI preview test."""
import contextlib,json,os,pathlib,sqlite3,subprocess,sys,time,uuid
assert os.geteuid()==0
layout=pathlib.Path(sys.argv[1]);digest=sys.argv[2]
def cli(*args,ok=True):
    p=subprocess.run(['/usr/local/bin/actryn',*args],capture_output=True,text=True,timeout=20,user=1000,group=1000,extra_groups=[])
    value=json.loads(p.stdout);assert (p.returncode==0)==ok,(args,value,p.stderr);return value

def run_import(pin,ok=True):
    p=subprocess.run(['/usr/bin/actryn-artifact','import','--layout',str(layout),'--digest',pin],capture_output=True,text=True,timeout=20)
    assert (p.returncode==0)==ok,(p.stdout,p.stderr)
    return json.loads(p.stdout) if ok else p.stderr

def cancel_once_and_wait(attempt):
    # A lost durability acknowledgement is not permission to resend a mutation.
    p=subprocess.run(['/usr/local/bin/actryn','server','cancel','--attempt',attempt],
        capture_output=True,text=True,timeout=20,user=1000,group=1000,extra_groups=[])
    reply=json.loads(p.stdout)
    print(json.dumps({'event':'cancel_once','attempt_id':attempt,'returncode':p.returncode,
        'reply':reply,'stderr':p.stderr,'mutation_retried':False}),flush=True)
    assert p.returncode==0 or (reply.get('outcome_unknown') is True and
        reply.get('automatic_retry') is False),reply
    deadline=time.monotonic()+10
    while True:
        inspection=cli('server','status','--attempt',attempt)['inspection']
        stores={}
        for name,path in [('launcher','/var/lib/actryn-server/launcher.sqlite'),
                          ('broker','/var/lib/actryn-server/broker/state.sqlite')]:
            with contextlib.closing(sqlite3.connect('file:'+path+'?mode=ro',uri=True)) as db:
                state=db.execute('SELECT state,binding FROM attempts WHERE id=?',(attempt,)).fetchone()
                assert state is not None,(name,attempt)
                gaps=db.execute('SELECT * FROM gaps WHERE attempt_id=?',(attempt,)).fetchall()
                stores[name]={'state':state[0],'binding':state[1],'gaps':gaps}
                if name=='launcher':
                    facts=db.execute('SELECT data FROM runtime_evidence WHERE attempt_id=?',(attempt,)).fetchone()
        if (inspection['attempt']['state']=='reaped' and
            all(value['state']=='reaped' for value in stores.values()) and
            not pathlib.Path('/sys/fs/cgroup/actryn',attempt).exists()):
            break
        assert time.monotonic()<deadline,{'attempt':attempt,'stores':stores,'inspection':inspection}
        time.sleep(.1)
    assert not inspection['evidence_gaps'] and all(not value['gaps'] for value in stores.values()),stores
    assert facts is not None,'resource/observer evidence missing'
    facts=json.loads(facts[0]);health=facts['observer']
    assert (facts['observer_health_unavailable'] is False and health['ready'] and health['lost']==0
        and not facts['resources']['unavailable']),facts
    epoch=json.loads(stores['launcher']['binding'])['observer']['collector_epoch']
    assert str(uuid.UUID(epoch))==epoch and health['collector_epoch']==epoch
    log=pathlib.Path('/var/lib/actryn-observer')/epoch/(attempt+'.jsonl')
    summary_path=log.with_suffix('.summary.json')
    assert summary_path.stat().st_size<=4096
    summary=json.loads(summary_path.read_text())
    assert (summary['status']['collector_epoch']==epoch and summary['status']['ready'] and
        summary['status']['lost']==0 and summary['local_lost']==0 and
        summary['status']['sequence']>=health['sequence'] and
        summary['retained_bytes']==log.stat().st_size<=16*1024*1024),summary
    print(json.dumps({'event':'retirement_observed','attempt_id':attempt,
        'states':{name:value['state'] for name,value in stores.items()},
        'cancel_reply_unknown':reply.get('outcome_unknown',False),'observer_summary':summary,
        'evidence_gaps':[],'cgroup_removed':True,'mutation_retried':False}),flush=True)

config_path=pathlib.Path('/etc/actryn/server.json')
config=json.loads(config_path.read_text());assert config['operator_uid']==1000
# The installed approval map and all retained attempt/evidence history remain intact.
before=config_path.read_bytes()
run_import('sha256:'+'0'*64,ok=False);assert config_path.read_bytes()==before
imported=run_import(digest);assert imported['artifact_digest']==digest
assert run_import(digest)['artifact_digest']==digest,'identical verified import should be idempotent'
unfinished='sha256:'+'f'*64
staging=pathlib.Path('/var/lib/actryn-artifacts')/('.incomplete-'+unfinished[7:])
staging.mkdir();(staging/'partial').write_bytes(b'interrupted import fixture')
subprocess.run(['/usr/bin/actryn-artifact','discard-incomplete','--digest',unfinished],check=True,capture_output=True,timeout=20)
assert not staging.exists() and pathlib.Path(imported['rootfs']).is_dir()
subprocess.run(['systemctl','start','actryn-serverd'],check=True)
run_import(digest,ok=False) # Lifetime locks prohibit registry/config changes under live daemons.
root=pathlib.Path(imported['rootfs'])
prepared=cli('server','prepare','--artifact',digest);attempt=prepared['inspection']['attempt']['id']
source=root/'etc/actryn/input.json';original=source.read_bytes()
try:
    source.chmod(0o644);source.write_bytes(original+b' ');source.chmod(0o444)
    rejected=cli('server','launch','--attempt',attempt,ok=False)
    assert 'OCI' in rejected['message'] or 'artifact' in rejected['message'] or 'rootfs' in rejected['message'],rejected
finally:
    source.chmod(0o644);source.write_bytes(original);source.chmod(0o444)
    cancel_once_and_wait(attempt)
assert (pathlib.Path('/var/lib/actryn-server')/attempt/'stdout.log').read_bytes()==b''
prepared=cli('server','prepare','--artifact',digest);attempt=prepared['inspection']['attempt']['id']
try:
    cli('server','launch','--attempt',attempt)
    log=pathlib.Path('/var/lib/actryn-server')/attempt/'stdout.log'
    for _ in range(60):
        lines=log.read_text().splitlines()
        if lines:break
        time.sleep(.1)
    else:raise AssertionError('preview result missing')
    proposal=json.loads(lines[0]);assert proposal['event']=='preview_proposal' and not proposal['authority_issued']
    result=cli('server','result','--attempt',attempt,'--key','preview-1')
    assert result['value']==proposal['value']
    assert result['value']['attempt_id']==attempt and result['value']['origin']=='server_attested'
    assert result['value']['output']=={'left_delta_ticks':10,'right_delta_ticks':10,'duration_ms':1000}
finally:
    cancel_once_and_wait(attempt)
assert cli('server','result','--attempt',attempt,'--key','preview-1')['value'] is None
assert not pathlib.Path('/sys/fs/cgroup/actryn',attempt).exists()
print(json.dumps({'test':'verified-oci-offline-preview','status':'PASS','artifact_digest':digest,'attempt_id':attempt,'output':proposal}))
