import { useDeferredValue, useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import type { NewsItem, TopStory } from './App.tsx'
import {
  byImportance,
  filterItems,
  formatAge,
  formatTime,
  groupByDay,
  hostname,
  isNewSince,
  itemDate,
  resolveTopStories,
  sourceCounts,
  type ResolvedStory,
} from './news.ts'

const DAY_MS = 24 * 60 * 60 * 1000

const chip =
  'rounded-full border px-2.5 py-0.5 text-xs transition-colors aria-pressed:border-zinc-900 aria-pressed:bg-zinc-900 aria-pressed:text-white dark:aria-pressed:border-zinc-100 dark:aria-pressed:bg-zinc-100 dark:aria-pressed:text-zinc-900 border-zinc-300 text-zinc-600 hover:border-zinc-500 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-zinc-500'

const heading =
  'mb-1 flex items-center gap-3 text-xs font-semibold uppercase tracking-wide after:h-px after:flex-1'

/** Full class names, so Tailwind can see them. A source keeps its colour across reloads. */
const SOURCE_COLOURS = [
  'bg-emerald-500',
  'bg-sky-500',
  'bg-amber-500',
  'bg-rose-500',
  'bg-violet-500',
  'bg-orange-500',
  'bg-teal-500',
  'bg-fuchsia-500',
]

function sourceColour(sourceId: string): string {
  let hash = 0
  for (const char of sourceId) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return SOURCE_COLOURS[hash % SOURCE_COLOURS.length]
}

/** "3h ago" for the last day, then the clock time (the day is in the group heading). */
function displayTime(date: Date, now: Date): string {
  return now.getTime() - date.getTime() < DAY_MS ? formatAge(date, now) : formatTime(date)
}

function isTyping(target: EventTarget | null): target is HTMLElement {
  return target instanceof HTMLElement && target.closest('input, textarea, select, [contenteditable]') !== null
}

/** j/k move between stories, o opens the focused one, / focuses search, Esc leaves it. */
function useKeyboardShortcuts(
  list: RefObject<HTMLElement | null>,
  search: RefObject<HTMLInputElement | null>,
) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (isTyping(event.target)) {
        if (event.key === 'Escape') event.target.blur()
        return
      }
      if (event.key === '/') {
        event.preventDefault()
        search.current?.focus()
        return
      }
      // Skip links inside a collapsed section: they can't take focus.
      const links = [
        ...(list.current?.querySelectorAll<HTMLAnchorElement>('a[data-story]') ?? []),
      ].filter((link) => !link.closest('details:not([open])'))
      const index = links.indexOf(document.activeElement as HTMLAnchorElement)
      if (event.key === 'j' || event.key === 'k') {
        event.preventDefault()
        const next = links[event.key === 'j' ? Math.min(index + 1, links.length - 1) : Math.max(index - 1, 0)]
        if (!next) return
        next.focus({ preventScroll: true })
        next.closest('li')?.scrollIntoView?.({ block: 'nearest' })
      } else if (event.key === 'o' && index >= 0) {
        window.open(links[index].href, '_blank', 'noopener,noreferrer')
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [list, search])
}

export function NewsTab({
  items,
  topStories,
  pastTopStories,
  now,
  lastVisit,
}: {
  items: NewsItem[]
  topStories: TopStory[]
  pastTopStories: TopStory[]
  now: Date
  lastVisit: Date | null
}) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const deferredQuery = useDeferredValue(query)
  const listRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  useKeyboardShortcuts(listRef, searchRef)

  const sources = useMemo(() => sourceCounts(items), [items])
  const visible = useMemo(
    () => filterItems(items, deferredQuery, selected),
    [items, deferredQuery, selected],
  )
  // Top stories show only when unfiltered; their items then aren't repeated in the list.
  const filtering = deferredQuery.trim() !== '' || selected.size > 0
  const top = useMemo(
    () => (filtering ? [] : resolveTopStories(topStories, items)),
    [filtering, topStories, items],
  )
  const past = useMemo(
    () => (filtering ? [] : resolveTopStories(pastTopStories, items)),
    [filtering, pastTopStories, items],
  )
  const listed = useMemo(() => {
    const inTop = new Set(top.flatMap((t) => t.items.map((i) => i.id)))
    return visible.filter((i) => !inTop.has(i.id))
  }, [visible, top])
  // Within each section the list is ordered by Gemini's importance score.
  const fresh = useMemo(
    () => byImportance(listed.filter((i) => isNewSince(i, lastVisit))),
    [listed, lastVisit],
  )
  const groups = useMemo(
    () =>
      groupByDay(listed.filter((i) => !isNewSince(i, lastVisit)), now).map((group) => ({
        ...group,
        items: byImportance(group.items),
      })),
    [listed, lastVisit, now],
  )

  function toggleSource(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }

  return (
    <>
      <div className="flex flex-col gap-3">
        <input
          ref={searchRef}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter headlines…"
          aria-label="Filter headlines"
          aria-keyshortcuts="/"
          className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm outline-none placeholder:text-zinc-400 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 dark:border-zinc-700 dark:bg-zinc-900"
        />
        <div className="flex flex-wrap gap-1.5" aria-label="Sources">
          <button
            type="button"
            className={chip}
            aria-pressed={selected.size === 0}
            onClick={() => setSelected(new Set())}
          >
            All
          </button>
          {sources.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`${chip} inline-flex items-center gap-1.5`}
              aria-pressed={selected.has(s.id)}
              onClick={() => toggleSource(s.id)}
            >
              <span className={`size-1.5 rounded-full ${sourceColour(s.id)}`} aria-hidden />
              {s.name} <span className="tabular-nums opacity-60">{s.count}</span>
            </button>
          ))}
        </div>
        <p className="flex justify-between text-xs text-zinc-500">
          <span aria-live="polite">
            {visible.length === items.length
              ? `${items.length} stories`
              : `${visible.length} of ${items.length} stories`}
          </span>
          <span className="hidden sm:inline">
            <Kbd>j</Kbd>/<Kbd>k</Kbd> move · <Kbd>o</Kbd> open · <Kbd>/</Kbd> search
          </span>
        </p>
      </div>

      <div ref={listRef}>
        {visible.length === 0 ? (
          <p className="py-12 text-center text-sm text-zinc-500">No stories match.</p>
        ) : (
          <>
            {top.length > 0 && (
              <section aria-labelledby="top-stories" className="mt-5">
                <h2
                  id="top-stories"
                  className={`${heading} mb-2 text-zinc-700 after:bg-zinc-200 dark:text-zinc-300 dark:after:bg-zinc-800`}
                >
                  Top stories
                </h2>
                <ul className="grid gap-3 sm:grid-cols-2">
                  {top.map((resolved, index) => (
                    <TopStoryCard
                      key={resolved.story.id}
                      resolved={resolved}
                      wide={index === 0 && top.length % 2 === 1}
                      now={now}
                      lastVisit={lastVisit}
                    />
                  ))}
                </ul>
              </section>
            )}
            {past.length > 0 && <EarlierTopStories stories={past} now={now} />}
            {fresh.length > 0 && (
              <section aria-labelledby="day-new" className="mt-5">
                <h2
                  id="day-new"
                  className={`${heading} text-emerald-700 after:bg-emerald-300 dark:text-emerald-400 dark:after:bg-emerald-800`}
                >
                  {fresh.length} new since your last visit
                </h2>
                <StoryList items={fresh} now={now} />
              </section>
            )}
            {groups.map((group) => (
              <section key={group.key} aria-labelledby={`day-${group.key}`} className="mt-5">
                <h2
                  id={`day-${group.key}`}
                  className={`${heading} text-zinc-500 after:bg-zinc-200 dark:after:bg-zinc-800`}
                >
                  {group.label}
                </h2>
                <StoryList items={group.items} now={now} />
              </section>
            ))}
          </>
        )}
      </div>
    </>
  )
}

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-zinc-300 px-1 font-mono text-[10px] dark:border-zinc-700">
      {children}
    </kbd>
  )
}

function TopStoryCard({
  resolved: { story, items },
  wide,
  now,
  lastVisit,
}: {
  resolved: ResolvedStory
  wide: boolean
  now: Date
  lastVisit: Date | null
}) {
  const [lead] = items
  const newest = items.map(itemDate).reduce((a, b) => (a > b ? a : b))
  const isNew = items.some((i) => isNewSince(i, lastVisit))
  const sourceCount = new Set(items.map((i) => i.source_id)).size
  return (
    <li
      className={`flex scroll-mt-20 flex-col rounded-xl border border-zinc-200 bg-white p-4 shadow-xs focus-within:border-emerald-500 dark:border-zinc-800 dark:bg-zinc-900 dark:focus-within:border-emerald-600 ${wide ? 'sm:col-span-2' : ''}`}
    >
      <div className="flex items-center justify-between gap-2 text-xs text-zinc-500">
        <span className="flex items-center gap-2">
          {sourceCount > 1 ? `${sourceCount} sources` : lead.source_name}
          {isNew && (
            <span className="rounded-full bg-emerald-100 px-1.5 font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
              New
            </span>
          )}
        </span>
        <time dateTime={newest.toISOString()} title={newest.toLocaleString()} className="tabular-nums text-zinc-400">
          {displayTime(newest, now)}
        </time>
      </div>
      <h3 className={`mt-1.5 font-semibold leading-snug ${wide ? 'text-lg' : 'text-base'}`}>
        <a
          href={lead.url}
          target="_blank"
          rel="noopener noreferrer"
          data-story
          className="text-zinc-900 outline-none visited:text-zinc-500 hover:underline focus-visible:underline dark:text-zinc-100 dark:visited:text-zinc-500"
        >
          {story.title}
        </a>
      </h3>
      {story.summary && (
        <p className="mt-1.5 line-clamp-4 text-sm text-zinc-600 dark:text-zinc-400">{story.summary}</p>
      )}
      {story.why_it_matters && (
        <p className="mt-2 border-l-2 border-emerald-500 pl-2 text-sm text-zinc-700 dark:text-zinc-300">
          <span className="font-medium">Why it matters: </span>
          {story.why_it_matters}
        </p>
      )}
      {story.primary_url && (
        <p className="mt-2 text-xs text-zinc-500">
          Primary source:{' '}
          <a
            href={story.primary_url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-emerald-700 hover:underline dark:text-emerald-400"
          >
            {hostname(story.primary_url)}
          </a>
        </p>
      )}
      <ul className="mt-auto flex flex-wrap gap-x-3 gap-y-1 pt-3 text-xs" aria-label="Coverage">
        {items.map((item) => (
          <li key={item.id}>
            <a
              href={item.url}
              title={item.title}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-zinc-500 hover:text-zinc-900 hover:underline dark:hover:text-zinc-100"
            >
              <span className={`size-1.5 rounded-full ${sourceColour(item.source_id)}`} aria-hidden />
              {item.source_name}
            </a>
            {item.discussion_url && (
              <>
                {' '}
                <DiscussionLink item={item} />
              </>
            )}
          </li>
        ))}
      </ul>
    </li>
  )
}

/** Top stories that have dropped off in the last two days, collapsed by default. */
function EarlierTopStories({ stories, now }: { stories: ResolvedStory[]; now: Date }) {
  return (
    <details className="group mt-4 rounded-lg border border-zinc-200 dark:border-zinc-800">
      <summary className="cursor-pointer select-none px-3 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
        Earlier top stories <span className="tabular-nums opacity-60">{stories.length}</span>
      </summary>
      <ul className="border-t border-zinc-200 px-3 py-1 dark:border-zinc-800">
        {stories.map(({ story, items }) => {
          const shown = story.last_shown ? new Date(story.last_shown) : null
          const sources = new Set(items.map((i) => i.source_id)).size
          return (
            <li key={story.id} className="py-1.5 text-xs">
              <a
                href={items[0].url}
                target="_blank"
                rel="noopener noreferrer"
                data-story
                className="text-sm font-medium text-zinc-900 outline-none visited:text-zinc-500 hover:underline focus-visible:underline dark:text-zinc-100"
              >
                {story.title}
              </a>
              <span className="ml-2 text-zinc-500">
                {sources > 1 ? `${sources} sources` : items[0].source_name}
                {shown && <> · top story until {formatAge(shown, now)}</>}
              </span>
              {story.why_it_matters && (
                <p className="line-clamp-1 text-zinc-500">{story.why_it_matters}</p>
              )}
            </li>
          )
        })}
      </ul>
    </details>
  )
}

/** "312 points · 145 comments" (or "Discussion" without counts), linking to the thread. */
function DiscussionLink({ item }: { item: NewsItem }) {
  const parts = [
    item.points !== null && `${item.points} points`,
    item.comments !== null && `${item.comments} comments`,
  ].filter(Boolean)
  return (
    <a
      href={item.discussion_url ?? undefined}
      target="_blank"
      rel="noopener noreferrer"
      className="text-zinc-500 underline decoration-zinc-300 hover:text-zinc-900 dark:decoration-zinc-700 dark:hover:text-zinc-100"
    >
      {parts.length > 0 ? parts.join(' · ') : 'Discussion'}
    </a>
  )
}

function StoryList({ items, now }: { items: NewsItem[]; now: Date }) {
  return (
    <ul>
      {items.map((item) => (
        <StoryRow key={item.id} item={item} now={now} />
      ))}
    </ul>
  )
}

function StoryRow({ item, now }: { item: NewsItem; now: Date }) {
  const date = itemDate(item)
  return (
    <li className="-mx-2 flex scroll-mt-20 scroll-mb-4 gap-2.5 rounded-md px-2 py-1.5 text-xs focus-within:bg-emerald-50 hover:bg-zinc-100 dark:hover:bg-zinc-900 dark:focus-within:bg-emerald-950/40">
      <span className={`mt-1.5 size-1.5 shrink-0 rounded-full ${sourceColour(item.source_id)}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          data-story
          className="text-sm font-medium text-zinc-900 outline-none visited:text-zinc-500 hover:underline focus-visible:underline dark:text-zinc-100 dark:visited:text-zinc-500"
        >
          {item.title}
        </a>
        <span className="ml-2 whitespace-nowrap text-zinc-500">
          {item.engineering && (
            <span className="mr-1.5 rounded bg-sky-100 px-1 font-medium text-sky-800 dark:bg-sky-950 dark:text-sky-300">
              Engineering
            </span>
          )}
          {item.source_name} · {hostname(item.url)}
          {item.discussion_url && (
            <>
              {' · '}
              <DiscussionLink item={item} />
            </>
          )}
        </span>
        {item.summary && <p className="line-clamp-1 text-zinc-500">{item.summary}</p>}
      </div>
      <time
        dateTime={date.toISOString()}
        title={date.toLocaleString()}
        className="shrink-0 pt-0.5 tabular-nums text-zinc-400"
      >
        {displayTime(date, now)}
      </time>
    </li>
  )
}
