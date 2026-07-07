# Sentinel — Agentic Pull-Request Review That Understands Your Design

**Track: Agents for Business**

## The problem

Every engineering team spends a large, recurring cost on code review. A senior
engineer reads each pull request to answer one question that no linter can:
*does this change respect how we decided to build this system?* That knowledge
lives in design documents and team conventions — and enforcing it by hand is
slow, inconsistent, and doesn't scale.

Generic AI review tools (Copilot, CodeRabbit, and the like) help with style and
obvious bugs, but they review code against *general* notions of "good code."
They don't know that *this* team decided email must go through a background
queue, or that *this* database has no cascade deletes. So they miss the failures
that actually hurt in production: design drift.

## The solution

**Sentinel** is a multi-agent service that automates pull-request review and
merge-conflict resolution for Python repositories, built on the
[Google Agent Development Kit (ADK)](https://adk.dev). It reads a repository's
*own* design document and engineering rules, and enforces them on every PR - no
human reviewer required.

When a pull request is opened, Sentinel runs a pipeline:

| # | Check | Mechanism |
|---|-------|-----------|
| 1 | PR title follows convention | CI (Conventional Commits) |
| 2 | Lint and syntax | CI (`ruff`) |
| 3 | Test coverage | CI (`pytest --cov`) |
| 4 | **Code aligns with design (TDD) and rules** | **Code Review Agent** |
| 5 | **Merge conflicts resolved** | **Conflict Agent** |
| 6 | Summary emailed to author and owner | Resend |

The mechanical checks are ordinary CI. The judgment calls - *does this fit the
architecture?* and *which side of a conflict is correct?* - are made by two ADK
agents. To close the loop, Sentinel wires up an email API (Resend) so the repo
owner and contributors receive a summary of the verdict once the review is completed.

## The two agents

**Code Review Agent.** Reads a PR's diff together with the target repository's
Technical Design Document and engineering rules, then returns a *structured*
verdict — approve or reject — with findings that cite the exact rule violated. A
Pydantic output schema turns a chatty model into a reliable component: CI can
branch on `verdict == "reject"` and block the merge.

**Conflict Agent.** Given a file with Git conflict markers plus the same design
documents, it decides which side of each conflict to keep, produces the fully
resolved file, commits it, and pushes to the PR branch — clearing the conflict
without a human.

## What makes it different

Sentinel's edge is **intent-awareness**. Because it reasons against the
project's own documented decisions, it catches drift a general reviewer
structurally cannot.

Concrete example, from the demo repository. A PR changes the API to send
completion emails *synchronously*, inside the request handler. It's valid
Python — a linter is happy. But the design document explicitly requires email to
go through a background queue so request latency stays independent of the email
provider. Sentinel rejects the PR and cites the rule:

```
❌ Sentinel Review: REJECT

| Severity | Rule                  | File          | Problem                                    |
|----------|-----------------------|---------------|--------------------------------------------|
| blocker  | TDD:notification-flow | app/api.py    | Sends email synchronously; design requires |
|          |                       |               | the notification to be queued off the      |
|          |                       |               | request path.                              |
| blocker  | thin-api              | app/api.py    | Business/DB logic added to the API layer.  |
| blocker  | no-secrets-in-code    | app/worker.py | API key hardcoded in source.               |
```

A generic tool cannot produce this finding — the "bug" is only a bug relative to
*this team's decision*. That is the business value: Sentinel enforces the
standards a company actually paid to establish.

## Evidence it works

Sentinel is validated against a controlled demonstration repository
([`sentinel-demo`](https://github.com/Meghana-davuluri/sentinel-demo)) — a small
"Tasks API" with a design document and five engineering rules, seeded with PRs
that contain deliberate violations and merge conflicts.

- **Reviewer accuracy: 1.0.** A systematic ADK evaluation over five PR scenarios
  (design violations, a clean PR, and a hard case where the author argues a bad
  change is an improvement) scores **100% correct verdicts** with zero variance.
  In the hard case, Sentinel rejects the change and cites the design document —
  it reasons against the spec rather than rubber-stamping the author.
- **Live on real PRs.** Running against an open PR on `sentinel-demo`, the
  reviewer caught all planted violations and posted its verdict as a PR comment;
  the conflict agent resolved a real merge conflict end to end, flipping the PR
  from *conflicting* to *mergeable*.

## How it's built

| Concern | Choice |
|---------|--------|
| Agent framework | Google ADK (multi-agent) |
| Model | Gemini (`gemini-flash-latest`) with Pydantic structured output |
| Orchestration | GitHub Actions |
| GitHub integration | `gh` CLI — diffs, file contents, comments, pushes |
| Notifications | Resend email API |
| Quality | ADK eval framework, custom verdict-match metric |

The pipeline is split across two workflows so the reviewer (which targets an
external repo) never blocks Sentinel's own PR checks.

## Business impact

- **Cheaper review.** The mechanical and design-conformance checks that consume
  senior-engineer time run automatically on every PR.
- **Consistent standards.** A rule is enforced the same way every time, on every
  PR — not dependent on which reviewer happened to look.
- **Faster merges.** Conflicts are resolved and verdicts delivered in seconds,
  not on the next reviewer's schedule.

## Links

- **Repository:** https://github.com/Meghana-davuluri/sentinel
- **Demonstration repo:** https://github.com/Meghana-davuluri/sentinel-demo

## Scope and honesty

Sentinel targets Python repositories, with agents implemented in ADK. It is a
capstone demonstration, not a hardened production service: the coverage gate is
in measurement mode pending a full agent test suite, and email delivery uses a
sandbox sender until a domain is verified. The core — two working ADK agents
that enforce a repository's own design intent, validated at 1.0 accuracy — is
complete and reproducible.
