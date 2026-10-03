import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  filterItems,
  formatAge,
  groupByDay,
  isSafeUrl,
  loadFeed,
  sourceCounts,
} from './news.ts'
import { NOW, makeItem, stubFetch } from './test-utils.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('isSafeUrl', () => {
  it.each(['https://example.com/a', 'http://example.com'])('accepts %s', (url) => {
    expect(isSafeUrl(url)).toBe(true)
  })

  it.each(['javascript:alert(1)', 'data:text/html,x', '/relative', 'not a url', '', null, 42])(
    'rejects %s',
    (url) => {
      expect(isSafeUrl(url)).toBe(false)
    },
  )
})

describe('loadFeed', () => {
  it('returns the feed and drops items that are unsafe or malformed', async () => {
    const good = makeItem('good', NOW.toISOString())
    const fetchMock = stubFetch({
      generated_at: NOW.toISOString(),
      items: [good, { ...good, id: 'js', url: 'javascript:alert(1)' }, { id: 'no-title' }, null],
    })

    const result = await loadFeed('/news.json')

    expect(result.items.map((i) => i.id)).toEqual(['good'])
    expect(fetchMock).toHaveBeenCalledWith('/news.json', expect.objectContaining({ cache: 'no-cache' }))
  })

  it('throws on an HTTP error', async () => {
    stubFetch('missing', { status: 404 })
    await expect(loadFeed('/news.json')).rejects.toThrow('HTTP 404')
  })

  it('throws on non-JSON, such as a dev server HTML fallback', async () => {
    stubFetch('<!doctype html><html></html>')
    await expect(loadFeed('/news.json')).rejects.toThrow('not valid JSON')
  })

  it.each([[[]], [{ items: [] }], [{ generated_at: 'x', items: {} }]])(
    'throws on the wrong shape: %j',
    async (body) => {
      stubFetch(body)
      await expect(loadFeed('/news.json')).rejects.toThrow('expected format')
    },
  )
})

describe('filterItems', () => {
  const items = [
    makeItem('a', null, { title: 'Rust 2.0 released', source_id: 'lobsters', source_name: 'Lobsters' }),
    makeItem('b', null, { title: 'GPU prices', summary: 'Rust belt fabs', source_id: 'wired', source_name: 'Wired' }),
    makeItem('c', null, { title: 'Kernel news', source_id: 'lobsters', source_name: 'Lobsters' }),
  ]
  const ids = (list: typeof items) => list.map((i) => i.id)

  it('returns everything with no query and no sources', () => {
    expect(ids(filterItems(items, '  ', new Set()))).toEqual(['a', 'b', 'c'])
  })

  it('matches title, summary and source name case-insensitively', () => {
    expect(ids(filterItems(items, 'RUST', new Set()))).toEqual(['a', 'b'])
    expect(ids(filterItems(items, 'wired', new Set()))).toEqual(['b'])
  })

  it('filters by source and combines with the query', () => {
    expect(ids(filterItems(items, '', new Set(['lobsters'])))).toEqual(['a', 'c'])
    expect(ids(filterItems(items, 'rust', new Set(['lobsters'])))).toEqual(['a'])
  })
})

describe('sourceCounts', () => {
  it('counts per source, most first, ties by name', () => {
    const items = [
      makeItem('1', null, { source_id: 'b', source_name: 'Bee' }),
      makeItem('2', null, { source_id: 'a', source_name: 'Ay' }),
      makeItem('3', null, { source_id: 'c', source_name: 'Cee' }),
      makeItem('4', null, { source_id: 'c', source_name: 'Cee' }),
    ]
    expect(sourceCounts(items)).toEqual([
      { id: 'c', name: 'Cee', count: 2 },
      { id: 'a', name: 'Ay', count: 1 },
      { id: 'b', name: 'Bee', count: 1 },
    ])
  })
})

describe('groupByDay', () => {
  // Tests run with TZ=UTC (see the `test` script).
  it('labels today and yesterday, keeps order, and dates undated items by fetch time', () => {
    const items = [
      makeItem('today', '2026-10-03T09:00:00Z'),
      makeItem('undated', null, { fetched_at: '2026-10-03T01:00:00Z' }),
      makeItem('yesterday', '2026-10-02T23:59:00Z'),
      makeItem('older', '2026-09-30T10:00:00Z'),
    ]

    const groups = groupByDay(items, NOW)

    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ['Today', ['today', 'undated']],
      ['Yesterday', ['yesterday']],
      [expect.stringContaining('30'), ['older']],
    ])
  })
})

describe('formatAge', () => {
  it.each([
    [0, 'just now'],
    [-5_000, 'just now'],
    [59_000, 'just now'],
    [5 * 60_000, '5m ago'],
    [3 * 3_600_000 + 1, '3h ago'],
    [2 * 86_400_000, '2d ago'],
  ])('%i ms -> %s', (elapsed, expected) => {
    expect(formatAge(new Date(NOW.getTime() - elapsed), NOW)).toBe(expected)
  })
})
