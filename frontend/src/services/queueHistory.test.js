import test from 'node:test'
import assert from 'node:assert/strict'
import { canDeleteJob, canRetryJob } from './queueHistory.js'

test('active jobs and unknown states cannot be removed or retried', () => {
  for (const status of ['queued', 'running', 'unknown', undefined]) {
    assert.equal(canDeleteJob({ status }), false)
    assert.equal(canRetryJob({ status }, []), false)
  }
})

test('finished jobs can be removed and only unsuccessful ones retried', () => {
  for (const status of ['succeeded', 'failed', 'interrupted']) {
    assert.equal(canDeleteJob({ status }), true)
    assert.equal(canRetryJob({ status }, []), status !== 'succeeded')
  }
})

test('another active retry disables repeat requests for its source', () => {
  const source = { job_id: 'original', status: 'failed' }
  for (const status of ['queued', 'running']) {
    assert.equal(canRetryJob(source, [{ retry_of: 'original', status }]), false)
  }
  assert.equal(canRetryJob(source, [{ retry_of: 'original', status: 'failed' }]), true)
  assert.equal(canRetryJob(source, [{ retry_of: 'other', status: 'running' }]), true)
})
