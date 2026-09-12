import assert from 'node:assert/strict'
import test from 'node:test'

import { formatBytes, statusEntries, statusLabel } from './systemStatus.js'


test('diagnostic states have explicit user-facing labels', () => {
  assert.equal(statusLabel('ok'), 'OK')
  assert.equal(statusLabel('warning'), 'Warning')
  assert.equal(statusLabel('error'), 'Error')
  assert.equal(statusLabel('disabled'), 'Disabled')
  assert.equal(statusLabel('unexpected'), 'Unknown')
})

test('components use a stable display order and preserve their details', () => {
  const entries = statusEntries({
    worker: { status: 'ok', state: 'idle' },
    library: { status: 'ok', free_bytes: 1024 },
    js_runtime: { status: 'warning', message: 'Deno missing' },
    yt_dlp: { status: 'ok', message: 'yt-dlp test' },
    redis: { status: 'disabled' },
  })

  assert.deepEqual(
    entries.map(entry => entry.key),
    ['library', 'yt_dlp', 'js_runtime', 'redis', 'worker'],
  )
  assert.equal(entries[0].free_bytes, 1024)
  assert.equal(entries[4].state, 'idle')
})

test('free space uses binary units without inventing invalid values', () => {
  assert.equal(formatBytes(0), '0 B')
  assert.equal(formatBytes(1024 ** 3), '1.0 GiB')
  assert.equal(formatBytes(183 * 1024 ** 3), '183 GiB')
  assert.equal(formatBytes(-1), null)
  assert.equal(formatBytes(undefined), null)
})
