<template>
  <section class="panel playlists-panel" aria-labelledby="playlists-title">
    <header class="panel-header">
      <div>
        <p class="panel-kicker">YouTube</p>
        <h2 id="playlists-title">Playlists</h2>
      </div>
      <span class="panel-count">{{ resultCount }}</span>
    </header>

    <div class="panel-body">
      <div v-if="loading" class="panel-state" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>
        <strong>Searching YouTube</strong>
        <span>Finding playlists and counting their tracks.</span>
      </div>

      <template v-else>
        <div v-if="error" class="panel-alert" role="alert">{{ error }}</div>
        <ul v-if="playlists.length" class="result-list">
          <li v-for="pl in playlists" :key="pl.id">
            <button
              class="result-item"
              :class="{ 'result-item--selected': selected?.id === pl.id }"
              type="button"
              :aria-pressed="selected?.id === pl.id"
              @click="$emit('select', pl)"
            >
              <img
                class="result-cover"
                :src="pl.thumbnail || defaultImg"
                @error="handleImageError"
                alt=""
                width="58"
                height="58"
                loading="lazy"
                decoding="async"
              />
              <span class="result-copy">
                <strong>{{ pl.title }}</strong>
                <span>{{ pl.channel || 'Unknown channel' }}</span>
              </span>
              <span class="track-pill">{{ trackCount(pl) }}</span>
            </button>
          </li>
        </ul>

        <div v-else-if="!error" class="panel-state panel-state--empty">
          <span class="empty-icon" aria-hidden="true">▶</span>
          <strong>No playlists yet</strong>
          <span>Search for an artist or album to get started.</span>
        </div>
      </template>
    </div>
  </section>
</template>

<script>
export default {
  props: {
    playlists: Array,
    selected: Object,
    loading: Boolean,
    error: String,
    defaultImg: {
      type: String,
      default: '/default__no_cover.jpg'
    }
  },
  computed: {
    resultCount() {
      if (this.loading) return 'Searching'
      const count = this.playlists.length
      return `${count} ${count === 1 ? 'result' : 'results'}`
    }
  },
  methods: {
    trackCount(playlist) {
      return Number.isInteger(playlist.track_count)
        ? `${playlist.track_count} tracks`
        : '? tracks'
    },
    handleImageError(event) {
      event.target.src = this.defaultImg
    }
  }
}
</script>
