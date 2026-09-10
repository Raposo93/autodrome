import axios from 'axios'
import {
  buildWebSocketUrl,
  createReconnectingWebSocket,
} from './websocket'

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

export function connectWebSocket(onMessage) {
  return createReconnectingWebSocket({
    onMessage,
    urlFactory() {
      return buildWebSocketUrl(window.location, apiToken())
    },
  })
}
