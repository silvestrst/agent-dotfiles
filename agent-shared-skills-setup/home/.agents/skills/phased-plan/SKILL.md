---
name: phased-plan
description: Plan and implement development work in small, reviewable steps that the developer approves one at a time — each step held to a size budget, measured against it, and shown for review before it counts as done — with progress saved to disk so work can span days and multiple sessions. Use this whenever the user wants to plan a feature or refactor incrementally, implement "just step 2" or "the next step", keep changes small enough to actually review, pause and save progress, resume earlier planned work, check progress, or list what plans are in flight — trigger on /phased-plan with any arguments, and on phrases like "phased plan", "plan this in phases/steps", "break this down", "resume the plan", "where did I leave off", "what's my progress", "do the next step", "checkpoint this", "save my progress", or "list my plans", and also on requests for reviewable increments like "keep the changes small", "don't dump a huge diff on me", "I want to review as we go", "one piece at a time", or "let me approve each change". Prefer it over ordinary ad-hoc planning whenever work is likely to span more than one sitting, or whenever it would otherwise produce more code than the user can comfortably review in one pass.
---

# Phased Plan

Ordinary planning produces one big plan that gets implemented wholesale — hard to
digest, and the developer loses control. This skill inverts that: the developer
approves a high-level plan first, then chooses which step(s) to implement and
when. State lives on disk, so work resumes cleanly days later, even in a fresh
session.

Sequencing alone isn't the point. A numbered list still buys the developer
nothing if step 3 lands 900 lines. So the skill also holds each step to a size
budget, measures what actually landed, and makes review an explicit gate before
anything is marked done. **The goal is that the developer understands every
change that goes in** — steps exist to keep each review small enough that they
can.

Plans are stored in `~/.agents/work/plans/<id>/` (override with the
`PHASED_PLAN_HOME` env var), one directory per plan:

- `plan.md` — the approved plan, human-readable
- `progress.md` — append-only log of what happened when
- `state.json` — machine state: steps, statuses, recorded commits, checkpoints

All mechanical operations (create, save, resume, list) go through
`scripts/plan.py` — never edit `state.json` by hand; the script keeps commits
and timestamps consistent. Run it as:

```bash
python3 <skill-dir>/scripts/plan.py <command> ...
```

The script is yours to run, never the user's. The user drives everything
through you — never tell them to run `plan.py` themselves, and when you point
at how to continue later, phrase it as `/phased-plan` commands, not script
invocations.

## User commands

Users drive this conversationally or as `/phased-plan <args>`. Route by
intent:

- `/phased-plan`, `progress`, or `status` — if one plan matches the current
  repo, show its progress: steps done/in-progress/pending, where work left
  off, what's next (`plan.py show` + `progress.md`). Otherwise `plan.py list`
  and summarize.
- `next` — resume the matching plan (see Resuming below, including the
  reassessment) and implement the next pending step.
- `step 3`, `steps 2-4` — same, but the user's chosen step(s).
- `review` — re-print the review packet for the step in flight
  (`plan.py review`), for when the user wants another look before approving.
- `new <topic>` — the Creating workflow below.
- `save [note]` / `checkpoint` — the Saving workflow below.
- `resume [plan]` — the Resuming workflow below.
- `list` — all plans, summarized.

When several plans could match, prefer the one whose `repo` is the current
repo; ask only if genuinely ambiguous.

## Creating a plan

Do this in two rounds of user approval — the whole point is developer control,
so do not skip ahead:

1. **High-level plan first.** Present only the major phases (3-7 bullets, one
   line each) and the intended progression: fundamentals first, then build up
   gradually. No implementation detail yet. Wait for the user to approve or
   adjust.
2. **Break into steps — vertical slices, not layers.** Expand the approved
   phases into concrete steps. The bar for each step is:

   - **Demonstrable.** The operator can run something and see a difference.
     "Builds without errors" is not enough — a step that only adds scaffolding
     gives them nothing to judge. Prefer a thin end-to-end slice (one route,
     one case, hardcoded where it must be) over a horizontal layer of
     groundwork that only pays off three steps later. Thicken in later steps.
   - **Self-contained.** It doesn't half-finish something a later step
     completes, and it can be reverted on its own.
   - **Small enough to read in one sitting.** Budget ~150 changed lines. If a
     step obviously can't fit, split it now rather than discovering it later.

   Every step needs a `verify` line: the concrete thing the operator runs or
   looks at to confirm it works. **If you can't write one, the step is
   groundwork and is sliced wrong** — reslice it. This is the main guard
   against dumping unreviewable code, so don't treat it as paperwork.

   Show the steps with their verify lines; wait for approval.
3. **Persist.** Only after approval:
   ```bash
   python3 <skill-dir>/scripts/plan.py new --title "Short title" --repo <repo>
   ```
   Then write the approved plan into the printed `plan.md` path (context,
   phases, per-step detail), and register the steps:
   ```bash
   echo '[{"title": "Step 1 title", "verify": "how the operator sees it work",
           "budget": 150}, ...]' | \
     python3 <skill-dir>/scripts/plan.py set-steps <id>
   ```
   `budget` is optional (defaults to 150 changed lines); set it lower for
   fiddly work, higher only when the user agrees the step genuinely warrants
   it. `set-steps` warns about any step missing a `verify` — treat that
   warning as a reslicing prompt, not noise.

## Step numbers vs step ids

Each step has two handles, and mixing them up corrupts history:

- **`n`** — display position (1, 2, 3…). What the user says out loud. It is
  recomputed on every `set-steps`, so it goes stale the moment the plan is
  edited.
- **`sid`** — stable id (`s1`, `s7`…). Assigned once, never changed, never
  reused. This is the step's real identity.

`start-step`, `review` and `complete-step` accept either. **Use the sid**, and
read it from `resume`/`set-steps` output rather than assuming it matches the
position. Speak positions to the user, act on sids.

When re-registering steps after a replan, pass `{"sid": "s2"}` for every step
that already exists — status, commits, sizes and notes are carried forward
automatically, so never hand-copy those fields. Omit `sid` only for genuinely
new steps. Anything you leave out is a deletion, and `set-steps` warns when a
step with progress disappears.

If `set-steps` prints `RENUMBERED`, the numbers the user has seen no longer
mean what they did. Re-show the list before acting on any number they gave
you, and if they name a step from memory ("do step 3"), confirm which one they
mean before starting it.

If the user asks to plan something without mentioning phases, still offer this
workflow when the work looks multi-step — that's exactly when it pays off.

Close by telling the user how to continue in their words, not the script's:
"`/phased-plan next` when you're ready to start, `/phased-plan progress`
anytime to see where things stand."

## Implementing steps

The user picks which step(s) to do — one, several, or "the next one". Never
implement steps the user didn't ask for; finishing early is not a reason to
continue into the next step.

For each chosen step:

1. `plan.py start-step <id> <n>` — records the baseline commit the step's size
   is measured from.
2. Implement only that step's scope. If during implementation you discover the
   plan needs changing (a step is wrong, missing, or already obsolete), say so
   and propose the change — update `plan.md` and re-run `set-steps`, passing
   `{"sid": ...}` for every step that already exists (see Step numbers vs step
   ids).
3. **Review gate — never skip this.** `plan.py review <id> <n>` prints what
   changed since the step started, how big it is against budget, and the
   step's verify line. Walk the user through it: what you changed and why,
   file by file if it's more than a couple, and what they should run to check
   it. Then ask whether it's good. Do not mark anything done on your own
   judgement — the user's approval is the gate, and `complete-step` refuses to
   run until `review` has.
4. Only after the user approves: `plan.py complete-step <id> <n> --note "..."`.
   The user commits however they like — never commit for them.

### When a step comes in over budget

`review` says so explicitly. Treat it as a real signal, not a formality:

- Present the change in digestible pieces rather than as one wall of diff.
- Say plainly that the step outgrew its estimate, and why.
- Offer to resplit the *remaining* steps finer — the overrun is evidence the
  original slicing was too coarse.
- If the step is over budget because it drifted beyond its own scope, offer to
  back the extra work out rather than asking the user to review scope they
  never approved.

If the tree is dirty at `complete-step`, the script warns that the recorded
commit doesn't contain the step's work. Don't wave this through: tell the user
their approved change isn't captured anywhere git can show them later, and
suggest committing first.

## Saving progress (checkpoint)

When the user asks to save/pause ("checkpoint this", "I'm stopping for today"):

```bash
python3 <skill-dir>/scripts/plan.py checkpoint <id> --note "where things stand"
```

Put anything a future session would need into the note: what's half-done, what
to watch out for, decisions made but not yet coded. The script records the
commit and dirty files automatically; the note is for the things git can't see.

## Resuming a plan

When the user wants to pick work back up:

1. `plan.py resume <id>` — prints the plan, progress log, step statuses, and a
   git delta: commits made since the last recorded point and current
   uncommitted changes.
2. **Reassess before continuing.** The codebase may have moved while the plan
   slept — commits outside the plan's tracking, or uncommitted work. Read the
   delta and judge holistically whether the remaining steps still make sense:
   - If gitnexus has this repo indexed (`gitnexus status`), use it:
     `gitnexus detect-changes --scope compare --base-ref <recorded-commit>`
     maps those changes to affected symbols and execution flows, and
     `gitnexus impact <symbol>` shows the blast radius where a remaining step
     touches something that changed. Fall back to reading the diff directly if
     the repo isn't indexed.
   - A step may be partially or fully done already, obsolete, or need
     rescoping. Don't silently trust the stored plan.
3. `resume` also prints size calibration: how many completed steps came in over
   budget and which was worst. If steps have been running large, say so and
   offer to resplit the remaining ones — the estimates were made before any of
   this code existed, so they're the least reliable part of the plan.
4. Tell the user what changed and what you recommend (proceed as planned /
   adjust steps X and Y / step Z is already done). Apply agreed adjustments via
   `plan.md` + `set-steps`, then continue with the step the user picks.

If the delta is empty (HEAD unchanged, clean tree), say so briefly and continue
— no need for a ceremony.

## Listing and finishing

- "What plans do I have?" → `plan.py list`, then summarize conversationally:
  which are active, how far along, where each left off (use `plan.py show <id>`
  or `progress.md` for detail).
- All steps done → confirm with the user, then
  `plan.py set-status <id> completed`. Same with `abandoned` if they drop it.

Plan ids accept unique substrings everywhere — `plan.py resume auth` works if
only one plan matches "auth".
