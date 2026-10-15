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
if __name__=='__main__':unittest.main()
