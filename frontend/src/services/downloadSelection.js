export function trackCountError(playlist, release) {
  const playlistCount = playlist?.track_count
  const releaseCount = Array.isArray(release?.tracks)
    ? release.tracks.length
    : release?.track_count
  if (Number.isInteger(playlistCount) && Number.isInteger(releaseCount)
      && playlistCount !== releaseCount) {
    return `Track count mismatch: playlist has ${playlistCount} tracks, but the selected release has ${releaseCount}. Choose a matching pair.`
  }
  return null
}
