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

"""Wire the reviewer agent to a real GitHub PR.

Given a repo + PR number, this:
  1. fetches the PR diff and the repo's TDD + team rules (via the `gh` CLI),
  2. runs the code_review_agent on them,
  3. posts the verdict as a PR comment,
  4. exits non-zero if the verdict is 'reject' (so a CI check fails).

Usage:
    uv run python -m app.review_pr --repo owner/name --pr 1
"""

import argparse
import asyncio
import json
import subprocess
import sys

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import Review, root_agent

# Where the source-of-truth docs live in the target repo.
TDD_PATH = "design/TDD.md"
RULES_PATH = "sentinel.rules.md"


def _gh(args: list[str]) -> str:
    """Run a `gh` CLI command and return stdout."""
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True
    )
    return result.stdout


def fetch_diff(repo: str, pr: int) -> str:
    """Fetch the unified diff of a PR."""
    return _gh(["pr", "diff", str(pr), "--repo", repo])


def fetch_file(repo: str, path: str) -> str:
    """Fetch a file's contents from the repo's default branch."""
    raw = _gh(["api", f"repos/{repo}/contents/{path}", "--jq", ".content"])
    import base64

    return base64.b64decode(raw).decode("utf-8")


def post_comment(repo: str, pr: int, body: str) -> None:
    """Post a comment on the PR."""
    _gh(["pr", "comment", str(pr), "--repo", repo, "--body", body])


def build_prompt(tdd: str, rules: str, diff: str) -> str:
    return (
        "Review this pull request.\n\n"
        f"=== TECHNICAL DESIGN DOCUMENT (TDD) ===\n{tdd}\n\n"
        f"=== TEAM RULES ===\n{rules}\n\n"
        f"=== PR DIFF ===\n{diff}\n"
    )


async def run_agent(prompt: str) -> Review:
    """Run the code_review_agent once and return its structured verdict."""
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name="app", user_id="ci", session_id="review"
    )
    runner = Runner(
        agent=root_agent, app_name="app", session_service=session_service
    )

    final_text = ""
    async for event in runner.run_async(
        user_id="ci",
        session_id="review",
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=prompt)]
        ),
    ):
        if event.is_final_response() and event.content:
            final_text = event.content.parts[0].text

    return Review.model_validate_json(final_text)


def format_comment(review: Review) -> str:
    """Render the verdict as a Markdown PR comment."""
    icon = "❌" if review.verdict == "reject" else "✅"
    lines = [
        f"## {icon} Sentinel Review: {review.verdict.upper()}",
        "",
        review.summary,
        "",
    ]
    if review.findings:
        lines.append("| Severity | Rule | File | Problem |")
        lines.append("|---|---|---|---|")
        for f in review.findings:
            lines.append(
                f"| {f.severity} | `{f.rule_id}` | `{f.file}` | {f.explanation} |"
            )
    else:
        lines.append("No issues found. 🎉")
    lines.append("")
    lines.append("_Reviewed by Sentinel (Code Review Agent)._")
    return "\n".join(lines)


async def main() -> int:
    # Load GOOGLE_API_KEY from .env for local runs. In CI the key comes from the
    # environment (a GitHub secret), and load_dotenv() is a harmless no-op there.
    load_dotenv()

    parser = argparse.ArgumentParser(description="Sentinel PR reviewer")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument(
        "--post", action="store_true", help="post the verdict as a PR comment"
    )
    parser.add_argument(
        "--email",
        action="append",
        default=[],
        help="email address to send the summary to (repeatable)",
    )
    args = parser.parse_args()

    print(f"Fetching diff + docs for {args.repo} PR #{args.pr}...")
    diff = fetch_diff(args.repo, args.pr)
    tdd = fetch_file(args.repo, TDD_PATH)
    rules = fetch_file(args.repo, RULES_PATH)

    print("Running the code review agent...")
    review = await run_agent(build_prompt(tdd, rules, diff))

    print(json.dumps(review.model_dump(), indent=2))

    comment = format_comment(review)
    if args.post:
        post_comment(args.repo, args.pr, comment)
        print("Posted review comment to the PR.")

    if args.email:
        from app.notify import send_review_email

        send_review_email(args.repo, args.pr, review, args.email)
        print(f"Emailed summary to: {', '.join(args.email)}")

    # Fail the CI check if the agent rejected the PR.
    return 1 if review.verdict == "reject" else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
