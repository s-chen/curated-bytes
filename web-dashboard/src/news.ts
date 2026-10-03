import type { NewsFeed, NewsItem } from './App.tsx'

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** Only http(s) links are rendered. The scraper enforces this too; this is defence in depth. */
export function isSafeUrl(url: unknown): url is string {
  if (typeof url !== 'string') return false
  try {
    const { protocol, hostname } = new URL(url)
    return (protocol === 'http:' || protocol === 'https:') && hostname !== ''
  } catch {
    return false
  }
}

function isRenderable(item: unknown): item is NewsItem {
  if (typeof item !== 'object' || item === null) return false
  const { id, title, url, source_id, fetched_at } = item as Record<string, unknown>
  return (
    typeof id === 'string' &&
    typeof title === 'string' &&
    typeof source_id === 'string' &&
    typeof fetched_at === 'string' &&
    isSafeUrl(url)
  )
}

/** Fetch and sanity-check `news.json`. Items that can't be rendered safely are dropped. */
export async function loadFeed(url: string, signal?: AbortSignal): Promise<NewsFeed> {
  const response = await fetch(url, { cache: 'no-cache', signal })
  if (!response.ok) throw new Error(`HTTP ${response.status} loading news.json`)
  let data: unknown
  try {
    data = await response.json()
  } catch {
    throw new Error('news.json is not valid JSON')
  }
  const { generated_at, items } = (data ?? {}) as Record<string, unknown>
  if (typeof generated_at !== 'string' || !Array.isArray(items)) {
    throw new Error('news.json is not in the expected format')
  }
  return { generated_at, items: items.filter(isRenderable) }
}

export function itemDate(item: NewsItem): Date {
  return new Date(item.published_at ?? item.fetched_at)
}

export function hostname(url: string): string {
  return new URL(url).hostname.replace(/^www\./, '')
}

export interface SourceCount {
  id: string
  name: string
  count: number
}

/** Sources present in `items`, most items first. */
export function sourceCounts(items: NewsItem[]): SourceCount[] {
  const counts = new Map<string, SourceCount>()
  for (const item of items) {
    const entry = counts.get(item.source_id)
    if (entry) entry.count++
    else counts.set(item.source_id, { id: item.source_id, name: item.source_name, count: 1 })
  }
  return [...counts.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
}

/** Case-insensitive match on title, summary and source; an empty `sources` set means all. */
export function filterItems(
  items: NewsItem[],
  query: string,
  sources: ReadonlySet<string>,
): NewsItem[] {
  const needle = query.trim().toLowerCase()
  return items.filter((item) => {
    if (sources.size > 0 && !sources.has(item.source_id)) return false
    if (!needle) return true
    return [item.title, item.summary ?? '', item.source_name].some((text) =>
      text.toLowerCase().includes(needle),
    )
  })
}

export interface DayGroup {
  key: string
  label: string
  items: NewsItem[]
}

function localDayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
}

/** Group items (already newest first) by local calendar day, keeping their order. */
export function groupByDay(items: NewsItem[], now: Date): DayGroup[] {
  const today = localDayKey(now)
  const yesterday = localDayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))
  const groups = new Map<string, DayGroup>()
  for (const item of items) {
    const date = itemDate(item)
    const key = localDayKey(date)
    let group = groups.get(key)
    if (!group) {
      const label =
        key === today
          ? 'Today'
          : key === yesterday
            ? 'Yesterday'
            : date.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })
      group = { key, label, items: [] }
      groups.set(key, group)
    }
    group.items.push(item)
  }
  return [...groups.values()]
}

/** Compact age: "just now", "5m ago", "3h ago", "2d ago". */
export function formatAge(date: Date, now: Date): string {
  const elapsed = Math.max(0, now.getTime() - date.getTime())
  if (elapsed < MINUTE) return 'just now'
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)}m ago`
  if (elapsed < DAY) return `${Math.floor(elapsed / HOUR)}h ago`
  return `${Math.floor(elapsed / DAY)}d ago`
}

export function formatTime(date: Date): string {
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}
