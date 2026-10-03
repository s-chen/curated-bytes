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

it('flags stale data', async () => {
  stubFetch(feed(ITEMS, '2026-10-03T06:00:00Z'))
  render(<App />)
  expect(await screen.findByText(/Stale: updated/)).toBeTruthy()
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
