import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { NewsTab } from './NewsTab.tsx'
import { formatAge, loadFeed } from './news.ts'

/** Must match `NewsItem` in scraper/src/scraper/models.py. Change both together. */
export interface NewsItem {
  id: string
  title: string
  url: string
  source_id: string
  source_name: string
  category: string
  summary: string | null
  /** ISO 8601, UTC. Null when the feed gave no date. */
  published_at: string | null
  /** ISO 8601, UTC. When the scraper first saw the item. */
  fetched_at: string
}

/** Must match `NewsFeed` in scraper/src/scraper/models.py. */
export interface NewsFeed {
  generated_at: string
  items: NewsItem[]
}

const NEWS_URL = `${import.meta.env.BASE_URL}news.json`
/** The scraper runs hourly; older than this means runs are failing. */
const STALE_AFTER_MS = 3 * 60 * 60 * 1000

type Tab = 'news' | 'jobs'
const TABS: { id: Tab; label: string }[] = [
  { id: 'news', label: 'News' },
  { id: 'jobs', label: 'Jobs' },
]

type FeedState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; feed: NewsFeed }

function tabFromHash(): Tab {
  return window.location.hash === '#jobs' ? 'jobs' : 'news'
}

/** Current time, refreshed every minute so relative ages stay accurate. */
function useNow(): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(timer)
  }, [])
  return now
}

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash)
  const [state, setState] = useState<FeedState>({ status: 'loading' })
  const tabRefs = useRef<Partial<Record<Tab, HTMLButtonElement | null>>>({})
  const now = useNow()

  useEffect(() => {
    const controller = new AbortController()
    loadFeed(NEWS_URL, controller.signal)
      .then((feed) => setState({ status: 'ready', feed }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({ status: 'error', message: error instanceof Error ? error.message : String(error) })
      })
    return () => controller.abort()
  }, [])

  function selectTab(next: Tab) {
    setTab(next)
    window.history.replaceState(null, '', `#${next}`)
  }

  function onTabKeyDown(event: KeyboardEvent) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    const index = TABS.findIndex((t) => t.id === tab)
    const step = event.key === 'ArrowRight' ? 1 : -1
    const next = TABS[(index + step + TABS.length) % TABS.length].id
    selectTab(next)
    tabRefs.current[next]?.focus()
  }

  const generatedAt = state.status === 'ready' ? new Date(state.feed.generated_at) : null
  const stale = generatedAt !== null && now.getTime() - generatedAt.getTime() > STALE_AFTER_MS

  return (
    <div className="mx-auto max-w-4xl px-4 pb-12">
      <header className="sticky top-0 z-10 flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-zinc-200 bg-white/90 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/90">
        <h1 className="font-mono text-lg font-bold tracking-tight">
          Curated<span className="text-emerald-600 dark:text-emerald-400">Bytes</span>
        </h1>
        <div role="tablist" aria-label="Sections" className="flex gap-1" onKeyDown={onTabKeyDown}>
          {TABS.map(({ id, label }) => {
            const selected = tab === id
            return (
              <button
                key={id}
                ref={(el) => {
                  tabRefs.current[id] = el
                }}
                id={`tab-${id}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`panel-${id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => selectTab(id)}
                className={`rounded-md px-3 py-1 text-sm font-medium transition-colors ${
                  selected
                    ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                    : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
                }`}
              >
                {label}
                {id === 'news' && state.status === 'ready' && (
                  <span className="ml-1.5 text-xs tabular-nums opacity-60">
                    {state.feed.items.length}
                  </span>
                )}
              </button>
            )
          })}
        </div>
        {generatedAt && (
          <p
            className={`ml-auto text-xs ${stale ? 'font-medium text-amber-600 dark:text-amber-400' : 'text-zinc-500'}`}
            title={generatedAt.toLocaleString()}
          >
            {stale ? 'Stale: updated ' : 'Updated '}
            <time dateTime={state.status === 'ready' ? state.feed.generated_at : undefined}>
              {formatAge(generatedAt, now)}
            </time>
          </p>
        )}
      </header>

      <main
        id={`panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
        className="pt-4"
      >
        {tab === 'jobs' ? (
          <Notice title="Job matching isn't live yet">
            Postings scored against your CV will appear here once the jobs pipeline is running.
          </Notice>
        ) : state.status === 'loading' ? (
          <p className="py-12 text-center text-sm text-zinc-500" role="status">
            Loading news…
          </p>
        ) : state.status === 'error' ? (
          <Notice title="Couldn't load the news" tone="error">
            {state.message}. Locally, generate it with{' '}
            <code className="font-mono">docker compose run --rm scraper</code>.
          </Notice>
        ) : (
          <NewsTab items={state.feed.items} now={now} />
        )}
      </main>
    </div>
  )
}

function Notice({
  title,
  tone = 'info',
  children,
}: {
  title: string
  tone?: 'info' | 'error'
  children: ReactNode
}) {
  return (
    <div
      role={tone === 'error' ? 'alert' : undefined}
      className={`rounded-lg border p-4 text-sm ${
        tone === 'error'
          ? 'border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200'
          : 'border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300'
      }`}
    >
      <p className="font-medium">{title}</p>
      <p className="mt-1">{children}</p>
    </div>
  )
}
