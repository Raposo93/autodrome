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
  combinedSearch(artist, album, youtubeLimit = 10, youtubeMaxTracks = null) {
    const params = { artist, album, youtube_limit: youtubeLimit }
    if (youtubeMaxTracks !== null && youtubeMaxTracks !== undefined) {
      params.youtube_max_tracks = youtubeMaxTracks
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

  retryJob(jobId) {
    return apiClient.post(`/download/jobs/${encodeURIComponent(jobId)}/retry`)
  },

  playlistPreflight(payload) {
    return apiClient.post('/download/preflight', payload)
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
