#!/usr/bin/env python3
"""Real disposable installed server guest; explicit fresh imported OCI preview test."""
import json,os,pathlib,subprocess,sys,time
assert os.geteuid()==0
layout=pathlib.Path(sys.argv[1]);digest=sys.argv[2]
def cli(*args,ok=True):
    p=subprocess.run(['/usr/local/bin/actryn',*args],capture_output=True,text=True,timeout=20,user=1000,group=1000,extra_groups=[])
    value=json.loads(p.stdout);assert (p.returncode==0)==ok,(args,value,p.stderr);return value

def run_import(pin,ok=True):
    p=subprocess.run(['/usr/bin/actryn-artifact','import','--layout',str(layout),'--digest',pin],capture_output=True,text=True,timeout=20)
    assert (p.returncode==0)==ok,(p.stdout,p.stderr)
    return json.loads(p.stdout) if ok else p.stderr

config_path=pathlib.Path('/etc/actryn/server.json')
config=json.loads(config_path.read_text());assert config['operator_uid']==1000
# Only legacy fixture approvals are replaced; attempt/evidence history remains intact.
config['artifacts']={};config_path.write_text(json.dumps(config));config_path.chmod(0o644)
before=config_path.read_bytes()
run_import('sha256:'+'0'*64,ok=False);assert config_path.read_bytes()==before
imported=run_import(digest);assert imported['artifact_digest']==digest
assert run_import(digest)['artifact_digest']==digest,'identical verified import should be idempotent'
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
    cli('server','cancel','--attempt',attempt)
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
    cli('server','cancel','--attempt',attempt)
assert cli('server','result','--attempt',attempt,'--key','preview-1')['value'] is None
assert not pathlib.Path('/sys/fs/cgroup/actryn',attempt).exists()
print(json.dumps({'test':'verified-oci-offline-preview','status':'PASS','artifact_digest':digest,'attempt_id':attempt,'output':proposal}))
