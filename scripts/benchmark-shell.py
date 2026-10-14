#!/usr/bin/env python3
"""Benchmark disposable shell startup and prompts without sourcing private config."""
import argparse
import json
import math
import os
import pathlib
import platform
import re
import shutil
import statistics
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


def executable(name):
    return shutil.which(name)


def measure(argv, environment, cwd, samples, warmups):
    values = []
    failures = 0
    for index in range(samples + warmups):
        start = time.perf_counter_ns()
        run = subprocess.run(argv, env=environment, cwd=cwd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, timeout=30)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        failures += run.returncode != 0
        if index >= warmups:
            values.append(elapsed)
    ordered = sorted(values)
    return dict(median_ms=round(statistics.median(values), 2),
                p95_ms=round(ordered[math.ceil(0.95 * len(ordered)) - 1], 2),
                samples=samples, failures=failures)


def stage(home, nvm, rvm, real_home, binary_paths):
    config = home / '.config/dotfiles'
    config.mkdir(parents=True)
    for source in (ROOT / 'home/dot_config/dotfiles').glob('*'):
        if source.is_file():
            target_name = source.name.removeprefix('executable_')
            shutil.copyfile(source, config / target_name)
            if source.name.startswith('executable_'):
                (config / target_name).chmod(0o700)
    shutil.copyfile(ROOT / 'home/dot_config/starship.toml', home / '.config/starship.toml')
    for name in ['.bashrc', '.zshrc', '.zshenv']:
        source = ROOT / 'home' / ('dot_' + name[1:])
        if source.is_file():
            shutil.copyfile(source, home / name)
    binaries = home / '.local/bin'
    binaries.mkdir(parents=True)
    for name, source in binary_paths.items():
        if source:
            (binaries / name).symlink_to(source)
    # Suppress unrelated installed pyenv integration without invoking user hooks.
    (binaries / 'pyenv').write_text('#!/bin/sh\nexit 0\n')
    (binaries / 'pyenv').chmod(0o700)
    if nvm:
        source = real_home / '.nvm'
        target = home / '.nvm'
        target.mkdir()
        for name in ['nvm.sh', 'nvm-exec']:
            if (source / name).is_file():
                shutil.copyfile(source / name, target / name)
        # Code and aliases are read-only inputs; activation writes only fixture HOME.
        if (source / 'alias').is_dir():
            shutil.copytree(source / 'alias', target / 'alias', symlinks=False)
        if (source / 'versions').is_dir():
            (target / 'versions').symlink_to(source / 'versions', target_is_directory=True)
    if rvm:
        source = real_home / '.rvm'
        target = home / '.rvm'
        target.mkdir()
        for name in ['scripts', 'config', 'bin']:
            if (source / name).is_dir():
                shutil.copytree(source / name, target / name, symlinks=False,
                                ignore=shutil.ignore_patterns('user') if name == 'config' else None)
        # Never source /etc/rvmrc, user rc, project hooks, or private runtime defaults.
        script = target / 'scripts/rvm'
        if script.is_file():
            text = script.read_text()
            text = text.replace('rvm_rvmrc_files=("/etc/rvmrc" "$HOME/.rvmrc")',
                                'rvm_rvmrc_files=("$HOME/.rvmrc")')
            script.write_text(text)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=('all', 'startup', 'prompts'), default='all')
    parser.add_argument('--samples', type=int, default=20)
    parser.add_argument('--warmups', type=int, default=3)
    args = parser.parse_args()
    if args.samples < 15 or args.warmups < 1:
        parser.error('Use at least 15 samples and one warmup.')
    real_home = pathlib.Path.home()
    shell_paths = [path for path in ['/bin/bash', '/bin/zsh'] if pathlib.Path(path).exists()]
    binary_paths = {name: executable(name) for name in ['starship', 'node', 'python3']}
    shell_versions = {pathlib.Path(shell).name: subprocess.check_output([shell, '--version'], text=True).splitlines()[0] for shell in shell_paths}
    manager_versions = {}
    nvm_script = real_home / '.nvm/nvm.sh'
    if nvm_script.is_file():
        match = re.search(r'(?m)^\s*["\']?--version["\']?.*\n\s*nvm_echo ["\']([0-9]+\.[0-9]+\.[0-9]+)["\']', nvm_script.read_text())
        manager_versions['nvm'] = match.group(1) if match else 'unknown'
    rvm_version = real_home / '.rvm/VERSION'
    if rvm_version.is_file():
        match = re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?', rvm_version.read_text().strip())
        manager_versions['rvm'] = match.group(0) if match else 'unknown'
    results = dict(samples=args.samples, warmups=args.warmups, shell_versions=shell_versions,
                   manager_versions=manager_versions, python_version=platform.python_version(),
                   host=dict(os=platform.system(), arch=platform.machine()),
                   constraints=['Private shell configuration is never sourced.',
                                'NVM code/aliases staged; existing Node executables read only.',
                                'RVM core code staged without private defaults/project hooks.',
                                'NVM --no-use reference changes activation behavior; not a default replacement.',
                                'No application installs, real HOME writes, or account output.'],
                   startup=[], prompts=[])
    with tempfile.TemporaryDirectory(prefix='dotfiles-shell-benchmark-') as directory:
        workspace = pathlib.Path(directory)
        variants = [('managed-no-managers', False, False)]
        if (real_home / '.nvm/nvm.sh').is_file():
            variants.append(('managed-nvm', True, False))
        if (real_home / '.rvm/scripts/rvm').is_file():
            variants.append(('managed-rvm-core', False, True))
        if len(variants) == 3:
            variants.append(('managed-both', True, True))
        if (real_home / '.nvm/nvm.sh').is_file():
            variants.append(('managed-nvm-no-use-reference', True, False))
        if args.only == 'prompts':
            variants = [('managed-no-managers', False, False)]
        for name, nvm, rvm in variants:
            home = workspace / name
            home.mkdir()
            config = stage(home, nvm, rvm, real_home, binary_paths)
            if name == 'managed-nvm-no-use-reference':
                helper = config / 'interactive.sh'
                helper.write_text(helper.read_text().replace('. "$NVM_DIR/nvm.sh"', '. "$NVM_DIR/nvm.sh" --no-use'))
            environment = dict(HOME=str(home), PATH=str(home / '.local/bin') + ':/usr/bin:/bin',
                               XDG_CONFIG_HOME=str(home / '.config'),
                               XDG_CACHE_HOME=str(home / '.cache'),
                               XDG_DATA_HOME=str(home / '.local/share'),
                               XDG_STATE_HOME=str(home / '.local/state'), TERM='xterm-256color',
                               NVM_SYMLINK_CURRENT='false', rvm_project_rvmrc='0',
                               rvm_ignore_rvmrc='1', ZDOTDIR=str(home), LC_ALL='C')
            for shell in shell_paths if args.only != 'prompts' else []:
                checks = ['type _dotfiles_external_exists >/dev/null 2>&1']
                if nvm:
                    checks.append('type nvm >/dev/null 2>&1')
                if rvm:
                    checks.append('type rvm >/dev/null 2>&1')
                startup_check = ' && '.join(checks)
                if shell.endswith('bash'):
                    command = [shell, '--noprofile', '--rcfile', str(home / '.bashrc'), '-ic', startup_check]
                    empty = [shell, '--noprofile', '--norc', '-ic', 'exit 0']
                else:
                    command = [shell, '-i', '-c', startup_check]
                    empty = [shell, '-f', '-i', '-c', 'exit 0']
                if name == 'managed-no-managers':
                    results['startup'].append(dict(shell=pathlib.Path(shell).name, variant='empty',
                                                   **measure(empty, environment, home, args.samples, args.warmups)))
                results['startup'].append(dict(shell=pathlib.Path(shell).name, variant=name,
                                               **measure(command, environment, home, args.samples, args.warmups)))
        if binary_paths['starship'] and args.only != 'startup':
            home = workspace / 'managed-no-managers'
            plain = home / 'plain'; plain.mkdir()
            node = home / 'node-project'; (node / 'src/deep/nested').mkdir(parents=True)
            (node / 'package.json').write_text('{"name":"benchmark","version":"1.0.0"}')
            aws = home / 'aws-project'; (aws / 'src/deep/nested').mkdir(parents=True)
            (aws / 'package.json').write_text('{"name":"benchmark","dependencies":{"@aws-sdk/client-s3":"1"}}')
            (aws / 'cdk.json').write_text('{"app":"node index.js"}')
            current = home / '.config/starship.toml'
            native = home / '.config/starship-native.toml'
            text = re.split(r'(?m)^\[custom\.', current.read_text(), maxsplit=1)[0]
            text = text.replace('[nodejs]\ndisabled = true', '[nodejs]\ndisabled = false')
            text = text.replace('[lua]\ndisabled = true', '[lua]\ndisabled = false')
            text = text.replace('[aws]\ndisabled = true', '[aws]\ndisabled = false')
            native.write_text(text)
            environment = dict(HOME=str(home), PATH=str(home / '.local/bin') + ':/usr/bin:/bin',
                               XDG_CONFIG_HOME=str(home / '.config'), TERM='xterm-256color',
                               STARSHIP_CACHE=str(home / '.cache/starship'),
                               AWS_REGION='eu-west-1', LC_ALL='C')
            for name, cwd in [('plain', plain), ('nested-node', node / 'src/deep/nested'),
                              ('nested-aws', aws / 'src/deep/nested')]:
                for mode, config in [('current-three-processes', current), ('native-reference', native)]:
                    environment['STARSHIP_CONFIG'] = str(config)
                    results['prompts'].append(dict(project=name, mode=mode,
                                                   **measure([binary_paths['starship'], 'prompt', '--path', str(cwd)],
                                                             environment, cwd, args.samples, args.warmups)))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
