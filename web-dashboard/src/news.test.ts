import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  filterItems,
  formatAge,
  groupByDay,
  MAX_DISPLAYED,
  byImportance,
  isNewSince,
  isSafeUrl,
  loadFeed,
  resolveTopStories,
  sourceCounts,
  splitArchive,
  archiveCutoff,
} from './news.ts'
import { NOW, feed, makeItem, stubFetch } from './test-utils.ts'

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
    expect(result.items[0]).toMatchObject({ discussion_url: null, points: null, comments: null })
    expect(result.top_stories).toEqual([])
    expect(fetchMock).toHaveBeenCalledWith('/news.json', expect.objectContaining({ cache: 'no-cache' }))
  })

  it('keeps only kept items, in file order', async () => {
    stubFetch({
      generated_at: NOW.toISOString(),
      items: [
        makeItem('pending', null, { review: 'pending' }),
        makeItem('excluded', null, { review: 'excluded' }),
        { ...makeItem('missing', null), review: undefined },
        makeItem('k0', null),
        makeItem('k1', null),
      ],
    })
    const { items } = await loadFeed('/news.json')
    expect(items.map((i) => i.id)).toEqual(['k0', 'k1'])
  })

  it('drops unsafe discussion links and bad counts', async () => {
    stubFetch({
      generated_at: NOW.toISOString(),
      items: [makeItem('a', null, { discussion_url: 'javascript:x', points: -1, comments: 1.5 } as never)],
    })
    const [item] = (await loadFeed('/news.json')).items
    expect(item).toMatchObject({ discussion_url: null, points: null, comments: null })
  })

  it('fills in missing top-story fields', async () => {
    const story = { id: 'old', title: 'Old', summary: null, item_ids: ['k0'] }
    stubFetch({ generated_at: NOW.toISOString(), items: [], past_top_stories: [story] })
    const result = await loadFeed('/news.json')
    expect(result.past_top_stories.map((s) => [s.id, s.last_shown])).toEqual([['old', null]])
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

describe('splitArchive', () => {
  const cutoff = archiveCutoff(NOW).getTime() // 2026-10-02T00:00 (tests run in UTC)
  const ids = (list: { id: string }[]) => list.map((i) => i.id)

  it('archives stories from before yesterday', () => {
    expect(new Date(cutoff).toISOString()).toBe('2026-10-02T00:00:00.000Z')
    const items = [
      makeItem('today', '2026-10-03T09:00:00Z'),
      makeItem('yesterday', '2026-10-02T00:30:00Z'),
      makeItem('old', '2026-10-01T23:00:00Z'),
      makeItem('older', '2026-09-28T10:00:00Z'),
    ]
    const { recent, archive } = splitArchive(feed(items), cutoff)
    expect(ids(recent)).toEqual(['today', 'yesterday'])
    expect(ids(archive)).toEqual(['old', 'older'])
  })

  it('puts every blog post on the Blogs tab, whatever its age', () => {
    const items = [
      makeItem('news', '2026-10-03T09:00:00Z'),
      makeItem('eng', '2026-10-03T08:00:00Z', { engineering: true }),
      makeItem('post', '2026-09-29T08:00:00Z', { blog: true }),
      makeItem('not-post', '2026-09-29T07:00:00Z', { blog: false }),
    ]
    const { recent, blogs, archive } = splitArchive(feed(items), cutoff)
    expect([ids(recent), ids(blogs), ids(archive)]).toEqual([['news'], ['eng', 'post'], ['not-post']])
  })

  it('keeps an old article on the News tab when it was only just found', () => {
    const late = makeItem('late', '2026-09-30T09:00:00Z', { fetched_at: '2026-10-03T11:00:00Z' })
    expect(ids(splitArchive(feed([late]), cutoff).recent)).toEqual(['late'])
  })

  it('shows at most MAX_DISPLAYED recent stories, without archiving the rest', () => {
    const items = Array.from({ length: MAX_DISPLAYED + 5 }, (_, n) => makeItem(`k${n}`, null))
    const { recent, archive } = splitArchive(feed(items), cutoff)
    expect(recent).toHaveLength(MAX_DISPLAYED)
    expect(recent.at(-1)?.id).toBe(`k${MAX_DISPLAYED - 1}`)
    expect(archive).toEqual([])
  })

  it('keeps stories a top-story card needs beyond the cap or the cutoff', () => {
    const items = [
      ...Array.from({ length: MAX_DISPLAYED + 2 }, (_, n) => makeItem(`k${n}`, null)),
      makeItem('old', '2026-09-30T09:00:00Z'),
    ]
    const story = { id: 'x', title: 'X', summary: null, why_it_matters: null, primary_url: null, first_shown: null, last_shown: null }
    const { recent, archive } = splitArchive(
      {
        ...feed(items, NOW.toISOString(), [{ ...story, item_ids: [`k${MAX_DISPLAYED + 1}`] }]),
        past_top_stories: [{ ...story, item_ids: ['old'] }],
      },
      cutoff,
    )
    expect(ids(recent).slice(MAX_DISPLAYED)).toEqual([`k${MAX_DISPLAYED + 1}`, 'old'])
    expect(ids(archive)).toEqual(['old'])
  })
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

describe('isNewSince', () => {
  const item = makeItem('a', '2026-10-01T00:00:00Z', { fetched_at: '2026-10-03T11:00:00.123456Z' })

  it('compares the fetch time, not the publish time', () => {
    expect(isNewSince(item, new Date('2026-10-03T10:00:00Z'))).toBe(true)
    // Same run as the last visit (JS dates drop the scraper's microseconds): already seen.
    expect(isNewSince(item, new Date('2026-10-03T11:00:00.123Z'))).toBe(false)
    expect(isNewSince(item, new Date('2026-10-03T11:00:01Z'))).toBe(false)
  })

  it('is never new on a first visit', () => {
    expect(isNewSince(item, null)).toBe(false)
  })
})

describe('top stories', () => {
  const a = makeItem('a', null, { source_id: 'one' })
  const b = makeItem('b', null, { source_id: 'two' })
  const c = makeItem('c', null, { source_id: 'one' })
  const story = (id: string, item_ids: string[]) => ({ id, title: id, summary: null, why_it_matters: null, primary_url: null, first_shown: null, last_shown: null, item_ids })

  it('loadFeed keeps well-formed top stories only', async () => {
    stubFetch({
      generated_at: NOW.toISOString(),
      items: [a, b],
      top_stories: [
        story('ok', ['a', 'b']),
        { ...story('js', ['a', 'b']), primary_url: 'javascript:alert(1)' },
        { id: 'bad', title: 1, item_ids: [] },
        null,
      ],
    })
    const stories = (await loadFeed('/news.json')).top_stories
    expect(stories.map((s) => [s.id, s.primary_url])).toEqual([['ok', null], ['js', null]])
  })

  it('resolves items lead first, keeps single-source standouts, drops stories with no shown items', () => {
    const resolved = resolveTopStories(
      [story('two-sources', ['b', 'missing', 'a']), story('standout', ['c']), story('gone', ['x', 'y'])],
      [a, b, c],
    )
    expect(resolved.map((r) => [r.story.id, r.items.map((i) => i.id)])).toEqual([
      ['two-sources', ['b', 'a']],
      ['standout', ['c']],
    ])
  })
})

describe('byImportance', () => {
  it('orders by score, unscored last, keeping order for ties', () => {
    const items = [
      makeItem('new-2', null, { importance: 2 }),
      makeItem('new-null', null),
      makeItem('new-5', null, { importance: 5 }),
      makeItem('old-2', null, { importance: 2 }),
      makeItem('old-5', null, { importance: 5 }),
    ]
    expect(byImportance(items).map((i) => i.id)).toEqual(['new-5', 'old-5', 'new-2', 'old-2', 'new-null'])
  })

  it('puts engineering-blog posts first, whatever their score', () => {
    const items = [
      makeItem('news-5', null, { importance: 5 }),
      makeItem('eng-2', null, { importance: 2, engineering: true }),
      makeItem('eng-4', null, { importance: 4, engineering: true }),
    ]
    expect(byImportance(items).map((i) => i.id)).toEqual(['eng-4', 'eng-2', 'news-5'])
  })
})
