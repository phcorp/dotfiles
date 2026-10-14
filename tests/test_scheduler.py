import os
import pathlib
import plistlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Scheduler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-scheduler-test-')
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name) / 'home with spaces'
        self.home.mkdir()
        config = self.home / 'alternate config'
        state = self.home / 'alternate state'
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(config),
                        XDG_STATE_HOME=str(state), DOTFILES_CONFIG=str(config / 'dotfiles'),
                        DOTFILES_STATE=str(state / 'dotfiles'), DOTFILES_SOURCE=str(ROOT),
                        DOTFILES_MODE='non-interactive', DOTFILES_TESTING='1')
        self.cli('install', '--non-interactive', '--profiles', 'shell')
        self.bin = self.home / 'fixture-bin'
        self.bin.mkdir()
        uname = self.bin / 'uname'
        uname.write_text('#!/bin/sh\nif [ "$1" = -s ]; then printf "%s\\n" "$DOTFILES_TEST_PLATFORM"; else exec /usr/bin/uname "$@"; fi\n')
        uname.chmod(0o755)
        self.log = self.home / 'scheduler.log'
        self.env['DOTFILES_SCHEDULER_LOG'] = str(self.log)
        for name in ('launchctl', 'systemctl'):
            script = self.bin / name
            script.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DOTFILES_SCHEDULER_LOG"\nexit 0\n')
            script.chmod(0o755)
        self.env['PATH'] = str(self.bin) + ':' + self.env['PATH']

    def cli(self, *args, check=True):
        result = subprocess.run([str(ROOT / 'bin/dotfiles'), *args], env=self.env,
                                cwd=self.home, text=True, capture_output=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def outside(self):
        outside = pathlib.Path(self.tmp.name) / 'outside'
        outside.mkdir()
        sentinel = outside / 'sentinel'
        sentinel.write_text('preserve\n')
        return outside, sentinel

    def test_macos_relocated_environment_is_preserved(self):
        self.env['DOTFILES_TEST_PLATFORM'] = 'Darwin'
        self.cli('sync', 'enable', '--non-interactive')
        path = self.home / 'Library/LaunchAgents/com.phcorp.dotfiles.plist'
        with path.open('rb') as source:
            plist = plistlib.load(source)
        for key in ('HOME', 'DOTFILES_SOURCE', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'DOTFILES_CONFIG', 'DOTFILES_STATE'):
            self.assertEqual(plist['EnvironmentVariables'][key], self.env[key])
        self.assertIn('bootstrap', self.log.read_text())

    def test_linux_relocated_environment_is_preserved(self):
        self.env['DOTFILES_TEST_PLATFORM'] = 'Linux'
        self.cli('sync', 'enable', '--non-interactive')
        service = pathlib.Path(self.env['XDG_CONFIG_HOME']) / 'systemd/user/dotfiles-sync.service'
        content = service.read_text()
        for key in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'DOTFILES_CONFIG', 'DOTFILES_STATE'):
            self.assertIn(f'{key}={self.env[key]}', content)
        self.assertIn('enable --now dotfiles-sync.timer', self.log.read_text())

    def test_macos_symlink_plist_is_rejected(self):
        self.env['DOTFILES_TEST_PLATFORM'] = 'Darwin'
        outside, sentinel = self.outside()
        path = self.home / 'Library/LaunchAgents/com.phcorp.dotfiles.plist'
        path.parent.mkdir(parents=True)
        path.symlink_to(sentinel)
        result = self.cli('sync', 'enable', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), 'preserve\n')
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['sentinel'])
        self.assertFalse(self.log.exists())

    def test_linux_symlink_jobs_are_rejected(self):
        self.env['DOTFILES_TEST_PLATFORM'] = 'Linux'
        outside, sentinel = self.outside()
        jobs = pathlib.Path(self.env['XDG_CONFIG_HOME']) / 'systemd/user'
        jobs.mkdir(parents=True)
        for name in ('dotfiles-sync.service', 'dotfiles-sync.timer'):
            with self.subTest(path=name):
                path = jobs / name
                if path.exists():
                    path.unlink()
                path.symlink_to(sentinel)
                result = self.cli('sync', 'enable', '--non-interactive', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sentinel.read_text(), 'preserve\n')
                self.assertEqual(sorted(p.name for p in outside.iterdir()), ['sentinel'])
                path.unlink()

    def test_macos_symlink_parent_is_rejected(self):
        self.env['DOTFILES_TEST_PLATFORM'] = 'Darwin'
        outside, sentinel = self.outside()
        library = self.home / 'Library'
        library.mkdir()
        (library / 'LaunchAgents').symlink_to(outside, target_is_directory=True)
        result = self.cli('sync', 'enable', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), 'preserve\n')
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['sentinel'])
        self.assertFalse(self.log.exists())

    def test_linux_symlink_parent_is_rejected(self):
        self.env['DOTFILES_TEST_PLATFORM'] = 'Linux'
        outside, sentinel = self.outside()
        parent = pathlib.Path(self.env['XDG_CONFIG_HOME']) / 'systemd'
        parent.mkdir()
        (parent / 'user').symlink_to(outside, target_is_directory=True)
        result = self.cli('sync', 'enable', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), 'preserve\n')
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['sentinel'])
