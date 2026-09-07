import axios from 'axios'
import {
  buildWebSocketUrl,
  createReconnectingWebSocket,
} from './websocket'

const apiToken = import.meta.env.VITE_API_TOKEN
const apiClient = axios.create({
  baseURL: '/api',
  headers: apiToken ? { Authorization: `Bearer ${apiToken}` } : {},
})

export default {
  combinedSearch(artist, album) {
    return apiClient.get('/search/', { params: { artist, album } })
  },

  releaseDetails(releaseId) {
    return apiClient.get(`/search/releases/${releaseId}`)
  },

  download(payload) {
    return apiClient.post('/download/', payload)
  },
}

export function connectWebSocket(onMessage) {
  return createReconnectingWebSocket({
    onMessage,
    urlFactory() {
      return buildWebSocketUrl(window.location, apiToken)
    },
  })
}
