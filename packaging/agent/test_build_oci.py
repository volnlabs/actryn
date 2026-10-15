#!/usr/bin/env python3
import hashlib,json,pathlib,struct,tempfile,unittest
from build_oci import build
class Packaging(unittest.TestCase):
    def test_identical_inputs_produce_identical_real_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);agent=root/'agent';elf=bytearray(120);elf[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',elf,18,62);struct.pack_into('<Q',elf,32,64);struct.pack_into('<HH',elf,54,56,1);struct.pack_into('<I',elf,64,1);agent.write_bytes(elf)
            first=build(agent,root/'one');second=build(agent,root/'two');self.assertEqual(first,second)
            manifest=(root/'one/blobs/sha256'/first[7:]).read_bytes();self.assertEqual('sha256:'+hashlib.sha256(manifest).hexdigest(),first)
            for file in (root/'one').rglob('*'):
                if file.is_file():self.assertEqual(file.read_bytes(),(root/'two'/file.relative_to(root/'one')).read_bytes())
            struct.pack_into('<I',elf,64,3);agent.write_bytes(elf)
            with self.assertRaises(AssertionError):build(agent,root/'dynamic')
    def test_live_profile_is_separate_and_requires_policy_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);agent=root/'agent';elf=bytearray(120);elf[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',elf,18,62);struct.pack_into('<Q',elf,32,64);struct.pack_into('<HH',elf,54,56,1);struct.pack_into('<I',elf,64,1);agent.write_bytes(elf)
            with self.assertRaises(AssertionError):build(agent,root/'missing',profile='live-preview-v1')
            policy={'profile':'live-preview-v1','model':'gpt-5.4-mini-2026-03-17','model_policy_sha256':'sha256:'+'1'*64}
            pin=root/'policy.json';pin.write_text(json.dumps(policy))
            live=build(agent,root/'live',profile='live-preview-v1',live_policy=pin)
            offline=build(agent,root/'offline');self.assertNotEqual(live,offline)
            manifest=json.loads((root/'live/blobs/sha256'/live[7:]).read_bytes());config=json.loads((root/'live/blobs/sha256'/manifest['config']['digest'][7:]).read_bytes())
            self.assertEqual(config['config']['Labels']['org.actryn.model-policy'],policy['model_policy_sha256'])
if __name__=='__main__':unittest.main()
