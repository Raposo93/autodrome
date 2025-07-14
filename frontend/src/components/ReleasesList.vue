<template>
  <div class="column releases">
    <h3>Releases</h3>
    <div v-if="loading">Loading releases...</div>
    <div v-if="error" class="error">{{ error }}</div>
    <ul>
      <li 
        v-for="rel in releases" 
        :key="rel.id" 
        :class="{ selected: selected?.id === rel.id }"
        @click="$emit('select', rel)"
      >
        <img 
          :src="rel.cover_url" 
          @error="handleImageError"
          alt="Release cover" 
          width="70"
        />        {{ rel.title }} by {{ rel.artist }} ({{ rel.date || '?' }}, {{ rel.tracks?.length || '?' }} tracks)
      </li>
    </ul>
    <div v-if="!loading && releases.length === 0">No releases found.</div>
  </div>
</template>

<script>
export default {
  props: {
    releases: Array,
    selected: Object,
    loading: Boolean,
    error: String,
    defaultImg: String,
  },
  methods: {
    handleImageError(event) {
      event.target.src = '/default__no_cover.jpg'
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

