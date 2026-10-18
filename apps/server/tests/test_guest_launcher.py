"""Retained fixture selection must reject a different execution configuration."""
import copy
import unittest

from guest_launcher import retained_fixture


class RetainedFixtureTests(unittest.TestCase):
    def setUp(self):
        self.artifact='sha256:'+'a'*64
        self.config={'server_uid':991,'operator_uid':1000,'io_device':'254:0','artifacts':{
            self.artifact:{'rootfs':'/var/lib/actryn-artifacts/'+'a'*64+'/rootfs','argv':['/bin/agent']}}}

    def test_exact_configuration_is_selected_without_mutation(self):
        original=copy.deepcopy(self.config)
        self.assertEqual(retained_fixture(self.config,self.artifact,'254:0'),self.artifact)
        self.assertEqual(self.config,original)

    def test_different_identity_device_artifact_or_command_is_rejected(self):
        cases=[(self.config,'sha256:'+'A'*64,'254:0'),(self.config,self.artifact,'8:0')]
        for key,value in [('server_uid',987),('operator_uid',0),('artifacts',{})]:
            config=copy.deepcopy(self.config);config[key]=value;cases.append((config,self.artifact,'254:0'))
        config=copy.deepcopy(self.config);config['artifacts'][self.artifact]['argv']=['/bin/sh'];cases.append((config,self.artifact,'254:0'))
        for config,artifact,device in cases:
            with self.subTest(config=config,artifact=artifact,device=device):
                with self.assertRaises(AssertionError):retained_fixture(config,artifact,device)
