<template>
  <main class="app-shell">
    <template v-if="authenticated">
      <MusicSearch
        v-if="view !== 'status'"
        :view="view"
        @navigate="selectView"
        @show-status="selectView('status')"
      />
      <SystemStatus v-else @show-music="selectView('dashboard')" />
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

function viewFromPath(path) {
  if (path === '/status') return 'status'
  if (path === '/published') return 'published'
  if (path === '/new/review') return 'review'
  if (path === '/new') return 'select'
  return 'dashboard'
}

export default {
  components: { MusicSearch, SystemStatus },
  data: () => ({
    authenticated: false,
    token: '',
    error: null,
    view: viewFromPath(window.location.pathname),
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
      this.view = viewFromPath(window.location.pathname)
    },
    selectView(view) {
      if (view === this.view) return
      this.view = view
      const paths = {
        dashboard: '/',
        select: '/new',
        review: '/new/review',
        status: '/status',
        published: '/published',
      }
      window.history.pushState({}, '', paths[view] || '/')
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
