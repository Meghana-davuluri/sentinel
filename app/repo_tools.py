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

"""ADK tools that let the reviewer investigate the repository under review.

The diff alone is often ambiguous: it may call a helper whose definition is not
in the diff, subclass something unseen, or read config defined elsewhere. These
tools let the investigator agent fetch exactly the context it needs.

Design rules:
- The repo coordinates (owner/name + head commit SHA) come from SESSION STATE,
  never from the model, so a malicious diff cannot steer the tools at another
  repository.
- Tools never raise: every failure is returned as an ``{"error": ...}`` dict so
  a bad path or missing context degrades the review instead of killing it.
  When no repo context is in state (evals, unit tests), the agent is told to
  proceed from the diff alone.
"""

import base64
import json
import subprocess

from google.adk.tools import ToolContext

# Truncate fetched files beyond this many characters.
MAX_FILE_CHARS = 50_000
# Soft cap on file reads per review, enforced via a session-state counter.
MAX_READS = 5

_NO_CONTEXT_ERROR = (
    "no repository context available — analyze the diff alone and say so in "
    "your notes"
)


def _gh_api(path: str, jq: str | None = None) -> str:
    """Call `gh api <path>` and return stdout; raises on failure."""
    cmd = ["gh", "api", path]
    if jq:
        cmd += ["--jq", jq]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh api failed")
    return result.stdout


def _repo_ref(tool_context: ToolContext) -> tuple[str, str] | None:
    """The repo + head SHA under review, from session state (never the model)."""
    repo = tool_context.state.get("repo")
    ref = tool_context.state.get("head_sha")
    if not repo or not ref:
        return None
    return repo, ref


def read_file(path: str, tool_context: ToolContext) -> dict:
    """Read one file from the repository under review, at the PR's head commit.

    Use this when the diff references code you cannot see — a called function,
    a base class, a config value — and the verdict depends on what that code
    actually does.

    Args:
        path: Repo-relative file path, e.g. "app/worker.py".

    Returns:
        {"path", "content", "truncated"} on success, or {"error": ...} if the
        file cannot be read (proceed with the diff alone in that case).
    """
    ctx = _repo_ref(tool_context)
    if ctx is None:
        return {"error": _NO_CONTEXT_ERROR}
    repo, ref = ctx

    if path.startswith(("/", "~")) or ".." in path:
        return {"error": f"invalid path: {path!r}"}

    reads = tool_context.state.get("tool_read_count", 0)
    if reads >= MAX_READS:
        return {
            "error": f"file-read limit ({MAX_READS}) reached — decide with "
            "the context you already have"
        }
    tool_context.state["tool_read_count"] = reads + 1

    try:
        raw = _gh_api(f"repos/{repo}/contents/{path}?ref={ref}", jq=".content")
        content = base64.b64decode(raw).decode("utf-8", errors="replace")
    except Exception as exc:
        return {"error": f"could not read {path!r}: {exc}"}

    truncated = len(content) > MAX_FILE_CHARS
    if truncated:
        content = content[:MAX_FILE_CHARS]
    return {"path": path, "content": content, "truncated": truncated}


def list_files(directory: str, tool_context: ToolContext) -> dict:
    """List the files in one directory of the repository under review.

    Use this to locate where something is defined before reading it.

    Args:
        directory: Repo-relative directory path, e.g. "app". Use "" for the
            repository root.

    Returns:
        {"directory", "entries": [{"path", "type"}, ...]} on success, or
        {"error": ...} on failure.
    """
    ctx = _repo_ref(tool_context)
    if ctx is None:
        return {"error": _NO_CONTEXT_ERROR}
    repo, ref = ctx

    directory = directory.strip("/")
    if directory.startswith("~") or ".." in directory:
        return {"error": f"invalid directory: {directory!r}"}

    try:
        out = _gh_api(f"repos/{repo}/contents/{directory}?ref={ref}")
        entries = json.loads(out)
    except Exception as exc:
        return {"error": f"could not list {directory!r}: {exc}"}

    if isinstance(entries, dict):  # a file path, not a directory
        return {"error": f"{directory!r} is a file, not a directory"}

    return {
        "directory": directory,
        "entries": [{"path": e["path"], "type": e["type"]} for e in entries],
    }
