<template>
  <main class="app-shell">
    <MusicSearch v-if="authenticated" />
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
import api, { setApiToken } from './services/api.js'

export default {
  components: { MusicSearch },
  data: () => ({ authenticated: false, token: '', error: null }),
  async mounted() {
    try {
      await api.authenticate()
      this.authenticated = true
    } catch {
      this.error = 'Authentication required or server unavailable.'
    }
  },
  methods: {
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
