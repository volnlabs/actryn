#!/usr/bin/env python3
"""Installed disposable Debian preview guest; reviewed guest_broker fixture required."""
import hashlib,json,os,pathlib,subprocess,sys,tempfile,time
assert os.geteuid()==0
binary=str(pathlib.Path(sys.argv[1]).resolve())
config=json.loads(pathlib.Path('/etc/actryn/server.json').read_text())
operator=config['operator_uid']
output=pathlib.Path(tempfile.mkdtemp(prefix='actryn-cli-',dir='/var/tmp'))
os.chown(output,operator,operator)
def cli(*args,ok=True):
    result=subprocess.run([binary,*args],capture_output=True,text=True,timeout=20,
                          user=operator,group=operator,extra_groups=[])
    value=json.loads(result.stdout)
    assert (result.returncode==0)==ok,(args,result.returncode,value,result.stderr)
    return value
assert cli('robot','grant','--epoch','00'*16,'--duration-ms','60001',ok=False)['outcome_unknown'] is False
prepared=cli('server','prepare','--artifact',next(iter(config['artifacts'])))
attempt=prepared['inspection']['attempt']['id']
assert prepared['inspection']['attempt']['state']=='prepared'
try:
    assert cli('server','launch','--attempt',attempt)['inspection']['attempt']['state']=='running'
    for _ in range(60):
        log=pathlib.Path('/var/lib/actryn-server',attempt,'stdout.log')
        if b'BROKER_ACCEPTANCE_PASS' in log.read_bytes():break
        time.sleep(.25)
    else:raise AssertionError('reviewed broker fixture did not complete')
    result=cli('server','result','--attempt',attempt,'--key','offline-1')
    assert result['call']['state']=='settled' and result['value']['origin']=='server_attested' and result['value']['output']=={'left_delta_ticks':10,'right_delta_ticks':10,'duration_ms':1000},result
finally:
    cli('server','cancel','--attempt',attempt)
assert cli('server','status','--attempt',attempt)['inspection']['attempt']['state']=='reaped'
assert cli('server','result','--attempt',attempt,'--key','offline-1')['value'] is None
path=output/'evidence.json'
exported=cli('server','export','--attempt',attempt,'--out',str(path))
assert not exported['execution_replay_eligible']
raw=path.read_bytes();assert len(raw)<=60*1024 and path.stat().st_mode&0o777==0o600
bundle=json.loads(raw);assert bundle['attempt_id']==attempt
for item in bundle['artifacts']:
    encoded=json.dumps(item['content'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    assert item['bytes']==len(encoded) and item['sha256']=='sha256:'+hashlib.sha256(encoded).hexdigest()
assert cli('server','export','--attempt',attempt,'--out',str(path),ok=False)['outcome_unknown'] is False
assert path.read_bytes()==raw
print(json.dumps({'test':'installed-cli-server','status':'PASS','attempt':attempt,'operator_uid':operator,'evidence':str(path)}))
