import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Tools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-tools-test-')
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.config = self.home / 'config'
        self.config.mkdir()
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin) + ':/usr/bin:/bin',
                        DOTFILES_SOURCE=str(ROOT), DOTFILES_CONFIG=str(self.config),
                        DOTFILES_STATE=str(self.home / 'state'), DOTFILES_MODE='non-interactive')

    def run_shell(self, body):
        return subprocess.run(['/bin/sh', '-c', '. "$DOTFILES_SOURCE/lib/tools.sh"; ' + body],
                              env=self.env, text=True, capture_output=True, timeout=10)

    def test_selected_missing_tool_installs_without_prompt(self):
        (self.config / 'tools').write_text('symfony\n')
        result = self.run_shell('tools_install() { printf "installed:%s" "$1"; }; tools_ensure symfony')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'installed:symfony')

    def test_unselected_missing_tool_never_installs(self):
        (self.config / 'tools').write_text('ripgrep\n')
        result = self.run_shell('tools_install() { printf unexpected-install; }; tools_ensure symfony')
        self.assertEqual(result.returncode, 127, result.stderr)
        self.assertEqual(result.stdout, '')

    def test_unknown_tool_never_installs(self):
        result = self.run_shell('tools_install() { printf unexpected-install; }; tools_ensure arbitrary-unknown-tool')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')

    def test_noninteractive_privilege_uses_sudo_n(self):
        (self.bin / 'id').write_text('#!/bin/sh\nprintf "1000\\n"\n')
        (self.bin / 'sudo').write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 42\n')
        for path in self.bin.iterdir():
            path.chmod(0o755)
        result = self.run_shell('_tools_privileged fake-package-manager install fixture')
        self.assertEqual(result.returncode, 42)
        self.assertEqual(result.stdout, '-n\nfake-package-manager\ninstall\nfixture\n')

    def test_interactive_privilege_keeps_terminal_prompt(self):
        self.env['DOTFILES_MODE'] = 'interactive'
        (self.bin / 'id').write_text('#!/bin/sh\nprintf "1000\\n"\n')
        (self.bin / 'sudo').write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        for path in self.bin.iterdir():
            path.chmod(0o755)
        result = self.run_shell('_tools_privileged fake-package-manager install fixture')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'fake-package-manager\ninstall\nfixture\n')
