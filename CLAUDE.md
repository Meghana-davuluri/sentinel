# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sentinel is agentic pull-request automation for **Python repositories only**. It reviews PRs against a project's design documents and engineering rules, and resolves merge conflicts, using two agents built on the **Google Agent Development Kit (ADK)** with **Gemini** (`gemini-flash-latest`). Orchestration is GitHub Actions; GitHub access is via the `gh` CLI. It is a Kaggle capstone submission (Agents track).

## Commands

```bash
uv sync --extra lint                 # install deps + linters (ruff, ty, codespell)
uv run ruff check .                  # lint (matches the CI check)
uv run ruff check --fix .            # lint + autofix
uv run pytest                        # run all tests
uv run pytest tests/unit             # unit tests only (what CI coverage runs on)
uv run pytest tests/unit/test_repo_tools.py::test_read_file_rejects_path_traversal   # single test
uv run pytest --cov=app --cov-report=term-missing   # coverage (80% gate is planned, not yet enforced)

# Run the agents against a real GitHub PR (needs GOOGLE_API_KEY in .env and gh auth)
uv run python -m app.review_pr --repo owner/name --pr 1 --post
uv run python -m app.resolve_conflict --file path/to/conflicted.py --tdd path/to/TDD.md --rules path/to/rules.md
```

Local runs need a `.env` with `GOOGLE_API_KEY=<key>` (from https://aistudio.google.com/apikey) and `GOOGLE_GENAI_USE_VERTEXAI=FALSE`. In CI the key comes from the `GOOGLE_API_KEY` repo secret; `load_dotenv()` is a harmless no-op there.

## Architecture

### The agents (`app/agent.py`, `app/repo_tools.py`, `app/conflict_agent.py`)

All LLM agents wrap `Gemini(..., retry_options=...)` (retries guard against transient 503s) with detailed `INSTRUCTION` prompts.

- **Code Review Pipeline** (`app/agent.py`) — a two-stage `SequentialAgent` (`root_agent`, name `code_review_pipeline`). Stage 1, `context_investigator`, has the `read_file`/`list_files` tools from `app/repo_tools.py` and writes notes to session state (`output_key="context_notes"`). Stage 2, `code_review_agent`, has `output_schema=Review` and reads the notes via the `{context_notes?}` instruction template. **This split is forced by ADK: an agent with `output_schema` cannot have tools.** `Review` schema: `verdict` approve/reject, `summary`, list of `Finding` (a `blocker` finding forces `reject`; `warning` is advisory).
- **Repo tools** (`app/repo_tools.py`) — read the repo coordinates (`repo`, `head_sha`) from **session state**, never from the model (prompt-injection guard). They never raise: all failures return `{"error": ...}` dicts, so with no repo context (evals, tests) the pipeline degrades to a diff-only review. Reads are capped (`MAX_READS=5` via a state counter, `MAX_FILE_CHARS` truncation); `RunConfig(max_llm_calls)` in `review_pr.py` is the hard ceiling.
- **Conflict Agent** (`app/conflict_agent.py`) → `Resolution` schema (full `resolved_content` with all conflict markers removed, one `HunkDecision` per hunk, `summary`). Chooses `ours`/`theirs`/`combined` per hunk, preferring the side that matches the design docs.

Both agents read the target repo's source-of-truth docs, whose paths are hardcoded in `app/review_pr.py`:
- `design/TDD.md` — Technical Design Document
- `sentinel.rules.md` — team engineering rules (each rule has an id like `thin-api`)

### CLI drivers (`app/review_pr.py`, `app/resolve_conflict.py`, `app/autoresolve_pr.py`)

These wire an agent to real inputs. Each builds a prompt embedding the TDD + rules + the diff/conflicted file, runs the agent via an ADK `Runner` + `InMemorySessionService`, parses the final event's text with `Model.model_validate_json`, and acts on the result. `review_pr.py` additionally fetches PR data via `gh`, formats the verdict as a Markdown PR comment (posted with `--post`), optionally emails a summary via Resend (`--email`), and **exits non-zero on `reject`** so it fails as a CI check.

- `resolve_conflict.py` — brain-only slice: runs the conflict agent on one conflicted file and prints the resolution (no git).
- `autoresolve_pr.py` — full pipeline: clones the target repo, merges base to surface conflicts, resolves each file with the agent, then commits + pushes to the PR branch (dry run unless `--push`).

### Pipeline (7 steps, PR workflow)

Steps run in order:
1. PR title = Conventional Commits — CI (`sentinel.yml`) ✅
2. Lint / syntax — CI `ruff` ✅
3. Coverage ≥ 80% — CI `pytest --cov`, currently measure-only ✅ (gate planned)
4. Code aligns with TDD + rules — **Code Review Agent** ✅
5. Merge conflicts resolved — **Conflict Agent** ✅
6. CI passes; revert on regression — planned ◻️
7. Summary email to author + owner — Resend via `--email` ✅

### GitHub Actions (`.github/workflows/`)

- `sentinel.yml` — runs on Sentinel's *own* PRs; does the mechanical checks (title, lint, coverage).
- `review.yml` — `workflow_dispatch` (manual); runs the Code Review Agent against a **target** repo/PR you choose.
- `resolve.yml` — `workflow_dispatch` (manual); runs the Conflict Agent (`autoresolve_pr.py`) against a target PR. Dry run unless `push=true`.

Both agent workflows use `SENTINEL_REVIEW_TOKEN` for `gh` and `GOOGLE_API_KEY` for Gemini.

### Live deployment (`app/webhook.py`, `Dockerfile`, `deploy_webhook.sh`)

The Code Review Agent also runs as a **live Cloud Run webhook**: a FastAPI service (`app/webhook.py`) that verifies GitHub's HMAC signature, then runs the reviewer in a background task and posts the verdict — no manual trigger. Deploy with `deploy_webhook.sh` (needs `--no-cpu-throttling` so the background task keeps CPU after the response). The GitHub webhook must be set to the `pull_request` event with the shared `GITHUB_WEBHOOK_SECRET`.

The demo target is [`sentinel-demo`](https://github.com/Meghana-davuluri/sentinel-demo), a "Tasks API" seeded with deliberate design violations and conflicts.

### ADK scaffolding

`app/fast_api_app.py`, `app/app_utils/`, `agents-cli-manifest.yaml`, and `tests/eval/` come from the `agents-cli` (`acli`) ADK base template — a FastAPI/A2A server-hosting layer and eval harness. This is boilerplate around the agents, not core Sentinel logic; the real work lives in the four `app/*.py` files above.

## Conventions

- PR titles must follow Conventional Commits (`feat:`, `fix:`, `docs:`, etc.) — enforced in CI.
- `ruff` line-length is 88 but `E501` (line too long) is ignored; `C901` and `B006` also ignored. Config in `pyproject.toml`.
- Tests are split into `tests/unit`, `tests/integration` (hits the live model, needs an API key), and `tests/eval`.
