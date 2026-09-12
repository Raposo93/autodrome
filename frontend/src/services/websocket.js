const CONNECTING = 0
const OPEN = 1
const CLOSING = 2

export function buildWebSocketUrl(location, ticket) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socketUrl = new URL(`${protocol}//${location.host}/ws`)
  if (ticket) {
    socketUrl.searchParams.set('ticket', ticket)
  }
  return socketUrl
}

export function createReconnectingWebSocket({
  urlFactory,
  onMessage,
  WebSocketImpl = WebSocket,
  setTimeoutFn = setTimeout,
  clearTimeoutFn = clearTimeout,
  setIntervalFn = setInterval,
  clearIntervalFn = clearInterval,
  baseDelayMs = 1_000,
  maxDelayMs = 30_000,
  heartbeatIntervalMs = 25_000,
}) {
  let socket = null
  let retryTimer = null
  let heartbeatTimer = null
  let retryCount = 0
  let stopped = false
  let acquiringUrl = false

  const clearHeartbeat = () => {
    if (heartbeatTimer !== null) {
      clearIntervalFn(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  const scheduleReconnect = () => {
    if (stopped || retryTimer !== null) {
      return
    }
    const delay = Math.min(maxDelayMs, baseDelayMs * (2 ** retryCount))
    retryCount += 1
    retryTimer = setTimeoutFn(() => {
      retryTimer = null
      connect()
    }, delay)
  }

  const openSocket = (url) => {
    if (stopped) {
      return
    }

    let currentSocket
    try {
      currentSocket = new WebSocketImpl(url)
    } catch {
      scheduleReconnect()
      return
    }
    socket = currentSocket

    currentSocket.onopen = () => {
      if (stopped || socket !== currentSocket) {
        currentSocket.close()
        return
      }
      retryCount = 0
      clearHeartbeat()
      heartbeatTimer = setIntervalFn(() => {
        if (socket === currentSocket && currentSocket.readyState === OPEN) {
          currentSocket.send('ping')
        }
      }, heartbeatIntervalMs)
    }

    currentSocket.onmessage = (event) => {
      if (socket !== currentSocket || stopped) {
        return
      }
      let parsed
      try {
        parsed = JSON.parse(event.data)
      } catch {
        console.warn('WebSocket message not JSON:', event.data)
        return
      }
      if (parsed?.type === 'heartbeat' || parsed?.type === 'pong') {
        return
      }
      onMessage(parsed)
    }

    currentSocket.onclose = () => {
      if (socket !== currentSocket) {
        return
      }
      socket = null
      clearHeartbeat()
      scheduleReconnect()
    }

    currentSocket.onerror = () => {
      if (socket === currentSocket && currentSocket.readyState !== CLOSING) {
        currentSocket.close()
      }
    }
  }

  const connect = () => {
    if (
      stopped ||
      acquiringUrl ||
      (socket && (socket.readyState === CONNECTING || socket.readyState === OPEN))
    ) {
      return
    }

    let url
    try {
      url = urlFactory()
    } catch {
      scheduleReconnect()
      return
    }
    if (!url || typeof url.then !== 'function') {
      openSocket(url)
      return
    }

    acquiringUrl = true
    Promise.resolve(url)
      .then((resolvedUrl) => {
        acquiringUrl = false
        openSocket(resolvedUrl)
      })
      .catch(() => {
        acquiringUrl = false
        scheduleReconnect()
      })
  }

  connect()

  return {
    close() {
      stopped = true
      if (retryTimer !== null) {
        clearTimeoutFn(retryTimer)
        retryTimer = null
      }
      clearHeartbeat()
      const currentSocket = socket
      socket = null
      if (currentSocket && currentSocket.readyState < CLOSING) {
        currentSocket.close()
      }
    },
  }
}
