# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Auto-resolve merge conflicts on a real PR and push the fix to its branch.

Flow:
  1. Clone the target repo into a temp dir.
  2. Check out the PR branch and merge the base branch -> surfaces conflicts.
  3. For each conflicted file, run the conflict agent -> write resolved content.
  4. Commit the merge and push to the PR branch, so the conflict clears.
  5. Post a summary comment on the PR.

Usage:
    uv run python -m app.autoresolve_pr --repo owner/name --pr 3 [--push]

Without --push it does a DRY RUN (resolves locally, prints, does not push).
"""

import argparse
import asyncio
import subprocess
import sys
import tempfile

from dotenv import load_dotenv

from app.conflict_agent import Resolution
from app.resolve_conflict import build_prompt, run_agent

TDD_PATH = "design/TDD.md"
RULES_PATH = "sentinel.rules.md"


def run(cmd: list[str], cwd: str | None = None) -> str:
    """Run a shell command, raising on failure (stderr included)."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result.stdout


def run_allow_fail(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run a command that is allowed to exit non-zero (e.g. git merge on conflict)."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def gh(args: list[str]) -> str:
    return run(["gh", *args])


def pr_info(repo: str, pr: int) -> tuple[str, str]:
    """Return (head_branch, base_branch) for the PR."""
    out = gh(
        ["pr", "view", str(pr), "--repo", repo, "--json", "headRefName,baseRefName"]
    )
    import json

    data = json.loads(out)
    return data["headRefName"], data["baseRefName"]


def conflicted_files(cwd: str) -> list[str]:
    """List files with unresolved conflicts after a merge attempt."""
    out = run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=cwd)
    return [line for line in out.splitlines() if line.strip()]


def read_file(cwd: str, path: str) -> str:
    with open(f"{cwd}/{path}", encoding="utf-8") as f:
        return f.read()


def write_file(cwd: str, path: str, content: str) -> None:
    with open(f"{cwd}/{path}", "w", encoding="utf-8") as f:
        f.write(content)


async def resolve_one(cwd: str, path: str, tdd: str, rules: str) -> Resolution:
    conflicted = read_file(cwd, path)
    resolution = await run_agent(build_prompt(conflicted, tdd, rules))
    if "<<<<<<<" in resolution.resolved_content:
        raise RuntimeError(f"Agent left conflict markers in {path}")
    write_file(cwd, path, resolution.resolved_content)
    return resolution


async def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Sentinel auto-resolve conflicts")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument(
        "--push", action="store_true", help="commit + push the fix (else dry run)"
    )
    args = parser.parse_args()

    head, base = pr_info(args.repo, args.pr)
    print(f"PR #{args.pr}: {head} <- {base}")

    with tempfile.TemporaryDirectory() as tmp:
        # 1. Clone and check out the PR branch.
        print("Cloning target repo...")
        url = gh(["repo", "view", args.repo, "--json", "url", "--jq", ".url"]).strip()
        run(["git", "clone", "--quiet", url, tmp])
        run(["git", "checkout", head], cwd=tmp)

        # 2. Merge the base branch to surface conflicts.
        merge = run_allow_fail(["git", "merge", f"origin/{base}"], cwd=tmp)
        files = conflicted_files(tmp)
        if not files:
            print("No conflicts to resolve. (Merge output below.)")
            print(merge.stdout or merge.stderr)
            return 0
        print(f"Conflicted files: {files}")

        # 3. Resolve each file with the agent.
        tdd = read_file(tmp, TDD_PATH)
        rules = read_file(tmp, RULES_PATH)
        resolutions = []
        for path in files:
            print(f"Resolving {path}...")
            res = await resolve_one(tmp, path, tdd, rules)
            resolutions.append((path, res))
            for i, d in enumerate(res.decisions, 1):
                print(f"  hunk {i}: keep '{d.choice}' — {d.reason}")

        if not args.push:
            print("\nDRY RUN (no --push): resolved locally, not committing.")
            return 0

        # 4. Stage, commit the merge, and push to the PR branch.
        for path, _ in resolutions:
            run(["git", "add", path], cwd=tmp)
        run(
            ["git", "commit", "-m", "Sentinel: auto-resolve merge conflict"],
            cwd=tmp,
        )
        # Use the gh token for auth on push.
        token = gh(["auth", "token"]).strip()
        push_url = url.replace("https://", f"https://x-access-token:{token}@")
        run(["git", "push", push_url, f"HEAD:{head}"], cwd=tmp)
        print("Pushed resolution to the PR branch.")

        # 5. Comment on the PR.
        summary = "\n".join(
            f"- `{path}`: {res.summary}" for path, res in resolutions
        )
        body = (
            "## 🔀 Sentinel auto-resolved the merge conflict\n\n"
            f"{summary}\n\n_Resolved by Sentinel (Conflict Agent)._"
        )
        gh(["pr", "comment", str(args.pr), "--repo", args.repo, "--body", body])
        print("Posted summary comment.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
