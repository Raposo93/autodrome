# Download concurrency benchmark

This is a manual, destructive-to-scratch benchmark for issue #44. It exercises
the real playlist downloader and ffmpeg conversion, then runs Autodrome's normal
tagging, staging validation and atomic publication for every tested level. It
does not use MusicBrainz, change `DOWNLOAD_CONCURRENCY`, or widen the supported
production range of `1–4`.

Do not run it in shared CI, on the production host, or against a real library.
Use a disposable host with enough temporary disk space and a playlist whose use
is permitted. Every run downloads and converts the full playlist once per level.

## Before running

Record the host purpose, CPU, memory, storage type, network connection, ffmpeg
and yt-dlp versions, playlist and time window. Stop if the provider returns
errors, the host starts swapping, free space approaches its safety margin, or
normal host responsiveness degrades. A failure above concurrency 4 is an
experimental result, not automatically a product bug.

Preview the plan without network or filesystem writes:

```bash
.venv/bin/python scripts/benchmark_download_concurrency.py \
  --playlist-url 'https://www.youtube.com/playlist?list=REPLACE_ME' \
  --expected-tracks 20 \
  --artist 'Benchmark Artist' \
  --album 'Benchmark Album' \
  --dry-run
```

Run the default `1 → 2 → 4 → 8 → 12 → 20` progression:

```bash
.venv/bin/python scripts/benchmark_download_concurrency.py \
  --playlist-url 'https://www.youtube.com/playlist?list=REPLACE_ME' \
  --expected-tracks 20 \
  --artist 'Benchmark Artist' \
  --album 'Benchmark Album' \
  --output-root /tmp/autodrome-benchmark-YYYYMMDD \
  --confirm-disposable
```

`--output-root` must be a new absolute directory below the system temporary
directory. If omitted, the script creates a uniquely named directory there. It
never deletes results automatically. A known track count is mandatory: manifest
drift or unavailable entries stop the benchmark before audio download.

The runner stops the progression at the first failed level and preserves failed
staging for inspection. `Ctrl+C` is the correct response to live saturation; do
not continue merely to reach 20.

## Results

`results.json` contains machine-readable environment data, the frozen manifest,
per-phase progress, every file checksum and these per-level measurements:

- total album time and tracks per second;
- configured and maximum active track downloads;
- peak concurrent ffmpeg children;
- approximate peak CPU and resident memory for the Python/ffmpeg process tree;
- minimum free space, free-space delta and published bytes;
- attempts and retries by track, provider errors and detected 429/throttling messages;
- final file count, tags, positive duration and atomic publication result.

`results.md` provides the comparison table. The supported recommendation is the
lowest `1–4` level within 90% of the best supported throughput on that host. If a
higher level succeeds, the report calls it experimental; it does not alter the
default of 1 or the production maximum of 4.

Attach both reports and a short note about any visible swapping, storage queueing,
network limitation or provider intervention to #44. Keep the issue open when the
runner exists but no disposable-host result has been collected.
