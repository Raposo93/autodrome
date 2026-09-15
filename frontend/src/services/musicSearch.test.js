import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { createReleaseHydration } from './releaseHydration.js'
import { parse } from '@vue/compiler-sfc'

// Exercise the component's actual search method without a browser or live APIs.
const source = readFileSync(new URL('../components/MusicSearch.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = descriptor.script.content
  .replace(/^import .*$/gm, '')
  .replace('export default', 'component =')

function setup(combinedSearch, playlistPreflight = async () => ({ data: { track_count: 1 } })) {
  const context = vm.createContext({
    createReleaseHydration,
    api: { combinedSearch, playlistPreflight, releaseDetails: async () => ({ data: { tracks: [] } }) }, PlaylistsList: {}, ReleasesList: {}, Queue: {}, PublishedAlbums: {},
  })
  vm.runInContext(script, context)
  const component = context.component
  const state = {
    ...component.data(), artist: 'Artist', album: 'Album',
    playlists: [{ id: 'old-playlist' }], releases: [{ id: 'old-release' }],
    destinationCheck: { reset() {}, inspect() {}, dispose() {} },
  }
  for (const [name, method] of Object.entries(component.methods)) state[name] = method.bind(state)
  for (const [name, getter] of Object.entries(component.computed)) Object.defineProperty(state, name, { get: () => getter.call(state) })
  return { state, context, component, search: () => component.methods.searchAll.call(state) }
}

for (const failed of [[], ['youtube'], ['musicbrainz'], ['youtube', 'musicbrainz']]) {
  test(`search displays results and errors independently: ${failed.join(',') || 'success'}`, async () => {
    const errors = Object.fromEntries(failed.map(provider => [provider, `${provider} unavailable`]))
    const data = {
      playlists: failed.includes('youtube') ? [] : [{ id: 'p' }],
      releases: failed.includes('musicbrainz') ? [] : [{ id: 'r' }],
      errors,
    }
    const { state, search } = setup(async () => {
      if (failed.length === 2) throw { response: { status: 502, data } }
      return { data }
    })
    await search()
    assert.equal(state.playlists[0]?.id, failed.includes('youtube') ? undefined : 'p')
    assert.equal(state.releases[0]?.id, failed.includes('musicbrainz') ? undefined : 'r')
    assert.equal(state.errorPlaylists, errors.youtube || null)
    assert.equal(state.errorReleases, errors.musicbrainz || null)
    assert.equal(state.loadingPlaylists, false)
    assert.equal(state.loadingReleases, false)
  })
}

test('transport failure clears stale results and ends loading', async () => {
  const { state, search } = setup(async () => { throw new Error('network offline') })
  await search()
  assert.equal(state.playlists.length, 0)
  assert.equal(state.releases.length, 0)
  assert.equal(state.errorPlaylists, 'Error fetching playlists')
  assert.equal(state.errorReleases, 'Error fetching releases')
  assert.equal(state.loadingPlaylists, false)
  assert.equal(state.loadingReleases, false)
})

test('entering review refreshes the final library destination', () => {
  const { state, component } = setup(async () => ({}))
  const inspections = []
  state.destinationCheck = {
    reset() {},
    inspect(destination) { inspections.push(destination) },
    dispose() {},
  }
  state.selectedPlaylist = { id: 'playlist' }
  state.selectedRelease = {
    id: 'release',
    artist: 'Röyksopp',
    title: 'Melody A.M.',
  }
  state.releaseDetailsReady = true

  component.watch.view.call(state, 'review')

  assert.equal(
    JSON.stringify(inspections),
    JSON.stringify([{ artist: 'Röyksopp', album: 'Melody A.M.' }]),
  )
})

test('each search sends its own shared result limit', async () => {
  const calls = []
  const { state, search } = setup(async (...args) => {
    calls.push(args)
    return { data: { playlists: [], releases: [], errors: {} } }
  })

  await search()
  state.resultLimit = 50
  await search()
  state.resultLimit = 7
  await search()

  assert.deepEqual(calls, [
    ['Artist', 'Album', 10, null],
    ['Artist', 'Album', 50, null],
    ['Artist', 'Album', 7, null],
  ])
})

test('invalid shared result limits are rejected before the request', async () => {
  let requests = 0
  const { state, search } = setup(async () => {
    requests += 1
    return { data: {} }
  })

  for (const limit of [0, 51, 2.5, '10', '']) {
    state.resultLimit = limit
    await search()
    assert.match(state.errorPlaylists, /whole number from 1 to 50/)
    assert.match(state.errorReleases, /whole number from 1 to 50/)
  }
  assert.equal(requests, 0)
})

test('maximum-track filtering is optional and scoped to each search', async () => {
  const calls = []
  const { state, search } = setup(async (...args) => {
    calls.push(args)
    return { data: { playlists: [], releases: [], errors: {} } }
  })

  await search()
  state.maxTracksEnabled = true
  state.maxTracks = 30
  await search()
  state.maxTracks = 12
  await search()
  state.maxTracksEnabled = false
  await search()

  assert.deepEqual(calls.map(call => call[3]), [null, 30, 12, null])
})

test('enabled maximum-track filter requires a positive whole number', async () => {
  let requests = 0
  const { state, search } = setup(async () => {
    requests += 1
    return { data: { playlists: [], releases: [], errors: {} } }
  })
  state.maxTracksEnabled = true

  for (const maxTracks of [0, -1, 2.5, '30', '']) {
    state.maxTracks = maxTracks
    await search()
    assert.match(state.errorPlaylists, /positive whole number/)
  }
  assert.equal(requests, 0)

  state.maxTracksEnabled = false
  await search()
  assert.equal(requests, 1)
})


test('only selected playlist is checked and stale selection results are ignored', async () => {
  const calls = []
  const { state, search } = setup(async () => ({ data: { playlists: [{ id: 'a' }, { id: 'b' }] } }),
    payload => new Promise((resolve, reject) => calls.push({ payload, resolve, reject })))
  await search()
  assert.equal(calls.length, 0)
  const first = state.selectPlaylist({ id: 'a', url: 'a', track_count: 2 })
  const second = state.selectPlaylist({ id: 'b', url: 'b', track_count: 1 })
  calls[1].resolve({ data: { track_count: 1 } })
  await second
  calls[0].reject({ response: { data: { detail: 'mismatch' } } })
  await first
  assert.equal(state.selectedPlaylist.id, 'b')
  assert.equal(state.playlistReady, true)
  assert.equal(state.playlistError, null)
  const old = state.selectPlaylist({ url: 'old' })
  await search()
  calls[2].resolve({ data: { track_count: 9 } })
  await old
  assert.equal(state.selectedPlaylist, null)
  assert.equal(state.playlistReady, false)
})

test('manifest mismatch leaves selection blocked with useful error', async () => {
  const { state } = setup(async () => ({}), async () => {
    throw { response: { data: { detail: 'expected 13 tracks, extractable 12' } } }
  })
  await state.selectPlaylist({ url: 'playlist' })
  assert.equal(state.playlistReady, false)
  assert.match(state.playlistError, /extractable 12/)
})

test('missing upstream tracklists produce no fictional compatibility result', async () => {
  const { state, context } = setup(async () => ({}))
  let requests = 0
  context.api.trackCompatibility = async () => {
    requests += 1
    return { data: { status: 'strong' } }
  }
  state.selectedPlaylist = { id: 'playlist', url: 'playlist', tracks: null }
  state.selectedRelease = { id: 'release', tracks: [{ global_position: 1, title: 'One' }] }

  await state.loadCompatibility()

  assert.equal(requests, 0)
  assert.equal(state.compatibilityResult, null)
  assert.match(state.compatibilityError, /unavailable/)
})


test('manual mode requires confirmation and submits edited metadata independent of search', async () => {
  const { state, context } = setup(async () => ({}))
  const downloads = []
  context.api.download = async payload => downloads.push(payload)
  state.selectedPlaylist = {
    id: 'playlist-id', url: 'playlist', title: 'Observed playlist',
    channel: 'Uploader', thumbnail: 'thumbnail', track_count: 1,
  }
  state.playlistReady = true
  state.manualArtist = ' Final Artist '
  state.manualAlbum = ' Final Album '
  await state.downloadManual()
  assert.equal(downloads.length, 0)
  state.manualConfirmed = true
  state.destinationState = 'not_found'
  await state.downloadManual()
  assert.equal(downloads[0].artist, 'Final Artist')
  assert.equal(downloads[0].album, 'Final Album')
  assert.equal(downloads[0].metadata_mode, 'manual')
  assert.equal(downloads[0].release_id, null)
  assert.equal(downloads[0].playlist_id, 'playlist-id')
  assert.equal(downloads[0].playlist_title, 'Observed playlist')
  assert.equal(downloads[0].playlist_channel, 'Uploader')
  state.manualAlbum = '   '
  await state.downloadManual()
  assert.equal(downloads.length, 1)
})

test('recreating a publication restores historical Review without enqueueing', () => {
  const { state, context } = setup(async () => ({}))
  let downloads = 0
  context.api.download = async () => { downloads += 1 }
  state.navigate = view => { state.lastView = view }
  const result = {
    review: {
      metadata_mode: 'manual',
      artist: 'Historical Artist',
      album: 'Historical Album',
      playlist: {
        id: 'playlist-id', url: 'playlist', title: 'Historical playlist',
        track_count: 1, tracks: [{ position: 1, title: 'Original upload' }],
      },
      release: null,
      cover: { source: 'none', square_strategy: null },
      accepted_overrides: ['manual_metadata_without_musicbrainz'],
    },
    drift: {
      playlist: { status: 'changed', changes: [] },
      release: { status: 'not_applicable', changes: [] },
    },
    enqueued: false,
  }

  state.recreatePublication(result)

  assert.equal(downloads, 0)
  assert.equal(state.lastView, 'review')
  assert.equal(state.selectedPlaylist.tracks[0].title, 'Original upload')
  assert.equal(state.manualArtist, 'Historical Artist')
  assert.equal(state.manualConfirmed, true)
  assert.equal(state.recreation, result)
})
