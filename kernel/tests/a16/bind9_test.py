# SPDX-License-Identifier: GPL-2.0-only
"""Compile only a native host fake of the actual frozen/derived bind function."""
import json
import pathlib
import signal
import subprocess
import tempfile
import unittest
import hashlib
import re
import amendment7
import bind9

HERE=pathlib.Path(__file__).resolve().parent


class Bind9Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='actryn-bind9-test-')
        cls.root=pathlib.Path(cls.directory.name)
        cls.base=amendment7.workload((HERE/'workload.c').read_text())
        cls.derived=bind9.render(cls.base)
        (cls.root/'bind9-workload.c').write_text(cls.derived)
        cls.binary=cls.root/'bind9-host-fake'
        command=['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-DBIND9_DERIVED=1',
            '-I',str(cls.root),'-I',str(HERE),str(HERE/'bind9_fake.c'),'-o',str(cls.binary),
            *('-Wl,--wrap='+name for name in ('socket','connect','send','poll','recv'))]
        built=subprocess.run(command,capture_output=True,text=True,timeout=20)
        if built.returncode:raise AssertionError(built.stderr)
        if built.stdout or built.stderr:raise AssertionError('unexpected compiler output: '+built.stdout+built.stderr)
    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def invoke(self,error,role=2,scope='trial_setup',trial=6,mode='ok'):
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            journal=pathlib.Path(tmp)/'events.jsonl';calls=pathlib.Path(tmp)/'calls'
            result=subprocess.run([str(self.binary),mode,str(error),str(role),scope,str(trial),str(journal),str(calls)],
                capture_output=True,text=True,timeout=3)
            raw=journal.read_bytes();rows=[json.loads(line) for line in raw.splitlines()]
            self.assertEqual(calls.read_text().splitlines(),['socket','connect','send','poll','recv'])
            self.assertEqual(result.stdout,'')
            return result,rows,raw

    def test_nonzero_reply_retains_role_signed_error_scope_before_same_abort(self):
        for role in range(1,5):
            with self.subTest(role=role):
                result,rows,raw=self.invoke(-16,role)
                self.assertEqual(result.returncode,-signal.SIGABRT)
                self.assertEqual(rows,[dict(type='bind_failure',diagnostic=9,phase='userspace_bind_reply',
                    scope='trial_setup',trial=6,role=role,reply_error=-16)])
                self.assertLessEqual(len(raw),256)

    def test_parent_scope_does_not_claim_trial_zero_and_signed_error_is_not_errno(self):
        result,rows,raw=self.invoke(-2147483648,1,'parent_setup',0)
        self.assertEqual(result.returncode,-signal.SIGABRT)
        self.assertEqual(rows,[dict(type='bind_failure',diagnostic=9,phase='userspace_bind_reply',
            scope='parent_setup',trial=None,role=1,reply_error=-2147483648)])
        self.assertLessEqual(len(raw),256)

    def test_success_has_no_diagnostic_output_and_one_exchange(self):
        result,rows,raw=self.invoke(0)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stderr,'')
        self.assertEqual(rows,[]);self.assertEqual(raw,b'')

    def test_malformed_reply_never_claims_a_bind_error(self):
        for mode in ('reserved','short'):
            with self.subTest(mode=mode):
                result,rows,raw=self.invoke(-16,mode=mode)
                self.assertEqual(result.returncode,-signal.SIGABRT)
                self.assertEqual(rows,[]);self.assertEqual(raw,b'')

    def test_exact_source_deterministic_derivative_and_no_other_changes(self):
        self.assertEqual(hashlib.sha256(self.base.encode()).hexdigest(),bind9.BASE_SHA256)
        self.assertEqual(bind9.render(self.base),self.derived)
        for source in (self.base+'\n',self.base.replace('alarm(10)','alarm(11)'),self.derived):
            with self.subTest(source_sha=hashlib.sha256(source.encode()).hexdigest()),self.assertRaises(ValueError):bind9.render(source)
        start='static int bind_role(';end='static struct actryn_status status('
        old=self.base[self.base.index(start):self.base.index(end)]
        new=self.derived[self.derived.index(start):self.derived.index(end)]
        restored=self.derived.replace(new,old)
        calls=re.findall(r'bind_role\((ACTRYN_[A-Z]+),"(parent_setup|trial_setup)"\)',restored)
        self.assertEqual(calls,[('ACTRYN_ADMIN','trial_setup'),('ACTRYN_RUNTIME','trial_setup'),
            ('ACTRYN_EVENTS','trial_setup'),('ACTRYN_ACQUISITION','trial_setup'),
            ('ACTRYN_ADMIN','parent_setup'),('ACTRYN_EVENTS','parent_setup')])
        restored=re.sub(r'bind_role\((ACTRYN_[A-Z]+),"(?:parent_setup|trial_setup)"\)',r'bind_role(\1)',restored)
        self.assertEqual(restored,self.base)
        self.assertEqual(new.count('exchange(fd,&c)'),1)
        self.assertIn('assert(!reply.error);',new)


if __name__=='__main__':unittest.main()
