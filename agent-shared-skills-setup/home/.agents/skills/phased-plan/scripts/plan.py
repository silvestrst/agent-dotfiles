#!/usr/bin/env python3
"""Deterministic state management for phased plans. No LLM needed here."""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PLANS_DIR = Path(os.environ.get("PHASED_PLAN_HOME", "~/.agents/work/plans")).expanduser()

# Target ceiling for a single step, in changed lines (insertions + deletions).
# A step over budget is not an error — it's a signal to stop and split the rest.
DEFAULT_BUDGET = int(os.environ.get("PHASED_PLAN_BUDGET", "150"))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today():
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def git(repo, *args):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_head(repo):
    return git(repo, "rev-parse", "HEAD")


def git_dirty(repo):
    out = git(repo, "status", "--porcelain")
    return out.splitlines() if out else []


def git_untracked(repo):
    out = git(repo, "ls-files", "--others", "--exclude-standard")
    return out.splitlines() if out else []


def measure(repo, base):
    """Size of everything that changed since `base`, committed or not.

    Diffing base against the working tree (rather than base..HEAD) means the
    number is honest whether or not the user has committed yet. Untracked
    files count as pure insertions; binary files count as changed files only.
    """
    files = insertions = deletions = 0
    out = git(repo, "diff", "--numstat", base) if base else None
    for line in (out or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, removed = parts[0], parts[1]
        files += 1
        insertions += int(added) if added.isdigit() else 0
        deletions += int(removed) if removed.isdigit() else 0
    new_files = git_untracked(repo)
    for rel in new_files:
        files += 1
        try:
            with open(Path(repo) / rel, "rb") as f:
                insertions += sum(1 for _ in f)
        except (OSError, ValueError):
            pass
    return {
        "files": files,
        "insertions": insertions,
        "deletions": deletions,
        "changed_lines": insertions + deletions,
        "untracked": new_files,
    }


def step_base(state, step):
    """Commit a step's diff should be measured from, with fallbacks for
    plans created before start_commit was recorded."""
    if step.get("start_commit"):
        return step["start_commit"]
    prior = [s for s in state["steps"] if s["n"] < step["n"] and s.get("commit")]
    if prior:
        return prior[-1]["commit"]
    return state.get("last_recorded_commit")


def budget_line(size, budget):
    total = size["changed_lines"]
    verdict = "within budget"
    if budget and total > budget:
        verdict = f"OVER BUDGET by {total - budget} lines ({total / budget:.1f}x)"
    return (f"{size['files']} file(s), +{size['insertions']} / -{size['deletions']} "
            f"= {total} changed lines (budget {budget or 'none'}) — {verdict}")


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40] or "plan"


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def migrate(state):
    """Give every step a stable id. Plans created before sids existed get them
    assigned in current order, which is deterministic, so this is idempotent."""
    nxt = state.get("next_sid", 1)
    for s in state.get("steps", []):
        if not s.get("sid"):
            s["sid"] = f"s{nxt}"
            nxt += 1
    state["next_sid"] = nxt
    return state


def load(plan_dir):
    with open(plan_dir / "state.json") as f:
        return migrate(json.load(f))


def save(plan_dir, state):
    state["updated"] = now()
    with open(plan_dir / "state.json", "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def append_progress(plan_dir, line):
    with open(plan_dir / "progress.md", "a") as f:
        f.write(f"- {now()} — {line}\n")


def all_plans():
    if not PLANS_DIR.is_dir():
        return []
    out = []
    for d in sorted(PLANS_DIR.iterdir()):
        if (d / "state.json").is_file():
            try:
                out.append((d, load(d)))
            except (json.JSONDecodeError, OSError):
                print(f"warning: unreadable state in {d}", file=sys.stderr)
    return out


def find_plan(idish):
    plans = all_plans()
    exact = [(d, s) for d, s in plans if d.name == idish or s["id"] == idish]
    if exact:
        return exact[0]
    matches = [(d, s) for d, s in plans if idish in d.name or idish in s.get("title", "")]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        die(f"no plan matching '{idish}' (try: plan.py list)")
    die(f"ambiguous '{idish}': " + ", ".join(d.name for d, _ in matches))


PROGRESS_FIELDS = ("status", "started_at", "start_commit",
                   "completed_at", "commit", "size", "note")


def normalize_steps(raw, existing, next_sid):
    """Rebuild the step list, matching incoming items to existing steps by
    stable `sid` so progress follows the step, not its position.

    `n` is display position and is recomputed every time; `sid` is identity and
    never changes or gets reused. Callers no longer need to hand-copy status or
    commit fields to preserve history — carrying them forward happens here.
    """
    by_sid = {s["sid"]: s for s in existing if s.get("sid")}
    steps, seen = [], set()
    for i, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {"title": item}
        sid = item.get("sid")
        if sid and sid not in by_sid:
            die(f"step {i} references unknown sid '{sid}' "
                "(omit sid to add a new step)")
        if sid in seen:
            die(f"sid '{sid}' appears more than once")
        prior = by_sid.get(sid, {}) if sid else {}
        if not sid:
            sid = f"s{next_sid}"
            next_sid += 1
        seen.add(sid)
        title = item.get("title") or prior.get("title")
        if not title:
            die(f"step {i} has no title")
        step = {
            "n": i,
            "sid": sid,
            "title": title,
            # How the operator can see this step working. A step with no
            # runnable verify is groundwork, not a reviewable slice.
            "verify": item.get("verify", prior.get("verify")),
            "budget": item.get("budget", prior.get("budget", DEFAULT_BUDGET)),
        }
        for f in PROGRESS_FIELDS:
            step[f] = item.get(f, prior.get(f))
        step["status"] = step["status"] or "pending"
        steps.append(step)
    dropped = [s for s in existing if s.get("sid") and s["sid"] not in seen]
    return steps, next_sid, dropped


def step_counts(state):
    done = sum(1 for s in state["steps"] if s["status"] == "done")
    return done, len(state["steps"])


def cmd_new(args):
    repo = str(Path(args.repo or ".").resolve())
    toplevel = git(repo, "rev-parse", "--show-toplevel")
    if toplevel:
        repo = toplevel
    plan_id = f"{today()}-{slugify(args.title)}-{secrets.token_hex(3)}"
    plan_dir = PLANS_DIR / plan_id
    plan_dir.mkdir(parents=True)
    state = {
        "id": plan_id,
        "title": args.title,
        "repo": repo,
        "status": "active",
        "created": now(),
        "updated": now(),
        "last_recorded_commit": git_head(repo),
        "steps": [],
        "next_sid": 1,
        "checkpoints": [],
    }
    save(plan_dir, state)
    (plan_dir / "plan.md").write_text(f"# {args.title}\n\n(plan not written yet)\n")
    (plan_dir / "progress.md").write_text(f"# Progress: {args.title}\n\n")
    append_progress(plan_dir, f"plan created (repo: {repo})")
    print(f"created {plan_id}")
    print(f"dir: {plan_dir}")
    print(f"write the approved plan to: {plan_dir}/plan.md")
    print("then register steps: plan.py set-steps " + plan_id + " < steps.json")


def cmd_set_steps(args):
    plan_dir, state = find_plan(args.id)
    try:
        raw = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        die(f"stdin must be a JSON array of step titles or objects: {e}")
    if not isinstance(raw, list) or not raw:
        die("expected a non-empty JSON array")
    was = {s["sid"]: s["n"] for s in state["steps"] if s.get("sid")}
    steps, next_sid, dropped = normalize_steps(raw, state["steps"],
                                               state.get("next_sid", 1))
    state["steps"] = steps
    state["next_sid"] = next_sid
    save(plan_dir, state)

    moved = [(was[s["sid"]], s) for s in steps
             if s["sid"] in was and was[s["sid"]] != s["n"]]
    if moved:
        print("RENUMBERED — step numbers the user has already seen are now stale:")
        for old_n, s in moved:
            print(f"  step {old_n} is now step {s['n']} ({s['sid']}): {s['title']}")
        print("Re-show the updated list before acting on any step number, and "
              "confirm which step the user means if they name one from memory.")
    for s in dropped:
        where = "with progress" if s["status"] != "pending" else "pending"
        print(f"warning: dropped step {s['sid']} ({where}): {s['title']}",
              file=sys.stderr)

    print("--- steps ---")
    for s in steps:
        print(f"  {s['n']} ({s['sid']}) [{s['status']}] {s['title']}")
    done, total = step_counts(state)
    print(f"{state['id']}: {total} steps registered ({done} done)")
    unverifiable = [s["n"] for s in state["steps"] if not s.get("verify")]
    if unverifiable:
        print(f"warning: step(s) {unverifiable} have no 'verify' — these are "
              "groundwork, not demonstrable slices; consider reslicing so each "
              "step does something the operator can run", file=sys.stderr)


def cmd_list(args):
    plans = all_plans()
    if not plans:
        print(f"no plans in {PLANS_DIR}")
        return
    for d, s in plans:
        done, total = step_counts(s)
        print(f"{s['id']}  [{s['status']}]  {done}/{total} steps  "
              f"updated {s['updated']}  repo={s['repo']}\n    {s['title']}")


def cmd_show(args):
    plan_dir, state = find_plan(args.id)
    print(f"dir: {plan_dir}")
    print(json.dumps(state, indent=2))


def _get_step(state, ref):
    """Resolve a step by stable id ('s3') or display position ('3').

    Prefer sids: a position is only meaningful against the list as it stands
    right now, and replanning renumbers positions.
    """
    ref = str(ref).strip()
    if re.fullmatch(r"s\d+", ref):
        for s in state["steps"]:
            if s.get("sid") == ref:
                return s
        die(f"no step with id '{ref}' in this plan")
    if ref.isdigit():
        for s in state["steps"]:
            if s["n"] == int(ref):
                return s
        die(f"no step {ref} (plan has {len(state['steps'])} steps)")
    die(f"bad step reference '{ref}': use a position like 3 or an id like s3")


def cmd_start_step(args):
    plan_dir, state = find_plan(args.id)
    step = _get_step(state, args.n)
    head = git_head(state["repo"])
    dirty = git_dirty(state["repo"])
    step["status"] = "in_progress"
    step["started_at"] = now()
    step["start_commit"] = head
    save(plan_dir, state)
    append_progress(plan_dir, f"step {step['n']} started: {step['title']} "
                              f"(from commit {head[:10] if head else 'n/a'})")
    print(f"step {step['n']} ({step['sid']}) in_progress: {step['title']}")
    print(f"baseline commit: {head or 'n/a'}  budget: {step.get('budget') or 'none'} changed lines")
    if step.get("verify"):
        print(f"verify when done: {step['verify']}")
    if dirty:
        print(f"note: {len(dirty)} file(s) already dirty at start; "
              "they will count toward this step's measured size")


def cmd_review(args):
    """Build the review packet for a step: what changed, how big, how to check."""
    plan_dir, state = find_plan(args.id)
    step = _get_step(state, args.n)
    repo = state["repo"]
    base = step_base(state, step)
    head = git_head(repo)
    size = measure(repo, base)
    budget = step.get("budget")

    print(f"=== REVIEW: step {step['n']} ({step['sid']}) — {step['title']} ===")
    print(f"plan: {state['id']}   repo: {repo}")
    print(f"base: {base[:10] if base else 'n/a'} (step start)   head: "
          f"{head[:10] if head else 'n/a'}")
    print()
    print("--- how to verify ---")
    print(step.get("verify") or "(none recorded — ask the user what would "
                                "convince them this step works)")
    print()
    print("--- size ---")
    print(budget_line(size, budget))
    print()
    print("--- files changed since step start ---")
    print(git(repo, "diff", "--stat", base) if base else "(no baseline commit)")
    if size["untracked"]:
        print(f"--- new untracked files ({len(size['untracked'])}) ---")
        for rel in size["untracked"]:
            print(f"?? {rel}")
    dirty = git_dirty(repo)
    print(f"--- uncommitted ({len(dirty)}) ---")
    for line in dirty:
        print(line)

    step["status"] = "awaiting_review"
    step["size"] = {k: v for k, v in size.items() if k != "untracked"}
    save(plan_dir, state)
    append_progress(plan_dir, f"step {step['n']} ready for review: "
                              f"{size['changed_lines']} changed lines "
                              f"across {size['files']} file(s)")
    print()
    print(f"step {step['n']} ({step['sid']}) -> awaiting_review")
    if budget and size["changed_lines"] > budget:
        print("ACTION: this step is over budget. Walk the user through it in "
              "pieces, and offer to split the remaining steps finer.")


def cmd_complete_step(args):
    plan_dir, state = find_plan(args.id)
    step = _get_step(state, args.n)
    if step["status"] != "awaiting_review" and not args.force:
        die(f"step {step['n']} is '{step['status']}', not 'awaiting_review' — "
            f"run `plan.py review {state['id']} {step['sid']}` and show the user "
            "what changed before marking it done (--force overrides)")
    head = git_head(state["repo"])
    dirty = git_dirty(state["repo"])
    base = step_base(state, step)
    size = measure(state["repo"], base)
    step["status"] = "done"
    step["completed_at"] = now()
    step["commit"] = head
    step["size"] = {k: v for k, v in size.items() if k != "untracked"}
    if args.note:
        step["note"] = args.note
    if head:
        state["last_recorded_commit"] = head
    save(plan_dir, state)
    note = f" — {args.note}" if args.note else ""
    append_progress(plan_dir, f"step {step['n']} done: {step['title']}{note} "
                              f"(commit {head[:10] if head else 'n/a'}, "
                              f"{size['changed_lines']} changed lines)")
    print(f"step {step['n']} ({step['sid']}) done at commit {head or 'n/a'}")
    print(budget_line(size, step.get("budget")))
    if dirty:
        print(f"WARNING: {len(dirty)} uncommitted change(s) — this step is "
              "recorded at a commit that does not contain its own work. "
              "Reviewing it later from git will not show what you just approved.")
    overruns = [s for s in state["steps"]
                if s["status"] == "done" and s.get("size") and s.get("budget")
                and s["size"]["changed_lines"] > s["budget"]]
    if len(overruns) >= 2:
        print(f"note: {len(overruns)} completed steps have come in over budget. "
              "The remaining steps are probably sized too optimistically — "
              "offer to resplit them.")


def cmd_checkpoint(args):
    plan_dir, state = find_plan(args.id)
    head = git_head(state["repo"])
    dirty = git_dirty(state["repo"])
    cp = {"time": now(), "commit": head, "dirty_files": dirty, "note": args.note}
    state["checkpoints"].append(cp)
    if head:
        state["last_recorded_commit"] = head
    save(plan_dir, state)
    note = f" — {args.note}" if args.note else ""
    append_progress(plan_dir, f"checkpoint{note} (commit {head[:10] if head else 'n/a'}, "
                              f"{len(dirty)} dirty file(s))")
    print(f"checkpoint saved (commit {head or 'n/a'}, {len(dirty)} dirty file(s))")


def cmd_set_status(args):
    plan_dir, state = find_plan(args.id)
    state["status"] = args.status
    save(plan_dir, state)
    append_progress(plan_dir, f"plan marked {args.status}")
    print(f"{state['id']}: {args.status}")


def cmd_resume(args):
    plan_dir, state = find_plan(args.id)
    repo = state["repo"]
    recorded = state.get("last_recorded_commit")
    head = git_head(repo)
    dirty = git_dirty(repo)

    print(f"=== PLAN {state['id']} ===")
    print(f"title: {state['title']}")
    print(f"repo: {repo}")
    print(f"status: {state['status']}")
    done, total = step_counts(state)
    print(f"steps: {done}/{total} done")
    print()
    print("=== STEPS ===")
    for s in state["steps"]:
        mark = {"done": "x", "in_progress": ">", "awaiting_review": "?",
                "skipped": "-"}.get(s["status"], " ")
        size = s.get("size")
        actual = f"  [{size['changed_lines']} lines]" if size else ""
        print(f"[{mark}] {s['n']} ({s['sid']}). {s['title']}{actual}"
              + (f"  — {s['note']}" if s.get("note") else ""))
        if s["status"] not in ("done", "skipped") and s.get("verify"):
            print(f"      verify: {s['verify']}")
    sized = [s for s in state["steps"] if s.get("size") and s.get("budget")]
    if sized:
        ratios = [(s["size"]["changed_lines"] / s["budget"], s) for s in sized]
        over = [(r, s) for r, s in ratios if r > 1]
        worst_r, worst_s = max(ratios, key=lambda x: x[0])
        print(f"\nsize calibration: {len(over)} of {len(sized)} measured step(s) "
              f"over budget; largest was step {worst_s['n']} at {worst_r:.1f}x "
              f"({worst_s['size']['changed_lines']} lines)")
        if over:
            print("  -> steps are running larger than planned; resplit the "
                  "remaining ones before continuing")
    print()
    print("=== GIT DELTA SINCE LAST RECORDED POINT ===")
    if not head:
        print(f"warning: cannot read git state in {repo}")
    elif not recorded:
        print(f"no recorded commit; current HEAD: {head}")
    elif recorded == head:
        print(f"HEAD unchanged since last record ({head[:10]})")
    else:
        print(f"recorded: {recorded}")
        print(f"current HEAD: {head}")
        log = git(repo, "log", "--oneline", f"{recorded}..{head}")
        if log is None:
            print("warning: recorded commit not reachable from HEAD "
                  "(rebase/amend?) — diff unavailable, reassess from full tree")
        else:
            n = len(log.splitlines())
            print(f"--- {n} unrecorded commit(s) made outside this plan's tracking ---")
            print(log)
            diff = git(repo, "diff", "--name-status", f"{recorded}..{head}")
            print("--- files changed in those commits ---")
            print(diff or "(none)")
    print(f"--- uncommitted changes ({len(dirty)}) ---")
    for line in dirty:
        print(line)
    print()
    print("=== plan.md ===")
    print((plan_dir / "plan.md").read_text())
    print("=== progress.md ===")
    print((plan_dir / "progress.md").read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="create a plan")
    s.add_argument("--title", required=True)
    s.add_argument("--repo", help="repo path (default: cwd's git toplevel)")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("set-steps", help="register steps from JSON array on stdin")
    s.add_argument("id")
    s.set_defaults(fn=cmd_set_steps)

    s = sub.add_parser("list", help="list all plans")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("show", help="dump a plan's state")
    s.add_argument("id")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("start-step", help="mark a step in_progress")
    s.add_argument("id")
    s.add_argument("n", metavar="step",
                   help="step position (3) or stable id (s3)")
    s.set_defaults(fn=cmd_start_step)

    s = sub.add_parser("review", help="show what a step changed, how big, how to verify")
    s.add_argument("id")
    s.add_argument("n", metavar="step",
                   help="step position (3) or stable id (s3)")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("complete-step", help="mark a reviewed step done, recording HEAD")
    s.add_argument("id")
    s.add_argument("n", metavar="step",
                   help="step position (3) or stable id (s3)")
    s.add_argument("--note")
    s.add_argument("--force", action="store_true",
                   help="mark done without a review pass (discouraged)")
    s.set_defaults(fn=cmd_complete_step)

    s = sub.add_parser("checkpoint", help="save current git position + dirty files")
    s.add_argument("id")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_checkpoint)

    s = sub.add_parser("set-status", help="mark plan active/completed/abandoned")
    s.add_argument("id")
    s.add_argument("status", choices=["active", "completed", "abandoned"])
    s.set_defaults(fn=cmd_set_status)

    s = sub.add_parser("resume", help="print full context + git delta for resuming")
    s.add_argument("id")
    s.set_defaults(fn=cmd_resume)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
