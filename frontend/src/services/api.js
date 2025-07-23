import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
})

export default {
  combinedSearch(artist, album) {
    return apiClient.get('/search', { params: { artist, album } })
  },

  download(payload) {
    return apiClient.post('/download', payload)
  },
}

export function connectWebSocket(onMessage) {
  const socket = new WebSocket(`ws://${window.location.host}/ws`);

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
