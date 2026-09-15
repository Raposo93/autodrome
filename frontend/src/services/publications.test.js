import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { parse } from '@vue/compiler-sfc'

const source = readFileSync(new URL('../components/PublishedAlbums.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = descriptor.script.content
  .replace(/^import .*$/gm, '')
  .replace('export default', 'component =')

function setup(api) {
  const context = vm.createContext({ api })
  vm.runInContext(script, context)
  const component = context.component
  const emitted = []
  const state = { ...component.data(), $emit: (...args) => emitted.push(args) }
  for (const [name, method] of Object.entries(component.methods)) state[name] = method.bind(state)
  return { state, emitted }
}

test('publication history loads detail and recreates through read-only APIs', async () => {
  const calls = []
  const api = {
    publications: async () => ({ data: [{ publication_id: 'pub-1' }] }),
    publication: async id => {
      calls.push(['detail', id])
      return { data: { publication_id: id, files: [] } }
    },
    recreatePublication: async id => {
      calls.push(['recreate', id])
      return { data: { publication: { publication_id: id }, enqueued: false } }
    },
  }
  const { state, emitted } = setup(api)
  await state.load()
  await state.viewProvenance(state.publications[0])
  await state.recreate(state.publications[0])

  assert.equal(state.selected.publication_id, 'pub-1')
  assert.deepEqual(calls, [['detail', 'pub-1'], ['recreate', 'pub-1']])
  assert.equal(emitted[0][0], 'recreate')
  assert.equal(emitted[0][1].enqueued, false)
})

test('provenance view names manifest, mapping and SHA-256 explicitly', () => {
  assert.match(descriptor.template.content, /Playlist manifest and final mapping/)
  assert.match(descriptor.template.content, /SHA-256/)
  assert.doesNotMatch(descriptor.template.content, /JSON\.stringify/)
})
