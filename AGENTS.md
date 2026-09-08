# Autodrome

## Project

Autodrome is a small self-hosted application for finding album playlists on YouTube, downloading audio, enriching it with MusicBrainz metadata and cover art, tagging the resulting MP3 files, and organizing them into a music library.

The current application is primarily a FastAPI backend with a Vue/Vite frontend. Some older CLI code and documentation still exist and may be obsolete. Do not decide whether to keep or remove the CLI unless the relevant issue explicitly resolves that product decision.

This project handles user files and external services. Prefer correctness, recoverability, and library integrity over cleverness or throughput.

## Development principles

Before changing code, understand the current flow and the responsibility of the affected modules.

Prefer:

- simple solutions that solve the current issue;
- small, coherent changes;
- explicit inputs, outputs, states, and failure modes;
- clear names and narrow responsibilities;
- async code only where the surrounding flow is already async or the problem benefits from it;
- validation before destructive or irreversible file operations;
- useful errors instead of silent fallback when data integrity is at risk;
- tests that describe the behavior required by the issue.

Avoid:

- speculative architecture for future requirements;
- broad refactors while fixing a focused issue;
- unrelated cleanup;
- hidden fallbacks that can produce incomplete or incorrectly tagged albums;
- treating caches as authoritative storage;
- introducing parallel playlist downloads before the sequential flow and queue lifecycle are reliable;
- adding abstractions only to make future concurrency theoretically easier.

Do not optimize for hypothetical scale. Autodrome should first be predictable when one album, one track, an external API, Redis, or a filesystem operation fails.

## Current architecture

Keep the existing responsibility boundaries unless an issue requires changing them:

- `app.py` wires application dependencies and owns FastAPI lifecycle concerns.
- `api/` contains HTTP and WebSocket adapters. Keep endpoints thin: validate input, obtain dependencies, delegate, and translate results to transport responses.
- `autodrome/controllers/` coordinates application workflows.
- `autodrome/services/` contains focused services such as queue management, organization, tagging, cover embedding, Redis caching, and WebSocket state propagation.
- `autodrome/metadata_service.py` handles MusicBrainz/release metadata concerns.
- `autodrome/yt_api.py` and `autodrome/yt_downloader.py` contain YouTube lookup/download behavior.
- `autodrome/models/` contains shared data models.
- `frontend/` contains the Vue/Vite client.
- `tests/` contains backend tests.
- `scripts/` contains legacy or auxiliary command-line tooling; do not assume it is a supported public interface.

Keep domain/application behavior out of FastAPI route handlers when it can reasonably live in controllers, services, or models.

## Integrity rules

These rules are important across issues:

- Redis is a cache, not the source of truth required to finish a download.
- Never silently pair tracks and files when their identity or counts are uncertain.
- Validate an album completely before publishing it to the final library location when practical.
- Do not overwrite existing library content unless an explicit policy or issue requires it.
- Keep paths inside the configured library/staging roots and validate path components before filesystem writes.
- Preserve enough failure context to diagnose or retry a job without pretending it succeeded.
- External API failures must not be confused with valid empty results when the distinction matters.
- Keep playlist downloads sequential for now. Issue #3 is future work and must not be started until its dependencies and the queue are stable.

## Issue priority and dependencies

When choosing work autonomously, first refresh the current open issues and their dependencies. Use issue #13 as the initial backlog ordering while it remains applicable, but prefer current issue state and explicit dependency information over a stale checklist.

The current intended sequence is:

1. P0 integrity/operation work: #4, #5, #15, #7.
2. Repair the test/CI baseline in #6.
3. Implement per-track download foundations in #2, then per-track failure handling in #1.
4. Complete the remaining P1 work, including #8, #9, and #14.
5. Complete P2 robustness/maintenance work such as #10 and #11.
6. Issue #12 requires a product decision about CLI support; do not choose one side autonomously.
7. Consider #3 only after #2, #1, and #7 are complete and stable.

Do not start a dependent issue merely because it looks easy. Finish or verify its prerequisites first.

## Autonomous working method

When asked to work autonomously through issues, continue without requesting confirmation whenever the next step can be determined from the issue, existing code, tests, or established project rules.

For each issue:

1. Read the complete issue and its acceptance criteria.
2. Check referenced/dependent issues when they affect the implementation.
3. Read the relevant existing code and tests before editing.
4. Establish the current behavior or failure mode.
5. Make the smallest coherent change that satisfies part or all of the issue.
6. Add or update tests for changed behavior.
7. Run the relevant checks.
8. Review the diff for unrelated changes, accidental complexity, and unsafe filesystem behavior.
9. Commit the coherent change atomically.
10. If the issue still has independent work remaining, continue with another atomic change and commit.
11. When the issue is complete, move directly to the next actionable issue unless a stop condition below applies.

Do not stop merely because several reasonable implementation techniques exist. Choose the simplest maintainable option consistent with the current architecture and acceptance criteria.

### Stop and ask only when

A human decision is genuinely required, for example:

- the issue explicitly presents unresolved product choices, as in #12;
- acceptance criteria conflict with each other or with a newer explicit project decision;
- intended user-visible behavior cannot be inferred safely from the issue, code, tests, or documentation;
- required credentials, secrets, services, permissions, or external resources are unavailable and there is no local substitute;
- the next action would intentionally destroy user data, rewrite history, or perform another irreversible operation not already authorized by the issue.

When blocked on one issue, do not assume the whole backlog is blocked. If another issue is independent and actionable, continue with that work and report the blocked issue clearly.

## Tests and validation

Run the complete project checks with:

`./check.sh`

Use focused tests during development when useful.

Before each commit, run the checks relevant to that change. Before the final
commit that completes an issue, run `./check.sh`.

The current test suite may contain failures caused by the pre-existing
async/FastAPI migration described in #6. Until #6 is complete:

- establish the relevant baseline when practical;
- do not hide, disable, or delete unrelated failing tests just to obtain green output;
- ensure the current change does not introduce additional relevant failures;
- a known pre-existing failure must not block an otherwise independent issue;
- keep #6-specific repair work inside #6 unless another issue genuinely depends
  on the same small fix.

Once #6 is complete, do not consider an implementation complete while
`./check.sh` is failing.

Tests involving external APIs should use controlled fakes/mocks rather than
depending on live YouTube, MusicBrainz, Cover Art Archive, or Redis availability
unless an explicit integration test requires otherwise.

## Commits

Create commits as you work. Do not wait for a separate request to commit when operating autonomously on this repository.

Commits must be atomic and easy to review:

- Prefer one coherent concern per commit.
- An issue may require several commits when it contains independently understandable steps.
- Never mix unrelated issues in the same commit.
- If a safe prerequisite is useful to more than one issue, give it its own commit and reference the most relevant issue(s) in the message body.
- Do not amend or rewrite earlier commits merely to make history prettier unless explicitly requested.
- Do not push or create a pull request unless the task/environment explicitly asks for it.

All commit messages must be written in English.

Use this title format:

`Type: Imperative summary`

Allowed types:

- `Feat:` new functionality;
- `Fix:` bug fixes;
- `Refactor:` structural improvements without behavior changes;
- `Test:` tests;
- `Docs:` documentation;
- `Chore:` tooling, configuration, dependencies, or maintenance.

Prefer titles under 72 characters and never exceed 100 characters. Use the imperative mood.

Add a body only when the reason, risk, or implementation choice is not obvious.

For intermediate commits belonging to an issue, place the reference on the final line:

`Ref #12`

For the final commit that completes an issue:

`Close #12`

Issue-closing keywords must be separated from the commit body by real newline characters. Never write literal escape sequences such as `\n\nClose #12` into the commit message: GitHub will treat them as text and will not close the issue automatically. Before finishing an issue, inspect the resulting commit message and verify the issue actually changed to `closed`; if it did not, fix the administrative state explicitly instead of assuming the keyword worked.

When one commit intentionally completes multiple tightly coupled issues, reference each explicitly, but prefer separate commits/issues whenever the work can be separated cleanly.

Before every commit:

1. Run the relevant tests/checks for that change.
2. Review the diff.
3. Ensure the commit contains only the intended concern.
4. Verify that logs, fixtures, generated files, secrets, downloaded media, and local environment artifacts are not included accidentally.

## Scope discipline

Issue acceptance criteria define completion, not an invitation to redesign nearby code.

If you discover another problem while implementing an issue:

- fix it immediately only if it is necessary for the current issue and small enough to remain coherent;
- otherwise leave it untouched and report it as follow-up work;
- do not silently expand the issue into a general cleanup project.

Prefer incremental improvement over rewrites. The repo is small enough that a boring solution which can be understood in one sitting is usually the correct one.
