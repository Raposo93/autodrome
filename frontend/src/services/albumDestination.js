const knownStates = new Set(['not_found', 'exists', 'unknown'])

export function createAlbumDestinationCheck(
  check,
  publish,
  { delay = 250, schedule = setTimeout, cancel = clearTimeout } = {},
) {
  let generation = 0
  let timer = null

  function clearTimer() {
    if (timer !== null) cancel(timer)
    timer = null
  }

  function reset() {
    generation += 1
    clearTimer()
    publish({ state: 'idle', result: null, error: null })
  }

  function inspect(destination) {
    generation += 1
    const current = generation
    clearTimer()
    if (!destination) {
      publish({ state: 'idle', result: null, error: null })
      return
    }

    publish({ state: 'checking', result: null, error: null })
    timer = schedule(async () => {
      timer = null
      try {
        const result = await check(destination)
        if (current !== generation) return
        if (!knownStates.has(result?.state)) {
          publish({
            state: 'unknown',
            result: null,
            error: 'The library returned an invalid destination check.',
          })
          return
        }
        publish({ state: result.state, result, error: null })
      } catch (error) {
        if (current !== generation) return
        publish({
          state: 'unknown',
          result: null,
          error: error.response?.data?.detail ||
            'The library destination could not be checked.',
        })
      }
    }, delay)
  }

  function dispose() {
    generation += 1
    clearTimer()
  }

  return { inspect, reset, dispose }
}
