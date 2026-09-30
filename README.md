# agent-dotfiles

Shared configuration for AI coding agents, kept in one place and installed
once per machine. A single `AGENTS.md` holds the instructions every tool
reads, alongside a common set of skills and custom subagents. Claude Code
and Codex are wired to it through a one-line import and symlinks, so there
is one source of truth to edit rather than a copy per tool.

## Setup

> **Disclaimer:** this script was generated after the fact, to reproduce a
> configuration that was originally set up by hand. I haven't tested it yet
> to make sure everything works and looks as expected.

`agent-shared-skills-setup/` holds the shared configuration (`AGENTS.md`, skills, subagents) and
a first-time installer that copies it to `~/.agents` and wires Claude Code
and Codex to it:

```sh
./agent-shared-skills-setup/setup.sh
```

See [agent-shared-skills-setup/README.md](agent-shared-skills-setup/README.md) for details.
