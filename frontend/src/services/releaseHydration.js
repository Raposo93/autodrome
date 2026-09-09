// One request at a time; the backend owns the global MusicBrainz cadence.
export function createReleaseHydration(fetchDetails, update) {
  const cache = new Map()
  let generation = 0
  let pending = []
  let active = null
  let candidates = new Set()

  async function pump() {
    if (active) return
    while (pending.length) {
      const id = pending.shift()
      if (cache.has(id)) {
        update(id, { ...cache.get(id), hydration: 'ready', hydrationError: null })
        continue
      }
      const current = generation
      active = id
      update(id, { hydration: 'loading', hydrationError: null })
      try {
        const details = await fetchDetails(id)
        cache.set(id, details)
        if (current === generation && candidates.has(id)) {
          update(id, { ...details, hydration: 'ready', hydrationError: null })
        }
      } catch (error) {
        if (current === generation && candidates.has(id)) {
          update(id, { hydration: 'error', hydrationError: error.response?.data?.error || 'Could not load details. Select to retry.' })
        }
      } finally {
        active = null
      }
    }
  }

  return {
    reset() {
      generation += 1
      pending = []
      candidates = new Set()
    },
    start(releases) {
      this.reset()
      candidates = new Set(releases.map(release => release.id))
      for (const release of releases) {
        if (Array.isArray(release.tracks)) cache.set(release.id, release)
        if (cache.has(release.id)) {
          update(release.id, { ...cache.get(release.id), hydration: 'ready', hydrationError: null })
        } else {
          pending.push(release.id)
          update(release.id, { hydration: 'pending', hydrationError: null })
        }
      }
      void pump()
    },
    prioritize(id) {
      if (!candidates.has(id) || active === id) return
      if (cache.has(id)) {
        update(id, { ...cache.get(id), hydration: 'ready', hydrationError: null })
        return
      }
      pending = [id, ...pending.filter(candidate => candidate !== id)]
      void pump()
    },
  }
}
