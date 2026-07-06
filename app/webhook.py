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

"""Sentinel webhook — makes PR review fully automatic.

A minimal FastAPI service that receives GitHub 'pull_request' webhooks, verifies
the signature, and runs the reviewer agent against the PR that just opened. Meant
to run on Cloud Run.

Environment:
    GITHUB_WEBHOOK_SECRET — shared secret configured on the GitHub webhook (HMAC).
    GOOGLE_API_KEY        — Gemini key for the agent.
    GH_TOKEN / GITHUB_TOKEN — token the review script uses to read/post on the PR.
"""

import hashlib
import hmac
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

from app.review_pr import (
    RULES_PATH,
    TDD_PATH,
    build_prompt,
    fetch_diff,
    fetch_file,
    format_comment,
    post_comment,
    run_agent,
)

load_dotenv()

app = FastAPI(title="Sentinel Webhook")


def verify_signature(body: bytes, signature: str | None) -> bool:
    """Verify GitHub's HMAC-SHA256 signature (X-Hub-Signature-256 header)."""
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not secret:
        # No secret configured -> reject, so we never run unauthenticated.
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/")
def health() -> dict:
    return {"status": "ok", "service": "sentinel-webhook"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"event {x_github_event}"}

    payload = await request.json()
    action = payload.get("action")
    if action not in ("opened", "reopened", "synchronize"):
        return {"status": "ignored", "reason": f"action {action}"}

    repo = payload["repository"]["full_name"]
    pr = payload["number"]

    # Run the reviewer, same pipeline as the CLI script.
    diff = fetch_diff(repo, pr)
    tdd = fetch_file(repo, TDD_PATH)
    rules = fetch_file(repo, RULES_PATH)
    review = await run_agent(build_prompt(tdd, rules, diff))
    post_comment(repo, pr, format_comment(review))

    return {
        "status": "reviewed",
        "repo": repo,
        "pr": pr,
        "verdict": review.verdict,
    }
