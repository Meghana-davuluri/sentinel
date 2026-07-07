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

"""Unit tests for the investigator's repo tools (no network, no API key)."""

import base64
import json
import subprocess
from unittest import mock

from app import repo_tools
from app.repo_tools import MAX_FILE_CHARS, MAX_READS, list_files, read_file


class FakeToolContext:
    """Stands in for ADK's ToolContext: just carries session state."""

    def __init__(self, state: dict | None = None):
        self.state = state if state is not None else {}


def ctx_with_repo(**extra) -> FakeToolContext:
    return FakeToolContext({"repo": "owner/name", "head_sha": "abc123", **extra})


def completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --- graceful degradation -----------------------------------------------


def test_read_file_without_repo_context_returns_error():
    result = read_file("app/api.py", FakeToolContext())
    assert "error" in result
    assert "diff alone" in result["error"]


def test_list_files_without_repo_context_returns_error():
    result = list_files("app", FakeToolContext())
    assert "error" in result


# --- path validation ------------------------------------------------------


def test_read_file_rejects_path_traversal():
    for bad in ("../secrets.txt", "a/../../b", "/etc/passwd", "~/x"):
        result = read_file(bad, ctx_with_repo())
        assert "error" in result, f"{bad!r} should be rejected"
        assert "invalid path" in result["error"]


def test_list_files_rejects_traversal():
    result = list_files("../other-repo", ctx_with_repo())
    assert "error" in result


# --- read_file behavior ----------------------------------------------------


@mock.patch.object(repo_tools.subprocess, "run")
def test_read_file_decodes_content_and_counts_reads(mock_run):
    content = "def enqueue_email():\n    queue.put('email')\n"
    encoded = base64.b64encode(content.encode()).decode()
    mock_run.return_value = completed(stdout=encoded)

    ctx = ctx_with_repo()
    result = read_file("app/queue.py", ctx)

    assert result == {"path": "app/queue.py", "content": content, "truncated": False}
    assert ctx.state["tool_read_count"] == 1
    # The gh call pins to the head SHA from state, not anything model-supplied.
    called = mock_run.call_args[0][0]
    assert "repos/owner/name/contents/app/queue.py?ref=abc123" in called


@mock.patch.object(repo_tools.subprocess, "run")
def test_read_file_truncates_large_files(mock_run):
    big = "x" * (MAX_FILE_CHARS + 1000)
    mock_run.return_value = completed(
        stdout=base64.b64encode(big.encode()).decode()
    )
    result = read_file("big.py", ctx_with_repo())
    assert result["truncated"] is True
    assert len(result["content"]) == MAX_FILE_CHARS


def test_read_file_enforces_read_limit():
    ctx = ctx_with_repo(tool_read_count=MAX_READS)
    result = read_file("app/api.py", ctx)
    assert "error" in result
    assert "limit" in result["error"]


@mock.patch.object(repo_tools.subprocess, "run")
def test_read_file_gh_failure_is_an_error_not_an_exception(mock_run):
    mock_run.return_value = completed(returncode=1, stderr="HTTP 404: Not Found")
    result = read_file("missing.py", ctx_with_repo())
    assert "error" in result
    assert "missing.py" in result["error"]


# --- list_files behavior ----------------------------------------------------


@mock.patch.object(repo_tools.subprocess, "run")
def test_list_files_returns_entries(mock_run):
    listing = [
        {"name": "api.py", "path": "app/api.py", "type": "file", "sha": "x"},
        {"name": "sub", "path": "app/sub", "type": "dir", "sha": "y"},
    ]
    mock_run.return_value = completed(stdout=json.dumps(listing))
    result = list_files("app", ctx_with_repo())
    assert result["entries"] == [
        {"path": "app/api.py", "type": "file"},
        {"path": "app/sub", "type": "dir"},
    ]


@mock.patch.object(repo_tools.subprocess, "run")
def test_list_files_on_a_file_path_is_an_error(mock_run):
    mock_run.return_value = completed(stdout=json.dumps({"name": "api.py"}))
    result = list_files("app/api.py", ctx_with_repo())
    assert "error" in result
