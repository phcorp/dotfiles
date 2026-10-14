"""Flatpak lifecycle tests mock every external package operation."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = 'org.mozilla.firefox'


class FlatpakDesktop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-flatpak-test-')
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        for command in ('awk', 'cut', 'grep', 'mkdir', 'mktemp', 'id', 'chmod', 'cp', 'find', 'sed', 'head', 'tar', 'env', 'sh', 'cat', 'mv', 'touch', 'rmdir', 'rm', 'readlink', 'sha256sum', 'shasum', 'basename', 'dirname', 'sort'):
            executable = shutil.which(command)
            if executable:
                (self.bin / command).symlink_to(executable)
        source = self.home / 'source'
        source.mkdir()
        (source / 'catalog.tsv').write_text(
            'id\tcommand\tmacos\tapt\tdnf\tprofile\n'
            f'firefox\tfirefox\tcask:firefox\tflatpak:{APP}\tflatpak:{APP}\tdesktop\n')
        self.config = self.home / 'config'
        self.config.mkdir()
        self.state = self.home / 'state'
        self.state.mkdir()
        self.fake_state = self.home / 'flatpak-state.json'
        self.log = self.home / 'flatpak-calls.jsonl'
        self.fake_state.write_text(json.dumps({'user': [], 'system': [], 'remote': False}))
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin),
                        DOTFILES_SOURCE=str(source), DOTFILES_LIBRARY=str(ROOT / 'lib/tools.sh'),
                        DOTFILES_CONFIG=str(self.config), DOTFILES_STATE=str(self.state),
                        DOTFILES_BIN=str(self.bin), XDG_DATA_HOME=str(self.home / 'data'), DOTFILES_MODE='non-interactive',
                        DOTFILES_FLATPAK_STATE=str(self.fake_state), DOTFILES_FLATPAK_LOG=str(self.log))
        for name, body in [('uname', 'printf "Linux\\n"'), ('apt-get', 'exit 99'), ('dnf', 'exit 99'), ('sudo', 'exit 99')]:
            script = self.bin / name
            script.write_text('#!/bin/sh\n' + body + '\n')
            script.chmod(0o755)
        flatpak = self.bin / 'flatpak'
        flatpak.write_text('#!' + sys.executable + '\n' + '''import json, os, pathlib, sys
args = sys.argv[1:]
state_path = pathlib.Path(os.environ['DOTFILES_FLATPAK_STATE'])
state = json.loads(state_path.read_text())
with open(os.environ['DOTFILES_FLATPAK_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
action = next((arg for arg in args if arg in ('info', 'remotes', 'remote-add', 'install', 'update', 'uninstall', 'run')), '')
if os.environ.get('DOTFILES_FLATPAK_FAIL') == action:
    sys.exit(7)
scope = 'system' if '--system' in args else 'user'
if action == 'info':
    if args[-1] not in state[scope]:
        sys.exit(1)
    if '--show-origin' in args:
        print(os.environ.get('DOTFILES_FLATPAK_ORIGIN', 'flathub'))
    sys.exit(0)
elif action == 'remotes':
    if state['remote']:
        print('flathub\\t' + os.environ.get('DOTFILES_FLATPAK_REMOTE_URL', 'https://dl.flathub.org/repo/') + '\\t' + os.environ.get('DOTFILES_FLATPAK_REMOTE_OPTIONS', 'user'))
elif action == 'remote-add':
    state['remote'] = True
elif action == 'install':
    state[scope].append(args[-1])
elif action == 'update':
    if args[-1] not in state[scope]:
        sys.exit(1)
    if '--show-origin' in args:
        print(os.environ.get('DOTFILES_FLATPAK_ORIGIN', 'flathub'))
    sys.exit(0)
elif action == 'uninstall':
    if args[-1] not in state[scope]:
        sys.exit(1)
    state[scope].remove(args[-1])
elif action == 'run':
    app_index = args.index('org.mozilla.firefox')
    print('\\n'.join(args[app_index + 1:]))
else:
    sys.exit(99)
state_path.write_text(json.dumps(state))
''')
        flatpak.chmod(0o755)

    def shell(self, body):
        return subprocess.run(['/bin/sh', '-c', '. "$DOTFILES_LIBRARY"; ' + body],
                              env=self.env, cwd=self.home, text=True, capture_output=True, timeout=15)

    def operation(self, action, success=True):
        result = self.shell('tools_' + action + ' firefox')
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def calls(self, action=None):
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return [call for call in calls if action is None or action in call]

    def package_ledger(self):
        path = self.state / 'packages'
        return path.read_text() if path.exists() else ''

    def existing(self, scope):
        state = json.loads(self.fake_state.read_text())
        state[scope] = [APP]
        state['remote'] = True
        self.fake_state.write_text(json.dumps(state))

    def test_prefix_maps_to_flatpak_backend(self):
        result = self.shell('_tools_id=firefox; _tools_record=$(_tools_row firefox); _tools_manager; '
                            'printf "%s|%s" "$_tools_manager_name" "$_tools_package"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'flatpak|' + APP)

    def test_install_update_remove_use_user_scope_and_owned_app_only(self):
        self.operation('install')
        self.assertIn('firefox\tflatpak\t' + APP + '\tcreated-by-dotfiles', self.package_ledger())
        self.assertTrue((self.bin / 'firefox').is_file())
        self.operation('update')
        self.operation('remove')
        for action in ('remote-add', 'install', 'update', 'uninstall'):
            calls = self.calls(action)
            self.assertTrue(calls, action)
            for call in calls:
                self.assertIn('--user', call)
                self.assertNotIn('--system', call)
                self.assertNotIn('--unused', call)
        self.assertEqual(self.package_ledger(), '')
        self.assertFalse((self.bin / 'firefox').exists())

    def test_existing_user_app_is_preserved_without_package_ownership(self):
        self.existing('user')
        self.operation('install')
        self.assertEqual(self.package_ledger(), '')
        self.assertEqual(self.calls('install'), [])
        self.assertIn('--user', (self.bin / 'firefox').read_text())
        self.operation('update')
        self.assertEqual(self.package_ledger(), '')
        self.operation('remove', success=False)
        self.assertEqual(self.calls('uninstall'), [])

    def test_existing_system_app_is_preserved_without_package_ownership(self):
        self.existing('system')
        self.operation('install')
        self.assertEqual(self.package_ledger(), '')
        self.assertEqual(self.calls('install'), [])
        self.assertIn('--system', (self.bin / 'firefox').read_text())
        self.operation('update', success=False)
        self.assertEqual(self.calls('update'), [])
        self.operation('remove', success=False)
        self.assertEqual(self.calls('uninstall'), [])

    def test_install_failure_never_records_ownership_or_launcher(self):
        self.env['DOTFILES_FLATPAK_FAIL'] = 'install'
        self.operation('install', success=False)
        self.assertEqual(self.package_ledger(), '')
        self.assertTrue(self.calls('install'))
        self.assertFalse((self.bin / 'firefox').exists())

    def test_remote_failure_never_installs_or_records_ownership(self):
        self.env['DOTFILES_FLATPAK_FAIL'] = 'remote-add'
        self.operation('install', success=False)
        self.assertTrue(self.calls('remote-add'))
        self.assertEqual(self.package_ledger(), '')
        self.assertEqual(self.calls('install'), [])

    def test_untrusted_existing_remote_is_refused(self):
        self.env['DOTFILES_FLATPAK_REMOTE_URL'] = 'https://example.invalid/repo/'
        self.operation('install', success=False)
        self.assertEqual(self.calls('install'), [])
        self.assertEqual(self.package_ledger(), '')

    def test_remote_with_signature_verification_disabled_is_refused(self):
        self.env['DOTFILES_FLATPAK_REMOTE_OPTIONS'] = 'user,no-gpg-verify'
        self.operation('install', success=False)
        self.assertEqual(self.calls('install'), [])
        self.assertEqual(self.package_ledger(), '')

    def test_modified_launcher_survives_owned_app_removal(self):
        self.operation('install')
        launcher = self.bin / 'firefox'
        edited = launcher.read_text() + '\n# user customization\n'
        launcher.write_text(edited)
        self.operation('remove')
        self.assertEqual(launcher.read_text(), edited)
        self.assertEqual(self.package_ledger(), '')

    def test_existing_executable_is_never_overwritten(self):
        launcher = self.bin / 'firefox'
        original = '#!/bin/sh\nprintf "custom launcher\\n"\n'
        launcher.write_text(original)
        launcher.chmod(0o755)
        self.operation('install')
        self.assertEqual(launcher.read_text(), original)
        self.assertEqual(self.package_ledger(), '')
        self.assertEqual(self.calls('install'), [])

    def test_update_from_untrusted_origin_is_refused(self):
        self.existing('user')
        self.operation('install')
        self.env['DOTFILES_FLATPAK_ORIGIN'] = 'untrusted'
        self.operation('update', success=False)
        self.assertEqual(self.calls('update'), [])
        self.assertEqual(self.package_ledger(), '')

    def test_update_with_changed_remote_url_is_refused(self):
        self.operation('install')
        ledger = self.package_ledger()
        self.env['DOTFILES_FLATPAK_REMOTE_URL'] = 'https://example.invalid/repo/'
        self.operation('update', success=False)
        self.assertEqual(self.calls('update'), [])
        self.assertEqual(self.package_ledger(), ledger)

    def test_update_with_disabled_signature_verification_is_refused(self):
        self.operation('install')
        ledger = self.package_ledger()
        self.env['DOTFILES_FLATPAK_REMOTE_OPTIONS'] = 'user,no-gpg-verify'
        self.operation('update', success=False)
        self.assertEqual(self.calls('update'), [])
        self.assertEqual(self.package_ledger(), ledger)

    def test_stale_owned_launcher_reinstalls_missing_app(self):
        self.operation('install')
        state = json.loads(self.fake_state.read_text())
        state['user'] = []
        self.fake_state.write_text(json.dumps(state))
        self.operation('install')
        self.assertEqual(len(self.calls('install')), 2)
        self.assertEqual(json.loads(self.fake_state.read_text())['user'], [APP])
        self.assertEqual(sum(line.split('\t')[0] == 'firefox' for line in self.package_ledger().splitlines()), 1)

    def test_stale_system_launcher_refreshes_to_new_user_install(self):
        self.existing('system')
        self.operation('install')
        self.assertIn('--system', (self.bin / 'firefox').read_text())
        state = json.loads(self.fake_state.read_text())
        state['system'] = []
        self.fake_state.write_text(json.dumps(state))
        self.operation('install')
        self.assertIn('--user', (self.bin / 'firefox').read_text())
        self.assertNotIn('--system', (self.bin / 'firefox').read_text())
        self.assertIn('created-by-dotfiles', self.package_ledger())

    def test_unowned_removal_is_refused(self):
        self.operation('remove', success=False)
        self.assertEqual(self.calls('uninstall'), [])

    def test_launcher_preserves_arguments(self):
        self.operation('install')
        result = subprocess.run([str(self.bin / 'firefox'), 'two words', '*', '--flag'],
                                env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'two words\n*\n--flag\n')


class AppBatches(unittest.TestCase):
    def setUp(self):
        FlatpakDesktop.setUp(self)
        source = pathlib.Path(self.env['DOTFILES_SOURCE'])
        with (source / 'catalog.tsv').open('a') as catalog:
            catalog.write('code\tcode\tcask:visual-studio-code\tflatpak:com.visualstudio.code\tflatpak:com.visualstudio.code\tdesktop\n')
            catalog.write('ripgrep\trg\tripgrep\tripgrep\tripgrep\tshell\n')
        self.env.update(DOTFILES_CORE=str(ROOT / 'lib/core.sh'), DOTFILES_FORCE='0',
                        DOTFILES_DRY_RUN='0', DOTFILES_PROFILES='', DOTFILES_SYNC_ENABLE='0',
                        XDG_CONFIG_HOME=str(self.home / 'config'), XDG_STATE_HOME=str(self.home / 'state'))

    def run_batch(self, command, mocks=''):
        body = '. "$DOTFILES_CORE"; . "$DOTFILES_LIBRARY"; ' + mocks + '; ' + command
        return subprocess.run(['/bin/sh', '-c', body], env=self.env, cwd=self.home,
                              capture_output=True, text=True, timeout=10)

    def test_install_all_uses_only_selected_desktop_apps(self):
        (self.config / 'tools').write_text('firefox\nripgrep\n')
        result = self.run_batch('apps_action install all',
                                'tools_install() { printf "install:%s\\n" "$1"; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'install:firefox\n')

    def test_update_failure_is_reported_and_remaining_apps_are_attempted(self):
        (self.config / 'tools').write_text('firefox\ncode\nripgrep\n')
        result = self.run_batch('apps_action update all',
                                'tools_update() { printf "update:%s\\n" "$1"; [ "$1" != firefox ]; }')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, 'update:firefox\nupdate:code\n')

    def test_remove_all_uses_owned_desktop_ledger_not_selection(self):
        (self.config / 'tools').write_text('code\nripgrep\n')
        (self.state / 'packages').write_text(
            f'firefox\tflatpak\t{APP}\tcreated-by-dotfiles\n'
            'code\tflatpak\tcom.visualstudio.code\tpreexisting\n'
            'ripgrep\tapt\tripgrep\tcreated-by-dotfiles\n')
        result = self.run_batch('apps_action remove all',
                                'tools_remove() { printf "remove:%s\\n" "$1"; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'remove:firefox\n')

    def test_explicit_app_is_allowed_without_saved_selection(self):
        result = self.run_batch('main apps install code --non-interactive',
                                'tools_install() { printf "install:%s\\n" "$1"; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'install:code\n')

    def test_non_desktop_explicit_tool_is_refused(self):
        result = self.run_batch('apps_action install ripgrep',
                                'tools_install() { printf unexpected-install; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_list_contains_desktop_apps_and_excludes_shell_tools(self):
        result = self.run_batch('main apps list --non-interactive', 'true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('firefox\t', result.stdout)
        self.assertIn('code\t', result.stdout)
        self.assertNotIn('ripgrep\t', result.stdout)

    def test_cli_dry_run_never_invokes_app_operation(self):
        result = self.run_batch('main apps remove firefox --non-interactive --dry-run',
                                'tools_remove() { printf unexpected-removal; return 7; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Dry run: apps remove firefox', result.stdout)
        self.assertNotIn('unexpected-removal', result.stdout)


class NativeDesktop(unittest.TestCase):
    def setUp(self):
        FlatpakDesktop.setUp(self)
        source = pathlib.Path(self.env['DOTFILES_SOURCE'])
        (source / 'lib').mkdir()
        self.env['DOTFILES_DESKTOP_LIBRARY'] = str(ROOT / 'lib/tools-desktop.sh')
        self.env['DOTFILES_TEST_PLATFORM'] = 'Linux'
        self.env['DOTFILES_PACKAGE_LOG'] = str(self.home / 'package-calls.log')
        self.env['DOTFILES_NATIVE_INSTALLED'] = str(self.home / 'installed')
        self.fingerprint = 'A' * 40
        self.env['DOTFILES_TEST_FINGERPRINT'] = self.fingerprint
        payload = b'fixture-package\n'
        import hashlib
        checksum = hashlib.sha256(payload).hexdigest()
        (source / 'lib/tools-desktop.tsv').write_text(
            'id\tbackend\tarch\tversion\turl\tsha256\tpackage\tcommand\trepository\tsignature\tkey\tfingerprint\n'
            f'chatgpt\tdeb\tamd64\t1\thttps://example.invalid/package.deb\t{checksum}\tchatgpt\tchatgpt\thttps://example.invalid/InRelease\t-\tkey.asc\t{self.fingerprint}\n')
        (source / 'key.asc').write_text('fixture public key\n')
        (source / 'catalog.tsv').write_text(
            'id\tcommand\tmacos\tapt\tdnf\tprofile\n'
            'chatgpt\tchatgpt\tcask:chatgpt\tdesktop:chatgpt\tdesktop:chatgpt\tdesktop\n'
            'mutekey\tmutekey\tmas:1509590766\t-\t-\tdesktop\n')
        (self.bin / 'uname').write_text('#!/bin/sh\ncase "$1" in -s) printf "%s\\n" "$DOTFILES_TEST_PLATFORM" ;; -m) printf "x86_64\\n" ;; esac\n')
        dpkg = self.bin / 'dpkg-query'
        dpkg.write_text('#!/bin/sh\n[ -f "$DOTFILES_NATIVE_INSTALLED" ] || exit 1\nprintf "install ok installed"\n')
        dpkg.chmod(0o755)
        cache = self.bin / 'apt-cache'
        cache.write_text('#!/bin/sh\nprintf "chatgpt\nReverse Depends:\n"\n')
        cache.chmod(0o755)
        compare = self.bin / 'dpkg'
        compare.write_text('#!/bin/sh\nexit 1\n')
        compare.chmod(0o755)
        gpg = self.bin / 'gpg'
        gpg.write_text('#!/bin/sh\nfor arg do\ncase "$arg" in\n--show-keys) printf "fpr:::::::::%s:\\n" "$DOTFILES_TEST_FINGERPRINT"; exit 0 ;;\n--verify) [ "${DOTFILES_SIGNATURE_FAIL:-0}" != 1 ]; exit $? ;;\nesac\ndone\nexit 0\n')
        gpg.chmod(0o755)
        gpgv = self.bin / 'gpgv'
        gpgv.write_text('#!/bin/sh\n[ "${DOTFILES_SIGNATURE_FAIL:-0}" != 1 ]\n')
        gpgv.chmod(0o755)
        mas = self.bin / 'mas'
        mas.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DOTFILES_PACKAGE_LOG"\nif [ "$1" = list ]; then [ "${DOTFILES_MAS_EXISTING:-0}" != 1 ] || printf "1509590766 MuteKey (1)\\n"; fi\n')
        mas.chmod(0o755)
        self.overrides = '''
_desktop_distro_supported() { return 0; }
desktop_exists() {
    case $1 in
        mutekey) if [ "$(uname -s)" = Darwin ]; then [ "${DOTFILES_MAS_EXISTING:-0}" = 1 ]; else [ -x "$DOTFILES_BIN/mutekey" ]; fi ;;
        chatgpt) [ -f "$DOTFILES_NATIVE_INSTALLED" ] ;;
        *) return 1 ;;
    esac
}
_desktop_download() { printf 'fixture-package\\n' > "$2"; }
_tools_apt_guard() {
    printf '%s\\n' "$*" >> "$DOTFILES_PACKAGE_LOG"
    : > "$DOTFILES_NATIVE_INSTALLED"
    printf '#!/bin/sh\\nexit 0\\n' > "$DOTFILES_BIN/chatgpt"
    chmod +x "$DOTFILES_BIN/chatgpt"
}
_tools_privileged() {
    printf '%s\\n' "$*" >> "$DOTFILES_PACKAGE_LOG"
    case "$*" in *'apt-get remove'*) rm -f "$DOTFILES_NATIVE_INSTALLED" "$DOTFILES_BIN/chatgpt" ;; esac
}
'''

    def shell(self, body):
        script = '. "$DOTFILES_LIBRARY"; . "$DOTFILES_DESKTOP_LIBRARY"; ' + self.overrides + '\n' + body
        return subprocess.run(['/bin/sh', '-c', script], env=self.env, cwd=self.home,
                              capture_output=True, text=True, timeout=15)

    def ledger(self):
        path = self.state / 'packages'
        return path.read_text() if path.exists() else ''

    def package_calls(self):
        path = pathlib.Path(self.env['DOTFILES_PACKAGE_LOG'])
        return path.read_text() if path.exists() else ''

    def test_existing_mas_app_requires_no_install_or_ownership(self):
        self.env['DOTFILES_TEST_PLATFORM'] = 'Darwin'
        self.env['DOTFILES_MAS_EXISTING'] = '1'
        result = self.shell('desktop_change mutekey install')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ledger(), '')
        self.assertNotIn('get ', self.package_calls())

    def test_unowned_mas_removal_is_refused(self):
        self.env['DOTFILES_TEST_PLATFORM'] = 'Darwin'
        self.env['DOTFILES_MAS_EXISTING'] = '1'
        result = self.shell('desktop_change mutekey uninstall')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('uninstall', self.package_calls())

    def test_missing_mas_app_noninteractive_fails_without_authentication_prompt(self):
        self.env['DOTFILES_TEST_PLATFORM'] = 'Darwin'
        result = self.shell('desktop_change mutekey install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('authentication', result.stderr)
        self.assertEqual(self.ledger(), '')
        self.assertNotIn('get ', self.package_calls())

    def test_repository_signature_failure_prevents_package_install(self):
        self.env['DOTFILES_SIGNATURE_FAIL'] = '1'
        result = self.shell('desktop_change chatgpt install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('signature verification failed', result.stderr)
        self.assertFalse(any(line.startswith('install ') or 'apt-get install' in line for line in self.package_calls().splitlines()))
        self.assertEqual(self.ledger(), '')
        self.assertFalse(pathlib.Path(self.env['DOTFILES_NATIVE_INSTALLED']).exists())

    def test_repository_key_fingerprint_failure_prevents_package_install(self):
        self.env['DOTFILES_TEST_FINGERPRINT'] = 'B' * 40
        result = self.shell('desktop_change chatgpt install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fingerprint mismatch', result.stderr)
        self.assertFalse(any(line.startswith('install ') or 'apt-get install' in line for line in self.package_calls().splitlines()))
        self.assertEqual(self.ledger(), '')

    def test_native_package_checksum_failure_prevents_install(self):
        self.overrides += "\n_desktop_download() { printf corrupted > \"$2\"; }\n"
        result = self.shell('desktop_change chatgpt install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertFalse(any(line.startswith('install ') or 'apt-get install' in line for line in self.package_calls().splitlines()))
        self.assertEqual(self.ledger(), '')

    def test_existing_native_package_is_not_adopted_or_reinstalled(self):
        pathlib.Path(self.env['DOTFILES_NATIVE_INSTALLED']).touch()
        result = self.shell('desktop_change chatgpt install')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.package_calls(), '')
        self.assertEqual(self.ledger(), '')

    def test_native_owned_package_install_upgrade_and_remove(self):
        result = self.shell('tools_install chatgpt; tools_update chatgpt; tools_remove chatgpt')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.package_calls().splitlines()
        self.assertEqual(sum(line.startswith('install ') for line in calls), 2)
        self.assertTrue(any('apt-get remove -y chatgpt' in line for line in calls))
        self.assertEqual(self.ledger(), '')
        self.assertFalse(pathlib.Path(self.env['DOTFILES_NATIVE_INSTALLED']).exists())


class MicrophoneHelper(unittest.TestCase):
    def setUp(self):
        NativeDesktop.setUp(self)
        source = pathlib.Path(self.env['DOTFILES_SOURCE'])
        (source / 'catalog.tsv').write_text(
            'id\tcommand\tmacos\tapt\tdnf\tprofile\n'
            'mutekey\tmutekey\tmas:1509590766\tdesktop:mutekey\tdesktop:mutekey\tdesktop\n')
        self.audio_log = self.home / 'audio-calls.log'
        self.env['DOTFILES_AUDIO_LOG'] = str(self.audio_log)
        wpctl = self.bin / 'pactl'
        wpctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DOTFILES_AUDIO_LOG"\n')
        wpctl.chmod(0o755)

    shell = NativeDesktop.shell

    def test_install_update_remove_never_toggles_microphone(self):
        result = self.shell('tools_install mutekey; tools_update mutekey; tools_remove mutekey')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.audio_log.exists())
        self.assertFalse((self.bin / 'mutekey').exists())
        self.assertFalse((self.home / 'data/applications/dotfiles-mutekey.desktop').exists())

    def test_microphone_toggles_only_when_helper_is_invoked(self):
        result = self.shell('tools_install mutekey')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.audio_log.exists())
        helper = self.bin / 'mutekey'
        result = subprocess.run([str(helper)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.audio_log.read_text(), 'set-source-mute @DEFAULT_SOURCE@ toggle\n')

    def test_modified_microphone_helper_is_preserved(self):
        result = self.shell('tools_install mutekey')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        helper = self.bin / 'mutekey'
        edited = helper.read_text() + '# user customization\n'
        helper.write_text(edited)
        result = self.shell('tools_remove mutekey')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(helper.read_text(), edited)
        self.assertFalse(self.audio_log.exists())
        self.assertTrue((self.home / 'data/applications/dotfiles-mutekey.desktop').exists())


class AppImageDesktop(unittest.TestCase):
    def setUp(self):
        NativeDesktop.setUp(self)
        import hashlib
        self.payload = self.home / 'appimage-fixture'
        self.payload.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        self.payload.chmod(0o755)
        self.env['DOTFILES_APPIMAGE_FIXTURE'] = str(self.payload)
        self.env['DOTFILES_STATE'] = str(self.home / "state with ' quote")
        pathlib.Path(self.env['DOTFILES_STATE']).mkdir()
        self.state = pathlib.Path(self.env['DOTFILES_STATE'])
        source = pathlib.Path(self.env['DOTFILES_SOURCE'])
        (source / 'catalog.tsv').write_text(
            'id\tcommand\tmacos\tapt\tdnf\tprofile\n'
            'hoppscotch\thoppscotch\tcask:hoppscotch\tdesktop:hoppscotch\tdesktop:hoppscotch\tdesktop\n')
        (source / 'lib/tools-desktop.tsv').write_text(
            'id\tbackend\tarch\tversion\turl\tsha256\tpackage\tcommand\trepository\tsignature\tkey\tfingerprint\n'
            'hoppscotch\tappimage\tamd64\t1\thttps://example.invalid/app.AppImage\t' +
            hashlib.sha256(self.payload.read_bytes()).hexdigest() + '\thoppscotch\thoppscotch\t-\t-\t-\t-\n')
        (self.bin / 'apt-get').unlink()
        self.overrides += '''
_desktop_download() { cp "$DOTFILES_APPIMAGE_FIXTURE" "$2"; }
desktop_exists() { [ -f "$DOTFILES_STATE/desktop/hoppscotch.AppImage" ] && [ -x "$DOTFILES_BIN/hoppscotch" ]; }
'''

    shell = NativeDesktop.shell

    def install(self):
        result = self.shell('tools_install hoppscotch')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_appimage_lifecycle_preserves_quoting_and_arguments(self):
        self.install()
        result = subprocess.run([str(self.bin / 'hoppscotch'), 'two words', '*'],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '--appimage-extract-and-run\ntwo words\n*\n')
        result = self.shell('tools_update hoppscotch; tools_remove hoppscotch')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.bin / 'hoppscotch').exists())
        self.assertFalse((self.state / 'desktop/hoppscotch.AppImage').exists())

    def test_modified_appimage_launcher_is_preserved_on_removal(self):
        self.install()
        launcher = self.bin / 'hoppscotch'
        edited = launcher.read_text() + '# user customization\n'
        launcher.write_text(edited)
        result = self.shell('tools_remove hoppscotch')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(launcher.read_text(), edited)
        self.assertTrue((self.state / 'desktop/hoppscotch.AppImage').exists())

    def test_modified_appimage_payload_is_preserved_on_update(self):
        self.install()
        image = self.state / 'desktop/hoppscotch.AppImage'
        edited = image.read_text() + '# user customization\n'
        image.write_text(edited)
        result = self.shell('tools_update hoppscotch')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(image.read_text(), edited)
        self.assertTrue((self.bin / 'hoppscotch').exists())


class CodexBarTransactions(unittest.TestCase):
    def setUp(self):
        FlatpakDesktop.setUp(self)
        self.env['DOTFILES_CODEXBAR_LIBRARY'] = str(ROOT / 'lib/tools-codexbar.sh')
        (self.bin / 'uname').write_text('#!/bin/sh\ncase "$1" in -s) printf "Linux\\n" ;; -m) printf "x86_64\\n" ;; esac\n')
        for command in ('cmp', 'wc'):
            executable = shutil.which(command)
            if executable:
                (self.bin / command).symlink_to(executable)
        self.root = self.home / 'data/dotfiles/apps/codexbar'
        self.overrides = '''
_codexbar_desktop_supported() { return 1; }
_codexbar_download() {
    mkdir -p "$_cb_work/$1/bundle/resources" || return
    printf '#!/bin/sh\\nprintf "%%s\\n" "%s"\\n' "${DOTFILES_CODEXBAR_VERSION:-original}" > "$_cb_work/$1/bundle/CodexBarCLI"
    chmod +x "$_cb_work/$1/bundle/CodexBarCLI"
    printf 'bundled resource\\n' > "$_cb_work/$1/bundle/resources/notice"
}
if [ "${DOTFILES_CODEXBAR_FAIL_LAUNCHER:-0}" = 1 ]; then
    _codexbar_write_launcher() { return 7; }
fi
'''

    def change(self, action):
        body = '. "$DOTFILES_LIBRARY"; . "$DOTFILES_CODEXBAR_LIBRARY"; ' + self.overrides + '\ncodexbar_change codexbar ' + action
        return subprocess.run(['/bin/sh', '-c', body], env=self.env, cwd=self.home,
                              capture_output=True, text=True, timeout=15)

    def install(self):
        result = self.change('install')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_failed_upgrade_restores_payload_launchers_and_manifest(self):
        self.install()
        payload = self.root / 'cli/bundle/CodexBarCLI'
        launcher = self.bin / 'codexbar'
        manifest = self.state / 'codexbar-manifest.tsv'
        before = (payload.read_bytes(), launcher.read_bytes(), manifest.read_bytes())
        self.env.update(DOTFILES_CODEXBAR_VERSION='replacement', DOTFILES_CODEXBAR_FAIL_LAUNCHER='1')
        result = self.change('upgrade')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((payload.read_bytes(), launcher.read_bytes(), manifest.read_bytes()), before)
        self.assertEqual((self.root / 'cli/bundle/resources/notice').read_text(), 'bundled resource\n')

    def test_edited_launcher_survives_upgrade_and_uninstall(self):
        self.install()
        launcher = self.bin / 'codexbar'
        edited = launcher.read_text() + '# user customization\n'
        launcher.write_text(edited)
        for action in ('upgrade', 'uninstall'):
            result = self.change(action)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(launcher.read_text(), edited)
            self.assertTrue((self.root / 'cli/bundle/CodexBarCLI').exists())

    def test_edited_payload_survives_uninstall(self):
        self.install()
        resource = self.root / 'cli/bundle/resources/notice'
        resource.write_text('user resource customization\n')
        result = self.change('uninstall')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(resource.read_text(), 'user resource customization\n')
        self.assertTrue((self.bin / 'codexbar').exists())


class MacDesktopRepair(unittest.TestCase):
    def setUp(self):
        FlatpakDesktop.setUp(self)
        source = pathlib.Path(self.env['DOTFILES_SOURCE'])
        (source / 'catalog.tsv').write_text(
            'id\tcommand\tmacos\tapt\tdnf\tprofile\n'
            'fixture-desktop\tfixture-desktop\tcask:fixture-desktop\t-\t-\tdesktop\n')
        (self.bin / 'uname').write_text('#!/bin/sh\nprintf "Darwin\\n"\n')
        self.log = self.home / 'brew-calls.log'
        self.env['DOTFILES_BREW_LOG'] = str(self.log)
        brew = self.bin / 'brew'
        brew.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$DOTFILES_BREW_LOG"
case $1 in
    list) exit 0 ;;
    reinstall)
        printf '#!/bin/sh\\nexit 0\\n' > "$DOTFILES_BIN/fixture-desktop"
        chmod +x "$DOTFILES_BIN/fixture-desktop"
        exit 0 ;;
    *) exit 7 ;;
esac
''')
        brew.chmod(0o755)

    def test_registered_cask_with_missing_command_is_repaired_without_adoption(self):
        result = subprocess.run(['/bin/sh', '-c', '. "$DOTFILES_LIBRARY"; tools_install fixture-desktop'],
                                env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('reinstall --cask fixture-desktop', self.log.read_text())
        self.assertNotIn('\ninstall ', '\n' + self.log.read_text())
        self.assertTrue((self.bin / 'fixture-desktop').is_file())
        ledger = self.state / 'packages'
        self.assertFalse(ledger.exists() and ledger.read_text())
