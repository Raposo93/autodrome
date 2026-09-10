import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createReleaseHydration } from './releaseHydration.js'

const complexReleaseFixture = JSON.parse(readFileSync(
  new URL('../../../tests/fixtures/complex_release.json', import.meta.url),
  'utf8',
))

const flush = () => new Promise(resolve => setImmediate(resolve))
function setup() {
  const calls = [], updates = []
  const hydrator = createReleaseHydration(id => new Promise((resolve, reject) => {
    calls.push({ id, resolve, reject })
  }), (id, value) => updates.push({ id, ...value }))
  return { hydrator, calls, updates }
}

test('progressive details prioritize selected candidate and reuse loaded data', async () => {
  const { hydrator, calls, updates } = setup()
  const releases = ['a', 'b', 'c'].map(id => ({ id }))
  hydrator.start(releases)
  assert.deepEqual(calls.map(c => c.id), ['a'])
  hydrator.prioritize('c')
  calls[0].resolve({ id: 'a', tracks: [1] })
  await flush()
  assert.equal(updates.find(u => u.id === 'a' && u.hydration === 'ready').tracks[0], 1)
  assert.deepEqual(calls.map(c => c.id), ['a', 'c'])
  calls[1].resolve({ id: 'c', tracks: [3] })
  await flush()
  calls[2].resolve({ id: 'b', tracks: [2] })
  await flush()
  hydrator.start(releases)
  assert.equal(calls.length, 3)
  assert.equal(updates.at(-1).hydration, 'ready')
})

test('new search invalidates old completion and abandons old pending requests', async () => {
  const { hydrator, calls, updates } = setup()
  hydrator.start([{ id: 'old' }, { id: 'unused' }])
  hydrator.reset()
  hydrator.start([{ id: 'new' }])
  calls[0].resolve({ tracks: [1] })
  await flush()
  assert.deepEqual(calls.map(c => c.id), ['old', 'new'])
  assert.equal(updates.some(u => u.id === 'old' && u.hydration === 'ready'), false)
  calls[1].resolve({ tracks: [2] })
  await flush()
  assert.equal(updates.at(-1).id, 'new')
})

test('isolated failure continues and selecting failed candidate retries', async () => {
  const { hydrator, calls, updates } = setup()
  hydrator.start([{ id: 'bad' }, { id: 'good' }])
  calls[0].reject(new Error('offline'))
  await flush()
  assert.equal(updates.find(u => u.id === 'bad' && u.hydration === 'error').hydrationError.includes('retry'), true)
  calls[1].resolve({ tracks: [] })
  await flush()
  hydrator.prioritize('bad')
  assert.deepEqual(calls.map(c => c.id), ['bad', 'good', 'bad'])
  calls[2].resolve({ tracks: [] })
  await flush()
  assert.equal(updates.at(-1).hydration, 'ready')
})

test('shared complex release keeps track identities and artist fallbacks', async () => {
  const release = complexReleaseFixture.expected_api
  const updates = []
  const hydrator = createReleaseHydration(
    async id => ({ ...release, id }),
    (id, value) => updates.push({ id, ...value }),
  )

  hydrator.start([{ id: release.id }])
  await flush()

  const hydrated = updates.find(update => update.hydration === 'ready')
  assert.deepEqual(
    hydrated.tracks.map(track => [track.disc_number, track.position, track.artist]),
    [
      [1, 1, 'Alice'],
      [1, 2, 'Bob feat. Carol'],
      [2, 1, 'Dvořák Ensemble'],
      [2, 2, null],
    ],
  )
  assert.equal(hydrated.artist, 'Various Artists')
  assert.equal(hydrated.tracks.at(-1).title, 'Unknown')
})
