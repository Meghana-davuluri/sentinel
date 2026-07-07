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

"""Integration test for the review pipeline (hits the live Gemini API).

Runs the full investigate -> verdict SequentialAgent on a tiny inline review
prompt and asserts the final output parses as a structured Review. Without
repo context in session state the tools degrade gracefully, so this exercises
the diff-only path.
"""

import os

import pytest
from dotenv import load_dotenv

from app.agent import Review
from app.review_pr import build_prompt, run_agent

load_dotenv()

requires_api_key = pytest.mark.skipif(
    not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_CLOUD_PROJECT")),
    reason="needs GOOGLE_API_KEY (or Vertex project) for a live model call",
)

TDD = """\
# Tasks API — TDD
notification-flow: when a task completes, the user must be emailed. Email is
slow and can fail, so it MUST NOT block the API response: the API enqueues a
job and a background worker sends it. The API must NEVER call
worker.send_email directly.
"""

RULES = """\
- thin-api (MUST): no business or DB logic in the API layer.
- no-secrets-in-code (MUST): never hardcode credentials.
"""

VIOLATING_DIFF = """\
--- a/app/api.py
+++ b/app/api.py
@@ -10,4 +10,6 @@ def complete_task(task_id):
     task.done = True
     db.save(task)
+    # send confirmation right away
+    worker.send_email(task.owner, "task complete")
     return {"ok": True}
"""


@requires_api_key
def test_pipeline_rejects_synchronous_email() -> None:
    """The pipeline must return a valid Review and catch the planted violation."""
    import asyncio

    review = asyncio.run(run_agent(build_prompt(TDD, RULES, VIOLATING_DIFF)))

    assert isinstance(review, Review)
    assert review.verdict == "reject"
    assert any(f.severity == "blocker" for f in review.findings)
    # The verdict must cite the design decision, not a generic style objection.
    cited = " ".join(f.rule_id for f in review.findings)
    assert "notification" in cited or "thin-api" in cited
