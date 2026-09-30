#!/usr/bin/env bash
#
# First-time installer for the shared agent configuration in this repo.
#
# Copies agent-shared-skills-setup/home/.agents into ~/.agents (the tool-agnostic source of truth)
# and wires Claude Code and Codex to it:
#
#   ~/.agents/            copy of agent-shared-skills-setup/home/.agents
#   ~/.claude/CLAUDE.md   real file containing only "@~/.agents/AGENTS.md"
#   ~/.claude/skills      symlink to ~/.agents/skills
#   ~/.claude/agents      symlink to ~/.agents/agents
#   ~/.codex/AGENTS.md    symlink to ~/.agents/AGENTS.md
#
# It only runs on a machine where none of those paths exist yet. If any of
# them do, it lists them and exits without changing anything. A pre-existing
# ~/.claude or ~/.codex directory that only holds tool state is fine.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/home"

agents_dir="$HOME/.agents"
claude_dir="$HOME/.claude"
codex_dir="$HOME/.codex"

# Every path this script creates.
targets=(
  "$agents_dir"
  "$claude_dir/CLAUDE.md"
  "$claude_dir/skills"
  "$claude_dir/agents"
  "$codex_dir/AGENTS.md"
)

# Pre-flight: refuse to touch anything if any target already exists.
# -L is checked as well as -e so that dangling symlinks count too.
existing=()
for t in "${targets[@]}"; do
  if [ -e "$t" ] || [ -L "$t" ]; then
    existing+=("$t")
  fi
done

if [ "${#existing[@]}" -gt 0 ]; then
  {
    echo "Agent configuration already present. The following paths exist:"
    for e in "${existing[@]}"; do
      echo "  $e"
    done
    echo
    echo "Back up anything you want to keep, remove the paths above, then run this script again."
  } >&2
  exit 1
fi

# 1. Source of truth
cp -R "$src/.agents" "$agents_dir"

# 2. Claude Code
mkdir -p "$claude_dir"
cp "$src/.claude/CLAUDE.md" "$claude_dir/CLAUDE.md"
ln -s "$agents_dir/skills" "$claude_dir/skills"
ln -s "$agents_dir/agents" "$claude_dir/agents"

# 3. Codex
mkdir -p "$codex_dir"
ln -s "$agents_dir/AGENTS.md" "$codex_dir/AGENTS.md"

echo "Done. Created:"
echo "  $agents_dir/"
echo "  $claude_dir/CLAUDE.md"
echo "  $claude_dir/skills -> $agents_dir/skills"
echo "  $claude_dir/agents -> $agents_dir/agents"
echo "  $codex_dir/AGENTS.md -> $agents_dir/AGENTS.md"
