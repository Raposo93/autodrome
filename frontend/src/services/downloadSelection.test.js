import test from 'node:test'
import assert from 'node:assert/strict'
import { trackCountError } from './downloadSelection.js'

test('known mismatches explain both counts, including empty playlists', () => {
  for (const count of [0, 2]) {
    assert.match(trackCountError({ track_count: count }, { tracks: [{}] }),
      new RegExp(`playlist has ${count} tracks.*release has 1`))
  }
  assert.match(trackCountError({ track_count: 2 }, { track_count: 3 }), /mismatch/)
})

test('matches and unknown counts allow continuing', () => {
  assert.equal(trackCountError({ track_count: 1 }, { tracks: [{}] }), null)
  assert.equal(trackCountError({ track_count: null }, { tracks: [{}] }), null)
  assert.equal(trackCountError({ track_count: 1 }, {}), null)
  assert.equal(trackCountError(null, null), null)
})

test('loaded track list takes precedence over summary counts', () => {
  assert.match(trackCountError({ track_count: 2 }, { tracks: [{}], track_count: 2 }), /mismatch/)
})
