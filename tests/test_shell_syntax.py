import pathlib
import shutil
import sys
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ShellSyntax(unittest.TestCase):
    def test_portable_scripts(self):
        files = [ROOT / 'bootstrap.sh', ROOT / 'bin/dotfiles']
        files += list((ROOT / 'lib').glob('*.sh'))
        files += list((ROOT / 'scripts').glob('*.sh'))
        for path in files:
            if path.exists():
                with self.subTest(path=str(path.relative_to(ROOT))):
                    result = subprocess.run(['sh', '-n', str(path)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_shell_entrypoints(self):
        for shell, names in [('bash', ['dot_bashrc', 'dot_bash_profile', 'dot_profile']),
                             ('zsh', ['dot_zshrc', 'dot_zprofile'])]:
            executable = '/bin/bash' if shell == 'bash' and sys.platform == 'darwin' else shutil.which(shell)
            if not executable:
                continue
            for name in names:
                path = ROOT / 'home' / name
                if path.exists():
                    with self.subTest(shell=shell, path=name):
                        result = subprocess.run([executable, '-n', str(path)], capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
