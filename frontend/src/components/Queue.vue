<template>
  <div>
    <h3>Download Queue</h3>
    <ul>
      <li v-for="(msg, index) in queueMessages" :key="index">
        {{ formatItem(msg) }}
      </li>
    </ul>
  </div>
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
  methods: {
    formatItem(item) {
      if (typeof item === 'object') {
        return `${item.artist || 'Unknown'} - ${item.album || 'Unknown'} [${item.status || 'queued'}]`
      }
      return item
    }
  }
}
</script>

<style scoped>
ul {
  list-style: none;
  padding: 0;
}

li {
  padding: 4px;
  border-bottom: 1px solid #ccc;
}
</style>
