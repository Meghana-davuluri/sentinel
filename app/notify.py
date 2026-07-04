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

"""Email notifications for Sentinel reviews, sent via Resend.

Sends a summary of a review verdict to the PR contributor and repo owner.

Environment:
    RESEND_API_KEY   — Resend API key (required to actually send).
    SENTINEL_EMAIL_FROM — sender address (default onboarding@resend.dev).
"""

import os

import httpx

from app.agent import Review

RESEND_ENDPOINT = "https://api.resend.com/emails"
DEFAULT_FROM = "onboarding@resend.dev"


def build_email_html(repo: str, pr: int, review: Review) -> str:
    """Render the review verdict as an HTML email body."""
    icon = "❌" if review.verdict == "reject" else "✅"
    rows = ""
    for f in review.findings:
        rows += (
            f"<tr><td>{f.severity}</td><td><code>{f.rule_id}</code></td>"
            f"<td><code>{f.file}</code></td><td>{f.explanation}</td></tr>"
        )
    findings_table = (
        f"<table border='1' cellpadding='6' cellspacing='0'>"
        f"<tr><th>Severity</th><th>Rule</th><th>File</th><th>Problem</th></tr>"
        f"{rows}</table>"
        if review.findings
        else "<p>No issues found. 🎉</p>"
    )
    return (
        f"<h2>{icon} Sentinel Review: {review.verdict.upper()}</h2>"
        f"<p><strong>{repo} — PR #{pr}</strong></p>"
        f"<p>{review.summary}</p>"
        f"{findings_table}"
        f"<hr><p><em>Reviewed by Sentinel.</em></p>"
    )


def send_review_email(
    repo: str, pr: int, review: Review, to: list[str]
) -> dict:
    """Send the review summary email via Resend.

    Returns Resend's JSON response. Raises if RESEND_API_KEY is unset or the
    API call fails.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set; cannot send email.")

    sender = os.environ.get("SENTINEL_EMAIL_FROM", DEFAULT_FROM)
    subject = f"[Sentinel] {repo} PR #{pr} — {review.verdict.upper()}"

    resp = httpx.post(
        RESEND_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": sender,
            "to": to,
            "subject": subject,
            "html": build_email_html(repo, pr, review),
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
