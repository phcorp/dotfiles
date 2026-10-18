"""Exercise ZLE with real keypresses in disposable terminal sessions."""
import errno
import fcntl
import struct
import termios
import time
import subprocess
import os
import pathlib
import pty
import re
import select
import shutil
import signal
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ZSH = shutil.which('zsh')
FZF = shutil.which('fzf')


@unittest.skipUnless(ZSH, 'zsh unavailable')
class ZshCompletion(unittest.TestCase):
    def shell(self, fuzzy=False, keymap='emacs'):
        temporary = tempfile.TemporaryDirectory(prefix='dotfiles-zle-')
        self.addCleanup(temporary.cleanup)
        home = pathlib.Path(temporary.name)
        config = home / '.config/dotfiles'
        shutil.copytree(ROOT / 'home/dot_config/dotfiles', config)
        binaries = home / 'bin'
        binaries.mkdir()
        if fuzzy:
            if not FZF:
                self.skipTest('fzf unavailable')
            (binaries / 'fzf').symlink_to(FZF)
        for name in ('Alpha One', 'Alpha Two', 'other-file'):
            (home / name).touch()
        # Stub discovery so optional prompt/runtime programs cannot affect ZLE.
        (home / '.zshrc').write_text('''
HISTFILE=/dev/null
_dotfiles_external_exists() { [[ $1 == fzf && -x $HOME/bin/fzf ]]; }
bindkey -'''+('v' if keymap == 'viins' else 'e')+'''
source "$XDG_CONFIG_HOME/dotfiles/zsh.sh"
PROMPT='READY> '
RPROMPT=''
KEYTIMEOUT=1
unset REPORTTIME
_dump_buffer() { print -r -- "" "BUFFER:$BUFFER:END"; zle redisplay; }
zle -N _dump_buffer
bindkey '^G' _dump_buffer
print -s -- 'git status'
print -s -- 'echo unrelated'
print -s -- 'git stash list'
''')
        pid, master = pty.fork()
        if pid == 0:
            os.chdir(home)
            environment = dict(os.environ, HOME=str(home), ZDOTDIR=str(home),
                               XDG_CONFIG_HOME=str(home / '.config'), TERM='xterm-256color',
                               PATH=str(binaries)+':/usr/bin:/bin', LC_ALL='C',
                               FZF_DEFAULT_OPTS='', FZF_DEFAULT_COMMAND='')
            os.execve(ZSH, [ZSH, '-d', '-i'], environment)
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
        def cleanup():
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(master)
            os.waitpid(pid, 0)
        self.addCleanup(cleanup)
        self.master = master
        self.pending = b''
        self.read_until(b'READY> ')
        return home

    def read_until(self, marker, timeout=10):
        deadline = time.monotonic() + timeout
        while marker not in self.pending:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                self.fail('terminal timed out: '+repr(self.pending[-3000:]))
            if select.select([self.master], [], [], remaining)[0]:
                try:
                    data = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    data = b''
                if not data:
                    self.fail('shell exited: '+repr(self.pending))
                if b'\x1b[6n' in data:
                    os.write(self.master, b'\x1b[1;1R')
                self.pending += data
        end = self.pending.index(marker)+len(marker)
        result, self.pending = self.pending[:end], self.pending[end:]
        return result

    def send(self, keys):
        os.write(self.master, keys)

    def buffer(self, keys, expected):
        self.send(keys+b'\x07')
        self.read_until(('BUFFER:'+expected+':END').encode())
        self.read_until(b'READY> ')

    def test_prefix_history_in_both_keymaps_and_arrow_sequences(self):
        for keymap in ('emacs', 'viins'):
            for up, down in ((b'\x1b[A', b'\x1b[B'), (b'\x1bOA', b'\x1bOB')):
                with self.subTest(keymap=keymap, up=up):
                    self.shell(keymap=keymap)
                    for keys, expected in (
                        (b'git s'+up, 'git stash list'),
                        (b'git s'+up+up, 'git status'),
                        (b'git s'+up+up+down, 'git stash list'),
                        (b'git s'+up+down, 'git s'),
                        (up, 'git stash list'),
                    ):
                        self.send(b'\x03')
                        self.read_until(b'READY> ')
                        self.buffer(keys, expected)

    def test_native_completion_without_fzf(self):
        self.shell()
        self.buffer(b'cat other-\t', 'cat other-file ')
        self.send(b'\x15print -r -- "MENU:$(zstyle -s \':completion:*\' menu value; print -r -- $value)"\n')
        self.read_until(b'MENU:select')

    def test_fuzzy_path_selection_and_cancellation(self):
        self.shell(fuzzy=True)
        self.send(b'cat alpha\t\t')
        self.read_until(b'2/2')
        self.send(b'Two')
        self.read_until(b'1/2')
        self.send(b'\r')
        self.read_until(b'READY> ')
        self.buffer(b'', 'cat Alpha\\ Two ')
        self.send(b'\x15cat Alpha\t\t')
        self.read_until(b'2/2')
        self.send(b'\x1b')
        self.read_until(b'READY> ')
        self.buffer(b'', 'cat Alpha\\ ')

    def test_fuzzy_git_branch_and_option_completion(self):
        home = self.shell(fuzzy=True)
        subprocess.run(['git', 'init', '-q', str(home)], check=True)
        subprocess.run(['git', '-C', str(home), '-c', 'user.name=fixture',
                        '-c', 'user.email=fixture@users.noreply.github.com',
                        '-c', 'core.hooksPath=/dev/null', 'commit', '--allow-empty',
                        '-qm', 'fixture'], check=True)
        for branch in ('feature-one', 'feature-two'):
            subprocess.run(['git', '-C', str(home), 'branch', branch], check=True)
        self.buffer(b'git --vers\t', 'git --version ')
        self.send(b'\x15git checkout feature-\t')
        listing = self.read_until(b' (0)')
        total = int(re.search(rb'(\d+)/(\d+) \(0\)', listing)[2])
        self.send(b'two')
        while True:
            listing = self.read_until(b' (0)')
            count = int(re.search(rb'(\d+)/(\d+) \(0\)', listing)[1])
            if count < total:
                break
        self.send(b'\r')
        self.read_until(b'READY> ')
        self.buffer(b'', 'git checkout feature-two ')
