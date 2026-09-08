# Autodrome

## Project

Autodrome is a small self-hosted application for finding album playlists on YouTube, downloading audio, enriching it with MusicBrainz metadata and cover art, tagging the resulting MP3 files, and organizing them into a music library.

The supported product is the FastAPI backend with the Vue/Vite frontend. The old public CLI has been removed; auxiliary scripts are not a second supported user interface unless an explicit issue says otherwise.

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
- increasing playlist-track download concurrency without an explicit issue that changes the current sequential policy;
- adding abstractions only to make future concurrency theoretically easier.

Do not optimize for hypothetical scale. Autodrome should first be predictable when one album, one track, an external API, Redis, or a filesystem operation fails.

## Current architecture

Keep the existing responsibility boundaries unless an issue requires changing them:

- `app.py` wires application dependencies and owns FastAPI lifecycle concerns.
- `api/` contains HTTP and WebSocket adapters. Keep endpoints thin: validate input, obtain dependencies, delegate, and translate results to transport responses.
- `autodrome/controllers/` coordinates application workflows.
- `autodrome/services/` contains focused services such as queue management, organization, tagging, cover embedding, Redis caching, and WebSocket state propagation.
- `autodrome/metadata_service.py` handles MusicBrainz/release metadata concerns.
- `autodrome/yt_api.py` handles YouTube search and playlist metadata.
- `autodrome/yt_downloader.py` handles playlist manifest extraction and sequential audio downloads.
- `autodrome/models/` contains shared data models.
- `frontend/` contains the supported Vue/Vite client.
- `tests/` contains backend/API tests; frontend service tests live under `frontend/src/services/`.
- `scripts/` contains auxiliary tooling only.

Keep domain/application behavior out of FastAPI route handlers when it can reasonably live in controllers, services, or models.

## Integrity rules

These rules are important across issues:

- Redis is a cache, not the source of truth required to finish a download.
- Never silently pair tracks and files when their identity or counts are uncertain.
- Validate known playlist/release counts before expensive work when practical, and keep the final staging validation as the authoritative guard before publication.
- Validate an album completely before publishing it to the final library location.
- Do not overwrite existing library content unless an explicit policy or issue requires it.
- Keep paths inside the configured library/staging roots and validate path components before filesystem writes.
- Preserve enough failure context to diagnose or retry a job without pretending it succeeded.
- External API failures must not be confused with valid empty results when the distinction matters.
- A failure from one external provider must not erase valid results from another provider when the product contract supports partial results.
- MusicBrainz request starts must continue to respect the configured request policy and the one-request-per-second cadence.
- Keep playlist-track downloads sequential unless an explicit issue deliberately changes that policy and preserves publication integrity.

## Current issue priority and dependencies

When choosing work autonomously, always refresh the current open issues before starting. Do not use old completed backlog issues as an ordering source.

At the time of this update, the active sequence is:

1. **#26** — validate the real yt-dlp manifest before downloading. This is the highest-priority integrity guard because it can reject a known incomplete playlist before any audio is downloaded.
2. **#25** — reduce YouTube requests used to obtain playlist track counts. Keep the result contract and per-playlist unknown state intact.
3. **#24** — run YouTube and MusicBrainz searches in parallel and support provider-specific partial failure. Preserve successful results from the provider that remains available.

These issues are independently actionable, but prefer the order above unless newer issue state, dependencies, or explicit instructions supersede it.

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
11. When the issue is complete, verify the issue is actually closed, then move directly to the next actionable issue unless a stop condition below applies.

Do not stop merely because several reasonable implementation techniques exist. Choose the simplest maintainable option consistent with the current architecture and acceptance criteria.

### Stop and ask only when

A human decision is genuinely required, for example:

- an issue explicitly presents unresolved product choices;
- acceptance criteria conflict with each other or with a newer explicit project decision;
- intended user-visible behavior cannot be inferred safely from the issue, code, tests, or documentation;
- required credentials, secrets, services, permissions, or external resources are unavailable and there is no local substitute;
- the next action would intentionally destroy user data, rewrite history, or perform another irreversible operation not already authorized by the issue.

When blocked on one issue, do not assume the whole backlog is blocked. If another issue is independent and actionable, continue with that work and report the blocked issue clearly.

## Tests and validation

Run the complete project checks with:

`./check.sh`

Use focused tests during development when useful.

Before each commit, run the checks relevant to that change. Before the final commit that completes an issue, run `./check.sh`.

The baseline test/CI repair is complete. Do not consider an implementation complete while `./check.sh` is failing. Do not hide, disable, or delete unrelated tests merely to obtain green output.

Tests involving external APIs should use controlled fakes/mocks rather than depending on live YouTube, MusicBrainz, Cover Art Archive, or Redis availability unless an explicit integration test requires otherwise.

When changing provider orchestration, test the distinction between:

- valid empty results;
- provider-specific failures;
- partial success where another provider still returned useful data;
- total failure.

When changing download integrity behavior, verify that failures occur before audio download or library mutation whenever the required mismatch is already knowable.

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

Issue-closing keywords must be separated from the commit body by real newline characters. Never write literal escape sequences such as `\n\nClose #12` into the commit message: GitHub will treat them as text and will not close the issue automatically.

Before finishing an issue:

1. Inspect the resulting commit message and confirm the closing keyword is on its own real line.
2. Verify on GitHub that the issue actually changed to `closed`.
3. If it did not close, fix the administrative state explicitly instead of assuming the keyword worked.

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
