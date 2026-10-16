#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare a new A16 directory only. Never launches a VM, fixture, or unit."""
import hashlib
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE.parents[2]


def digest(path, algorithm='sha256'):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def call(command, **kwargs):
    return subprocess.run(command, check=True, timeout=120, **kwargs)


def qemu_command(output, mode, label):
    if mode not in ('raw', 'protected') or not label.isalnum():
        raise ValueError('fixed mode and alphanumeric boot label required')
    return ['qemu-system-aarch64', '-name', 'actryn-a16', '-machine', 'virt', '-accel', 'tcg',
            '-cpu', 'cortex-a72', '-smp', '2', '-m', '2048', '-display', 'none',
            '-kernel', str(output / 'boot/vmlinuz'), '-initrd', str(output / 'boot/initrd'),
            '-dtb', str(output / f'boot/{mode}.dtb'), '-append', 'root=/dev/vda1 rw console=ttyAMA0',
            '-drive', f'file={output}/disk.qcow2,format=qcow2,if=virtio',
            '-drive', f'file={output}/seed.iso,format=raw,if=virtio,readonly=on',
            '-netdev', 'user,id=net0,hostfwd=tcp:127.0.0.1:26224-:22,hostfwd=tcp:127.0.0.1:27446-:7443',
            '-device', 'virtio-net-pci,netdev=net0,mac=52:54:00:a1:60:24',
            '-serial', f'file:{output}/serial-{label}.log',
            '-chardev', f'socket,id=controller,path={output}/controller.sock', '-serial', 'chardev:controller',
            '-qmp', f'unix:{output}/qmp.sock,server=on,wait=off']


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: prepare.py ROOT_REPO_WITH_PINNED_CACHE')
    inputs = pathlib.Path(sys.argv[1]).resolve()
    output = inputs / '.cache/qemu/a16'
    manifest = tomllib.loads((HERE / 'manifest.toml').read_text())
    assert not output.exists(), 'existing attempts are never overwritten'
    assert not subprocess.check_output(['git', 'status', '--porcelain', '--', 'kernel',
                                       'targets/qemu-arm64-fixture/1/profile.toml'], cwd=SOURCE)
    assert digest(SOURCE / 'kernel/actryn_driver.c') == manifest['authority_source_sha256']
    assert digest(SOURCE / 'targets/qemu-arm64-fixture/1/profile.toml') == manifest['profile_sha256']
    for name, expected in manifest['baseline'].items():
        assert digest(SOURCE / name) == expected, name
    for port in (26224, 27446):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    version = subprocess.check_output(['qemu-system-aarch64', '--version'], text=True)
    assert version.splitlines()[0].endswith(' ' + manifest['vm']['qemu_version'])
    image = inputs / manifest['image']['path']
    assert digest(image, 'sha512') == manifest['image']['sha512']
    for asset in manifest['assets'].values():
        assert digest(inputs / asset['path']) == asset['sha256'], asset['path']
    assert shutil.disk_usage(inputs).free >= 8 * 1024**3
    os.umask(0o077)
    output.mkdir()
    try:
        (output / 'boot').mkdir()
        (output / 'bin').mkdir()
        (output / 'qualification').mkdir()
        shutil.copyfile(HERE / 'manifest.toml', output / 'manifest.toml')
        names = {'kernel': 'boot/vmlinuz', 'initrd': 'boot/initrd', 'raw_dtb': 'boot/raw.dtb',
                 'protected_dtb': 'boot/protected.dtb', 'fixture': 'bin/controller-fixture'}
        for name, asset in manifest['assets'].items():
            shutil.copyfile(inputs / asset['path'], output / names[name])
        (output / 'bin/controller-fixture').chmod(0o700)
        call(['qemu-img', 'convert', '-f', 'qcow2', '-O', 'qcow2', str(image), str(output / 'disk.qcow2')])
        call(['qemu-img', 'resize', str(output / 'disk.qcow2'), '16G'])
        call(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'actryn-a16-disposable',
              '-f', str(output / 'id_ed25519')], stdout=subprocess.DEVNULL)
        cloud = {'hostname': manifest['name'], 'disable_root': False, 'ssh_pwauth': False,
                 'users': [{'name': 'root', 'lock_passwd': True,
                            'ssh_authorized_keys': [(output / 'id_ed25519.pub').read_text().strip()]}]}
        (output / 'user-data').write_text('#cloud-config\n' + json.dumps(cloud) + '\n')
        (output / 'meta-data').write_text('instance-id: ' + manifest['instance_id'] +
                                        '\nlocal-hostname: ' + manifest['name'] + '\n')
        call(['xorriso', '-as', 'mkisofs', '-quiet', '-output', str(output / 'seed.iso'),
              '-volid', 'cidata', '-joliet', '-rock', str(output / 'user-data'), str(output / 'meta-data')])
        call(['git', 'archive', '--format=tar.gz', '--output=' + str(output / 'source.tar.gz'),
              'HEAD', 'kernel', 'targets/qemu-arm64-fixture/1/profile.toml'], cwd=SOURCE)
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()
        inventory = {'source_commit': commit, 'manifest_sha256': digest(output / 'manifest.toml'),
                     'source_sha256': digest(output / 'source.tar.gz'), 'qemu_version': version,
                     'base_image_sha512': manifest['image']['sha512'], 'launch_status': 'NOT_RUN'}
        (output / 'prepared.json').write_text(json.dumps(inventory, indent=2) + '\n')
        # Only command data is written. A later explicit root action selects the
        # mode and starts dedicated units after a fresh memory/port preflight.
        for mode, label in (('protected', 'provision01'), ('raw', 'pilot01'),
                            ('protected', 'block01'), ('raw', 'block02'),
                            ('raw', 'block03'), ('protected', 'block04')):
            (output / f'qemu-{label}.json').write_text(json.dumps(qemu_command(output, mode, label), indent=2) + '\n')
        fixture = [str(output / 'bin/controller-fixture'), '--socket', str(output / 'controller.sock'),
                   '--state', str(output / 'fixture.state'), '--admin', str(output / 'fixture-admin.sock')]
        (output / 'fixture-command.json').write_text(json.dumps(fixture, indent=2) + '\n')
        print('Prepared', output, '; no VM or fixture launched')
    except BaseException as error:
        (output / 'PREPARATION_FAILED').write_text(repr(error) + '\n')
        raise


if __name__ == '__main__':
    main()
