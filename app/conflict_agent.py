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

"""Sentinel Merge Conflict Agent.

Given a file containing Git conflict markers (<<<<<<< / ======= / >>>>>>>) plus
the project's TDD and team rules, this agent decides how to resolve EACH
conflict hunk and returns the fully resolved file content (markers removed).
"""

from typing import Literal

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types
from pydantic import BaseModel, Field


class HunkDecision(BaseModel):
    """The agent's decision for one conflict hunk."""

    choice: Literal["ours", "theirs", "combined"] = Field(
        description="Which side to keep: 'ours' (the PR branch / HEAD side), "
        "'theirs' (the base branch side), or 'combined' (a merge of both)."
    )
    reason: str = Field(
        description="Why this choice aligns with the TDD/rules or is otherwise "
        "correct. Cite a rule id or TDD section when relevant."
    )


class Resolution(BaseModel):
    """The agent's full resolution of a conflicted file."""

    resolved_content: str = Field(
        description="The ENTIRE file content with every conflict resolved and "
        "ALL conflict markers (<<<<<<<, =======, >>>>>>>) removed. This must be "
        "valid, complete source code ready to commit."
    )
    decisions: list[HunkDecision] = Field(
        description="One decision per conflict hunk, in order."
    )
    summary: str = Field(
        description="A short plain-English summary of how the conflict was "
        "resolved, for the PR author."
    )


INSTRUCTION = """
You are Sentinel's merge-conflict resolver for a Python project. You are given a
single source file that contains one or more Git merge conflicts, marked like:

    <<<<<<< HEAD
    ...the PR branch's version ("ours")...
    =======
    ...the base branch's version ("theirs")...
    >>>>>>> origin/main

You also get the project's Technical Design Document (TDD) and team rules.

Your job:
- For EACH conflict hunk, decide whether to keep 'ours', 'theirs', or a
  'combined' version that merges both intents.
- Prefer the side that better matches the TDD's design decisions and the team
  rules. If neither side conflicts with the docs, prefer the PR author's side
  ('ours') since that is the intended change, unless combining is clearly better.
- Produce `resolved_content`: the COMPLETE file with every conflict resolved and
  ALL conflict markers removed. It must be valid Python that could be committed
  as-is. Do not leave any <<<<<<<, =======, or >>>>>>> lines.
- Record one HunkDecision per hunk (in order) explaining your choice.
- Write a short `summary` for the PR author.

Never invent code unrelated to the conflict. Preserve everything outside the
conflict hunks exactly as given.
"""


root_agent = Agent(
    name="conflict_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=5),
    ),
    description="Resolves Git merge conflicts in a file, guided by TDD and rules.",
    instruction=INSTRUCTION,
    output_schema=Resolution,
    output_key="resolution",
)

app = App(
    root_agent=root_agent,
    name="app",
)
