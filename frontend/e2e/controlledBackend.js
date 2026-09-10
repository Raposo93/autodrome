class ControlledRequest {
  constructor(route, kind) {
    this.route = route
    this.kind = kind
    this.method = route.request().method()
    this.url = new URL(route.request().url())
    this.query = Object.fromEntries(this.url.searchParams)
    this.body = this.readBody(route.request())
    this.settled = false
    this.finished = new Promise(resolve => {
      this.finish = resolve
    })
  }

  readBody(request) {
    if (!request.postData()) return null
    try {
      return request.postDataJSON()
    } catch {
      return request.postData()
    }
  }

  async reply(body = {}, status = 200) {
    if (this.settled) throw new Error(`Request ${this.kind} was already settled`)
    this.settled = true
    await this.route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
    this.finish()
  }

  reject(status, body) {
    return this.reply(body, status)
  }
}

export class ControlledBackend {
  constructor(queue = []) {
    this.calls = []
    this.available = new Map()
    this.requestWaiters = new Map()
    this.queue = structuredClone(queue)
    this.executedJobs = []
    this.sockets = new Set()
    this.connectionCount = 0
    this.socketWaiters = []
  }

  async install(page) {
    await page.route('**/api/**', route => this.handleHttp(route))
    await page.routeWebSocket('**/ws**', socket => this.handleSocket(socket))
  }

  classify(request) {
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    if (method === 'GET' && path === '/api/search/') return 'search'
    if (method === 'GET' && path === '/api/status/') return 'status'
    if (method === 'GET' && path.startsWith('/api/search/releases/')) {
      return `release:${decodeURIComponent(path.slice('/api/search/releases/'.length))}`
    }
    if (method === 'POST' && path === '/api/download/preflight') return 'preflight'
    if (method === 'POST' && path === '/api/download/destination') return 'destination'
    if (method === 'POST' && path === '/api/download/covers/youtube') return 'cover-youtube'
    if (method === 'POST' && path === '/api/download/covers/manual') return 'cover-manual'
    if (method === 'POST' && path === '/api/download/') return 'download'
    const action = path.match(/^\/api\/download\/jobs\/([^/]+)\/(cancel|retry)$/)
    if (method === 'POST' && action) {
      return `${action[2]}:${decodeURIComponent(action[1])}`
    }
    if (method === 'DELETE' && path === '/api/download/history') return 'clear-history'
    const deletion = path.match(/^\/api\/download\/jobs\/([^/]+)$/)
    if (method === 'DELETE' && deletion) {
      return `delete:${decodeURIComponent(deletion[1])}`
    }
    return null
  }

  async handleHttp(route) {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'GET' && path === '/api/auth') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ authenticated: true }),
      })
      return
    }

    const kind = this.classify(request)
    if (!kind) {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `Unexpected controlled-backend request: ${request.method()} ${path}` }),
      })
      return
    }

    const exchange = new ControlledRequest(route, kind)
    this.calls.push(exchange)
    const waiters = this.requestWaiters.get(kind)
    if (waiters?.length) {
      waiters.shift()(exchange)
    } else {
      const available = this.available.get(kind) || []
      available.push(exchange)
      this.available.set(kind, available)
    }
    await exchange.finished
  }

  next(kind) {
    const available = this.available.get(kind)
    if (available?.length) return Promise.resolve(available.shift())
    return new Promise(resolve => {
      const waiters = this.requestWaiters.get(kind) || []
      waiters.push(resolve)
      this.requestWaiters.set(kind, waiters)
    })
  }

  callCount(kind) {
    return this.calls.filter(call => call.kind === kind).length
  }

  handleSocket(socket) {
    this.connectionCount += 1
    this.sockets.add(socket)
    socket.send(JSON.stringify(this.queue))
    socket.onMessage(message => {
      if (message === 'ping') socket.send(JSON.stringify({ type: 'pong' }))
    })
    const remaining = []
    for (const waiter of this.socketWaiters) {
      if (this.connectionCount >= waiter.count) waiter.resolve(socket)
      else remaining.push(waiter)
    }
    this.socketWaiters = remaining
  }

  waitForSocket(count) {
    if (this.connectionCount >= count) return Promise.resolve()
    return new Promise(resolve => this.socketWaiters.push({ count, resolve }))
  }

  setQueue(queue) {
    this.queue = structuredClone(queue)
    this.broadcastQueue()
  }

  broadcastQueue() {
    const message = JSON.stringify(this.queue)
    for (const socket of this.sockets) {
      try {
        socket.send(message)
      } catch {
        this.sockets.delete(socket)
      }
    }
  }

  executeQueuedJobs() {
    for (const job of this.queue) {
      if (job.status === 'queued') {
        this.executedJobs.push(job.job_id)
        job.status = 'running'
      }
    }
    this.broadcastQueue()
  }
}

export const playlist = (id, trackCount = 2) => ({
  id,
  title: `Playlist ${id}`,
  url: `https://youtube.test/playlist?list=${id}`,
  channel: `Channel ${id}`,
  track_count: trackCount,
  thumbnail: `https://i.ytimg.com/vi/${id}/mqdefault.jpg`,
})

export const release = (id, trackCount = 2, withCover = true) => ({
  id,
  title: `Release ${id}`,
  artist: `Artist ${id}`,
  date: '2026',
  track_count: trackCount,
  cover_url: withCover ? `https://coverartarchive.org/release/${id}/front` : null,
})

export const releaseDetails = (id, trackCount = 2, withCover = true) => ({
  id,
  cover_url: withCover ? `https://coverartarchive.org/release/${id}/front` : null,
  tracks: Array.from({ length: trackCount }, (_, index) => ({
    title: `Track ${id}-${index + 1}`,
    artist: `Artist ${id}`,
    disc_number: 1,
    position: index + 1,
    global_position: index + 1,
  })),
})
