# Introduction

This is a requirements document for Sentinel, which is a tool that uses agentic workflows to review PRs, resolve merge conflicts and complete PRs without the involvement of a human reviewer. The repo contains a PRD (product requirements document) and TRD (technical design document). There will be 2 AI agents, one will have skills and instructions to resolve merge conflicts and another will review the functionality of the code against the existing PRD and TDD and decide whether the code that is being reviewed in the PR is in alignment with the over direction and functionality of the code already existing in the repository.

## Checks
When a contributor creates a PR to the repo, the following checks will be done in order:
1. Checks if the title of the PR matches the requirements.
2. Lints the code, ensures that there are no syntax errors, etc.
3. Code coverage will be tested, ensuring that the code that is being pushed will have test cases that cover at least 80% of the code.
4. Agent will review the code and ensure that it is conforming to the PRD and TDD.
5. Agent will ensure that the merge conflicts have been resolved by accepting or rejecting the appropriate changes.
6. The continuous integration (CI) process will run and ensure that the merged code will not break any existing functionality. If any functionality breaks, all the changes will be reverted and PR will be rejected.
7. Once the PR is closed, an email will be sent to the contributor and the repo owner summarizing the changes that were made.

## Technical Requirements 
- This workflow will be applied only to repositories written in Python
- Agents will be written using ADK

