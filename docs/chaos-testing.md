# Reproducible chaos testing

Autodrome's chaos runner is an opt-in test tool. It never talks to YouTube,
MusicBrainz, Redis or a real music library. Every backend run creates a new
temporary library, staging directory and queue, uses simulated providers and
deletes that disposable root when the run finishes.

The normal test suite runs two small known seeds as regression. A manual run
executes both the durable album workflow and the browser selection race:

```bash
python scripts/chaos_test.py --seed 666
```

Run only one scenario when investigating it:

```bash
python scripts/chaos_test.py --scenario album-download --seed 666
python scripts/chaos_test.py --scenario selection-race --seed 666
```

Explore a larger consecutive range without changing production configuration:

```bash
python scripts/chaos_test.py --seed 1000 --runs 100
```

Add `--verbose` only when the normal application lifecycle logs are useful; the
ordered chaos events are always retained for a failure report.

The album campaign generates its complete plan from `random.Random(seed)` before
starting asynchronous work. It always combines success, simulated provider
latency and timeout/429, a particular track failure, `ENOSPC` at publication,
a durable queue-write failure, cancellation of a running job and a worker
restart. The order, track counts, failing track and supported test concurrency
(`1–4`) vary with the seed. Named deterministic points from
`tests/fault_injection.py` inject the faults; there are no production chaos
flags or random monkeypatches.

After the initial failures the runner removes them, retries every failed or
interrupted job and verifies all of these invariants:

- no partial or unvalidated album was published;
- an existing album cannot be enqueued again or overwritten;
- persisted queue state exactly matches the explainable terminal job state;
- provider failure remains a provider failure rather than an empty success;
- running cancellation never reaches publication;
- restart preserves the interrupted job, continues queued work and permits an
  explicit successful retry;
- the final state has no unresolved durable-storage error.

The browser scenario uses the controlled Playwright backend and permutes stale
playlist/release completion order from the same seed. It asserts that only the
newest selection can own Review.

Every campaign has an event cap and a wall-clock timeout. A backend failure
prints the seed, ordered event sequence, last durable state and an exact
`scripts/chaos_test.py` reproduction command. A browser failure includes the
same seed, response order and reproduction command in the thrown error. Keep the
seed unchanged while debugging; changing code, configuration or the chaos
harness version can intentionally change its sequence.

## Recorded acceptance campaign

The issue-closing campaign ran on 2026-09-16:

- backend regression seeds `666` and `20260916` passed and replayed stable plans,
  events and final states;
- backend exploration seeds `1000–1099` all passed; every run ended with one
  intentional cancellation, three explained failures, one explained
  interruption and six successful original/recovery jobs;
- browser seeds `666` and `20260916` passed with different seeded completion
  orders;
- `./check.sh` passed with 379 backend tests, 41 frontend unit tests and 20
  Playwright E2E tests.

All campaign storage lived under temporary directories and all providers were
controlled fakes.
