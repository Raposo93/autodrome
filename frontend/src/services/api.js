import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
})

export default {
  combinedSearch(artist, album) {
    return apiClient.get('/search', { params: { artist, album } })
  },

  getCoverArt(release_id) {
    return apiClient.get(`/cover_art/${encodeURIComponent(release_id)}`)
  },

  download(payload) {
    return apiClient.post('/download', payload)
  },
}
