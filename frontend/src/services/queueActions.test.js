import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { parse } from '@vue/compiler-sfc'
import { canCancelJob, canDeleteJob, canRetryJob } from './queueHistory.js'
import { progressLabel } from './queueProgress.js'

const source = readFileSync(new URL('../components/Queue.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = descriptor.script.content
  .replace(/^import .*$/gm, '')
  .replace('export default', 'component =')

function setup(cancelJob) {
  const context = vm.createContext({
    api: { cancelJob },
    connectWebSocket: () => ({ close() {} }),
    progressLabel,
    canCancelJob,
    canDeleteJob,
    canRetryJob,
    console,
  })
  vm.runInContext(script, context)
  const component = context.component
  const state = { ...component.data(), queueMessages: [] }
  for (const [name, method] of Object.entries(component.methods)) {
    state[name] = method.bind(state)
  }
  return state
}

test('cancel action is single-shot for queued and running jobs', async () => {
  const calls = []
  let finish
  const state = setup(jobId => {
    calls.push(jobId)
    if (calls.length === 1) {
      return new Promise(resolve => { finish = resolve })
    }
    return Promise.resolve()
  })
  const queued = { job_id: 'queued-job', status: 'queued' }

  const first = state.cancelJob(queued)
  const duplicate = state.cancelJob(queued)
  await state.cancelJob({ job_id: 'running-job', status: 'running' })

  assert.deepEqual(calls, ['queued-job'])
  assert.equal(await duplicate, undefined)
  finish()
  await first
  await state.cancelJob({ job_id: 'running-job', status: 'running' })
  assert.deepEqual(calls, ['queued-job', 'running-job'])
  assert.equal(state.busy, false)
})

test('cancel race rejection is shown to the user', async () => {
  const state = setup(async () => {
    throw { response: { data: { detail: 'This job has started publishing' } } }
  })

  await state.cancelJob({ job_id: 'stale-queued-job', status: 'queued' })

  assert.equal(state.actionError, 'This job has started publishing')
})
