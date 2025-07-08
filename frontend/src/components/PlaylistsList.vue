<template>
  <div class="column playlists">
    <h3>Playlists</h3>
    <div v-if="loading">Loading playlists...</div>
    <div v-if="error" class="error">{{ error }}</div>
    <ul>
      <li 
        v-for="pl in playlists" 
        :key="pl.id" 
        :class="{ selected: selected?.id === pl.id }"
        @click="$emit('select', pl)"
      >
        <img 
          :src="pl.thumbnail" 
          @error="handleImageError"
          alt="Playlist cover" 
          width="70" 
        />
        {{ pl.title }} - {{ pl.track_count || '?' }} tracks
      </li>
    </ul>
    <div v-if="!loading && playlists.length === 0">No playlists found.</div>
  </div>
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
  methods: {
    handleImageError(event) {
      event.target.src = this.defaultImg
    }
  }
}
</script>

<style scoped>
.column {
  flex: 1;
  max-height: 400px;
  overflow-y: auto;
}
ul {
  list-style: none;
  padding: 0;
}
li {
  cursor: pointer;
  padding: 5px;
  display: flex;
  align-items: center;
  gap: 10px;
}
li.selected {
  background-color: #cce5ff;
}
.error {
  color: red;
}
</style>