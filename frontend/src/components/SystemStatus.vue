<template>
  <section class="system-status" aria-labelledby="system-status-title">
    <header class="status-hero">
      <button class="view-switch" type="button" @click="$emit('show-music')">
        Music
      </button>
      <div>
        <p class="eyebrow">Diagnostics</p>
        <h1 id="system-status-title">System status</h1>
        <p>
          A live, read-only view of Autodrome and its dependencies. Provider
          failures do not mean the server itself is offline.
        </p>
      </div>
      <button type="button" :disabled="loading" @click="loadStatus">
        {{ loading ? 'Checking…' : 'Refresh checks' }}
      </button>
    </header>

    <p v-if="error" class="status-load-error" role="alert">{{ error }}</p>
    <div v-if="loading && !report" class="status-loading" role="status">
      Running bounded diagnostic checks…
    </div>

    <template v-if="report">
      <section class="version-card" aria-label="Autodrome build">
        <div>
          <span>Version</span>
          <strong>{{ report.version }}</strong>
        </div>
        <div>
          <span>Commit</span>
          <strong>{{ report.commit || 'Not provided by this build' }}</strong>
        </div>
      </section>

      <section class="status-grid" aria-label="System diagnostics">
        <article
          v-for="component in components"
          :key="component.key"
          class="status-card"
          :aria-label="component.label"
        >
          <div class="status-card-heading">
            <h2>{{ component.label }}</h2>
            <span
              class="status-badge"
              :class="`status-badge--${component.status}`"
            >
              {{ statusLabel(component.status) }}
            </span>
          </div>
          <p>{{ component.message }}</p>
          <dl v-if="component.free_bytes !== undefined || component.state">
            <div v-if="component.free_bytes !== undefined">
              <dt>Free space</dt>
              <dd>{{ formatBytes(component.free_bytes) }}</dd>
            </div>
            <div v-if="component.state">
              <dt>State</dt>
              <dd>{{ component.state }}</dd>
            </div>
          </dl>
        </article>
      </section>

      <p v-if="report.storage_error" class="storage-error" role="alert">
        <strong>Latest queue storage error</strong>
        {{ report.storage_error }}
      </p>
    </template>
  </section>
</template>

<script>
import api from '../services/api.js'
import {
  formatBytes,
  statusEntries,
  statusLabel,
} from '../services/systemStatus.js'

export default {
  emits: ['show-music'],
  data: () => ({
    report: null,
    loading: false,
    error: null,
  }),
  computed: {
    components() {
      return statusEntries(this.report?.components)
    },
  },
  mounted() {
    this.loadStatus()
  },
  methods: {
    formatBytes,
    statusLabel,
    async loadStatus() {
      if (this.loading) return
      this.loading = true
      this.error = null
      try {
        this.report = (await api.systemStatus()).data
      } catch (error) {
        this.error = error.response?.data?.detail ||
          'Could not load system diagnostics. The previous result is still shown.'
      } finally {
        this.loading = false
      }
    },
  },
}
</script>
