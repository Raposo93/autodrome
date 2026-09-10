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

  await expect(page.getByText('Playlist p2', { exact: true })).toHaveCount(2)
  await expect(page.getByText('Release r2', { exact: true })).toHaveCount(2)
  await expect(page.getByText('Both selections are ready to download.')).toBeVisible()
  await expect(page.getByText('stale playlist mismatch')).toHaveCount(0)
  expect(backend.callCount('download')).toBe(0)
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
  const manualButton = page.getByRole('button', { name: 'Confirm metadata & queue manual download' })
  await manualButton.dispatchEvent('click')
  await manualButton.dispatchEvent('click')

  const download = await backend.next('download')
  expect(download.body).toEqual({
    playlist_url: 'https://youtube.test/playlist?list=manual',
    track_count: 3,
    release_id: null,
    metadata_mode: 'manual',
    manual_confirmed: true,
    artist: 'Edited Artist',
    album: 'Edited Album',
  })
  expect(backend.callCount('download')).toBe(1)
  expect(backend.calls.some(call => call.kind.startsWith('release:'))).toBe(false)
  await expect(manualButton).toBeDisabled()
  await download.reply({ job_id: 'manual-job' }, 202)
  await expect(page.getByText('Download queued successfully.')).toBeVisible()
})
