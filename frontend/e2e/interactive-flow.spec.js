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
  await expect(page.getByRole('heading', { name: 'Find the right album release' })).toBeVisible()
}

async function startSearch(page, { artist = 'Test Artist', album = 'Test Album' } = {}) {
  await page.getByLabel('Artist').fill(artist)
  await page.getByLabel('Album').fill(album)
  await page.getByRole('button', { name: 'Search music' }).click()
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
      youtube: { status: 'error', message: 'Configured, but unreachable.' },
      musicbrainz: { status: 'warning', message: 'Temporarily unreachable.' },
      redis: { status: 'disabled', message: 'Optional cache is disabled.' },
      worker: { status: 'ok', message: 'Worker is idle.', state: 'idle' },
    },
  })

  await expect(page.getByRole('heading', { name: 'System status' })).toBeVisible()
  const diagnostics = page.getByRole('region', { name: 'System diagnostics' })
  await expect(diagnostics.getByText('OK', { exact: true })).toHaveCount(3)
  await expect(diagnostics.getByText('Warning', { exact: true })).toHaveCount(2)
  await expect(diagnostics.getByText('Error', { exact: true })).toHaveCount(2)
  await expect(diagnostics.getByText('Disabled', { exact: true })).toHaveCount(1)
  await expect(diagnostics.getByRole('article', { name: 'Library' })).toContainText('183 GiB')
  await expect(page.getByRole('alert')).toContainText('retrying automatically')
})

test('happy path queues one fully checked download', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page)
  const search = await backend.next('search')
  expect(search.query).toEqual({
    artist: 'Test Artist',
    album: 'Test Album',
    youtube_limit: '10',
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

  const downloadButton = page.getByRole('button', { name: 'Loading release details...' })
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
  const readyButton = page.getByRole('button', { name: 'Download & Tag' })
  await expect(readyButton).toBeEnabled()

  const downloadAction = page.locator('.download-button')
  await downloadAction.dispatchEvent('click')
  await downloadAction.dispatchEvent('click')
  const download = await backend.next('download')
  expect(download.body).toEqual({
    playlist_url: 'https://youtube.test/playlist?list=happy',
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
  await page.getByLabel('YouTube results').fill('3')
  await page.getByLabel('Max tracks').check()
  await page.getByLabel('Maximum tracks').fill('5')
  await page.getByRole('button', { name: 'Search music' }).click()
  const newSearch = await backend.next('search')
  expect(newSearch.query).toEqual({
    artist: 'New Artist',
    album: 'New Album',
    youtube_limit: '3',
    youtube_max_tracks: '5',
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

  await expect(page.getByText('Choose a playlist', { exact: true })).toBeVisible()
  await expect(page.getByText('Choose a release', { exact: true })).toBeVisible()
  await expect(releasesPanel(page)).toContainText('Track new-1')
  await expect(releasesPanel(page)).not.toContainText('Track old-1')
  expect(backend.callCount('download')).toBe(0)
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

  await expect(page.getByText('Playlist p2', { exact: true })).toHaveCount(2)
  await expect(page.getByText('Release r2', { exact: true })).toHaveCount(2)
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
  await destination.reply({
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

  await expect(page.getByText('Release current', { exact: true })).toHaveCount(2)
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

  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({ playlists: [playlist('first'), playlist('second')], releases: [], errors: {} })
  await playlistsPanel(page).getByRole('button', { name: /Playlist first/ }).click()
  const firstPreflight = await backend.next('preflight')
  await firstPreflight.reply({ track_count: 2 })

  const retryButton = queuePanel(page).getByRole('button', { name: 'Retry' }).first()
  await retryButton.dispatchEvent('click')
  await retryButton.dispatchEvent('click')
  const retry = await backend.next('retry:failed-job')
  expect(backend.callCount('retry:failed-job')).toBe(1)

  await playlistsPanel(page).getByRole('button', { name: /Playlist second/ }).click()
  const secondPreflight = await backend.next('preflight')
  await secondPreflight.reply({ track_count: 2 })
  await retry.reply({ job_id: 'retry-job', retry_of: 'failed-job' }, 202)
  backend.setQueue([
    ...initialQueue,
    {
      job_id: 'retry-job', retry_of: 'failed-job', artist: 'Failed Artist',
      album: 'Failed Album', status: 'queued', metadata_mode: 'musicbrainz',
    },
  ])
  await expect(page.getByText('Playlist second', { exact: true })).toHaveCount(2)

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

  backend.executeQueuedJobs()
  expect(backend.executedJobs).not.toContain('queued-job')
  expect(backend.queue.find(job => job.job_id === 'queued-job').status).toBe('cancelled')

  const nextConnection = backend.waitForSocket(backend.connectionCount + 1)
  await page.reload()
  await nextConnection
  backend.broadcastQueue()
  await expect(queuePanel(page)).toContainText('Running Artist — Running Album')
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

  await expect(page.getByText('Cover Art Archive has no artwork for this release', { exact: false })).toBeVisible()
  await expect(page.getByText(/not authoritative/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Download & Tag' })).toBeDisabled()
  await page.getByRole('button', { name: /Use playlist thumbnail/ }).click()
  const cover = await backend.next('cover-youtube')
  expect(cover.body).toEqual({
    thumbnail_url: 'https://i.ytimg.com/vi/fallback/mqdefault.jpg',
  })
  await cover.reply({
    cover_id: '12345678-1234-1234-1234-123456789abc',
    mime_type: 'image/jpeg', size: 100, width: 480, height: 480,
  }, 201)

  const readyButton = page.getByRole('button', { name: 'Download & Tag' })
  await expect(readyButton).toBeEnabled()
  await readyButton.click()
  const download = await backend.next('download')
  expect(download.body).toEqual({
    playlist_url: 'https://youtube.test/playlist?list=fallback',
    artist: 'Artist fallback',
    album: 'Release fallback',
    release_id: 'fallback',
    track_count: 2,
    cover_source: 'youtube_thumbnail',
    cover_id: '12345678-1234-1234-1234-123456789abc',
    cover_url: 'https://i.ytimg.com/vi/fallback/mqdefault.jpg',
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

  await page.getByRole('button', { name: /Use playlist thumbnail/ }).click()
  const youtubeCover = await backend.next('cover-youtube')
  await youtubeCover.reject(502, { detail: 'YouTube thumbnail could not be downloaded.' })
  await expect(page.getByRole('alert')).toContainText('choose another cover option')
  await expect(page.getByRole('button', { name: 'Download & Tag' })).toBeDisabled()

  await page.locator('.cover-option--upload input').setInputFiles({
    name: 'cover.png',
    mimeType: 'image/png',
    buffer: Buffer.from('controlled image'),
  })
  const manualCover = await backend.next('cover-manual')
  expect(String(manualCover.body)).toContain('controlled image')
  await manualCover.reply({
    cover_id: 'abcdefab-1234-1234-1234-abcdefabcdef',
    mime_type: 'image/png', size: 100, width: 600, height: 600,
  }, 201)

  const readyButton = page.getByRole('button', { name: 'Download & Tag' })
  await expect(readyButton).toBeEnabled()
  await readyButton.click()
  const download = await backend.next('download')
  expect(download.body.cover_source).toBe('manual_upload')
  expect(download.body.cover_id).toBe('abcdefab-1234-1234-1234-abcdefabcdef')
  expect(download.body.cover_url).toBeUndefined()
  await download.reply({ job_id: 'manual-cover-job' }, 202)
})

test('missing archive artwork can be consciously queued without a cover', async ({ page }) => {
  const backend = new ControlledBackend()
  await openApp(page, backend)

  await startSearch(page)
  const search = await backend.next('search')
  await search.reply({
    playlists: [playlist('none')],
    releases: [release('none', 2, false)],
    errors: {},
  })
  const hydration = await backend.next('release:none')
  await playlistsPanel(page).getByRole('button', { name: /Playlist none/ }).click()
  const preflight = await backend.next('preflight')
  await preflight.reply({ track_count: 2 })
  await releasesPanel(page).getByRole('button', { name: /Release none/ }).click()
  await hydration.reply(releaseDetails('none', 2, false))
  const destination = await backend.next('destination')
  await destination.reply({ state: 'not_found', exists: false })

  await page.getByRole('button', { name: /Continue without cover/ }).click()
  await page.getByRole('button', { name: 'Download & Tag' }).click()
  const download = await backend.next('download')
  expect(download.body.cover_source).toBe('none')
  expect(download.body.cover_id).toBeUndefined()
  expect(backend.callCount('cover-youtube')).toBe(0)
  expect(backend.callCount('cover-manual')).toBe(0)
  await download.reply({ job_id: 'none-job' }, 202)
})
