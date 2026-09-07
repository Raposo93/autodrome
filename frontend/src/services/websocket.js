const CONNECTING = 0
const OPEN = 1
const CLOSING = 2

export function buildWebSocketUrl(location, apiToken) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socketUrl = new URL(`${protocol}//${location.host}/ws`)
  if (apiToken) {
    socketUrl.searchParams.set('token', apiToken)
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

  const connect = () => {
    if (
      stopped ||
      (socket && (socket.readyState === CONNECTING || socket.readyState === OPEN))
    ) {
      return
    }

    const currentSocket = new WebSocketImpl(urlFactory())
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
