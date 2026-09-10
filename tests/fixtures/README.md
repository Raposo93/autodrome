# Adversarial fixtures

These fixtures are deterministic, local, and require no provider credentials.
They model provider responses instead of treating Redis or a live playlist as a
source of truth.

- `playlist_from_hell.json` is raw yt-dlp-style data. Positions 4–6 are private,
  deleted, or lack an identity/URL and must make preflight fail rather than
  silently producing a shorter valid manifest. Its valid entries cover Unicode,
  combining characters, emoji, duplicate titles with distinct video IDs,
  sanitization collisions, and a long filename-safe title.
- `complex_release.json` is raw MusicBrainz-style data plus the normalized API
  shape expected by the frontend. It covers two discs, duplicate titles with
  distinct positions, track artists, a collaboration join phrase, recording-level
  credits, and explicit `Unknown`/album-artist fallbacks for missing metadata.
- `generated_playlist()` creates the 99, 100, and 101-track playlist boundaries.
  Every video ID encodes the original audio identity.
- `generated_musicbrainz_release()` creates matching single- or multi-disc
  releases. Unique titles and artists encode global identity so tests detect an
  audio/metadata swap even when counts still match.

Keep compact scenarios in JSON so backend and frontend tests can share them. Use
the generators for large boundaries to keep reviews and diffs readable.
