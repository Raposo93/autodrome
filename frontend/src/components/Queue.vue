<template>
  <section class="panel queue-panel" aria-labelledby="queue-title">
    <header class="panel-header">
      <div>
        <p class="panel-kicker">Activity</p>
        <h2 id="queue-title">Download queue</h2>
      </div>
      <span class="panel-count">{{ queueCount }}</span>
    </header>

    <div class="panel-body">
      <ul v-if="queueMessages.length" class="queue-list">
        <li
          v-for="(item, index) in queueMessages"
          :key="item.job_id || index"
          class="queue-item"
        >
          <span
            class="status-dot"
            :class="`status-dot--${statusClass(item)}`"
            aria-hidden="true"
          ></span>
          <span class="queue-copy">
            <strong>{{ itemTitle(item) }}</strong>
            <span class="queue-status">{{ statusLabel(item) }}</span>
            <span v-if="item.error" class="queue-error">{{ item.error }}</span>
          </span>
        </li>
      </ul>

      <div v-else class="panel-state panel-state--empty">
        <span class="empty-icon" aria-hidden="true">↓</span>
        <strong>Nothing queued</strong>
        <span>Completed and active downloads will appear here.</span>
      </div>
    </div>
  </section>
</template>

<script>
import { connectWebSocket } from '../services/api'

export default {
  data() {
    return {
      queueMessages: [],
      socket: null
    }
  },
  mounted() {
    this.socket = connectWebSocket((msg) => {
      if (Array.isArray(msg)) {
        this.queueMessages = msg
      } else {
        console.warn('Unexpected message:', msg)
      }
    })
  },
  beforeUnmount() {
    if (this.socket) {
      this.socket.close()
    }
  },
  computed: {
    queueCount() {
      const count = this.queueMessages.length
      return `${count} ${count === 1 ? 'job' : 'jobs'}`
    }
  },
  methods: {
    itemTitle(item) {
      if (typeof item !== 'object') return item
      return `${item.artist || 'Unknown artist'} — ${item.album || 'Unknown album'}`
    },
    statusClass(item) {
      const status = typeof item === 'object' ? item.status : null
      return ['queued', 'running', 'succeeded', 'failed', 'interrupted'].includes(status)
        ? status
        : 'unknown'
    },
    statusLabel(item) {
      const status = this.statusClass(item)
      return status.charAt(0).toUpperCase() + status.slice(1)
    }
  }
}
</script>
