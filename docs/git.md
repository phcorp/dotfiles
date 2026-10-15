# Private Git setup

Use Git setup to choose identity, signing, and supported credential integration
without putting personal settings in the public dotfiles repository:

```sh
dotfiles git status
dotfiles git setup --dry-run
dotfiles git setup
```

The wizard has a Git setup entry and offers setup after installation. Setup is
optional. Skipping it preserves existing identity, signing, and authentication
choices. `dotfiles git setup` is interactive unless you pass
`--non-interactive`, regardless of the saved first-use mode. Status and previews report categories and configured/unconfigured
states; they do not print identities, email domains, key paths, or profile paths.

Setup is local. It does not contact a hosting service, change repository remote
URLs, generate keys, upload public keys, or log in. Existing SSH configuration,
host aliases, keys, agents, and keychain integration are retained. Existing
credential helpers, including custom ones, remain untouched when you keep existing
authentication. Choosing a new supported helper writes an empty-helper reset
followed by that helper, so the earlier helper chain is excluded from the active
configuration. The legacy file itself is retained; setup does not execute helpers.

## Shared defaults and private overrides

The shared Git configuration supplies these defaults:

| Setting | Default behavior |
| --- | --- |
| `init.defaultBranch=main` | New repositories start on `main`; existing branches are not renamed |
| `pull.ff=only` | Pulls require a fast-forward |
| `fetch.prune=true` | Fetch prunes obsolete remote-tracking refs |
| `push.default=simple` | Use Git's simple push behavior |
| `user.useConfigOnly=true` | Require an explicitly configured identity |

Explicit private and repository settings override these defaults using Git's
normal precedence. The legacy
private include, `$DOTFILES_CONFIG/local/gitconfig`, is retained. Setup writes
`$DOTFILES_CONFIG/local/git/config`, included after that legacy file, so explicitly
chosen setup values can override earlier private values. Both includes follow
the configured `DOTFILES_CONFIG` location, including when it is relocated. Repository-specific
configuration and explicit Git command/environment overrides still apply.

This Git configuration is independent of `DOTFILES_PUBLISH_NAME` and
`DOTFILES_PUBLISH_EMAIL`. Those settings supply a public noreply author/committer
identity only when publishing the dotfiles repository; see
[publication settings](configuration.md#repository-and-publication-settings).

## Unattended input

Unattended setup reads one fixed private input file:

```text
$DOTFILES_CONFIG/local/git/setup-input.gitconfig
```

It uses native Git configuration syntax, not shell syntax or the CLI's separate
`settings` format. Create the file without exposing values in command arguments,
then edit it locally with your preferred text editor:

```sh
config=${DOTFILES_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles}
(umask 077; mkdir -p "$config/local/git"; touch "$config/local/git/setup-input.gitconfig")
chmod 600 "$config/local/git/setup-input.gitconfig"
```

Keep the input and profile files owner-only, owned by you, and inside HOME,
outside the public source checkout. Populate the desired values before running:

```sh
dotfiles git setup --non-interactive --dry-run
dotfiles git setup --non-interactive
dotfiles git status
```

Only these settings are accepted as new setup input:

| Area | Allowed keys/values |
| --- | --- |
| Identity | `user.name`, `user.email`, `user.useConfigOnly` |
| Signing key | `user.signingkey` |
| Signing format | `gpg.format` set to `ssh` or `openpgp` |
| Signing switches | `commit.gpgsign`, `tag.gpgsign` |
| SSH verification | `gpg.ssh.allowedSignersFile` |
| Pull policy | `pull.ff` set to `only` |
| Credential integration | `credential.helper` using an existing `osxkeychain`, `libsecret`, `manager`, or `manager-core` helper |

New arbitrary helper commands and Git program/alias/hook overrides are not
accepted. Setup validates the input before applying it; existing custom
credential helpers remain part of the preserved configuration.

## Repository profiles

Use native `includeIf` conditions with `gitdir:` to select private profiles for
repository directories. Each included profile is a separate owner-only native
Git configuration file inside HOME and outside public source. Profiles accept only
identity (`user.name`, `user.email`) and the signing settings listed above. They
do not accept credential helpers, `pull.ff`, or `user.useConfigOnly`.

Use a literal absolute directory inside HOME, ending in `/`; wildcard patterns
are rejected. Setup normalizes directories to their physical paths while
preserving their case, then writes native `gitdir:` conditions. Add the directory
condition and profile include locally in the setup input; do
not copy private repository directory patterns or profile contents into shared
configuration. Git processes matching includes at their include position.
[Git's configuration reference](https://git-scm.com/docs/git-config#_conditional_includes)
explains native `gitdir:` matching and configuration precedence.

## Signing and recovery

Signing remains unchanged unless explicitly configured. The interactive flow can
select an existing SSH public key or existing local OpenPGP identity. SSH setup
accepts an existing `.pub` file; it does not copy or create a private key. The
preflight validates the public-key format and checks either the companion private
key's presence and ownership/permissions or a matching public key advertised by
the SSH agent. It never reads private-key contents, tests an actual signature, or
cryptographically verifies that a companion private key matches the public key.
The existing SSH agent/keychain remains responsible for private-key access. An
allowed-signers file controls SSH signature verification, not SSH authentication.

For OpenPGP, preview does not open the keyring: it reports `NEEDS INFO` for the
local identity check. Applying setup checks local secret-signing-key metadata and
rejects unavailable, expired, revoked, disabled, or otherwise unusable identities.

Missing identities, unsupported signing tools, or invalid signing configuration
are errors. Setup never silently switches signing methods or disables signing to
make an operation succeed. It neither signs a test commit nor contacts a remote.

Changes are transactional and recoverable. If setup is interrupted, use
`dotfiles doctor` and the [recovery procedure](recovery.md); verified stale locks
require explicit recovery. Uninstalling dotfiles retains the private Git overlay
and keeps its include active in the restored `~/.gitconfig`. Your private identity,
signing choices, credential helpers, and profiles therefore remain available.
