<template>
  <section class="published-view">
    <header class="published-hero">
      <button class="view-switch" type="button" @click="$emit('navigate', 'dashboard')">
        Dashboard
      </button>
      <div class="hero-copy">
        <p class="eyebrow">Durable library history</p>
        <h1>Published albums</h1>
        <p class="hero-description">
          Inspect the exact sources, decisions and final file hashes behind each album.
        </p>
      </div>
    </header>

    <p v-if="loading" class="panel-state" role="status">Loading publication history…</p>
    <p v-else-if="error" class="feedback feedback--error" role="alert">{{ error }}</p>
    <div v-else-if="!publications.length" class="panel panel-state panel-state--empty">
      <strong>No published albums yet</strong>
      <span>Successful publications will be recorded here.</span>
    </div>
    <ul v-else class="publication-list">
      <li v-for="publication in publications" :key="publication.publication_id" class="panel publication-card">
        <div>
          <p class="panel-kicker">{{ formatDate(publication.published_at) }}</p>
          <h2>{{ publication.metadata.artist }} — {{ publication.metadata.album }}</h2>
          <p>
            {{ publication.track_count }} tracks · {{ coverLabel(publication.cover) }} ·
            {{ publication.metadata.mode === 'manual' ? 'Manual metadata' : 'MusicBrainz' }}
          </p>
          <small>{{ publication.destination.relative_path }}</small>
        </div>
        <div class="publication-actions">
          <button type="button" :disabled="busy" @click="viewProvenance(publication)">
            View provenance
          </button>
          <button type="button" :disabled="busy" @click="recreate(publication)">
            Recreate in Review
          </button>
        </div>
      </li>
    </ul>

    <p v-if="actionError" class="feedback feedback--error" role="alert">{{ actionError }}</p>

    <article v-if="selected" class="panel provenance-detail" aria-labelledby="provenance-title">
      <header class="provenance-heading">
        <div>
          <p class="panel-kicker">Publication {{ selected.publication_id }}</p>
          <h2 id="provenance-title">{{ selected.metadata.artist }} — {{ selected.metadata.album }}</h2>
        </div>
        <button type="button" @click="selected = null">Close</button>
      </header>

      <dl class="provenance-facts">
        <div><dt>Published</dt><dd>{{ formatDate(selected.published_at) }}</dd></div>
        <div><dt>Job</dt><dd>{{ selected.job_id }}</dd></div>
        <div><dt>Destination</dt><dd>{{ selected.destination.relative_path }}</dd></div>
        <div><dt>Autodrome</dt><dd>{{ selected.autodrome.version }}<template v-if="selected.autodrome.commit"> · {{ selected.autodrome.commit }}</template></dd></div>
        <div><dt>Cover</dt><dd>{{ coverLabel(selected.cover) }}</dd></div>
        <div><dt>Metadata mode</dt><dd>{{ selected.metadata.mode }}</dd></div>
        <div v-if="selected.metadata.date"><dt>Release date applied</dt><dd>{{ selected.metadata.date }}</dd></div>
        <div v-if="selected.release"><dt>MusicBrainz release</dt><dd>{{ selected.release.id }} · {{ selected.release.country || 'No country' }} · {{ selected.release.media_format || 'Unknown format' }}</dd></div>
        <div><dt>YouTube playlist</dt><dd><a :href="selected.playlist.url" target="_blank" rel="noreferrer">{{ selected.playlist.title || selected.playlist.id || 'Open playlist' }}</a></dd></div>
      </dl>

      <section>
        <h3>Playlist manifest and final mapping</h3>
        <ol class="manifest-list">
          <li v-for="entry in selected.mapping" :key="entry.playlist_position">
            <strong>{{ entry.playlist_position }}. {{ manifestTitle(entry.playlist_position) }}</strong>
            <span>Video {{ entry.video_id || 'ID unavailable' }}</span>
            <span>→ metadata {{ entry.disc_number }}.{{ entry.track_position }} · {{ entry.title }}</span>
            <span>→ {{ entry.published_file }}</span>
          </li>
        </ol>
      </section>

      <section>
        <h3>Final metadata applied</h3>
        <ol class="manifest-list">
          <li v-for="track in selected.metadata.tracks" :key="track.global_position">
            <strong>{{ track.disc_number }}.{{ track.position }} · {{ track.title }}</strong>
            <span>{{ track.artist || selected.metadata.artist }}</span>
          </li>
        </ol>
      </section>

      <section>
        <h3>Published files</h3>
        <ul class="checksum-list">
          <li v-for="file in selected.files" :key="file.name">
            <strong>{{ file.name }}</strong>
            <span>{{ file.size }} bytes</span>
            <code>SHA-256 {{ file.sha256 }}</code>
          </li>
        </ul>
      </section>

      <section v-if="selected.accepted_overrides?.length">
        <h3>Accepted overrides</h3>
        <ul><li v-for="override in selected.accepted_overrides" :key="override">{{ override }}</li></ul>
      </section>
    </article>
  </section>
</template>

<script>
import api from '../services/api.js'

export default {
  emits: ['navigate', 'recreate'],
  data: () => ({
    publications: [],
    selected: null,
    loading: true,
    busy: false,
    error: null,
    actionError: null,
  }),
  mounted() {
    this.load()
  },
  methods: {
    async load() {
      this.loading = true
      this.error = null
      try {
        this.publications = (await api.publications()).data
      } catch (error) {
        this.error = error.response?.data?.detail || 'Could not load publication history.'
      } finally {
        this.loading = false
      }
    },
    async viewProvenance(publication) {
      this.busy = true
      this.actionError = null
      try {
        this.selected = (await api.publication(publication.publication_id)).data
      } catch (error) {
        this.actionError = error.response?.data?.detail || 'Could not load publication provenance.'
      } finally {
        this.busy = false
      }
    },
    async recreate(publication) {
      this.busy = true
      this.actionError = null
      try {
        const result = (await api.recreatePublication(publication.publication_id)).data
        this.$emit('recreate', result)
      } catch (error) {
        this.actionError = error.response?.data?.detail || 'Could not recreate this publication.'
      } finally {
        this.busy = false
      }
    },
    formatDate(value) {
      return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
    },
    coverLabel(cover) {
      const source = {
        cover_art_archive: 'Cover Art Archive',
        youtube_thumbnail: 'YouTube thumbnail',
        manual_upload: 'Manual upload',
        none: 'No cover',
      }[cover?.source] || 'Unknown cover'
      return cover?.square_strategy ? `${source} · ${cover.square_strategy === 'crop' ? 'Crop' : 'Fit'}` : source
    },
    manifestTitle(position) {
      return this.selected.manifest.tracks.find(track => track.position === position)?.title || 'Untitled entry'
    },
  },
}
</script>

<style scoped>
.published-view { display: grid; gap: 1rem; }
.published-hero, .provenance-heading, .publication-card, .publication-actions { display: flex; align-items: center; gap: 1rem; }
.published-hero, .provenance-heading, .publication-card { justify-content: space-between; }
.publication-list, .manifest-list, .checksum-list { display: grid; gap: 0.75rem; margin: 0; padding: 0; list-style: none; }
.publication-card { padding: 1.25rem; }
.publication-card h2 { margin: 0.2rem 0; }
.publication-card p, .publication-card small { color: var(--muted); }
.provenance-detail { display: grid; gap: 1.5rem; padding: 1.5rem; }
.provenance-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 1rem; margin: 0; }
.provenance-facts div { display: grid; gap: 0.2rem; }
.provenance-facts dt { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; }
.provenance-facts dd { margin: 0; overflow-wrap: anywhere; }
.manifest-list li, .checksum-list li { display: grid; gap: 0.2rem; padding: 0.75rem; border: 1px solid var(--line); border-radius: 8px; }
.manifest-list span, .checksum-list span { color: var(--muted); }
.checksum-list code { overflow-wrap: anywhere; font-size: 0.72rem; }
@media (max-width: 720px) { .published-hero, .publication-card, .provenance-heading { align-items: stretch; flex-direction: column; } }
</style>
