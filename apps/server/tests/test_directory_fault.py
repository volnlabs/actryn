import errno
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

PROBE = r'''
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int argc, char **argv) {
 if(argc!=3) return 2;
 int result=strcmp(argv[1],"mkdir")==0?mkdir(argv[2],0700):rmdir(argv[2]);
 int saved=errno; printf("{\"return\":%d,\"errno\":%d}\n",result,result? saved:0); return 0;
}
'''


class DirectoryFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.control = self.root/'control'; self.control.mkdir(mode=0o700)
        self.brokers = self.root/'brokers'; self.brokers.mkdir()
        self.library = self.root/'fault.so'; self.probe = self.root/'probe'
        (self.root/'probe.c').write_text(PROBE)
        for command in [
            ['cc','-std=c11','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
             '-DACTRYN_A08_HOST_TEST',f'-DCONTROL_DIR="{self.control}"',
             f'-DBROKER_PREFIX="{self.brokers}/"','-o',str(self.library),
             str(Path(__file__).with_name('directory_fault.c'))],
            ['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-o',str(self.probe),str(self.root/'probe.c')]]:
            subprocess.run(command,check=True,capture_output=True,timeout=15)

    def arm(self, mode='A', active='a'*32, target=None, start=None, end=None):
        target = target if target is not None else ('0'*32 if mode == 'A' else 'b'*32)
        start = start if start is not None else time.monotonic_ns()
        end = end if end is not None else start+5_000_000_000
        path = self.control/'control'; path.write_text(f'1 {mode} {start} {end} {active} {target}\n'); path.chmod(0o600)

    def call(self, op, path):
        run = subprocess.run([str(self.probe),op,str(path)],env=dict(os.environ,LD_PRELOAD=str(self.library)),
                             capture_output=True,check=True,timeout=2)
        return json.loads(run.stdout)

    def test_real_libc_interposition_injects_once_and_preserves_errno_and_active_path(self):
        self.arm()
        self.assertEqual(self.call('mkdir',self.brokers/('a'*32)), {'return':0,'errno':0})
        target = self.brokers/('b'*32)
        self.assertEqual(self.call('mkdir',target), {'return':-1,'errno':errno.ENOSPC})
        self.assertFalse(target.exists())
        self.assertEqual((self.control/'latched').read_text(), 'b'*32+'\n')
        self.assertEqual(self.call('mkdir',target), {'return':0,'errno':0})
        events=(self.control/'events').read_text().splitlines(); self.assertEqual(len(events),1)
        self.assertIn(' A 28 ',events[0]); self.assertIn(str(target),events[0])

    def test_reclaim_matches_only_exact_target_and_expires_without_blocking(self):
        target=self.brokers/('b'*32);target.mkdir();other=self.brokers/('c'*32);other.mkdir()
        self.arm('R')
        self.assertEqual(self.call('rmdir',other),{'return':0,'errno':0})
        self.assertEqual(self.call('rmdir',target),{'return':-1,'errno':errno.EBUSY})
        self.assertTrue(target.exists())
        self.arm('R',start=1,end=2)
        self.assertEqual(self.call('rmdir',target),{'return':0,'errno':0})

    def test_malformed_long_lived_writable_or_symlink_control_is_inert(self):
        for fault in ('syntax','long_lease','writable','symlink','oversize','same_identity','nonhex'):
            with self.subTest(fault=fault):
                self.arm();control=self.control/'control'
                if fault=='syntax':control.write_text('garbage\n')
                elif fault=='long_lease':self.arm(end=time.monotonic_ns()+11_000_000_000)
                elif fault=='writable':control.chmod(0o666)
                elif fault=='symlink':control.rename(self.control/'source');control.symlink_to('source')
                elif fault=='oversize':control.write_text('x'*200)
                elif fault=='same_identity':self.arm(target='a'*32)
                else:self.arm(active='z'*32)
                target=self.brokers/('d'*32)
                self.assertEqual(self.call('mkdir',target),{'return':0,'errno':0})
                target.rmdir();control.unlink()

    def test_unrelated_paths_and_regular_kernel_errors_are_unchanged(self):
        self.arm()
        target=self.root/'other';target.mkdir()
        self.assertEqual(self.call('mkdir',target),{'return':-1,'errno':errno.EEXIST})
        self.assertEqual(self.call('rmdir',self.root/'absent'),{'return':-1,'errno':errno.ENOENT})
        self.assertFalse((self.control/'events').exists())

    def test_fifo_control_and_symlink_events_are_inert_and_do_not_block(self):
        os.mkfifo(self.control/'control',0o600)
        target=self.brokers/('d'*32)
        self.assertEqual(self.call('mkdir',target),{'return':0,'errno':0})
        target.rmdir(); (self.control/'control').unlink()
        self.arm('R'); target=self.brokers/('b'*32); target.mkdir()
        (self.control/'outside').write_text('preserve'); (self.control/'events').symlink_to('outside')
        self.assertEqual(self.call('rmdir',target),{'return':0,'errno':0})
        self.assertEqual((self.control/'outside').read_text(),'preserve')

    def test_full_event_inventory_stops_injection_without_extending_the_lease(self):
        self.arm('R'); target=self.brokers/('b'*32); target.mkdir()
        event=self.control/'events'; event.write_text('record\n'*64);event.chmod(0o600)
        self.assertEqual(self.call('rmdir',target),{'return':0,'errno':0})
        self.assertEqual(event.read_text(),'record\n'*64)


if __name__=='__main__':unittest.main()
