import axios from 'axios'

const apiToken = import.meta.env.VITE_API_TOKEN
const apiClient = axios.create({
  baseURL: '/api',
  headers: apiToken ? { Authorization: `Bearer ${apiToken}` } : {},
})

export default {
  combinedSearch(artist, album) {
    return apiClient.get('/search/', { params: { artist, album } })
  },

  download(payload) {
    return apiClient.post('/download/', payload)
  },
}

export function connectWebSocket(onMessage) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socketUrl = new URL(`${protocol}//${window.location.host}/ws`)
  if (apiToken) {
    socketUrl.searchParams.set('token', apiToken)
  }
  const socket = new WebSocket(socketUrl)

  socket.onopen = () => {
    console.log('WebSocket connected');
  };

  socket.onmessage = (event) => {
    const message = event.data;
    try {
      const parsed = JSON.parse(message);
      onMessage(parsed);
    } catch (e) {
      console.warn('WebSocket message not JSON:', message);
      onMessage(message);
    }
  };

  socket.onclose = () => {
    console.log('WebSocket disconnected');
  };

  socket.onerror = (error) => {
    console.error('WebSocket error:', error);
  };

  return socket;
}
