#!/usr/bin/env python3
"""Create the deterministic narrow reviewed OCI layout; never run the supplied agent."""
import argparse,hashlib,io,json,pathlib,struct,tarfile
MAX_AGENT=8*1024*1024

def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def build(agent,output,input_path=None,schema_path=None,profile="offline-preview-v1",live_policy=None):
    here=pathlib.Path(__file__).resolve().parent
    assert profile in ['offline-preview-v1','live-preview-v1'],'unsupported profile'
    labels={'org.actryn.profile':profile}
    live=profile=='live-preview-v1'
    if live:
        assert live_policy,'live profile requires the reviewed server policy digest'
        policy=json.loads(pathlib.Path(live_policy).read_bytes())
        assert policy['profile']==profile and policy['model']=='gpt-5.4-mini-2026-03-17','unsupported live model/profile'
        pin=policy['model_policy_sha256'];assert len(pin)==71 and pin.startswith('sha256:') and all(c in '0123456789abcdef' for c in pin[7:]),'invalid policy digest'
        labels.update({'org.actryn.model':policy['model'],'org.actryn.model-policy':pin})
    binary=pathlib.Path(agent).read_bytes();assert 64<=len(binary)<=MAX_AGENT and binary[:6]==b'\x7fELF\x02\x01','static amd64 ELF required'
    assert struct.unpack_from('<H',binary,18)[0]==62,'amd64 only'
    offset=struct.unpack_from('<Q',binary,32)[0];size,count=struct.unpack_from('<HH',binary,54)
    assert size==56 and 1<=count<=128 and offset+size*count<=len(binary),'ELF program headers'
    kinds=[struct.unpack_from('<I',binary,offset+n*size)[0] for n in range(count)]
    assert 1 in kinds and 3 not in kinds,'dynamic interpreter unsupported'
    data=pathlib.Path(input_path or here/('input-live.json' if live else 'input.json')).read_bytes();schema=pathlib.Path(schema_path or here/('input-live.schema.json' if live else 'input.schema.json')).read_bytes()
    assert len(data)<=4096 and len(schema)<=8192;value=json.loads(data);json.loads(schema)
    assert value.get('mode','offline')==('live' if live else 'offline'),'input mode/profile mismatch'
    output=pathlib.Path(output);output.mkdir(mode=0o755);blobs=output/'blobs/sha256';blobs.mkdir(parents=True)
    def blob(data,media):
        digest='sha256:'+hashlib.sha256(data).hexdigest();(blobs/digest[7:]).write_bytes(data)
        return {'mediaType':media,'digest':digest,'size':len(data)}
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w',format=tarfile.USTAR_FORMAT) as layer:
        for name,contents,mode in [('bin/agent',binary,0o555),('etc/actryn/input.json',data,0o444),('etc/actryn/input.schema.json',schema,0o444)]:
            header=tarfile.TarInfo(name);header.size=len(contents);header.mode=mode;header.uid=header.gid=header.mtime=0;header.uname=header.gname='';layer.addfile(header,io.BytesIO(contents))
    layer=blob(buffer.getvalue(),'application/vnd.oci.image.layer.v1.tar')
    config=blob(encode({'architecture':'amd64','os':'linux','config':{'Entrypoint':['/bin/agent'],'User':'65532:65532','WorkingDir':'/tmp','Labels':labels},'rootfs':{'type':'layers','diff_ids':[layer['digest']]}}),'application/vnd.oci.image.config.v1+json')
    manifest=blob(encode({'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json','config':config,'layers':[layer]}),'application/vnd.oci.image.manifest.v1+json')
    (output/'index.json').write_bytes(encode({'schemaVersion':2,'mediaType':'application/vnd.oci.image.index.v1+json','manifests':[manifest]}))
    (output/'oci-layout').write_bytes(encode({'imageLayoutVersion':'1.0.0'}))
    return manifest['digest']
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--agent',required=True);parser.add_argument('--out',required=True);parser.add_argument('--input');parser.add_argument('--schema');parser.add_argument('--profile',choices=['offline-preview-v1','live-preview-v1'],default='offline-preview-v1');parser.add_argument('--live-policy');args=parser.parse_args()
    print(json.dumps({'artifact_digest':build(args.agent,args.out,args.input,args.schema,args.profile,args.live_policy),'layout':args.out}))
