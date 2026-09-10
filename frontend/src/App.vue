<template>
  <main class="app-shell">
    <template v-if="authenticated">
      <MusicSearch
        v-if="view === 'search'"
        @show-status="selectView('status')"
      />
      <SystemStatus v-else @show-music="selectView('search')" />
    </template>
    <form v-else class="panel" @submit.prevent="connect">
      <h1>Connect to Autodrome</h1>
      <p>Enter the API token configured by the server owner.</p>
      <label>API token <input v-model="token" type="password" autocomplete="off" /></label>
      <button type="submit">Connect</button>
      <p v-if="error" role="alert">{{ error }}</p>
    </form>
  </main>
</template>

<script>
import MusicSearch from './components/MusicSearch.vue'
import SystemStatus from './components/SystemStatus.vue'
import api, { setApiToken } from './services/api.js'

export default {
  components: { MusicSearch, SystemStatus },
  data: () => ({
    authenticated: false,
    token: '',
    error: null,
    view: window.location.pathname === '/status' ? 'status' : 'search',
  }),
  async mounted() {
    window.addEventListener('popstate', this.syncViewFromPath)
    try {
      await api.authenticate()
      this.authenticated = true
    } catch {
      this.error = 'Authentication required or server unavailable.'
    }
  },
  beforeUnmount() {
    window.removeEventListener('popstate', this.syncViewFromPath)
  },
  methods: {
    syncViewFromPath() {
      this.view = window.location.pathname === '/status' ? 'status' : 'search'
    },
    selectView(view) {
      if (view === this.view) return
      this.view = view
      window.history.pushState({}, '', view === 'status' ? '/status' : '/')
    },
    async connect() {
      setApiToken(this.token)
      try {
        await api.authenticate()
        this.authenticated = true
        this.token = ''
        this.error = null
      } catch {
        setApiToken('')
        this.error = 'Could not connect. Check the token and server.'
      }
    }
  }
}
</script>
