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
