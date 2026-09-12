import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildWebSocketUrl,
  createReconnectingWebSocket,
} from './websocket.js'
import { connectWebSocket, setApiToken } from './api.js'

class FakeWebSocket {
  static instances = []

  constructor(url) {
    this.url = url
    this.readyState = 0
    this.sent = []
    FakeWebSocket.instances.push(this)
  }

  open() {
    this.readyState = 1
    this.onopen?.()
  }

  receive(data) {
    this.onmessage?.({ data })
  }

  send(data) {
    this.sent.push(data)
  }

  close() {
    if (this.readyState >= 2) {
      return
    }
    this.readyState = 3
    this.onclose?.()
  }
}

function createScheduler() {
  const timeouts = []
  const intervals = []

  return {
    timeouts,
    intervals,
    setTimeoutFn(callback, delay) {
      const timer = { callback, delay, cancelled: false }
      timeouts.push(timer)
      return timer
    },
    clearTimeoutFn(timer) {
      timer.cancelled = true
    },
    setIntervalFn(callback, delay) {
      const timer = { callback, delay, cancelled: false }
      intervals.push(timer)
      return timer
    },
    clearIntervalFn(timer) {
      timer.cancelled = true
    },
  }
}

function connect(options = {}) {
  const scheduler = createScheduler()
  const messages = []
  const controller = createReconnectingWebSocket({
    urlFactory: () => new URL('ws://localhost/ws'),
    onMessage: (message) => messages.push(message),
    WebSocketImpl: FakeWebSocket,
    ...scheduler,
    ...options,
  })
  return { controller, messages, scheduler }
}

test('buildWebSocketUrl selects secure transport and includes a ticket', () => {
  const url = buildWebSocketUrl(
    { protocol: 'https:', host: 'music.example.test' },
    'ephemeral ticket',
  )

  assert.equal(url.protocol, 'wss:')
  assert.equal(url.host, 'music.example.test')
  assert.equal(url.pathname, '/ws')
  assert.equal(url.searchParams.get('ticket'), 'ephemeral ticket')
  assert.equal(url.searchParams.has('token'), false)
  assert.equal(
    buildWebSocketUrl({ protocol: 'http:', host: 'localhost:5000' }).protocol,
    'ws:',
  )
})

test('authenticated connection obtains a fresh ticket without exposing the API token', async () => {
  FakeWebSocket.instances = []
  const scheduler = createScheduler()
  const values = new Map()
  globalThis.sessionStorage = {
    getItem(key) {
      return values.get(key) || null
    },
    setItem(key, value) {
      values.set(key, value)
    },
    removeItem(key) {
      values.delete(key)
    },
  }
  setApiToken('master-api-secret')
  let issued = 0
  const controller = connectWebSocket(() => {}, {
    location: { protocol: 'https:', host: 'music.example.test' },
    ticketIssuer: async () => ({
      data: { ticket: `ticket-${++issued}` },
    }),
    WebSocketImpl: FakeWebSocket,
    ...scheduler,
  })

  await new Promise(resolve => setImmediate(resolve))
  const firstSocket = FakeWebSocket.instances[0]
  assert.equal(new URL(firstSocket.url).searchParams.get('ticket'), 'ticket-1')
  assert.equal(firstSocket.url.toString().includes('master-api-secret'), false)
  assert.equal(new URL(firstSocket.url).searchParams.has('token'), false)

  firstSocket.close()
  scheduler.timeouts[0].callback()
  await new Promise(resolve => setImmediate(resolve))

  const secondSocket = FakeWebSocket.instances[1]
  assert.equal(new URL(secondSocket.url).searchParams.get('ticket'), 'ticket-2')
  assert.equal(issued, 2)

  controller.close()
  setApiToken('')
  delete globalThis.sessionStorage
})

test('loopback connection opens directly without requesting a ticket', async () => {
  FakeWebSocket.instances = []
  const values = new Map()
  globalThis.sessionStorage = {
    getItem(key) {
      return values.get(key) || null
    },
    setItem(key, value) {
      values.set(key, value)
    },
    removeItem(key) {
      values.delete(key)
    },
  }
  let issued = 0
  const controller = connectWebSocket(() => {}, {
    location: { protocol: 'http:', host: 'localhost:5000' },
    ticketIssuer: async () => {
      issued += 1
      return { data: { ticket: 'unused' } }
    },
    WebSocketImpl: FakeWebSocket,
  })

  await new Promise(resolve => setImmediate(resolve))

  assert.equal(FakeWebSocket.instances[0].url.search, '')
  assert.equal(issued, 0)
  controller.close()
  delete globalThis.sessionStorage
})

test('connection handles snapshots and sends heartbeat pings', () => {
  FakeWebSocket.instances = []
  const { controller, messages, scheduler } = connect()
  const socket = FakeWebSocket.instances[0]

  socket.open()
  socket.receive(JSON.stringify([{ job_id: 'job-1', status: 'running' }]))
  socket.receive(JSON.stringify({ type: 'pong' }))
  scheduler.intervals[0].callback()

  assert.deepEqual(messages, [[{ job_id: 'job-1', status: 'running' }]])
  assert.deepEqual(socket.sent, ['ping'])
  controller.close()
  assert.equal(scheduler.intervals[0].cancelled, true)
})

test('connection reconnects with backoff and never schedules duplicates', () => {
  FakeWebSocket.instances = []
  const { controller, scheduler } = connect()
  const firstSocket = FakeWebSocket.instances[0]

  firstSocket.close()
  firstSocket.onclose()

  assert.equal(scheduler.timeouts.length, 1)
  assert.equal(scheduler.timeouts[0].delay, 1_000)

  scheduler.timeouts[0].callback()
  const secondSocket = FakeWebSocket.instances[1]
  secondSocket.close()

  assert.equal(scheduler.timeouts.length, 2)
  assert.equal(scheduler.timeouts[1].delay, 2_000)

  controller.close()
  assert.equal(scheduler.timeouts[1].cancelled, true)
  if (!scheduler.timeouts[1].cancelled) {
    scheduler.timeouts[1].callback()
  }
  assert.equal(FakeWebSocket.instances.length, 2)
})
