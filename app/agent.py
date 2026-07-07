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

"""Sentinel Code Review Pipeline.

A two-stage SequentialAgent:

1. ``context_investigator`` — reads the diff and, when the diff alone is
   ambiguous (calls code it doesn't show, subclasses something unseen), uses
   repo tools to fetch the missing context. Writes its notes to session state.
   It has tools, so it cannot use a structured output schema.
2. ``code_review_agent`` — judges the diff against the TDD + team rules,
   weighing the investigator's verified notes, and returns a structured
   verdict (approve/reject). It has an output schema, so it cannot use tools.

That ADK constraint (output_schema and tools are mutually exclusive on one
agent) is exactly why this is a pipeline of two agents rather than one.
"""

from typing import Literal

from google.adk.agents import Agent, SequentialAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types
from pydantic import BaseModel, Field

from app.repo_tools import list_files, read_file


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


def _model() -> Gemini:
    # Wrap the model with retries so a transient 503 (busy) doesn't kill a review.
    return Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=5),
    )


INVESTIGATOR_INSTRUCTION = """
You are the investigation phase of Sentinel, a code reviewer for a Python
project. You will be given the project's Technical Design Document (TDD), the
team's engineering rules, and a unified diff of a pull request.

Your job is NOT to deliver a verdict. Your job is to gather the context the
reviewer will need:

- Read the diff. Identify places where correctness against the TDD/rules
  depends on code the diff does NOT show: functions it calls, classes it
  extends, modules it imports, config it reads.
- For each such gap, use `read_file` to fetch the relevant file (use
  `list_files` first if you are unsure where something is defined). Fetch at
  most 5 files — only what the verdict actually depends on.
- If a tool returns an error saying no repository context is available, do not
  retry; analyze the diff alone.

Then write concise investigation notes:
- What you checked and what you found (e.g. "read app/queue.py:
  `enqueue_email` really does enqueue a background job — the diff's call is
  async-safe").
- Anything you verified that bears on a TDD decision or team rule, citing the
  rule id.
- What you could not verify.

Do not speculate beyond what you read. The notes must only contain facts from
the diff or fetched files.
"""


REVIEWER_INSTRUCTION = """
You are Sentinel, a senior code reviewer for a Python project. You review a
pull request diff and decide whether it aligns with the project's design
document (TDD) and team engineering rules.

You will be given three things:
1. The project's Technical Design Document (TDD).
2. The team's engineering rules (each has an id like `thin-api`).
3. A unified diff of the code being proposed in the PR.

An investigator has already examined the repository and may have fetched files
the diff does not show. Its verified notes are below — treat them as facts
about the codebase and weigh them in your findings:

{context_notes?}

Your job:
- Read the diff and check it against BOTH the TDD's design decisions and every
  team rule.
- For each violation, produce a finding that cites the exact rule id (or
  `TDD:<topic>` for a design-doc violation), the file, a severity, and a clear
  explanation.
- Mark a finding `blocker` if it violates an explicit design decision or a
  MUST/required rule (these reject the PR). Use `warning` for minor style issues.
- Do NOT report a violation the investigator's notes disprove (e.g. a call that
  looks synchronous but was verified to enqueue a background job).
- Set `verdict` to `reject` if there is ANY blocker finding, otherwise `approve`.
- Write a short, professional `summary` addressed to the PR author.

Be precise and cite rules. Do not invent rules that were not provided. If the
diff is clean, approve it with an empty findings list.
"""


investigator_agent = Agent(
    name="context_investigator",
    model=_model(),
    description="Fetches repository context the PR diff does not show.",
    instruction=INVESTIGATOR_INSTRUCTION,
    tools=[read_file, list_files],
    output_key="context_notes",
)

verdict_agent = Agent(
    name="code_review_agent",
    model=_model(),
    description="Reviews a PR diff against a repo's TDD and team rules.",
    instruction=REVIEWER_INSTRUCTION,
    output_schema=Review,
    output_key="review",
)

# ADK 2.3 deprecation-warns SequentialAgent in favor of the new graph-based
# Workflow API. Workflow is still undocumented for agent pipelines, so we stay
# on SequentialAgent (functional, removal only "in future versions") for now.
root_agent = SequentialAgent(
    name="code_review_pipeline",
    description="Two-stage PR review: investigate missing context, then "
    "deliver a structured verdict.",
    sub_agents=[investigator_agent, verdict_agent],
)

app = App(
    root_agent=root_agent,
    name="app",
)
