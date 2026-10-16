import pathlib
import unittest

import prepare


class PreparationTests(unittest.TestCase):
    def test_commands_are_confined_to_new_guest(self):
        root = pathlib.Path('/tmp/isolated/.cache/qemu/a16')
        command = prepare.qemu_command(root, 'raw', 'pilot01')
        self.assertEqual(command[0], 'qemu-system-aarch64')
        self.assertIn('user,id=net0,hostfwd=tcp:127.0.0.1:26224-:22,hostfwd=tcp:127.0.0.1:27446-:7443', command)
        self.assertNotIn('26221', ' '.join(command))
        self.assertIn(str(root / 'boot/raw.dtb'), command)
        self.assertIn('file:' + str(root / 'serial-pilot01.log'), command)
        self.assertFalse(any('systemctl' in arg or 'systemd-run' in arg for arg in command))

    def test_boot_logs_are_distinct_and_disk_is_identical(self):
        root = pathlib.Path('/tmp/a16')
        a = prepare.qemu_command(root, 'raw', 'block02')
        b = prepare.qemu_command(root, 'raw', 'block03')
        self.assertNotEqual(a[a.index('-serial') + 1], b[b.index('-serial') + 1])
        self.assertEqual(a[a.index('-drive') + 1], b[b.index('-drive') + 1])

    def test_invalid_mode_or_path_label_rejected(self):
        for mode, label in [('physical', 'one'), ('raw', '../one')]:
            with self.assertRaises(ValueError):
                prepare.qemu_command(pathlib.Path('/tmp/a16'), mode, label)


if __name__ == '__main__':
    unittest.main()
