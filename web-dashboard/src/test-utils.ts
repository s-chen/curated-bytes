import { vi } from 'vitest'
import type { NewsFeed, NewsItem } from './App.tsx'

export const NOW = new Date('2026-10-03T12:00:00Z')

export function makeItem(id: string, publishedAt: string | null, overrides: Partial<NewsItem> = {}): NewsItem {
  return {
    id,
    title: `Story ${id}`,
    url: `https://example.com/${id}`,
    source_id: 'example',
    source_name: 'Example',
    category: 'tech',
    summary: null,
    published_at: publishedAt,
    fetched_at: publishedAt ?? NOW.toISOString(),
    ...overrides,
  }
}

/** Stub `fetch` to answer with `body` (JSON-encoded unless it's a string). */
export function stubFetch(body: unknown, init: ResponseInit = { status: 200 }) {
  const text = typeof body === 'string' ? body : JSON.stringify(body)
  const fetchMock = vi.fn(async () => new Response(text, init))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export function feed(items: NewsItem[], generatedAt = NOW.toISOString()): NewsFeed {
  return { generated_at: generatedAt, items }
}
