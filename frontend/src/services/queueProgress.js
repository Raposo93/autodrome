export function progressLabel(progress) {
  const phases = {
    metadata: 'Loading metadata', manifest: 'Checking playlist', staging: 'Preparing staging',
    downloading: 'Downloading and converting audio', cover: 'Loading cover art',
    tagging: 'Tagging', validating: 'Validating album', publishing: 'Publishing album'
  }
  const label = phases[progress.phase] || progress.phase
  if (progress.phase === 'downloading' && Number.isInteger(progress.total)) {
    return `${label} · track ${progress.current} of ${progress.total} · ${progress.completed} completed`
  }
  return label
}
