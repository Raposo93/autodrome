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

function setup(combinedSearch) {
  const context = vm.createContext({
    createReleaseHydration,
    api: { combinedSearch, releaseDetails: async () => ({ data: { tracks: [] } }) }, PlaylistsList: {}, ReleasesList: {}, Queue: {},
  })
  vm.runInContext(script, context)
  const component = context.component
  const state = {
    ...component.data(), artist: 'Artist', album: 'Album',
    playlists: [{ id: 'old-playlist' }], releases: [{ id: 'old-release' }],
  }
  for (const [name, method] of Object.entries(component.methods)) state[name] = method.bind(state)
  return { state, search: () => component.methods.searchAll.call(state) }
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
