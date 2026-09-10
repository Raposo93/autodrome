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
      <div class="queue-toolbar">
        <button type="button" :disabled="busy || !hasFinishedJobs" @click="clearHistory">
          Clear finished jobs
        </button>
        <span v-if="busy" role="status">Saving queue changes…</span>
      </div>
      <p v-if="storageError" class="queue-error" role="alert">{{ storageError }}</p>
      <p v-if="actionError" class="queue-error" role="alert">{{ actionError }}</p>
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
            <span>{{ item.metadata_mode === 'manual' ? 'Manual metadata' : 'MusicBrainz metadata' }}</span>
            <span class="queue-status">{{ statusLabel(item) }}</span>
            <span v-if="item.progress">{{ progressLabel(item.progress) }}</span>
            <span v-if="item.error" class="queue-error">{{ item.error }}</span>
          </span>
          <div class="queue-actions">
            <button
              v-if="canCancel(item)"
              type="button"
              :disabled="busy"
              @click="cancelJob(item)"
            >
              Cancel
            </button>
            <button type="button" :disabled="busy || !canRetry(item)" @click="retryJob(item)">
              Retry
            </button>
            <button type="button" :disabled="busy || !canDelete(item)" @click="deleteJob(item)">
              Remove
            </button>
          </div>
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
import api, { connectWebSocket } from '../services/api'
import { progressLabel } from '../services/queueProgress.js'
import { canCancelJob, canDeleteJob, canRetryJob } from '../services/queueHistory.js'

export default {
  data() {
    return {
      queueMessages: [],
      socket: null,
      busy: false,
      storageError: null,
      actionError: null
    }
  },
  mounted() {
    this.socket = connectWebSocket((msg) => {
      if (Array.isArray(msg)) {
        this.queueMessages = msg
      } else if (msg?.type === 'queue_processing') {
        this.storageError = msg.error
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
    hasFinishedJobs() {
      return this.queueMessages.some(canDeleteJob)
    },
    queueCount() {
      const count = this.queueMessages.length
      return `${count} ${count === 1 ? 'job' : 'jobs'}`
    }
  },
  methods: {
    progressLabel,
    canCancel: canCancelJob,
    canDelete: canDeleteJob,
    canRetry(item) {
      return canRetryJob(item, this.queueMessages)
    },
    async runAction(action) {
      if (this.busy) return
      this.busy = true
      this.actionError = null
      try {
        await action()
      } catch (error) {
        this.actionError = error.response?.data?.detail || 'Could not update the queue. Please try again.'
      } finally {
        this.busy = false
      }
    },
    clearHistory() {
      if (!this.hasFinishedJobs) return
      return this.runAction(() => api.clearQueueHistory())
    },
    deleteJob(item) {
      if (!this.canDelete(item)) return
      return this.runAction(() => api.deleteJob(item.job_id))
    },
    cancelJob(item) {
      if (!this.canCancel(item)) return
      return this.runAction(() => api.cancelJob(item.job_id))
    },
    retryJob(item) {
      if (!this.canRetry(item)) return
      return this.runAction(() => api.retryJob(item.job_id))
    },
    itemTitle(item) {
      if (typeof item !== 'object') return item
      return `${item.artist || 'Unknown artist'} — ${item.album || 'Unknown album'}`
    },
    statusClass(item) {
      const status = typeof item === 'object' ? item.status : null
      return [
        'queued', 'running', 'succeeded', 'failed', 'interrupted', 'cancelled'
      ].includes(status)
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

<style scoped>
.queue-toolbar, .queue-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.queue-toolbar {
  margin-bottom: 1rem;
  align-items: center;
}
.queue-actions {
  grid-column: 2;
}
button {
  padding: 0.4rem 0.65rem;
  font-size: 0.75rem;
  color: var(--brand-dark);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 7px;
}
button:disabled {
  opacity: 0.45;
}
</style>
