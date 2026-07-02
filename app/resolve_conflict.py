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

"""Run the merge-conflict agent on a conflicted file.

This is the 'brain' slice: it takes a file that already contains Git conflict
markers, plus the TDD + rules, and prints the agent's proposed resolution.
It does NOT touch git yet — apply/commit comes in a later step.

Usage:
    uv run python -m app.resolve_conflict \\
        --file /path/to/conflicted_file.py \\
        --tdd /path/to/TDD.md \\
        --rules /path/to/sentinel.rules.md
"""

import argparse
import asyncio
import sys

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.conflict_agent import Resolution, root_agent


def build_prompt(conflicted: str, tdd: str, rules: str) -> str:
    return (
        "Resolve the merge conflicts in this file.\n\n"
        f"=== TECHNICAL DESIGN DOCUMENT (TDD) ===\n{tdd}\n\n"
        f"=== TEAM RULES ===\n{rules}\n\n"
        f"=== CONFLICTED FILE ===\n{conflicted}\n"
    )


async def run_agent(prompt: str) -> Resolution:
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name="app", user_id="ci", session_id="resolve"
    )
    runner = Runner(
        agent=root_agent, app_name="app", session_service=session_service
    )

    final_text = ""
    async for event in runner.run_async(
        user_id="ci",
        session_id="resolve",
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=prompt)]
        ),
    ):
        if event.is_final_response() and event.content:
            final_text = event.content.parts[0].text

    return Resolution.model_validate_json(final_text)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


async def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Sentinel conflict resolver")
    parser.add_argument("--file", required=True, help="path to conflicted file")
    parser.add_argument("--tdd", required=True, help="path to TDD.md")
    parser.add_argument("--rules", required=True, help="path to rules file")
    args = parser.parse_args()

    conflicted = read(args.file)
    tdd = read(args.tdd)
    rules = read(args.rules)

    if "<<<<<<<" not in conflicted:
        print("No conflict markers found in the file — nothing to resolve.")
        return 0

    print("Running the conflict resolver agent...")
    resolution = await run_agent(build_prompt(conflicted, tdd, rules))

    print("\n=== DECISIONS ===")
    for i, d in enumerate(resolution.decisions, 1):
        print(f"  Hunk {i}: keep '{d.choice}' — {d.reason}")
    print(f"\n=== SUMMARY ===\n{resolution.summary}")
    print("\n=== RESOLVED FILE ===")
    print(resolution.resolved_content)

    if "<<<<<<<" in resolution.resolved_content:
        print("\n⚠️ WARNING: resolved content still contains conflict markers!")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
