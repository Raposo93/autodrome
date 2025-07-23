<template>
  <div>
    <h2>Music Search</h2>
    <div class="search-form">
      <input v-model="artist" placeholder="Artist" />
      <input v-model="album" placeholder="Album" />
      <button :disabled="!artist && !album" @click="searchAll">Search</button>
    </div>

    <div class="results-container">
      <PlaylistsList
        :playlists="playlists"
        :selected="selectedPlaylist"
        :loading="loadingPlaylists"
        :error="errorPlaylists"
        :default-img="defaultPlaylistImg"
        @select="selectPlaylist"
      />

      <ReleasesList
        :releases="releases"
        :selected="selectedRelease"
        :loading="loadingReleases"
        :error="errorReleases"
        :default-img="defaultReleaseImg"
        @select="selectRelease"
      />
      <Queue />
    </div>

    <button 
      :disabled="!selectedPlaylist || !selectedRelease || downloading" 
      @click="downloadSelected"
    >
      {{ downloading ? 'Downloading...' : 'Download & Tag' }}
    </button>

    <div v-if="downloadError" class="error">{{ downloadError }}</div>
    <div v-if="downloadSuccess" class="success">Download complete!</div>
  </div>
</template>

<script>
import api from '../services/api.js'
import PlaylistsList from './PlaylistsList.vue'
import ReleasesList from './ReleasesList.vue'
import Queue from './Queue.vue'

export default {
  components: {
    PlaylistsList,
    ReleasesList,
    Queue
  },
  data() {
    return {
      artist: '',
      album: '',
      playlists: [],
      releases: [],
      loadingPlaylists: false,
      loadingReleases: false,
      errorPlaylists: null,
      errorReleases: null,
      selectedPlaylist: null,
      selectedRelease: null,
      downloading: false,
      downloadError: null,
      downloadSuccess: false,
      defaultPlaylistImg: '/default_playlist.png',
      defaultReleaseImg: '/default_release.png'
    }
  },
  methods: {
    async searchAll() {
      this.errorPlaylists = null
      this.errorReleases = null
      this.downloadSuccess = false
      this.selectedPlaylist = null
      this.selectedRelease = null

      if (!this.artist && !this.album) return

      const artist = this.artist.trim()
      const album = this.album.trim()

      this.loadingPlaylists = true
      this.loadingReleases = true

      try {
        const response = await api.combinedSearch(artist, album)
        this.playlists = response.data.playlists || []
        this.releases = response.data.releases || []

      } catch (e) {
        this.errorPlaylists = "Error fetching playlists"
        this.errorReleases = "Error fetching releases"
      } finally {
        this.loadingPlaylists = false
        this.loadingReleases = false
      }
    },
    selectPlaylist(pl) {
      this.selectedPlaylist = pl
    },
    selectRelease(rel) {
      this.selectedRelease = rel
    },
    async downloadSelected() {
      this.downloading = true
      this.downloadError = null
      this.downloadSuccess = false

      console.log({
        playlist_url: this.selectedPlaylist.url,
        artist: this.selectedRelease.artist,
        album: this.selectedRelease.title,
        release_id: this.selectedRelease.id,
        track_count: this.selectedPlaylist.track_count || null
      })

      try {
        await api.download({
          playlist_url: this.selectedPlaylist.url,
          artist: this.selectedRelease.artist,
          album: this.selectedRelease.title,
          release_id: this.selectedRelease.id,
          track_count: this.selectedPlaylist.track_count || null
        })
        this.downloadSuccess = true
      } catch (e) {
        this.downloadError = "Download failed"
        console.error(e)
      } finally {
        this.downloading = false
      }
    }
  }
}
</script>

<style scoped>
.results-container {
  display: flex;
  gap: 20px;
}
.column {
  flex: 1;
  max-height: 400px;
  overflow-y: auto;
}
ul {
  list-style: none;
  padding: 0;
}
li {
  cursor: pointer;
  padding: 5px;
  display: flex;
  align-items: center;
  gap: 10px;
}
li.selected {
  background-color: #cce5ff;
}
.error {
  color: red;
}
.success {
  color: green;
}
.search-form {
  margin-bottom: 1rem;
}
</style>
