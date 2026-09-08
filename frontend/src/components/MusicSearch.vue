<template>
  <div class="music-search">
    <header class="search-hero">
      <div class="hero-copy">
        <p class="eyebrow">Autodrome music library</p>
        <h1>Find the right album release</h1>
        <p class="hero-description">
          Match a YouTube playlist with trusted MusicBrainz metadata, then
          download it ready for your library.
        </p>
      </div>

      <form class="search-toolbar" @submit.prevent="searchAll">
        <label class="search-field">
          <span>Artist</span>
          <input
            v-model="artist"
            type="search"
            placeholder="e.g. La Fuga"
            autocomplete="off"
          />
        </label>
        <label class="search-field">
          <span>Album</span>
          <input
            v-model="album"
            type="search"
            placeholder="e.g. Mira"
            autocomplete="off"
          />
        </label>
        <button
          class="search-button"
          type="submit"
          :disabled="(!artist && !album) || isSearching"
        >
          {{ isSearching ? 'Searching...' : 'Search music' }}
        </button>
      </form>
    </header>

    <section class="workspace-grid" aria-label="Search results and queue">
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
    </section>

    <section class="download-panel" aria-labelledby="download-title">
      <div class="download-heading">
        <p class="eyebrow">Current selection</p>
        <h2 id="download-title">Download &amp; tag</h2>
      </div>

      <div class="selection-pair">
        <div
          class="selection-card"
          :class="{ 'selection-card--ready': selectedPlaylist }"
        >
          <span class="selection-label">YouTube playlist</span>
          <strong>{{ selectedPlaylist?.title || 'Choose a playlist' }}</strong>
          <span class="selection-meta">
            {{ selectionTrackLabel(selectedPlaylist) }}
          </span>
        </div>

        <span class="selection-link" aria-hidden="true">+</span>

        <div
          class="selection-card"
          :class="{ 'selection-card--ready': releaseDetailsReady }"
        >
          <span class="selection-label">MusicBrainz release</span>
          <strong>{{ selectedRelease?.title || 'Choose a release' }}</strong>
          <span class="selection-meta">
            {{ selectionTrackLabel(selectedRelease) }}
          </span>
        </div>
      </div>

      <div class="download-action">
        <p>{{ downloadStatusText }}</p>
        <button
          class="download-button"
          type="button"
          :disabled="!selectionReady || downloading"
          @click="downloadSelected"
        >
          {{ releaseDetailsLoading
            ? 'Loading release details...'
            : (downloading ? 'Adding to queue...' : 'Download & Tag')
          }}
        </button>
        <div class="download-feedback" aria-live="polite">
          <span v-if="downloadError" class="feedback feedback--error">
            {{ downloadError }}
          </span>
          <span v-if="downloadSuccess" class="feedback feedback--success">
            Download queued successfully.
          </span>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
import api from '../services/api.js'
import { trackCountError } from '../services/downloadSelection.js'
import PlaylistsList from './PlaylistsList.vue'
import ReleasesList from './ReleasesList.vue'
import Queue from './Queue.vue'

export default {
  components: {
    PlaylistsList,
    ReleasesList,
    Queue
  },
  computed: {
    isSearching() {
      return this.loadingPlaylists || this.loadingReleases
    },
    trackCountError() {
      return trackCountError(this.selectedPlaylist, this.selectedRelease)
    },
    selectionReady() {
      return Boolean(
        this.selectedPlaylist &&
        this.releaseDetailsReady &&
        !this.releaseDetailsLoading &&
        !this.trackCountError
      )
    },
    downloadStatusText() {
      if (this.releaseDetailsLoading) {
        return 'Loading the selected release metadata.'
      }
      if (!this.selectedPlaylist && !this.selectedRelease) {
        return 'Choose one playlist and one release to continue.'
      }
      if (!this.selectedPlaylist) {
        return 'Choose the YouTube playlist that matches this release.'
      }
      if (!this.selectedRelease) {
        return 'Choose the MusicBrainz release that matches this playlist.'
      }
      if (!this.releaseDetailsReady) {
        return 'Release details could not be loaded. Choose another release or retry.'
      }
      return this.trackCountError || 'Both selections are ready to download.'
    }
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
      releaseDetailsLoading: false,
      releaseDetailsReady: false,
      downloading: false,
      downloadError: null,
      downloadSuccess: false,
      defaultPlaylistImg: '/default__no_cover.jpg',
      defaultReleaseImg: '/default__no_cover.jpg'
    }
  },
  methods: {
    async searchAll() {
      this.errorPlaylists = null
      this.errorReleases = null
      this.downloadError = null
      this.downloadSuccess = false
      this.selectedPlaylist = null
      this.selectedRelease = null
      this.releaseDetailsLoading = false
      this.releaseDetailsReady = false

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
    selectionTrackLabel(item) {
      if (!item) return 'No selection'
      if (Number.isInteger(item.track_count)) {
        return `${item.track_count} tracks`
      }
      if (Array.isArray(item.tracks)) {
        return `${item.tracks.length} tracks`
      }
      return 'Track count unknown'
    },
    async selectRelease(rel) {
      this.selectedRelease = rel
      this.releaseDetailsReady = Array.isArray(rel.tracks)
      this.releaseDetailsLoading = false
      this.errorReleases = null

      if (this.releaseDetailsReady) return

      const releaseId = rel.id
      this.releaseDetailsLoading = true
      try {
        const response = await api.releaseDetails(releaseId)
        if (this.selectedRelease?.id !== releaseId) return

        this.selectedRelease = response.data
        this.releaseDetailsReady = true
        const index = this.releases.findIndex(item => item.id === releaseId)
        if (index !== -1) this.releases.splice(index, 1, response.data)
      } catch (error) {
        if (this.selectedRelease?.id !== releaseId) return

        this.releaseDetailsReady = false
        this.errorReleases = (
          error.response?.data?.error || 'Error loading release details'
        )
      } finally {
        if (this.selectedRelease?.id === releaseId) {
          this.releaseDetailsLoading = false
        }
      }
    },
    async downloadSelected() {
      if (!this.selectionReady) {
        this.downloadError = this.trackCountError || this.downloadStatusText
        return
      }
      this.downloading = true
      this.downloadError = null
      this.downloadSuccess = false

      try {
        await api.download({
          playlist_url: this.selectedPlaylist.url,
          artist: this.selectedRelease.artist,
          album: this.selectedRelease.title,
          release_id: this.selectedRelease.id,
          track_count: this.selectedPlaylist.track_count ?? null
        })
        this.downloadSuccess = true
      } catch (e) {
        this.downloadError = e.response?.data?.detail || "Download failed"
        console.error(e)
      } finally {
        this.downloading = false
      }
    }
  }
}
</script>
