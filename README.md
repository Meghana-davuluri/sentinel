<div align="center">

# Sentinel

**Agentic pull-request automation for Python repositories.**

Sentinel reviews pull requests against a project's design documents and
engineering rules, and resolves merge conflicts automatically using
multi-agent workflows built on the [Google Agent Development Kit (ADK)](https://adk.dev).

</div>

---

## Overview

Code review is where a team's design intent is enforced and where generic
tools fall short. A linter checks syntax; it cannot tell that an API handler
sends email synchronously when the design mandates a background queue, or that a
delete will orphan child rows in production.

Sentinel closes that gap. Every pull request runs through a pipeline: the
mechanical checks (title, lint, coverage) are ordinary CI, while the judgment
calls *does this change fit the architecture?* and *which side of a conflict is
correct?*  are made by two ADK agents that read the repository's own design
documents.

## Pipeline

When a pull request is opened, Sentinel executes the following checks in order:

| # | Check | Mechanism | Status |
|---|-------|-----------|:------:|
| 1 | PR title follows convention | CI — Conventional Commits | ✅ |
| 2 | Lint and syntax | CI — `ruff` | ✅ |
| 3 | Test coverage ≥ 80% | CI — `pytest --cov` | ✅ |
| 4 | Code aligns with design (TDD) and rules | **Code Review Agent** | ✅ |
| 5 | Merge conflicts resolved | **Conflict Agent** | ✅ |
| 6 | CI passes; revert on regression | _planned_ | ◻️ |
| 7 | Summary email to author and owner | _planned_ | ◻️ |

> Coverage currently runs in measurement mode; the 80% gate is enabled once the
> agent test suite lands.

## Architecture

```
                          Pull Request
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │              GitHub Actions (CI)              │
        │                                               │
        │   1. Title    2. Lint    3. Coverage          │
        └───────────────────────┬───────────────────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              ▼                                      ▼
    ┌───────────────────┐                 ┌────────────────────┐
    │ Code Review Agent │                 │   Conflict Agent   │
    │      (ADK)        │                 │       (ADK)        │
    └─────────┬─────────┘                 └──────────┬─────────┘
              │  reads diff + TDD + rules            │  reads conflict + TDD + rules
              │  → structured verdict                │  → resolved file, committed
              ▼                                      ▼
      approve / reject                       conflict cleared
      posted to the PR                       pushed to the branch
```

## The agents

### Code Review Agent

Reads a pull request's diff together with the target repository's Technical
Design Document (`design/TDD.md`) and engineering rules (`sentinel.rules.md`),
and returns a structured verdict — approve or reject — with findings that cite
the exact rule or design decision violated.

Because it reasons against the project's *own* documented intent, it detects
design drift that a general-purpose reviewer cannot. Example finding, produced
against the demo repository:

```
❌ Sentinel Review: REJECT

| Severity | Rule                     | File         | Problem                                        |
|----------|--------------------------|--------------|------------------------------------------------|
| blocker  | TDD:notification-flow    | app/api.py   | Sends email synchronously; design requires the |
|          |                          |              | notification to be queued off the request path.|
| blocker  | thin-api                 | app/api.py   | Business/DB logic added to the API layer.      |
| blocker  | cascade-deletes          | app/api.py   | Deletes a Task without its child Reminder rows.|
| blocker  | no-secrets-in-code       | app/worker.py| API key hardcoded in source.                   |
```

### Conflict Agent

Given a file containing Git conflict markers alongside the same design
documents, the agent decides which side of each conflict to keep — guided by the
TDD and rules — produces the fully resolved file, commits it, and pushes to the
pull request branch, clearing the conflict without human intervention.

## Technology

| Concern | Choice |
|---------|--------|
| Agent framework | Google ADK |
| Model | Gemini (`gemini-flash-latest`), structured output via Pydantic schemas |
| Orchestration | GitHub Actions |
| GitHub integration | `gh` CLI (diffs, file contents, comments, pushes) |
| Packaging | `uv`, `ruff`, `pytest` |

The pipeline is split across two workflows: `sentinel.yml` runs the mechanical
checks on Sentinel's own pull requests, and `review.yml` runs the Code Review
Agent against a target repository.

## Repository layout

```
app/
├── agent.py            # Code Review Agent (LlmAgent + Review schema)
├── conflict_agent.py   # Conflict Agent (LlmAgent + Resolution schema)
├── review_pr.py        # Fetch a PR, run the review agent, post the verdict
├── resolve_conflict.py # Run the conflict agent on a single file
└── autoresolve_pr.py   # Clone, merge, resolve, commit, and push a fix
.github/workflows/
├── sentinel.yml        # Mechanical checks (title, lint, coverage)
└── review.yml          # Code Review Agent (manual trigger)
```

## Usage

```bash
# Install dependencies and configure the API key
uv sync --extra lint
echo "GOOGLE_API_KEY=<your-key>"        >> .env   # https://aistudio.google.com/apikey
echo "GOOGLE_GENAI_USE_VERTEXAI=FALSE"  >> .env

# Review a pull request
uv run python -m app.review_pr --repo owner/name --pr 1 --post

# Auto-resolve a merge conflict (dry run without --push)
uv run python -m app.autoresolve_pr --repo owner/name --pr 3 --push
```

In CI, the Gemini key is provided as the repository secret `GOOGLE_API_KEY`.

## Demonstration repository

[`sentinel-demo`](https://github.com/Meghana-davuluri/sentinel-demo) is a small
"Tasks API" with a Technical Design Document and five engineering rules. It
serves as a controlled target: pull requests there contain deliberate design
violations and merge conflicts, against which Sentinel's agents are validated
end to end.

## Scope

Sentinel targets Python repositories, with agents implemented in ADK. It is a
Kaggle capstone submission (Agents track) — a working demonstration of agentic
pull-request automation.
