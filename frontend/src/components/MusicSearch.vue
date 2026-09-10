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
          <span>Results per source</span>
          <input
            v-model.number="resultLimit"
            type="number"
            min="1"
            max="50"
            step="1"
            inputmode="numeric"
            aria-describedby="result-limit-error"
            :aria-invalid="Boolean(resultLimitError)"
          />
          <small
            v-if="resultLimitError"
            id="result-limit-error"
            class="search-field-error"
            role="alert"
          >
            {{ resultLimitError }}
          </small>
        </label>
        <div class="search-field">
          <label class="search-checkbox" for="max-tracks-enabled">
            <input
              id="max-tracks-enabled"
              v-model="maxTracksEnabled"
              type="checkbox"
            />
            <span>Max tracks per result</span>
          </label>
          <input
            id="max-tracks"
            v-model.number="maxTracks"
            type="number"
            min="1"
            step="1"
            inputmode="numeric"
            aria-label="Maximum tracks per result"
            aria-describedby="max-tracks-error"
            :disabled="!maxTracksEnabled"
            :aria-invalid="Boolean(maxTracksError)"
          />
          <small
            v-if="maxTracksError"
            id="max-tracks-error"
            class="search-field-error"
            role="alert"
          >
            {{ maxTracksError }}
          </small>
        </div>
        <button
          class="search-button"
          type="submit"
          :disabled="
            (!artist && !album) ||
            isSearching ||
            Boolean(resultLimitError || maxTracksError)
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
          <button type="submit" :disabled="!manualReady || downloading">
            {{ destinationButtonLabel('Confirm metadata & queue manual download') }}
          </button>
        </form>
      </div>

      <div
        v-if="selectedPlaylist && selectedRelease && releaseDetailsReady"
        class="cover-choice"
        aria-labelledby="cover-choice-title"
      >
        <div v-if="hasAuthoritativeCover" class="cover-authoritative">
          <img :src="selectedRelease.cover_url" alt="Selected MusicBrainz release cover" />
          <div>
            <strong id="cover-choice-title">Cover Art Archive artwork</strong>
            <p>The authoritative release artwork will be used automatically.</p>
          </div>
        </div>
        <template v-else>
          <div class="cover-choice-heading">
            <div>
              <strong id="cover-choice-title">Choose cover artwork</strong>
              <p>Cover Art Archive has no artwork for this release. Choose explicitly before queuing.</p>
            </div>
            <span v-if="coverPreparing">Preparing image…</span>
          </div>
          <div class="cover-options">
            <button
              type="button"
              class="cover-option"
              :class="{ 'cover-option--selected': coverSelection?.source === 'youtube_thumbnail' }"
              :disabled="coverPreparing || !selectedPlaylist.thumbnail"
              @click="prepareYoutubeCover"
            >
              <img
                v-if="selectedPlaylist.thumbnail"
                :src="selectedPlaylist.thumbnail"
                alt="Selected YouTube playlist thumbnail preview"
              />
              <span>
                <strong>Use playlist thumbnail</strong>
                <small>Alternative artwork from the selected YouTube playlist; not authoritative.</small>
              </span>
            </button>
            <label
              class="cover-option cover-option--upload"
              :class="{ 'cover-option--selected': coverSelection?.source === 'manual_upload' }"
            >
              <img v-if="manualCoverPreview" :src="manualCoverPreview" alt="Manual cover preview" />
              <span>
                <strong>Upload an image</strong>
                <small>JPEG, PNG or WebP. The file is validated before audio is downloaded.</small>
              </span>
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                :disabled="coverPreparing"
                @change="prepareManualCover"
              />
            </label>
            <button
              type="button"
              class="cover-option cover-option--none"
              :class="{ 'cover-option--selected': coverSelection?.source === 'none' }"
              :disabled="coverPreparing"
              @click="chooseNoCover"
            >
              <span>
                <strong>Continue without cover</strong>
                <small>No artwork will be embedded in the album files.</small>
              </span>
            </button>
          </div>
          <p v-if="!selectedPlaylist.thumbnail" class="cover-choice-note">
            This playlist has no thumbnail, so choose an upload or continue without cover.
          </p>
          <p v-if="coverError" class="feedback feedback--error" role="alert">
            {{ coverError }} You can choose another cover option.
          </p>
        </template>
      </div>

      <div
        v-if="destinationState === 'exists'"
        class="destination-alert destination-alert--exists"
        role="alert"
      >
        <strong>This album already appears to exist in the library.</strong>
        <span>Path: {{ destinationResult.relative_path }}</span>
        <span v-if="destinationResult.mp3_count !== null">
          MP3 files found: {{ destinationResult.mp3_count }}
        </span>
        <span v-else>MP3 file count is unavailable.</span>
        <span>Download is blocked because Autodrome never overwrites existing albums.</span>
      </div>
      <div
        v-if="destinationState === 'unknown'"
        class="destination-alert destination-alert--unknown"
        role="alert"
      >
        <strong>Library destination could not be checked.</strong>
        <span>{{ destinationError || 'Filesystem access prevented a reliable result.' }}</span>
        <span>Download remains blocked; the backend no-overwrite guard is unchanged.</span>
      </div>

      <div class="download-action">
        <p>{{ downloadStatusText }}</p>
        <button
          class="download-button"
          type="button"
          :disabled="!selectionReady || downloading"
          @click="downloadSelected"
        >
          {{ destinationButtonLabel('Download & Tag') }}
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
import { createAlbumDestinationCheck } from '../services/albumDestination.js'
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
        Boolean(this.manualArtist.trim() && this.manualAlbum.trim()) &&
        this.destinationState === 'not_found'
    },
    finalDestination() {
      if (
        this.selectedRelease &&
        this.releaseDetailsReady &&
        this.selectedRelease.artist?.trim() &&
        this.selectedRelease.title?.trim()
      ) {
        return {
          artist: this.selectedRelease.artist.trim(),
          album: this.selectedRelease.title.trim(),
        }
      }
      if (
        this.manualConfirmed &&
        this.selectedPlaylist &&
        !this.selectedRelease &&
        this.manualArtist.trim() &&
        this.manualAlbum.trim()
      ) {
        return {
          artist: this.manualArtist.trim(),
          album: this.manualAlbum.trim(),
        }
      }
      return null
    },
    isSearching() {
      return this.loadingPlaylists || this.loadingReleases
    },
    resultLimitError() {
      return Number.isInteger(this.resultLimit) &&
        this.resultLimit >= 1 && this.resultLimit <= 50
        ? null
        : 'Enter a whole number from 1 to 50.'
    },
    maxTracksError() {
      if (!this.maxTracksEnabled) return null
      return Number.isInteger(this.maxTracks) && this.maxTracks >= 1
        ? null
        : 'Enter a positive whole number.'
    },
    trackCountError() {
      return trackCountError(this.selectedPlaylist, this.selectedRelease)
    },
    hasAuthoritativeCover() {
      return Boolean(this.selectedRelease?.cover_url)
    },
    coverReady() {
      return this.hasAuthoritativeCover || Boolean(this.coverSelection)
    },
    selectionReady() {
      return Boolean(
        this.selectedPlaylist && this.playlistReady &&
        this.releaseDetailsReady &&
        !this.releaseDetailsLoading &&
        !this.trackCountError &&
        this.coverReady &&
        !this.coverPreparing &&
        this.destinationState === 'not_found'
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
      if (this.coverPreparing) {
        return 'Preparing and validating the selected cover image.'
      }
      if (!this.coverReady) {
        return 'Cover Art Archive has no artwork. Choose a cover option to continue.'
      }
      if (this.destinationState === 'checking') {
        return 'Checking whether the final library destination already exists…'
      }
      if (this.destinationState === 'exists') {
        return 'This album already exists and cannot be queued.'
      }
      if (this.destinationState === 'unknown') {
        return 'The library destination check failed; download remains blocked.'
      }
      return this.trackCountError || 'Both selections are ready to download.'
    }
  },
  watch: {
    finalDestination(destination) {
      this.destinationCheck.inspect(destination)
    }
  },
  data() {
    return {
      manualPrompt: false,
      manualConfirmed: false,
      manualArtist: '',
      manualAlbum: '',
      destinationCheck: null,
      destinationState: 'idle',
      destinationResult: null,
      destinationError: null,
      hydrator: null,
      artist: '',
      album: '',
      resultLimit: 10,
      maxTracksEnabled: false,
      maxTracks: 30,
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
      coverSelection: null,
      coverPreparing: false,
      coverError: null,
      coverGeneration: 0,
      manualCoverPreview: null,
      downloading: false,
      downloadError: null,
      downloadSuccess: false,
      defaultPlaylistImg: '/default__no_cover.jpg',
      defaultReleaseImg: '/default__no_cover.jpg'
    }
  },
  beforeUnmount() {
    this.hydrator?.reset()
    this.destinationCheck?.dispose()
    this.revokeManualCoverPreview()
  },
  created() {
    this.destinationCheck = createAlbumDestinationCheck(
      async destination => (await api.albumDestination(destination)).data,
      update => {
        this.destinationState = update.state
        this.destinationResult = update.result
        this.destinationError = update.error
      }
    )
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
      this.destinationCheck.reset()
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
      this.resetCoverChoice()

      if (!this.artist && !this.album) return
      const searchOptionError = this.resultLimitError || this.maxTracksError
      if (searchOptionError) {
        this.errorPlaylists = searchOptionError
        this.errorReleases = searchOptionError
        return
      }

      const artist = this.artist.trim()
      const album = this.album.trim()
      const resultLimit = this.resultLimit
      const maxTracks = this.maxTracksEnabled ? this.maxTracks : null

      this.playlists = []
      this.releases = []
      this.loadingPlaylists = true
      this.loadingReleases = true

      try {
        const response = await api.combinedSearch(
          artist,
          album,
          resultLimit,
          maxTracks
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
      this.resetCoverChoice()
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
      this.destinationCheck.reset()
      this.manualConfirmed = false
      this.manualPrompt = false
      this.resetCoverChoice()
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
          cover_source: 'none',
          artist: this.manualArtist.trim(), album: this.manualAlbum.trim()
        })
        this.downloadSuccess = true
      } catch (error) {
        this.downloadError = error.response?.data?.detail || 'Manual download failed'
      } finally {
        this.downloading = false
      }
    },
    destinationButtonLabel(readyLabel) {
      if (this.releaseDetailsLoading) return 'Loading release details...'
      if (this.downloading) return 'Adding to queue...'
      if (this.destinationState === 'checking') return 'Checking library...'
      if (this.destinationState === 'exists') return 'Album already exists'
      if (this.destinationState === 'unknown') return 'Library check unavailable'
      return readyLabel
    },
    resetCoverChoice() {
      this.coverGeneration += 1
      this.coverSelection = null
      this.coverPreparing = false
      this.coverError = null
      this.revokeManualCoverPreview()
    },
    revokeManualCoverPreview() {
      if (this.manualCoverPreview) {
        URL.revokeObjectURL(this.manualCoverPreview)
        this.manualCoverPreview = null
      }
    },
    async prepareYoutubeCover() {
      const thumbnailUrl = this.selectedPlaylist?.thumbnail
      if (!thumbnailUrl || this.coverPreparing) return
      const generation = ++this.coverGeneration
      this.revokeManualCoverPreview()
      this.coverSelection = null
      this.coverPreparing = true
      this.coverError = null
      try {
        const response = await api.prepareYoutubeCover(thumbnailUrl)
        if (generation !== this.coverGeneration) return
        this.coverSelection = {
          source: 'youtube_thumbnail',
          cover_id: response.data.cover_id,
          cover_url: thumbnailUrl,
        }
      } catch (error) {
        if (generation !== this.coverGeneration) return
        this.coverError = error.response?.data?.detail || 'Could not prepare the YouTube thumbnail.'
      } finally {
        if (generation === this.coverGeneration) this.coverPreparing = false
      }
    },
    async prepareManualCover(event) {
      const file = event.target.files?.[0]
      event.target.value = ''
      if (!file || this.coverPreparing) return
      const generation = ++this.coverGeneration
      this.revokeManualCoverPreview()
      this.manualCoverPreview = URL.createObjectURL(file)
      this.coverSelection = null
      this.coverPreparing = true
      this.coverError = null
      try {
        const response = await api.prepareManualCover(file)
        if (generation !== this.coverGeneration) return
        this.coverSelection = {
          source: 'manual_upload',
          cover_id: response.data.cover_id,
        }
      } catch (error) {
        if (generation !== this.coverGeneration) return
        this.coverError = error.response?.data?.detail || 'Could not prepare the uploaded cover.'
      } finally {
        if (generation === this.coverGeneration) this.coverPreparing = false
      }
    },
    chooseNoCover() {
      this.coverGeneration += 1
      this.revokeManualCoverPreview()
      this.coverPreparing = false
      this.coverError = null
      this.coverSelection = { source: 'none' }
    },
    selectedCoverPayload() {
      if (this.hasAuthoritativeCover) {
        return { cover_source: 'cover_art_archive' }
      }
      return {
        cover_source: this.coverSelection.source,
        ...(this.coverSelection.cover_id
          ? { cover_id: this.coverSelection.cover_id }
          : {}),
        ...(this.coverSelection.cover_url
          ? { cover_url: this.coverSelection.cover_url }
          : {}),
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
          track_count: this.selectedPlaylist.track_count ?? null,
          ...this.selectedCoverPayload(),
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
