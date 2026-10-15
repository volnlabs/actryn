#!/usr/bin/env python3
"""Explicit single-call live-profile acceptance in the installed disposable guest.

Never reads or prints credential bytes. Failed/unknown calls are preserved, not retried.
"""
import argparse,json,os,pathlib,subprocess,time

parser=argparse.ArgumentParser()
parser.add_argument('layout',type=pathlib.Path)
parser.add_argument('digest')
parser.add_argument('--expect',required=True,choices=['missing-credential','completed'])
args=parser.parse_args()
assert os.geteuid()==0
config=json.loads(pathlib.Path('/etc/actryn/server.json').read_bytes())
assert config['operator_uid']==1000

def cli(*arguments):
    process=subprocess.run(['/usr/local/bin/actryn',*arguments],capture_output=True,text=True,
        timeout=20,user=1000,group=1000,extra_groups=[])
    assert process.returncode==0,(arguments,process.stdout,process.stderr)
    return json.loads(process.stdout)

subprocess.run(['systemctl','stop','actryn-serverd','actryn-launcher'],check=True,timeout=40)
process=subprocess.run(['/usr/bin/actryn-artifact','import','--layout',str(args.layout),'--digest',args.digest],
    capture_output=True,text=True,timeout=20)
assert process.returncode==0,(process.stdout,process.stderr)
subprocess.run(['systemctl','start','actryn-serverd'],check=True,timeout=40)
credential=pathlib.Path('/run/credentials/actryn-serverd.service/openai-api-key')
assert credential.exists()==(args.expect=='completed'),'credential metadata does not match explicit test mode'
prepared=cli('server','prepare','--artifact',args.digest)
attempt=prepared['inspection']['attempt']['id']
print(json.dumps({'event':'prepared','attempt_id':attempt,'artifact_digest':args.digest,'expect':args.expect}),flush=True)
root=pathlib.Path('/var/lib/actryn-server')/attempt
output=None
started=time.monotonic()
try:
    cli('server','launch','--attempt',attempt)
    for _ in range(400):
        stdout=(root/'stdout.log').read_text().splitlines()
        stderr=(root/'stderr.log').read_text().splitlines()
        if stdout or stderr:break
        time.sleep(.1)
    else:raise AssertionError('agent has no bounded outcome; inspect retained attempt')
    elapsed_ms=round((time.monotonic()-started)*1000)
    status=cli('server','status','--attempt',attempt)
    if args.expect=='missing-credential':
        assert not stdout and len(stderr)==1,(stdout,stderr)
        output=json.loads(stderr[0]);assert output['event']=='preview_error' and output['automatic_retry'] is False
        assert status['inspection']['calls']==[],status
    else:
        assert not stderr and len(stdout)==1,(stdout,stderr)
        output=json.loads(stdout[0]);assert output['event']=='preview_proposal' and output['authority_issued'] is False
        result=cli('server','result','--attempt',attempt,'--key','live-preview-1')
        assert result['value']==output['value']
        assert result['value']['model']=='gpt-5.4-mini-2026-03-17'
        assert result['value']['origin']=='server_attested' and result['value']['attempt_id']==attempt
        calls=status['inspection']['calls'];assert len(calls)==1 and calls[0]['state']=='settled',status
finally:
    cli('server','cancel','--attempt',attempt)
assert not pathlib.Path('/sys/fs/cgroup/actryn',attempt).exists()
print(json.dumps({'test':'verified-oci-live-preview','status':'PASS','expect':args.expect,
    'artifact_digest':args.digest,'attempt_id':attempt,'elapsed_ms':elapsed_ms,'output':output}),flush=True)
