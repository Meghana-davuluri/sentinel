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

"""Sentinel Code Review Agent.

Reviews a PR diff against a target repo's TDD and team rules, and returns a
structured verdict (approve/reject) with findings that cite the violated rule.
"""

from typing import Literal

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types
from pydantic import BaseModel, Field


class Finding(BaseModel):
    """A single problem the reviewer found in the diff."""

    rule_id: str = Field(
        description="The id of the violated rule or design decision, "
        "e.g. 'thin-api', 'cascade-deletes', or 'TDD:notification-flow'."
    )
    file: str = Field(description="The file the problem is in, e.g. 'app/api.py'.")
    severity: Literal["blocker", "warning"] = Field(
        description="'blocker' rejects the PR; 'warning' is advisory only."
    )
    explanation: str = Field(
        description="One or two sentences: what the code does wrong and why it "
        "violates the cited rule."
    )


class Review(BaseModel):
    """The reviewer agent's structured verdict for a PR."""

    verdict: Literal["approve", "reject"] = Field(
        description="'reject' if there is any blocker finding, else 'approve'."
    )
    summary: str = Field(
        description="A short plain-English summary of the review for the PR author."
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="All problems found. Empty list means the code is clean.",
    )


INSTRUCTION = """
You are Sentinel, a senior code reviewer for a Python project. You review a
pull request diff and decide whether it aligns with the project's design
document (TDD) and team engineering rules.

You will be given three things:
1. The project's Technical Design Document (TDD).
2. The team's engineering rules (each has an id like `thin-api`).
3. A unified diff of the code being proposed in the PR.

Your job:
- Read the diff and check it against BOTH the TDD's design decisions and every
  team rule.
- For each violation, produce a finding that cites the exact rule id (or
  `TDD:<topic>` for a design-doc violation), the file, a severity, and a clear
  explanation.
- Mark a finding `blocker` if it violates an explicit design decision or a
  MUST/required rule (these reject the PR). Use `warning` for minor style issues.
- Set `verdict` to `reject` if there is ANY blocker finding, otherwise `approve`.
- Write a short, professional `summary` addressed to the PR author.

Be precise and cite rules. Do not invent rules that were not provided. If the
diff is clean, approve it with an empty findings list.
"""


root_agent = Agent(
    name="code_review_agent",
    # Wrap the model with retries so a transient 503 (busy) doesn't kill a review.
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=5),
    ),
    description="Reviews a PR diff against a repo's TDD and team rules.",
    instruction=INSTRUCTION,
    output_schema=Review,
    output_key="review",
)

app = App(
    root_agent=root_agent,
    name="app",
)
