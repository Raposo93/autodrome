import assert from 'node:assert/strict'
import test from 'node:test'
import { progressLabel } from './queueProgress.js'

test('queue explains real phases and counts without inventing percentages', () => {
  assert.equal(progressLabel({ phase: 'downloading', current: 3, total: 12, completed: 2 }),
    'Downloading and converting audio · track 3 of 12 · 2 completed')
  assert.equal(progressLabel({ phase: 'validating' }), 'Validating album')
  assert.equal(progressLabel({ phase: 'publishing' }), 'Publishing album')
})
