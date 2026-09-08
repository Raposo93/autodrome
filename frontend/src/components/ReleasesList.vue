<template>
  <section class="panel releases-panel" aria-labelledby="releases-title">
    <header class="panel-header">
      <div>
        <p class="panel-kicker">MusicBrainz</p>
        <h2 id="releases-title">Releases</h2>
      </div>
      <span class="panel-count">{{ resultCount }}</span>
    </header>

    <div class="panel-body">
      <div v-if="loading" class="panel-state" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>
        <strong>Searching MusicBrainz</strong>
        <span>Looking for matching album editions.</span>
      </div>

      <template v-else>
        <div v-if="error" class="panel-alert" role="alert">{{ error }}</div>
        <ul v-if="releases.length" class="result-list">
          <li v-for="rel in releases" :key="rel.id">
            <button
              class="result-item"
              :class="{ 'result-item--selected': selected?.id === rel.id }"
              type="button"
              :aria-pressed="selected?.id === rel.id"
              @click="$emit('select', rel)"
            >
              <img
                class="result-cover"
                :src="rel.cover_url || defaultImg"
                @error="handleImageError"
                alt=""
                width="58"
                height="58"
                loading="lazy"
                decoding="async"
              />
              <span class="result-copy">
                <strong>{{ rel.title }}</strong>
                <span>{{ rel.artist }} · {{ rel.date || 'Date unknown' }}</span>
              </span>
              <span class="track-pill">{{ trackCountLabel(rel) }}</span>
            </button>
          </li>
        </ul>

        <div v-else-if="!error" class="panel-state panel-state--empty">
          <span class="empty-icon" aria-hidden="true">♪</span>
          <strong>No releases yet</strong>
          <span>MusicBrainz results will appear here.</span>
        </div>
      </template>
    </div>
  </section>
</template>

<script>
export default {
  props: {
    releases: Array,
    selected: Object,
    loading: Boolean,
    error: String,
    defaultImg: {
      type: String,
      default: '/default__no_cover.jpg'
    },
  },
  computed: {
    resultCount() {
      if (this.loading) return 'Searching'
      const count = this.releases.length
      return `${count} ${count === 1 ? 'result' : 'results'}`
    }
  },
  methods: {
    trackCountLabel(release) {
      if (Number.isInteger(release.track_count)) {
        return `${release.track_count} tracks`
      }
      if (Array.isArray(release.tracks)) {
        return `${release.tracks.length} tracks`
      }
      return '? tracks'
    },
    handleImageError(event) {
      event.target.src = this.defaultImg
    }
  }
}
</script>
