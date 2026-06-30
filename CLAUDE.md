# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sentinel is a tool that uses agentic workflows to automatically review PRs, resolve merge conflicts, and complete PRs without human reviewer involvement. It targets **Python repositories only** and agents are built using **ADK (Agent Development Kit)**.

## Architecture

### Two-Agent System

1. **Merge Conflict Agent** - Resolves merge conflicts by accepting or rejecting incoming changes.
2. **Code Review Agent** - Reviews code against the repository's PRD (Product Requirements Document) and TDD (Technical Design Document) to verify alignment with the project's intended direction.

### PR Workflow (Sequential)

When a contributor opens a PR, Sentinel executes these checks in order:

1. Validate PR title against requirements
2. Lint the code (syntax error checks)
3. Verify test coverage ≥ 80%
4. Code Review Agent validates code against PRD/TDD
5. Merge Conflict Agent resolves conflicts (accept/reject changes)
6. Run CI pipeline — if existing functionality breaks, revert all changes and reject PR
7. Send summary email to contributor and repo owner

## Current State

This repository is in early development. No implementation code exists yet — only the product requirements document (`product-requirements.txt`) and README. The next implementation steps involve:

- Setting up Python project structure and dependency management
- Implementing agents using ADK
- Building the 7-step PR workflow pipeline
- Adding linting configuration and test framework
