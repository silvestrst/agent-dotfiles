# agent-shared-skills-setup

First-time installer for the shared agent configuration.

`home/` mirrors the layout the script creates under `$HOME`:

| In this repo             | Installed as                                                     |
|--------------------------|------------------------------------------------------------------|
| `home/.agents/`          | `~/.agents/`, copied. The tool-agnostic source of truth.         |
| `home/.claude/CLAUDE.md` | `~/.claude/CLAUDE.md`, copied. Contains only `@~/.agents/AGENTS.md`. |
| (created by the script)  | `~/.claude/skills`, symlink to `~/.agents/skills`                |
| (created by the script)  | `~/.claude/agents`, symlink to `~/.agents/agents`                |
| (created by the script)  | `~/.codex/AGENTS.md`, symlink to `~/.agents/AGENTS.md`           |

`CLAUDE.md` is a real file with an `@import` rather than a symlink because
Claude Code's Cowork sessions skip a symlinked `CLAUDE.md`. See the notes in
`home/.agents/README.md`.

## Usage

```sh
./agent-shared-skills-setup/setup.sh
```

The script only runs on a machine where none of the paths above exist yet.
If any do, it prints them and exits without changing anything. To reinstall,
back up what you want to keep, remove the listed paths, and run it again.

It only creates the paths listed above. A pre-existing `~/.claude/` or
`~/.codex/` directory holding tool state (settings, credentials, sessions)
is left alone.

## Editing the configuration

Edit files under `home/.agents/` in this repo, then copy them into
`~/.agents/` (or reinstall). Everything else is a symlink or a one-line
import, so `~/.agents/` is the only place the tools actually read from.
