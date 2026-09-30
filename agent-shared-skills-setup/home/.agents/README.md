# ~/.agents

Canonical, tool-agnostic agent configuration, shared across AI coding tools.
This is maintainer documentation about the wiring below — none of it is
read by the agents themselves (that's what `AGENTS.md` is for).

Source: https://github.com/silvestrst/agent-dotfiles (`agent-shared-skills-setup/home/.agents/`).
Edit it there and reinstall, or copy changes back, so the repo stays canonical.

- `AGENTS.md` — canonical instructions, read natively by tools that support
  the AGENTS.md convention. Tools that don't should import/reference it
  rather than duplicating its content.
- `skills/` — canonical skills directory, one folder per skill.
- `agents/` — canonical custom-subagent definitions, one file per subagent.

## Current wiring

- Codex: `~/.codex/AGENTS.md` → symlink → `~/.agents/AGENTS.md`
- Claude Code: `~/.claude/CLAUDE.md` contains only `@~/.agents/AGENTS.md`
  (a real import, not a symlink — see caveat below);
  `~/.claude/skills` → symlink → `~/.agents/skills`;
  `~/.claude/agents` → symlink → `~/.agents/agents`

## Adding another tool

- Symlink its expected instructions filename to `AGENTS.md`, or, if it uses
  its own filename/convention, make that file import/reference `AGENTS.md`
  the way `~/.claude/CLAUDE.md` does.
- If it has its own skills or subagent lookup path, symlink that path to
  `skills/` / `agents/` respectively.

## Known caveat: symlinks in Claude Code Cowork sessions

Claude Code's desktop "Cowork" sessions are documented to skip a
`~/.claude/CLAUDE.md` that is itself a symlink/hard link, and separately to
skip a symlinked `~/.claude/rules/` directory — both go silently unloaded
there even though they work fine in normal CLI sessions. Skills/agents
directories aren't explicitly addressed in the docs either way, so the
symlinked `~/.claude/skills` and `~/.claude/agents` above carry the same
undocumented risk of being silently skipped in Cowork specifically. This is
why `CLAUDE.md` itself uses an `@import` instead of a symlink. If Cowork
usage becomes relevant, re-verify this before relying on it there.

## Not included: eval suites

`claude plugin eval` suites are scoped per-plugin (an `evals/` dir inside
that plugin, or a configurable path) — Claude Code has no user-level/global
eval directory to point at, so there's nothing to share here.
