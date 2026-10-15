# Portable dotfiles

A chezmoi-based shell configuration and lifecycle CLI for Bash 3.2+ and Zsh on
macOS, Debian/Ubuntu, and Fedora. Uses XDG directories, a shared Starship prompt,
explicit application management, and guarded synchronization. Licensed under
[MIT](LICENSE).

## Install

Download and review the bootstrap script before running it:

```sh
curl -fsSLo bootstrap.sh https://raw.githubusercontent.com/phcorp/dotfiles/master/bootstrap.sh
sh bootstrap.sh
```

Bootstrap installs prerequisites and verifies the exact checkout revision against
the latest successful **Verify push** run before executing repository code.
Existing checkouts must be clean. Missing, pending, failed, or unavailable CI
stops installation. On macOS, install Apple Command Line Tools first with
`xcode-select --install`; initial Homebrew setup may need administrator access.

For an unattended machine with suitable root or passwordless sudo access:

```sh
sh bootstrap.sh --non-interactive --profiles=shell,php,runtimes --sync
```

Profiles: `shell`, `runtimes`, `php`, `cloud`, `databases`, `desktop`. Existing
software and active runtime versions are retained. Tool installation happens on
first use in interactive shells, or through explicit tool/app commands. Shell
startup performs no installation, network requests, or synchronization.

## Preview, apply, recover

```sh
dotfiles install --profiles shell,php --dry-run
dotfiles repair --dry-run
dotfiles sync --dry-run
dotfiles apps install --dry-run
dotfiles repair
dotfiles doctor
dotfiles recover
```

`--dry-run` previews operations without changing configuration, tool selection,
ownership, packages, or schedulers. Package versions and authentication that
cannot be established locally are reported as **NEEDS INFO**; prerequisites and
conflicts can be **BLOCKED**. Configuration previews suppress private file content.

Apply records backups and ownership. Interrupted or failed configuration changes
retain a transaction for recovery when rollback cannot finish. Read
[recovery and uninstallation](docs/recovery.md) before using `--force`.

## Configure and share

Private overrides, Git credentials, histories, backups, and application data stay
outside the source checkout. Repository, branch, and public publication identity
can be configured without changing your private Git identity. See
[configuration and fork setup](docs/configuration.md).

```sh
dotfiles wizard
dotfiles git setup --dry-run
dotfiles git status
dotfiles tools list
dotfiles apps list
dotfiles sync enable
dotfiles sync disable
dotfiles publish "Improve shared configuration"
```

Hourly synchronization only pulls CI-approved changes. Dirty checkouts, changed
managed files, divergence, remote mismatches, and unavailable CI stop the update.
Publishing is explicit and requires public-file checks, a matching GitHub noreply
identity, and redacted secret scans. Automatic synchronization never pushes.

- [Platforms, prerequisites, and validation](docs/platforms.md)
- [Applications, equivalents, and ownership](docs/applications.md)
- [Private settings, prompt behavior, and reuse](docs/configuration.md)
- [Git identity, signing, credentials, and profiles](docs/git.md)
- [Recovery, backups, and uninstall](docs/recovery.md)
- [Measured shell startup and prompt performance](docs/performance.md)

No secret scanner recognizes every private value. Keep machine-specific data out
of public source files and review publication changes. Rewriting history cannot
erase existing downloaded copies or GitHub caches.
