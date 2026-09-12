import axios from 'axios'
import {
  buildWebSocketUrl,
  createReconnectingWebSocket,
} from './websocket.js'

const tokenKey = 'autodrome-api-token'
const apiToken = () => sessionStorage.getItem(tokenKey) || ''
export function setApiToken(value) {
  if (value) sessionStorage.setItem(tokenKey, value)
  else sessionStorage.removeItem(tokenKey)
}
const apiClient = axios.create({ baseURL: '/api' })
apiClient.interceptors.request.use(config => {
  const token = apiToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export default {
  authenticate() {
    return apiClient.get('/auth')
  },
  systemStatus() {
    return apiClient.get('/status/')
  },
  combinedSearch(artist, album, resultLimit = 10, maxTracks = null) {
    const params = { artist, album, result_limit: resultLimit }
    if (maxTracks !== null && maxTracks !== undefined) {
      params.max_tracks = maxTracks
    }
    return apiClient.get('/search/', {
      params
    })
  },

  releaseDetails(releaseId) {
    return apiClient.get(`/search/releases/${releaseId}`)
  },

  clearQueueHistory() {
    return apiClient.delete('/download/history')
  },

  deleteJob(jobId) {
    return apiClient.delete(`/download/jobs/${encodeURIComponent(jobId)}`)
  },

  cancelJob(jobId) {
    return apiClient.post(`/download/jobs/${encodeURIComponent(jobId)}/cancel`)
  },

  retryJob(jobId) {
    return apiClient.post(`/download/jobs/${encodeURIComponent(jobId)}/retry`)
  },

  playlistPreflight(payload) {
    return apiClient.post('/download/preflight', payload)
  },

  albumDestination(payload) {
    return apiClient.post('/download/destination', payload)
  },

  prepareYoutubeCover(thumbnailUrl) {
    return apiClient.post('/download/covers/youtube', {
      thumbnail_url: thumbnailUrl,
    })
  },

  prepareManualCover(file) {
    const form = new FormData()
    form.append('cover', file)
    return apiClient.post('/download/covers/manual', form)
  },

  download(payload) {
    return apiClient.post('/download/', payload)
  },
}

export function connectWebSocket(onMessage, options = {}) {
  const location = options.location || window.location
  const ticketIssuer = options.ticketIssuer || (() => (
    apiClient.post('/auth/ws-ticket')
  ))
  return createReconnectingWebSocket({
    onMessage,
    WebSocketImpl: options.WebSocketImpl,
    setTimeoutFn: options.setTimeoutFn,
    clearTimeoutFn: options.clearTimeoutFn,
    setIntervalFn: options.setIntervalFn,
    clearIntervalFn: options.clearIntervalFn,
    async urlFactory() {
      if (!apiToken()) {
        return buildWebSocketUrl(location)
      }
      const response = await ticketIssuer()
      return buildWebSocketUrl(location, response.data.ticket)
    },
  })
}
