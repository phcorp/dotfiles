# Applications and tools

Select profiles through `dotfiles wizard`, or save them explicitly. Configuration
application saves tool choices; it does not start applications or services.

```sh
dotfiles repair --profiles shell,runtimes,php,cloud,databases,desktop --dry-run
dotfiles repair --profiles shell,runtimes,php,cloud,databases,desktop
dotfiles apps list
dotfiles apps install --dry-run
dotfiles apps install --non-interactive
```

`apps install` and `apps update` without an ID operate on selected desktop apps.
`apps remove` without an ID targets only apps recorded as installed by dotfiles.
`dotfiles tools` uses the same catalog for individual CLI tools. Existing commands
and applications win; discovering them does not grant removal ownership.

## Desktop mappings

| Catalog ID | macOS | Linux |
| --- | --- | --- |
| `claude-desktop` | Claude | Official Claude desktop beta on Debian/Ubuntu |
| `chatgpt` | ChatGPT, including Codex | Official ChatGPT preview |
| `codexbar` | CodexBar | Official desktop and CLI |
| `cyberduck` | Cyberduck | FileZilla |
| `github-desktop` | GitHub Desktop | Community GitHub Desktop fork |
| `orbstack` | OrbStack | Podman Desktop and Podman |
| `hoppscotch` | Hoppscotch | Official amd64 DEB or AppImage |
| `mutekey` | MuteKey | Microphone-toggle helper |
| `sequel-ace` | Sequel Ace | DBeaver Community |
| `stats` | Stats | Mission Center |
| `cmux` | cmux | WezTerm |

Linux equivalents retain the original catalog ID. FileZilla covers FTP/SFTP but
not every Cyberduck cloud backend. Podman Desktop is a container engine interface,
not a replacement for OrbStack's macOS Linux-machine integration. WezTerm provides
a terminal/multiplexer; cmux-specific browser, API, and agent features are not
reproduced. GitHub Desktop's Linux fork is community-supported.

[Claude](https://code.claude.com/docs/en/desktop-linux) requires Ubuntu 22+ or Debian
12+. [ChatGPT/Codex](https://learn.chatgpt.com/docs/linux/linux-app) requires Ubuntu
24+, Debian 13+, or Fedora 43+. Both support x86_64 and arm64. Their Linux releases
are beta/preview and have platform-specific feature limitations.

[CodexBar's Linux desktop](https://github.com/steipete/CodexBar/blob/main/Integrations/Linux/README.md)
requires glibc 2.39+ and Qt 6.4+. Its official CLI remains available on older
supported Linux systems. Hoppscotch's current published Linux desktop binaries
support amd64 only. Unsupported apps are excluded rather than installed under a
misleading platform claim.

MuteKey uses the Mac App Store and can request Apple authentication during
installation or update. Existing installations are retained. On Linux, running
`mutekey` toggles the default microphone through `pactl` using PulseAudio or
PipeWire's PulseAudio compatibility interface. Installation never changes
microphone state. An owned desktop shortcut is provided; bind the command to a
hotkey yourself if desired.

## Updates and removal

```sh
dotfiles apps update hoppscotch --dry-run
dotfiles apps update hoppscotch --non-interactive
dotfiles apps remove hoppscotch --dry-run
dotfiles apps remove hoppscotch --non-interactive
```

Native packages follow their supported package managers. Explicit updates can
update registered existing apps without adopting them for removal. Apps installed
outside those managers retain their original updater. Upstream tools and desktop
artifacts are pinned in `lib/tools-upstream.tsv` and `lib/tools-desktop.tsv`;
adopting a newer pinned release requires a reviewed manifest change. Existing
newer native installations are retained.

Native Claude/ChatGPT downloads verify pinned checksums and signed vendor
repository metadata. Flatpak apps use signed Flathub metadata and per-user
installation. Shared Flatpak runtimes, remotes, and application dependencies are
retained on removal. Database profiles install clients without starting database
services; Docker's CLI catalog entry does not provision a running engine.

Removal requires recorded dotfiles ownership and checks installed dependents.
Runtime removal is intentionally delegated to the original runtime manager.
Modified owned launchers and payloads are preserved or cause a clear refusal.
Application data, credentials, login sessions, and shared dependencies remain.
Normal `dotfiles uninstall` removes configuration, not applications.
