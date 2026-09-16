import { expect, test } from '@playwright/test'
import {
  ControlledBackend,
  playlist,
  release,
  releaseDetails,
} from './controlledBackend.js'

const playlistsPanel = page => page.getByRole('region', { name: 'Playlists' })
const releasesPanel = page => page.getByRole('region', { name: 'Releases' })
const queuePanel = page => page.getByRole('region', { name: 'Download queue' })

async function openApp(page, backend) {
  await backend.install(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Download dashboard' })).toBeVisible()
  await expect(queuePanel(page)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Review download' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Download & Tag' })).toHaveCount(0)
}

async function startSearch(page, { artist = 'Test Artist', album = 'Test Album' } = {}) {
  if (await page.getByLabel('Artist').count() === 0) {
    await page.getByRole('button', { name: /New download/ }).click()
  }
  await expect(page.getByRole('heading', { name: 'Find the right album release' })).toBeVisible()
  await page.getByLabel('Artist').fill(artist)
  await page.getByLabel('Album').fill(album)
  await page.getByRole('button', { name: 'Search music' }).click()
}

async function continueToReview(
  page,
  backend = null,
  destinationResult = { state: 'not_found', exists: false },
) {
  const button = page.getByRole('button', { name: 'Continue to review' })
  await expect(button).toBeEnabled()
  await button.click()
  if (backend) {
    const destination = await backend.next('destination')
    await destination.reply(destinationResult)
  }
  await expect(page.getByRole('heading', { name: 'Check before you queue' })).toBeVisible()
}

test('system status route renders partial diagnostics and every state', async ({ page }) => {
  const backend = new ControlledBackend()
  await backend.install(page)
  await page.goto('/status')
  const request = await backend.next('status')
  await request.reply({
    version: 'autodrome/test',
    commit: 'abcdef1',
    storage_error: 'Queue persistence is unavailable; retrying automatically.',
    components: {
      library: { status: 'ok', message: 'Writable.', free_bytes: 183 * 1024 ** 3 },
      staging: { status: 'warning', message: 'Directory has not been created yet.' },
      queue_storage: { status: 'error', message: 'Filesystem is read-only.' },
      ffmpeg: { status: 'ok', message: 'ffmpeg version test' },
      yt_dlp: { status: 'ok', message: 'yt-dlp 2026.8.19 · EJS 0.8.0' },
      js_runtime: { status: 'warning', message: 'No supported runtime available.' },
      youtube: { status: 'error', message: 'Configured, but unreachable.' },
      musicbrainz: { status: 'warning', message: 'Temporarily unreachable.' },
      redis: { status: 'disabled', message: 'Optional cache is disabled.' },
      worker: { status: 'ok', message: 'Worker is idle.', state: 'idle' },
    },
  })

  await expect(page.getByRole('heading', { name: 'System status' })).toBeVisible()
  await expect(page.locator('.status-hero').getByRole('button', { name: 'Music' })).toBeVisible()
  await expect(page.locator('.app-navigation')).toHaveCount(0)
  const diagnostics = page.getByRole('region', { name: 'System diagnostics' })
  await expect(diagnostics.getByText('OK', { exact: true })).toHaveCount(4)
  await expect(diagnostics.getByText('Warning', { exact: true })).toHaveCount(3)
  await expect(diagnostics.getByText('Error', { exact: true })).toHaveCount(2)
  await expect(diagnostics.getByText('Disabled', { exact: true })).toHaveCount(1)
  await expect(diagnostics.getByRole('article', { name: 'Library' })).toContainText('183 GiB')
  await expect(diagnostics.getByRole('article', { name: 'JS runtime' })).toContainText('No supported runtime')
  await expect(page.getByRole('alert')).toContainText('retrying automatically')
})

test('dashboard reveals the download flow without reopening it on refresh', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await expect(page.getByLabel('Artist')).toHaveCount(0)
  await expect(queuePanel(page).getByRole('button', { name: 'Clear finished jobs' })).toHaveCount(0)
  await page.getByRole('button', { name: /New download/ }).click()
  await expect(page).toHaveURL(/\/new$/)
  await expect(page.getByLabel('Maximum tracks per result')).toBeDisabled()
  await page.getByLabel('Max tracks per result').check()
  await expect(page.getByLabel('Maximum tracks per result')).toBeEnabled()

  await page.locator('.search-hero').getByRole('button', { name: 'Dashboard' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(queuePanel(page)).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Download dashboard' })).toBeVisible()
  await expect(page.getByLabel('Artist')).toHaveCount(0)
})

test('published provenance can be inspected and recreated without enqueueing', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)
  await page.getByRole('button', { name: 'Published albums' }).click()
  const history = await backend.next('publications')
  const summary = {
    publication_id: 'pub-1', job_id: 'job-1', published_at: '2026-09-15T12:00:00Z',
    track_count: 1,
    destination: { relative_path: 'Historical Artist/Historical Album' },
    metadata: { mode: 'manual', artist: 'Historical Artist', album: 'Historical Album' },
    release: null,
    playlist: { id: 'playlist-id', url: 'https://youtube.test/playlist?list=playlist-id', title: 'Historical playlist' },
    cover: { source: 'none', square_strategy: null },
    autodrome: { version: 'autodrome/test', commit: 'abcdef1' },
  }
  await history.reply([summary])
  await expect(page.getByRole('heading', { name: 'Published albums' })).toBeVisible()
  await expect(page.getByText('Historical Artist — Historical Album')).toBeVisible()

  await page.getByRole('button', { name: 'View provenance' }).click()
  const detailRequest = await backend.next('publication:pub-1')
  const detail = {
    ...summary,
    record_version: 1,
    metadata: {
      ...summary.metadata, date: null,
      tracks: [{ disc_number: 1, position: 1, global_position: 1, title: 'Original track', artist: null }],
    },
    manifest: { track_count: 1, unavailable: 0, tracks: [{ position: 1, id: 'video-1', url: 'video', title: 'Original upload' }] },
    mapping: [{ playlist_position: 1, video_id: 'video-1', metadata_position: 1, disc_number: 1, track_position: 1, title: 'Original track', published_file: '01 - Original track.mp3' }],
    files: [{ name: '01 - Original track.mp3', size: 123, sha256: 'a'.repeat(64) }],
    accepted_overrides: ['manual_metadata_without_musicbrainz'],
  }
  await detailRequest.reply(detail)
  await expect(page.getByText(`SHA-256 ${'a'.repeat(64)}`)).toBeVisible()
  await expect(page.getByText('Original upload')).toBeVisible()

  await page.getByRole('button', { name: 'Recreate in Review' }).click()
  const recreate = await backend.next('publication-recreate:pub-1')
  await recreate.reply({
    publication: detail,
    review: {
      metadata_mode: 'manual', artist: 'Historical Artist', album: 'Historical Album',
      playlist: { ...summary.playlist, track_count: 1, tracks: detail.manifest.tracks },
      release: null, cover: detail.cover,
      accepted_overrides: detail.accepted_overrides,
    },
    drift: {
      playlist: { status: 'changed', changed: true, error: null, changes: [{ position: 1, status: 'changed', original: detail.manifest.tracks[0], current: { position: 1, title: 'Current upload' } }] },
      release: { status: 'not_applicable', changed: false, error: null, changes: [] },
    },
    enqueued: false,
  })
  const destination = await backend.next('destination')
  await destination.reply({ state: 'exists', exists: true, relative_path: 'Historical Artist/Historical Album', mp3_count: 1 })
  await expect(page.getByRole('heading', { name: 'Historical decisions are preserved' })).toBeVisible()
  await expect(page.getByText(/was “Original upload”.*now “Current upload”/)).toBeVisible()
  await expect(page.getByText('This album already appears to exist in the library.')).toBeVisible()
  expect(backend.callCount('download')).toBe(0)
})

test('a stale review URL falls back to a fresh selection screen', async ({ page }) => {
  const backend = new ControlledBackend()
  await backend.install(page)
  await page.goto('/new/review')

  await expect(page).toHaveURL(/\/new$/)
  await expect(page.getByRole('heading', { name: 'Find the right album release' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Review download' })).toHaveCount(0)
})

test('the ready desktop workflow fits without document scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 900 })
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page)
  await expect(page.locator('.search-hero').getByRole('button', { name: 'Dashboard' })).toBeVisible()
  const search = await backend.next('search')
  await search.reply({
    playlists: [playlist('layout')],
    releases: [release('layout')],
    errors: {},
  })

  const hydration = await backend.next('release:layout')
  await playlistsPanel(page).getByRole('button', { name: /Playlist layout/ }).click()
  const preflight = await backend.next('preflight')
  await releasesPanel(page).getByRole('button', { name: /Release layout/ }).click()
  await preflight.reply({ track_count: 2 })
  await hydration.reply(releaseDetails('layout'))
  const destination = await backend.next('destination')
  await destination.reply({ state: 'not_found', exists: false })
  await continueToReview(page, backend)

  const readyButton = page.getByRole('button', { name: 'Download & Tag' })
  await expect(readyButton).toBeEnabled()
  await expect(page.locator('.selection-card--with-cover')).toContainText('Archive cover')
  await expect(page.getByText('Cover Art Archive artwork', { exact: true })).toHaveCount(0)

  const viewport = await page.evaluate(() => ({
    height: window.innerHeight,
    scrollHeight: document.documentElement.scrollHeight,
  }))
  expect(viewport.scrollHeight).toBeLessThanOrEqual(viewport.height)
  const buttonBounds = await readyButton.boundingBox()
  expect(buttonBounds.y + buttonBounds.height).toBeLessThanOrEqual(viewport.height)
})

test('happy path queues one fully checked download', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page)
  const search = await backend.next('search')
  expect(search.query).toEqual({
    artist: 'Test Artist',
    album: 'Test Album',
    result_limit: '10',
  })
  await search.reply({
    playlists: [playlist('happy')],
    releases: [release('happy')],
    errors: {},
  })

  const hydration = await backend.next('release:happy')
  await playlistsPanel(page).getByRole('button', { name: /Playlist happy/ }).click()
  const preflight = await backend.next('preflight')
  expect(preflight.body).toEqual({
    playlist_url: 'https://youtube.test/playlist?list=happy',
    track_count: 2,
  })
  await releasesPanel(page).getByRole('button', { name: /Release happy/ }).click()

  const downloadButton = page.getByRole('button', { name: 'Loading release details…' })
  await expect(downloadButton).toBeDisabled()
  expect(backend.callCount('download')).toBe(0)

  await preflight.reply({ track_count: 2 })
  await hydration.reply(releaseDetails('happy'))
  const destination = await backend.next('destination')
  expect(destination.body).toEqual({
    artist: 'Artist happy',
    album: 'Release happy',
  })
  await destination.reply({
    state: 'not_found', exists: false, artist: 'Artist happy',
    album: 'Release happy', relative_path: 'Artist happy/Release happy',
    mp3_count: 0, file_count: 0,
  })
  await continueToReview(page, backend)
  const readyButton = page.getByRole('button', { name: 'Download & Tag' })
  await expect(readyButton).toBeEnabled()

  const downloadAction = page.locator('.download-button')
  await downloadAction.dispatchEvent('click')
  await downloadAction.dispatchEvent('click')
  const download = await backend.next('download')
  expect(download.body).toEqual({
    playlist_url: 'https://youtube.test/playlist?list=happy',
    playlist_id: 'happy',
    playlist_title: 'Playlist happy',
    playlist_channel: 'Channel happy',
    playlist_thumbnail: 'https://i.ytimg.com/vi/happy/mqdefault.jpg',
    artist: 'Artist happy',
    album: 'Release happy',
    release_id: 'happy',
    track_count: 2,
    cover_source: 'cover_art_archive',
  })
  expect(backend.callCount('download')).toBe(1)
  await expect(page.locator('.feedback--error')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Adding to queue...' })).toBeDisabled()

  await download.reply({ job_id: 'happy-job' }, 202)
  backend.setQueue([{
    job_id: 'happy-job',
    artist: 'Artist happy',
    album: 'Release happy',
    status: 'queued',
    metadata_mode: 'musicbrainz',
  }])
  await expect(page.getByText('Download queued successfully.')).toBeVisible()
  await expect(queuePanel(page)).toContainText('Artist happy — Release happy')
  expect(backend.queue[0].status).toBe('queued')
})

test('a new search owns the UI while old hydration and preflight finish', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page, { artist: 'Old Artist', album: 'Old Album' })
  const oldSearch = await backend.next('search')
  await oldSearch.reply({
    playlists: [playlist('old')],
    releases: [release('old')],
    errors: {},
  })
  const oldHydration = await backend.next('release:old')
  await playlistsPanel(page).getByRole('button', { name: /Playlist old/ }).click()
  const oldPreflight = await backend.next('preflight')

  await page.getByLabel('Artist').fill('New Artist')
  await page.getByLabel('Album').fill('New Album')
  await page.getByLabel('Results per source').fill('3')
  await page.getByLabel('Max tracks per result').check()
  await page.getByLabel('Maximum tracks per result').fill('5')
  await page.getByRole('button', { name: 'Search music' }).click()
  const newSearch = await backend.next('search')
  expect(newSearch.query).toEqual({
    artist: 'New Artist',
    album: 'New Album',
    result_limit: '3',
    max_tracks: '5',
  })
  await newSearch.reply({
    playlists: [playlist('new')],
    releases: [release('new')],
    errors: {},
  })

  await expect(playlistsPanel(page)).toContainText('Playlist new')
  await expect(playlistsPanel(page)).not.toContainText('Playlist old')
  await oldPreflight.reply({ track_count: 2 })
  await oldHydration.reply(releaseDetails('old'))
  const newHydration = await backend.next('release:new')
  await newHydration.reply(releaseDetails('new'))

  await expect(page.locator('.selection-preview')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Continue to review' })).toHaveCount(0)
  await expect(releasesPanel(page)).toContainText('Track new-1')
  await expect(releasesPanel(page)).not.toContainText('Track old-1')
  expect(backend.callCount('download')).toBe(0)
})

test('same-title releases expose edition metadata before expansion', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)
  await startSearch(page, { artist: 'Metallica', album: 'Master of Puppets' })
  const search = await backend.next('search')
  await search.reply({
    playlists: [],
    releases: [
      release('original', 8, true, {
        title: 'Master of Puppets', artist: 'Metallica', date: '1986-03-03',
        country: 'US', media_format: 'CD', medium_count: 1,
      }),
      release('box', 46, true, {
        title: 'Master of Puppets', artist: 'Metallica', date: '2017',
        country: 'XE', media_format: '3×CD', medium_count: 3,
      }),
      release('unknown', 8, true, {
        title: 'Master of Puppets', artist: 'Metallica', date: null,
        country: null, media_format: null, medium_count: null,
      }),
    ],
    errors: {},
  })

  await expect(releasesPanel(page).getByText('1986 · US · CD')).toBeVisible()
  await expect(releasesPanel(page).getByText('2017 · XE · 3×CD')).toBeVisible()
  await expect(
    releasesPanel(page).getByText('Year unknown · Country unknown · Format unknown')
  ).toBeVisible()
  await expect(releasesPanel(page).getByText('8 tracks')).toHaveCount(2)
  await expect(releasesPanel(page).getByText('46 tracks')).toBeVisible()
})

test('review matching is positional, cached, and ignores stale responses', async ({ page }) => {
  const backend = new ControlledBackend()
  const releaseTracklist = ['One', 'Two', 'Three'].map((title, index) => ({
    title,
    artist: 'Artist match',
    duration_seconds: 240 + index,
    disc_number: 1,
    position: index + 1,
    global_position: index + 1,
  }))
  const matchingTracks = ['One', 'Two (Official Audio)', 'Three (Live)'].map(
    (title, index) => ({
      position: index + 1,
      title,
      duration_seconds: 240 + index,
      url: `track-${index + 1}`,
    })
  )
  const comparison = {
    status: 'review',
    reason: null,
    playlist_count: 3,
    release_count: 3,
    summary: { exact: 1, clean: 1, close: 0, warning: 1, mismatch: 0 },
    tracks: [
      { position: 1, youtube_title: 'One', release_title: 'One', score: 1, status: 'exact', reasons: [] },
      { position: 2, youtube_title: 'Two (Official Audio)', release_title: 'Two', score: 1, status: 'clean', reasons: ['youtube_decoration'] },
      { position: 3, youtube_title: 'Three (Live)', release_title: 'Three', score: 0.7, status: 'warning', reasons: ['version_marker:live'] },
    ],
  }

  await openApp(page, backend)
  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({
    playlists: [playlist('match', 3), playlist('other', 3)],
    releases: [release('match', 3)],
    errors: {},
  })
  const hydration = await backend.next('release:match')
  await playlistsPanel(page).getByRole('button', { name: /Playlist match/ }).click()
  const preflight = await backend.next('preflight')
  await preflight.reply({ track_count: 3, tracks: matchingTracks, unavailable: 0 })
  await releasesPanel(page).getByRole('button', { name: /Release match/ }).click()
  await hydration.reply({ ...releaseDetails('match', 3), tracks: releaseTracklist })
  const destination = await backend.next('destination')
  await destination.reply({ state: 'not_found', exists: false })
  await continueToReview(page, backend)

  const compatibility = await backend.next('compatibility')
  expect(compatibility.body.artist).toBe('Artist match')
  expect(compatibility.body.playlist_tracks.map(track => track.title)).toEqual(
    matchingTracks.map(track => track.title)
  )
  expect(compatibility.body.playlist_tracks.map(track => track.duration_seconds)).toEqual(
    matchingTracks.map(track => track.duration_seconds)
  )
  expect(compatibility.body.release_tracks.map(track => track.title)).toEqual(
    releaseTracklist.map(track => track.title)
  )
  expect(compatibility.body.release_tracks.map(track => track.duration_seconds)).toEqual(
    releaseTracklist.map(track => track.duration_seconds)
  )
  await compatibility.reply(comparison)
  await expect(page.getByText('Review recommended', { exact: true })).toBeVisible()
  await page.getByText('Review 3 track comparisons').click()
  await expect(page.getByText('Minor noise', { exact: true })).toBeVisible()
  await expect(page.getByText('Three (Live)', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Back to selections' }).click()
  await continueToReview(page, backend)
  expect(backend.callCount('compatibility')).toBe(1)

  await page.getByRole('button', { name: 'Back to selections' }).click()
  await playlistsPanel(page).getByRole('button', { name: /Playlist other/ }).click()
  const otherPreflight = await backend.next('preflight')
  await otherPreflight.reply({
    track_count: 3,
    unavailable: 0,
    tracks: ['Wrong A', 'Wrong B', 'Wrong C'].map((title, index) => ({
      position: index + 1, title, url: `wrong-${index + 1}`,
    })),
  })
  await continueToReview(page, backend)
  const staleCompatibility = await backend.next('compatibility')

  await page.getByRole('button', { name: 'Back to selections' }).click()
  await playlistsPanel(page).getByRole('button', { name: /Playlist match/ }).click()
  const currentPreflight = await backend.next('preflight')
  await currentPreflight.reply({ track_count: 3, tracks: matchingTracks, unavailable: 0 })
  await continueToReview(page, backend)
  const currentCompatibility = await backend.next('compatibility')
  await currentCompatibility.reply(comparison)
  await staleCompatibility.reply({
    ...comparison,
    status: 'mismatch',
    summary: { exact: 0, clean: 0, close: 0, warning: 0, mismatch: 3 },
  })

  await expect(page.getByText('Review recommended', { exact: true })).toBeVisible()
  await expect(page.getByText('Likely wrong release', { exact: true })).toHaveCount(0)
})

test('review exposes count mismatch as a hard gate without title scoring', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)
  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({
    playlists: [playlist('count-mismatch', 3)],
    releases: [release('count-mismatch', 2)],
    errors: {},
  })
  const hydration = await backend.next('release:count-mismatch')
  await playlistsPanel(page).getByRole('button', { name: /Playlist count-mismatch/ }).click()
  const preflight = await backend.next('preflight')
  await preflight.reply({ track_count: 3 })
  await releasesPanel(page).getByRole('button', { name: /Release count-mismatch/ }).click()
  await hydration.reply(releaseDetails('count-mismatch', 2))
  const destination = await backend.next('destination')
  await destination.reply({ state: 'not_found', exists: false })
  await continueToReview(page, backend)
  const compatibility = await backend.next('compatibility')
  await compatibility.reply({
    status: 'mismatch',
    reason: 'track_count_mismatch',
    playlist_count: 3,
    release_count: 2,
    summary: { exact: 0, clean: 0, close: 0, warning: 0, mismatch: 0 },
    tracks: [],
  })

  await expect(page.getByText('Likely wrong release', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('YouTube has 3 tracks')
  await expect(page.getByRole('alert')).toContainText('Title scoring was skipped')
  await expect(page.getByRole('button', { name: 'Download & Tag' })).toBeDisabled()
})

test('rapid playlist and release changes ignore stale completions', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({
    playlists: [playlist('p1'), playlist('p2')],
    releases: [release('r1'), release('r2')],
    errors: {},
  })
  const firstHydration = await backend.next('release:r1')

  await playlistsPanel(page).getByRole('button', { name: /Playlist p1/ }).click()
  const firstPreflight = await backend.next('preflight')
  await playlistsPanel(page).getByRole('button', { name: /Playlist p2/ }).click()
  const secondPreflight = await backend.next('preflight')
  await releasesPanel(page).getByRole('button', { name: /Release r1/ }).click()
  await releasesPanel(page).getByRole('button', { name: /Release r2/ }).click()

  await secondPreflight.reply({ track_count: 2 })
  await firstPreflight.reject(409, { detail: 'stale playlist mismatch' })
  await firstHydration.reply(releaseDetails('r1'))
  const secondHydration = await backend.next('release:r2')
  await secondHydration.reply(releaseDetails('r2'))
  const destination = await backend.next('destination')
  await destination.reply({ state: 'not_found', exists: false })

  await expect(page.getByText('Playlist p2', { exact: true })).toHaveCount(1)
  await expect(page.getByText('Release r2', { exact: true })).toHaveCount(1)
  await expect(page.locator('.selection-preview')).toContainText('Playlist p2')
  await expect(page.locator('.selection-preview')).toContainText('Release r2')
  await continueToReview(page, backend)
  await page.getByRole('button', { name: 'Back to selections' }).click()
  await expect(page.getByText('Playlist p2', { exact: true })).toHaveCount(1)
  await expect(page.getByText('Release r2', { exact: true })).toHaveCount(1)
  await expect(page.locator('.selection-preview')).toContainText('Playlist p2')
  await expect(page.locator('.selection-preview')).toContainText('Release r2')
  await continueToReview(page, backend)
  await expect(page.getByText('Both selections are ready to download.')).toBeVisible()
  await expect(page.getByText('stale playlist mismatch')).toHaveCount(0)
  expect(backend.callCount('download')).toBe(0)
})

test('existing albums are explained and blocked before enqueue', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page, { artist: 'Search words', album: 'Not final metadata' })
  const search = await backend.next('search')
  await search.reply({
    playlists: [playlist('existing', 13)],
    releases: [release('existing', 13)],
    errors: {},
  })
  const hydration = await backend.next('release:existing')
  await playlistsPanel(page).getByRole('button', { name: /Playlist existing/ }).click()
  const playlistCheck = await backend.next('preflight')
  await playlistCheck.reply({ track_count: 13 })
  await releasesPanel(page).getByRole('button', { name: /Release existing/ }).click()
  await hydration.reply(releaseDetails('existing', 13))

  const destination = await backend.next('destination')
  expect(destination.body).toEqual({
    artist: 'Artist existing',
    album: 'Release existing',
  })
  await destination.reply({ state: 'not_found', exists: false })
  await continueToReview(page, backend, {
    state: 'exists', exists: true, artist: 'Artist existing',
    album: 'Release existing', relative_path: 'Artist existing/Release existing',
    mp3_count: 13, file_count: 14,
  })

  const warning = page.getByRole('alert')
  await expect(warning).toContainText('already appears to exist')
  await expect(warning).toContainText('Artist existing/Release existing')
  await expect(warning).toContainText('MP3 files found: 13')
  await expect(page.getByRole('button', { name: 'Album already exists' })).toBeDisabled()
  expect(backend.callCount('download')).toBe(0)
})

test('late destination results cannot contaminate a newer release', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({
    playlists: [playlist('playlist')],
    releases: [release('old'), release('current')],
    errors: {},
  })
  const oldHydration = await backend.next('release:old')
  await playlistsPanel(page).getByRole('button', { name: /Playlist playlist/ }).click()
  const playlistCheck = await backend.next('preflight')
  await playlistCheck.reply({ track_count: 2 })
  await releasesPanel(page).getByRole('button', { name: /Release old/ }).click()
  await oldHydration.reply(releaseDetails('old'))
  const oldDestination = await backend.next('destination')

  await releasesPanel(page).getByRole('button', { name: /Release current/ }).click()
  const currentHydration = await backend.next('release:current')
  await currentHydration.reply(releaseDetails('current'))
  const currentDestination = await backend.next('destination')
  await currentDestination.reply({ state: 'not_found', exists: false })
  await oldDestination.reply({
    state: 'exists', exists: true, relative_path: 'Artist old/Release old',
    mp3_count: 2, file_count: 2,
  })

  await expect(page.getByText('Release current', { exact: true })).toHaveCount(1)
  await expect(page.locator('.selection-preview')).toContainText('Release current')
  await continueToReview(page, backend)
  await expect(page.getByText('Both selections are ready to download.')).toBeVisible()
  await expect(page.getByText('Artist old/Release old')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Download & Tag' })).toBeEnabled()
})

test('queue actions are single-shot, selection-safe, and restored on reentry', async ({ page }) => {
  const initialQueue = [
    {
      job_id: 'failed-job', artist: 'Failed Artist', album: 'Failed Album',
      status: 'failed', metadata_mode: 'musicbrainz', error: 'controlled failure',
    },
    {
      job_id: 'queued-job', artist: 'Queued Artist', album: 'Queued Album',
      status: 'queued', metadata_mode: 'manual',
    },
    {
      job_id: 'running-job', artist: 'Running Artist', album: 'Running Album',
      status: 'running', metadata_mode: 'musicbrainz',
      progress: { phase: 'downloading', current: 2, total: 4, completed: 1 },
    },
  ]
  const backend = new ControlledBackend(initialQueue)
  await openApp(page, backend)
  await backend.waitForSocket(1)
  backend.broadcastQueue()
  await expect(queuePanel(page)).toContainText('Downloading and converting audio · track 2 of 4 · 1 completed')
  await expect(queuePanel(page).getByRole('button', { name: 'Clear finished jobs' })).toBeVisible()

  const retryButton = queuePanel(page).getByRole('button', { name: 'Retry' }).first()
  await retryButton.dispatchEvent('click')
  await retryButton.dispatchEvent('click')
  const retry = await backend.next('retry:failed-job')
  expect(backend.callCount('retry:failed-job')).toBe(1)
  await retry.reply({ job_id: 'retry-job', retry_of: 'failed-job' }, 202)
  backend.setQueue([
    ...initialQueue,
    {
      job_id: 'retry-job', retry_of: 'failed-job', artist: 'Failed Artist',
      album: 'Failed Album', status: 'queued', metadata_mode: 'musicbrainz',
    },
  ])

  const queuedItem = queuePanel(page).getByText('Queued Artist — Queued Album').locator('..').locator('..')
  const cancelButton = queuedItem.getByRole('button', { name: 'Cancel' })
  await cancelButton.dispatchEvent('click')
  await cancelButton.dispatchEvent('click')
  const cancel = await backend.next('cancel:queued-job')
  expect(backend.callCount('cancel:queued-job')).toBe(1)
  await cancel.reply({ job_id: 'queued-job', status: 'cancelled' })
  backend.setQueue(backend.queue.map(job => job.job_id === 'queued-job'
    ? { ...job, status: 'cancelled' }
    : job))
  await expect(queuedItem).toContainText('Cancelled')

  const runningItem = queuePanel(page).getByText('Running Artist — Running Album').locator('..').locator('..')
  const runningCancel = runningItem.getByRole('button', { name: 'Cancel' })
  await runningCancel.dispatchEvent('click')
  await runningCancel.dispatchEvent('click')
  const cancelRunning = await backend.next('cancel:running-job')
  expect(backend.callCount('cancel:running-job')).toBe(1)
  await cancelRunning.reply({ job_id: 'running-job', status: 'cancelling' })
  backend.setQueue(backend.queue.map(job => job.job_id === 'running-job'
    ? { ...job, status: 'cancelling' }
    : job))
  await expect(runningItem).toContainText('Cancelling…')
  await expect(runningItem.getByRole('button', { name: 'Cancel' })).toHaveCount(0)

  backend.executeQueuedJobs()
  expect(backend.executedJobs).not.toContain('queued-job')
  expect(backend.queue.find(job => job.job_id === 'queued-job').status).toBe('cancelled')

  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({ playlists: [playlist('first'), playlist('second')], releases: [], errors: {} })
  await expect(queuePanel(page)).toHaveCount(0)
  await playlistsPanel(page).getByRole('button', { name: /Playlist second/ }).click()
  const preflight = await backend.next('preflight')
  await preflight.reply({ track_count: 2 })
  await expect(page.getByText('Playlist second', { exact: true })).toHaveCount(1)
  await expect(page.locator('.selection-preview')).toContainText('Playlist second')
  await page.locator('.search-hero').getByRole('button', { name: 'Dashboard' }).click()
  await expect(queuePanel(page)).toBeVisible()

  const nextConnection = backend.waitForSocket(backend.connectionCount + 1)
  await page.reload()
  await nextConnection
  backend.broadcastQueue()
  await expect(queuePanel(page)).toContainText('Running Artist — Running Album')
  await expect(queuePanel(page)).toContainText('Cancelling…')
  await expect(queuePanel(page)).toContainText('Downloading and converting audio · track 2 of 4 · 1 completed')
  await expect(queuePanel(page)).toContainText('Queued Artist — Queued Album')
  await expect(queuePanel(page)).toContainText('Cancelled')
})

test('manual mode is explicit and does not acquire MusicBrainz metadata', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page, { artist: 'Search Artist', album: 'Search Album' })
  const search = await backend.next('search')
  await search.reply({ playlists: [playlist('manual', 3)], releases: [], errors: {} })
  await playlistsPanel(page).getByRole('button', { name: /Playlist manual/ }).click()
  const preflight = await backend.next('preflight')
  await preflight.reply({ track_count: 3 })
  await continueToReview(page)

  await page.getByRole('button', { name: 'Download without MusicBrainz' }).click()
  await expect(page.getByRole('alert')).toContainText('There will be no MusicBrainz date')
  await page.getByRole('button', { name: 'I understand — enter manual metadata' }).click()
  await page.getByLabel('Artist').last().fill('Edited Artist')
  await page.getByLabel('Album').last().fill('Edited Album')
  const destination = await backend.next('destination')
  expect(destination.body).toEqual({ artist: 'Edited Artist', album: 'Edited Album' })
  await destination.reply({ state: 'not_found', exists: false })
  const manualButton = page.locator('.manual-metadata form button')
  await expect(manualButton).toHaveText('Confirm metadata & queue manual download')
  await manualButton.dispatchEvent('click')
  await manualButton.dispatchEvent('click')

  const download = await backend.next('download')
  expect(download.body).toEqual({
    playlist_url: 'https://youtube.test/playlist?list=manual',
    playlist_id: 'manual',
    playlist_title: 'Playlist manual',
    playlist_channel: 'Channel manual',
    playlist_thumbnail: 'https://i.ytimg.com/vi/manual/mqdefault.jpg',
    track_count: 3,
    release_id: null,
    metadata_mode: 'manual',
    manual_confirmed: true,
    cover_source: 'none',
    artist: 'Edited Artist',
    album: 'Edited Album',
  })
  expect(backend.callCount('download')).toBe(1)
  expect(backend.calls.some(call => call.kind.startsWith('release:'))).toBe(false)
  await expect(manualButton).toBeDisabled()
  await download.reply({ job_id: 'manual-job' }, 202)
  await expect(page.getByText('Download queued successfully.')).toBeVisible()
})

test('missing archive artwork requires and persists the selected playlist thumbnail', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({
    playlists: [playlist('fallback')],
    releases: [release('fallback', 2, false)],
    errors: {},
  })
  const hydration = await backend.next('release:fallback')
  await playlistsPanel(page).getByRole('button', { name: /Playlist fallback/ }).click()
  const preflight = await backend.next('preflight')
  await preflight.reply({ track_count: 2 })
  await releasesPanel(page).getByRole('button', { name: /Release fallback/ }).click()
  await hydration.reply(releaseDetails('fallback', 2, false))
  const destination = await backend.next('destination')
  await destination.reply({ state: 'not_found', exists: false })
  await continueToReview(page, backend)

  await expect(page.getByText('Cover Art Archive has no artwork for this release', { exact: false })).toBeVisible()
  await expect(page.getByText(/not authoritative/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Download & Tag' })).toBeDisabled()
  await page.getByRole('button', { name: /Use playlist thumbnail/ }).click()
  await expect(page.getByText('YouTube playlist thumbnail — not official artwork')).toBeVisible()
  await expect(page.getByText(/technically valid thumbnail can be unrelated/)).toBeVisible()
  await expect(page.getByRole('radio', { name: /Fit entire image/ })).toBeChecked()
  expect(backend.callCount('cover-youtube')).toBe(0)
  await page.getByRole('radio', { name: /Crop to square/ }).check()
  await expect(page.locator('.cover-result--crop')).toBeVisible()
  expect(backend.callCount('cover-youtube')).toBe(0)
  await page.getByRole('button', { name: 'Confirm Crop cover' }).click()
  const cover = await backend.next('cover-youtube')
  expect(cover.body).toEqual({
    thumbnail_url: 'https://i.ytimg.com/vi/fallback/mqdefault.jpg',
    square_mode: 'crop',
  })
  await cover.reply({
    cover_id: '12345678-1234-1234-1234-123456789abc',
    mime_type: 'image/jpeg', size: 100, width: 480, height: 480, square_mode: 'crop',
  }, 201)

  const readyButton = page.getByRole('button', { name: 'Download & Tag' })
  await expect(readyButton).toBeEnabled()
  await readyButton.click()
  const download = await backend.next('download')
  expect(download.body).toEqual({
    playlist_url: 'https://youtube.test/playlist?list=fallback',
    playlist_id: 'fallback',
    playlist_title: 'Playlist fallback',
    playlist_channel: 'Channel fallback',
    playlist_thumbnail: 'https://i.ytimg.com/vi/fallback/mqdefault.jpg',
    artist: 'Artist fallback',
    album: 'Release fallback',
    release_id: 'fallback',
    track_count: 2,
    cover_source: 'youtube_thumbnail',
    cover_id: '12345678-1234-1234-1234-123456789abc',
    cover_url: 'https://i.ytimg.com/vi/fallback/mqdefault.jpg',
    cover_square_mode: 'crop',
  })
  await download.reply({ job_id: 'fallback-job' }, 202)
})

test('failed and manual fallback covers remain explicit and recoverable', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({
    playlists: [playlist('manual-cover')],
    releases: [release('manual-cover', 2, false)],
    errors: {},
  })
  const hydration = await backend.next('release:manual-cover')
  await playlistsPanel(page).getByRole('button', { name: /Playlist manual-cover/ }).click()
  const preflight = await backend.next('preflight')
  await preflight.reply({ track_count: 2 })
  await releasesPanel(page).getByRole('button', { name: /Release manual-cover/ }).click()
  await hydration.reply(releaseDetails('manual-cover', 2, false))
  const destination = await backend.next('destination')
  await destination.reply({ state: 'not_found', exists: false })
  await continueToReview(page, backend)

  await page.getByRole('button', { name: /Use playlist thumbnail/ }).click()
  await page.getByRole('button', { name: 'Confirm Fit cover' }).click()
  const youtubeCover = await backend.next('cover-youtube')
  await youtubeCover.reject(502, { detail: 'YouTube thumbnail could not be downloaded.' })
  await expect(page.getByRole('alert')).toContainText('choose another cover option')
  await expect(page.getByRole('button', { name: 'Download & Tag' })).toBeDisabled()

  await page.locator('.cover-option--upload input').setInputFiles({
    name: 'cover.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
      'base64'
    ),
  })
  await expect(page.getByText(/already square/)).toBeVisible()
  await expect(page.getByRole('radio')).toHaveCount(0)
  await page.getByRole('button', { name: 'Confirm Fit cover' }).click()
  const manualCover = await backend.next('cover-manual')
  expect(String(manualCover.body)).toContain('name="square_mode"')
  expect(String(manualCover.body)).toContain('fit')
  await manualCover.reply({
    cover_id: 'abcdefab-1234-1234-1234-abcdefabcdef',
    mime_type: 'image/png', size: 100, width: 1, height: 1, square_mode: 'fit',
  }, 201)

  const readyButton = page.getByRole('button', { name: 'Download & Tag' })
  await expect(readyButton).toBeEnabled()
  await readyButton.click()
  const download = await backend.next('download')
  expect(download.body.cover_source).toBe('manual_upload')
  expect(download.body.cover_id).toBe('abcdefab-1234-1234-1234-abcdefabcdef')
  expect(download.body.cover_url).toBeUndefined()
  expect(download.body.cover_square_mode).toBe('fit')
  await download.reply({ job_id: 'manual-cover-job' }, 202)
})

test('missing archive artwork can be consciously queued without a cover', async ({ page }) => {
  const backend = new ControlledBackend()
  await page.route('https://i.ytimg.com/vi/crypto-podcast/mqdefault.jpg', route => route.fulfill({
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#251b35"/><circle cx="210" cy="150" r="70" fill="#f0b35b"/><circle cx="430" cy="150" r="70" fill="#59adb3"/><text x="320" y="300" text-anchor="middle" fill="white" font-size="42">CRYPTO PODCAST</text></svg>',
  }))
  await openApp(page, backend)

  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({
    playlists: [{
      ...playlist('none'),
      title: 'Oracular Spectacular playlist',
      thumbnail: 'https://i.ytimg.com/vi/crypto-podcast/mqdefault.jpg',
    }],
    releases: [release('none', 2, false)],
    errors: {},
  })
  const hydration = await backend.next('release:none')
  await playlistsPanel(page).getByRole('button', { name: /Oracular Spectacular playlist/ }).click()
  const preflight = await backend.next('preflight')
  await preflight.reply({ track_count: 2 })
  await releasesPanel(page).getByRole('button', { name: /Release none/ }).click()
  await hydration.reply(releaseDetails('none', 2, false))
  const destination = await backend.next('destination')
  await destination.reply({ state: 'not_found', exists: false })
  await continueToReview(page, backend)

  await page.getByRole('button', { name: /Use playlist thumbnail/ }).click()
  await expect(page.getByAltText('Original alternative cover preview')).toBeVisible()
  await expect(page.getByText(/technically valid thumbnail can be unrelated/)).toBeVisible()
  await page.getByRole('button', { name: /Continue without cover/ }).click()
  await page.getByRole('button', { name: 'Download & Tag' }).click()
  const download = await backend.next('download')
  expect(download.body.cover_source).toBe('none')
  expect(download.body.cover_id).toBeUndefined()
  expect(backend.callCount('cover-youtube')).toBe(0)
  expect(backend.callCount('cover-manual')).toBe(0)
  await download.reply({ job_id: 'none-job' }, 202)
})
