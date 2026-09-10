import assert from 'node:assert/strict'
import test from 'node:test'

import { createAlbumDestinationCheck } from './albumDestination.js'


const tick = () => new Promise(resolve => setTimeout(resolve, 0))

test('destination checks publish not-found and filesystem error states', async () => {
  const updates = []
  const checks = [
    async () => ({ state: 'not_found', exists: false }),
    async () => { throw { response: { data: { detail: 'Permission denied' } } } },
  ]
  const preflight = createAlbumDestinationCheck(
    destination => checks.shift()(destination),
    update => updates.push(update),
    { delay: 0 },
  )

  preflight.inspect({ artist: 'Artist', album: 'First' })
  await tick()
  assert.equal(updates.at(-1).state, 'not_found')

  preflight.inspect({ artist: 'Artist', album: 'Second' })
  await tick()
  assert.equal(updates.at(-1).state, 'unknown')
  assert.equal(updates.at(-1).error, 'Permission denied')
})

test('a late result cannot overwrite the current destination state', async () => {
  const pending = []
  const updates = []
  const preflight = createAlbumDestinationCheck(
    destination => new Promise(resolve => pending.push({ destination, resolve })),
    update => updates.push(update),
    { delay: 0 },
  )

  preflight.inspect({ artist: 'Artist', album: 'Old' })
  await tick()
  preflight.inspect({ artist: 'Artist', album: 'Current' })
  await tick()
  pending[1].resolve({ state: 'not_found', exists: false })
  await tick()
  pending[0].resolve({ state: 'exists', exists: true })
  await tick()

  assert.equal(updates.at(-1).state, 'not_found')
  assert.equal(pending[1].destination.album, 'Current')
})

test('reset invalidates an in-flight result', async () => {
  let resolve
  const updates = []
  const preflight = createAlbumDestinationCheck(
    () => new Promise(done => { resolve = done }),
    update => updates.push(update),
    { delay: 0 },
  )

  preflight.inspect({ artist: 'Artist', album: 'Album' })
  await tick()
  preflight.reset()
  resolve({ state: 'exists', exists: true })
  await tick()

  assert.equal(updates.at(-1).state, 'idle')
})
