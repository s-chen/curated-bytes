import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App.tsx'
import { NOW, feed, makeItem, stubFetch } from './test-utils.ts'

const ITEMS = [
  makeItem('rust', '2026-10-03T11:00:00Z', {
    title: 'Rust 2.0 released',
    url: 'https://blog.rust-lang.org/rust-2',
    source_id: 'lobsters',
    source_name: 'Lobsters',
    summary: 'A big release.',
  }),
  makeItem('gpu', '2026-10-02T15:00:00Z', {
    title: 'GPU prices fall',
    source_id: 'wired',
    source_name: 'Wired',
  }),
]

beforeEach(() => {
  vi.useFakeTimers({ now: NOW, toFake: ['Date'] })
  window.history.replaceState(null, '', '/')
  localStorage.clear()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const titles = () => screen.queryAllByRole('link').map((a) => a.textContent)

it('renders stories grouped by day with safe external links', async () => {
  stubFetch(feed(ITEMS, '2026-10-03T11:55:00Z'))
  render(<App />)

  const link = await screen.findByRole('link', { name: 'Rust 2.0 released' })
  expect(link).toHaveProperty('href', 'https://blog.rust-lang.org/rust-2')
  expect(link.getAttribute('target')).toBe('_blank')
  expect(link.getAttribute('rel')).toBe('noopener noreferrer')
  expect(screen.getByText(/Lobsters · blog\.rust-lang\.org/)).toBeTruthy()
  expect(screen.getByText('1h ago')).toBeTruthy()

  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
    'Today',
    'Yesterday',
  ])
  expect(screen.getByText('5m ago')).toBeTruthy()
  expect(screen.queryByText(/Stale/)).toBeNull()
})

it('filters by search text and by source', async () => {
  stubFetch(feed(ITEMS))
  render(<App />)
  await screen.findByRole('link', { name: 'Rust 2.0 released' })

  fireEvent.change(screen.getByRole('searchbox', { name: 'Filter headlines' }), {
    target: { value: 'gpu' },
  })
  expect(titles()).toEqual(['GPU prices fall'])
  expect(screen.getByText('1 of 2 stories')).toBeTruthy()

  fireEvent.change(screen.getByRole('searchbox'), { target: { value: '' } })
  const lobsters = screen.getByRole('button', { name: /Lobsters/ })
  fireEvent.click(lobsters)
  expect(lobsters.getAttribute('aria-pressed')).toBe('true')
  expect(titles()).toEqual(['Rust 2.0 released'])

  fireEvent.click(screen.getByRole('button', { name: 'All' }))
  expect(titles()).toHaveLength(2)

  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'nothing matches' } })
  expect(screen.getByText('No stories match.')).toBeTruthy()
})

it('shows nothing as new on a first visit, then remembers the visit', async () => {
  stubFetch(feed(ITEMS, '2026-10-03T11:55:00Z'))
  render(<App />)
  await screen.findByRole('link', { name: 'Rust 2.0 released' })

  expect(screen.queryByText(/new since your last visit/)).toBeNull()
  expect(document.title).toBe('CuratedBytes')
  expect(localStorage.getItem('curatedbytes:lastVisit')).toBe('2026-10-03T11:55:00Z')
})

it('lists stories fetched since the last visit first and counts them in the title', async () => {
  localStorage.setItem('curatedbytes:lastVisit', '2026-10-03T10:00:00Z')
  const items = [
    { ...ITEMS[0], fetched_at: '2026-10-03T11:00:00Z' },
    // Published long ago but only just picked up: still new to the reader.
    makeItem('late', '2026-10-01T09:00:00Z', { title: 'Late arrival', fetched_at: '2026-10-03T11:00:00Z' }),
    { ...ITEMS[1], fetched_at: '2026-10-02T15:00:00Z' },
  ]
  stubFetch(feed(items, '2026-10-03T11:00:00Z'))
  render(<App />)

  const fresh = await screen.findByRole('region', { name: '2 new since your last visit' })
  expect(within(fresh).getAllByRole('link').map((a) => a.textContent)).toEqual([
    'Rust 2.0 released',
    'Late arrival',
  ])
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
    '2 new since your last visit',
    'Yesterday',
  ])
  expect(document.title).toBe('(2) CuratedBytes')
  expect(localStorage.getItem('curatedbytes:lastVisit')).toBe('2026-10-03T11:00:00Z')
})

it('supports j/k to move, o to open, / to search and Esc to leave search', async () => {
  stubFetch(feed(ITEMS))
  const open = vi.spyOn(window, 'open').mockReturnValue(null)
  render(<App />)
  const [rust, gpu] = await screen.findAllByRole('link')

  fireEvent.keyDown(document.body, { key: 'j' })
  expect(document.activeElement).toBe(rust)
  fireEvent.keyDown(rust, { key: 'j' })
  expect(document.activeElement).toBe(gpu)
  fireEvent.keyDown(gpu, { key: 'j' })
  expect(document.activeElement).toBe(gpu)
  fireEvent.keyDown(gpu, { key: 'k' })
  expect(document.activeElement).toBe(rust)

  fireEvent.keyDown(rust, { key: 'o' })
  expect(open).toHaveBeenCalledWith('https://blog.rust-lang.org/rust-2', '_blank', 'noopener,noreferrer')

  fireEvent.keyDown(rust, { key: '/' })
  const search = screen.getByRole('searchbox')
  expect(document.activeElement).toBe(search)
  fireEvent.keyDown(search, { key: 'j' })
  expect(document.activeElement).toBe(search)
  fireEvent.keyDown(search, { key: 'Escape' })
  expect(document.activeElement).not.toBe(search)
})

it('shows top stories as cards and leaves them out of the list', async () => {
  const other = makeItem('other', '2026-10-03T10:00:00Z', { title: 'Unrelated story', source_id: 'hn', source_name: 'Hacker News' })
  const top = { id: 'rust', title: 'Rust 2.0 ships', summary: 'Everyone covered it.', why_it_matters: null, item_ids: ['rust', 'gpu'] }
  stubFetch(feed([...ITEMS, other], NOW.toISOString(), [top]))
  render(<App />)

  const section = await screen.findByRole('region', { name: 'Top stories' })
  const lead = within(section).getByRole('link', { name: 'Rust 2.0 ships' })
  expect(lead).toHaveProperty('href', 'https://blog.rust-lang.org/rust-2')
  expect(within(section).getByText('Everyone covered it.')).toBeTruthy()
  expect(within(section).getByText('2 sources')).toBeTruthy()
  const coverage = within(within(section).getByRole('list', { name: 'Coverage' })).getAllByRole('link')
  expect(coverage.map((a) => a.textContent)).toEqual(['Lobsters', 'Wired'])

  expect(titles()).toEqual(['Rust 2.0 ships', 'Lobsters', 'Wired', 'Unrelated story'])

  // A single-source standout card names its source instead of a count.
  cleanup()
  const standout = { id: 'other', title: 'Unrelated story', summary: null, why_it_matters: null, item_ids: ['other'] }
  stubFetch(feed([...ITEMS, other], NOW.toISOString(), [top, standout]))
  render(<App />)
  const cards = await screen.findByRole('region', { name: 'Top stories' })
  expect(within(cards).getByRole('link', { name: 'Unrelated story' })).toBeTruthy()
  expect(within(cards).getAllByText('Hacker News').length).toBeGreaterThan(0)
  expect(titles()).toEqual(['Rust 2.0 ships', 'Lobsters', 'Wired', 'Unrelated story', 'Hacker News'])

  // Filtering hides the cards and searches every story.
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'rust' } })
  expect(screen.queryByRole('region', { name: 'Top stories' })).toBeNull()
  expect(titles()).toEqual(['Rust 2.0 released'])
})

it('links to discussion threads and shows why a top story matters', async () => {
  const hn = makeItem('hn', '2026-10-03T11:00:00Z', {
    title: 'Kernel bug found',
    source_id: 'hacker-news',
    source_name: 'Hacker News',
    discussion_url: 'https://news.ycombinator.com/item?id=1',
    points: 312,
    comments: 145,
  })
  const lob = makeItem('lob', '2026-10-03T10:00:00Z', {
    title: 'Zig released',
    discussion_url: 'https://lobste.rs/s/abc',
  })
  const top = { id: 'rust', title: 'Rust ships', summary: null, why_it_matters: 'Upgrade your toolchain.', item_ids: ['rust', 'gpu'] }
  stubFetch(feed([...ITEMS, hn, lob], NOW.toISOString(), [top]))
  render(<App />)

  const thread = await screen.findByRole('link', { name: '312 points · 145 comments' })
  expect(thread).toHaveProperty('href', 'https://news.ycombinator.com/item?id=1')
  expect(screen.getByRole('link', { name: 'Discussion' })).toHaveProperty('href', 'https://lobste.rs/s/abc')
  expect(within(screen.getByRole('region', { name: 'Top stories' })).getByText('Upgrade your toolchain.')).toBeTruthy()
})

it('lists engineering-blog posts first with a badge', async () => {
  const items = [
    makeItem('news', '2026-10-03T11:30:00Z', { title: 'Big news', importance: 5 }),
    makeItem('eng', '2026-10-03T09:00:00Z', { title: 'How we scaled Postgres', importance: 3, engineering: true }),
  ]
  stubFetch(feed(items))
  render(<App />)
  await screen.findByRole('link', { name: 'Big news' })
  expect(titles()).toEqual(['How we scaled Postgres', 'Big news'])
  expect(screen.getAllByText('Engineering')).toHaveLength(1)
})

it('orders each day by importance', async () => {
  const items = [
    makeItem('minor', '2026-10-03T11:30:00Z', { title: 'Minor update', importance: 2 }),
    makeItem('major', '2026-10-03T09:00:00Z', { title: 'Major outage', importance: 5 }),
    makeItem('unscored', '2026-10-03T11:45:00Z', { title: 'Unscored item' }),
  ]
  stubFetch(feed(items))
  render(<App />)
  await screen.findByRole('link', { name: 'Major outage' })
  expect(titles()).toEqual(['Major outage', 'Minor update', 'Unscored item'])
})

it('flags stale data', async () => {
  stubFetch(feed(ITEMS, '2026-10-03T06:00:00Z'))
  render(<App />)
  expect(await screen.findByText(/Stale: updated/)).toBeTruthy()
})

it('explains an empty dashboard when nothing has been reviewed yet', async () => {
  stubFetch(feed([makeItem('p', NOW.toISOString(), { review: 'pending' })]))
  render(<App />)
  expect(await screen.findByText('Nothing to show yet')).toBeTruthy()
})

it('shows an error when news.json cannot be loaded', async () => {
  stubFetch('missing', { status: 404 })
  render(<App />)
  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toContain('HTTP 404')
})

it('switches tabs, with the selection kept in the URL hash', async () => {
  stubFetch(feed(ITEMS))
  render(<App />)
  await screen.findByRole('link', { name: 'Rust 2.0 released' })

  const tabs = within(screen.getByRole('tablist'))
  fireEvent.click(tabs.getByRole('tab', { name: 'Jobs' }))

  expect(tabs.getByRole('tab', { name: 'Jobs' }).getAttribute('aria-selected')).toBe('true')
  expect(screen.getByRole('tabpanel').textContent).toContain("Job matching isn't live yet")
  expect(window.location.hash).toBe('#jobs')

  fireEvent.keyDown(tabs.getByRole('tab', { name: 'Jobs' }), { key: 'ArrowRight' })
  expect(tabs.getByRole('tab', { name: /News/ }).getAttribute('aria-selected')).toBe('true')
  expect(document.activeElement).toBe(tabs.getByRole('tab', { name: /News/ }))
})

it('opens on the tab named in the URL hash', () => {
  stubFetch(feed(ITEMS))
  window.history.replaceState(null, '', '/#jobs')
  render(<App />)
  expect(screen.getByRole('tab', { name: 'Jobs' }).getAttribute('aria-selected')).toBe('true')
})
