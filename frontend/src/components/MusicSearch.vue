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
        <label class="search-field">
          <span>YouTube results</span>
          <input
            v-model.number="youtubeLimit"
            type="number"
            min="1"
            max="50"
            step="1"
            inputmode="numeric"
            aria-describedby="youtube-limit-error"
            :aria-invalid="Boolean(youtubeLimitError)"
          />
          <small
            v-if="youtubeLimitError"
            id="youtube-limit-error"
            class="search-field-error"
            role="alert"
          >
            {{ youtubeLimitError }}
          </small>
        </label>
        <div class="search-field">
          <label class="search-checkbox" for="youtube-max-tracks-enabled">
            <input
              id="youtube-max-tracks-enabled"
              v-model="maxTracksEnabled"
              type="checkbox"
            />
            <span>Max tracks</span>
          </label>
          <input
            id="youtube-max-tracks"
            v-model.number="youtubeMaxTracks"
            type="number"
            min="1"
            step="1"
            inputmode="numeric"
            aria-label="Maximum tracks"
            aria-describedby="youtube-max-tracks-error"
            :disabled="!maxTracksEnabled"
            :aria-invalid="Boolean(youtubeMaxTracksError)"
          />
          <small
            v-if="youtubeMaxTracksError"
            id="youtube-max-tracks-error"
            class="search-field-error"
            role="alert"
          >
            {{ youtubeMaxTracksError }}
          </small>
        </div>
        <button
          class="search-button"
          type="submit"
          :disabled="
            (!artist && !album) ||
            isSearching ||
            Boolean(youtubeLimitError || youtubeMaxTracksError)
          "
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

      <div v-if="selectedPlaylist && !selectedRelease" class="manual-metadata">
        <p>MusicBrainz metadata is recommended when a matching release exists.</p>
        <button v-if="!manualPrompt && !manualConfirmed" type="button" @click="manualPrompt = true">
          Download without MusicBrainz
        </button>
        <div v-if="manualPrompt && !manualConfirmed" role="alert">
          <p>Without MusicBrainz, titles and order come from the playlist and Artist + Album
            from your input. There will be no MusicBrainz date, track credits, multidisc
            metadata or cover art.</p>
          <button type="button" @click="manualConfirmed = true">I understand — enter manual metadata</button>
        </div>
        <form v-if="manualConfirmed" @submit.prevent="downloadManual">
          <label>Artist <input v-model="manualArtist" required maxlength="255" /></label>
          <label>Album <input v-model="manualAlbum" required maxlength="255" /></label>
          <button type="submit" :disabled="!manualReady || downloading">Confirm metadata &amp; queue manual download</button>
        </form>
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
import { createReleaseHydration } from '../services/releaseHydration.js'
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
    manualReady() {
      return this.manualConfirmed && this.playlistReady && !this.selectedRelease &&
        Boolean(this.manualArtist.trim() && this.manualAlbum.trim())
    },
    isSearching() {
      return this.loadingPlaylists || this.loadingReleases
    },
    youtubeLimitError() {
      return Number.isInteger(this.youtubeLimit) &&
        this.youtubeLimit >= 1 && this.youtubeLimit <= 50
        ? null
        : 'Enter a whole number from 1 to 50.'
    },
    youtubeMaxTracksError() {
      if (!this.maxTracksEnabled) return null
      return Number.isInteger(this.youtubeMaxTracks) && this.youtubeMaxTracks >= 1
        ? null
        : 'Enter a positive whole number.'
    },
    trackCountError() {
      return trackCountError(this.selectedPlaylist, this.selectedRelease)
    },
    selectionReady() {
      return Boolean(
        this.selectedPlaylist && this.playlistReady &&
        this.releaseDetailsReady &&
        !this.releaseDetailsLoading &&
        !this.trackCountError
      )
    },
    downloadStatusText() {
      if (this.playlistError) return this.playlistError
      if (this.selectedPlaylist && !this.playlistReady) return 'Checking playlist availability…'
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
      manualPrompt: false,
      manualConfirmed: false,
      manualArtist: '',
      manualAlbum: '',
      hydrator: null,
      artist: '',
      album: '',
      youtubeLimit: 10,
      maxTracksEnabled: false,
      youtubeMaxTracks: 30,
      playlists: [],
      releases: [],
      loadingPlaylists: false,
      loadingReleases: false,
      errorPlaylists: null,
      errorReleases: null,
      selectedPlaylist: null,
      playlistReady: false,
      playlistError: null,
      playlistGeneration: 0,
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
  beforeUnmount() {
    this.hydrator?.reset()
  },
  methods: {
    hydrateReleases() {
      if (!this.hydrator) {
        this.hydrator = createReleaseHydration(
          async id => (await api.releaseDetails(id)).data,
          (id, details) => {
            const release = this.releases.find(item => item.id === id)
            if (!release) return
            Object.assign(release, details)
            if (this.selectedRelease?.id === id) {
              this.selectedRelease = release
              this.releaseDetailsReady = details.hydration === 'ready'
              this.releaseDetailsLoading = ['pending', 'loading'].includes(details.hydration)
            }
          }
        )
      }
      this.hydrator.start(this.releases)
    },
    async searchAll() {
      this.manualConfirmed = false
      this.manualPrompt = false
      this.hydrator?.reset()
      this.playlistGeneration += 1
      this.playlistReady = false
      this.playlistError = null
      this.errorPlaylists = null
      this.errorReleases = null
      this.downloadError = null
      this.downloadSuccess = false
      this.selectedPlaylist = null
      this.selectedRelease = null
      this.releaseDetailsLoading = false
      this.releaseDetailsReady = false

      if (!this.artist && !this.album) return
      const youtubeSearchError = this.youtubeLimitError || this.youtubeMaxTracksError
      if (youtubeSearchError) {
        this.errorPlaylists = youtubeSearchError
        return
      }

      const artist = this.artist.trim()
      const album = this.album.trim()
      const youtubeLimit = this.youtubeLimit
      const youtubeMaxTracks = this.maxTracksEnabled ? this.youtubeMaxTracks : null

      this.playlists = []
      this.releases = []
      this.loadingPlaylists = true
      this.loadingReleases = true

      try {
        const response = await api.combinedSearch(
          artist,
          album,
          youtubeLimit,
          youtubeMaxTracks
        )
        this.playlists = response.data.playlists || []
        this.releases = response.data.releases || []
        this.errorPlaylists = response.data.errors?.youtube || null
        this.errorReleases = response.data.errors?.musicbrainz || null
        this.hydrateReleases()

      } catch (e) {
        this.errorPlaylists = e.response?.data?.errors?.youtube || "Error fetching playlists"
        this.errorReleases = e.response?.data?.errors?.musicbrainz || "Error fetching releases"
      } finally {
        this.loadingPlaylists = false
        this.loadingReleases = false
      }
    },
    async selectPlaylist(pl) {
      this.manualConfirmed = false
      this.manualPrompt = false
      const generation = ++this.playlistGeneration
      this.selectedPlaylist = pl
      this.playlistReady = false
      this.playlistError = null
      try {
        const response = await api.playlistPreflight({ playlist_url: pl.url, track_count: pl.track_count ?? null })
        if (generation !== this.playlistGeneration) return
        this.selectedPlaylist = { ...pl, track_count: response.data.track_count }
        this.playlistReady = true
      } catch (error) {
        if (generation !== this.playlistGeneration) return
        this.playlistError = error.response?.data?.detail || 'Could not check playlist. Select it again to retry.'
      }
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
    selectRelease(rel) {
      this.manualConfirmed = false
      this.manualPrompt = false
      this.selectedRelease = rel
      this.releaseDetailsReady = Array.isArray(rel.tracks)
      this.releaseDetailsLoading = !this.releaseDetailsReady
      this.hydrator?.prioritize(rel.id)
    },
    async downloadManual() {
      if (!this.manualReady || this.downloading) return
      this.downloading = true
      this.downloadError = null
      this.downloadSuccess = false
      try {
        await api.download({
          playlist_url: this.selectedPlaylist.url,
          track_count: this.selectedPlaylist.track_count,
          release_id: null, metadata_mode: 'manual', manual_confirmed: true,
          artist: this.manualArtist.trim(), album: this.manualAlbum.trim()
        })
        this.downloadSuccess = true
      } catch (error) {
        this.downloadError = error.response?.data?.detail || 'Manual download failed'
      } finally {
        this.downloading = false
      }
    },
    async downloadSelected() {
      if (this.downloading) return
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
