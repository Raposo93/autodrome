const componentDefinitions = [
  ['library', 'Library'],
  ['staging', 'Staging'],
  ['queue_storage', 'Queue state'],
  ['ffmpeg', 'ffmpeg'],
  ['youtube', 'YouTube'],
  ['musicbrainz', 'MusicBrainz'],
  ['redis', 'Redis'],
  ['worker', 'Queue worker'],
]

const labels = {
  ok: 'OK',
  warning: 'Warning',
  error: 'Error',
  disabled: 'Disabled',
}

export function statusEntries(components = {}) {
  return componentDefinitions
    .filter(([key]) => components[key])
    .map(([key, label]) => ({ key, label, ...components[key] }))
}

export function statusLabel(status) {
  return labels[status] || 'Unknown'
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return null
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  const precision = value >= 10 || unit === 0 ? 0 : 1
  return `${value.toFixed(precision)} ${units[unit]}`
}
