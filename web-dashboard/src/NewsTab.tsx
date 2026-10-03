import { useDeferredValue, useMemo, useState } from 'react'
import type { NewsItem } from './App.tsx'
import { filterItems, formatTime, groupByDay, hostname, itemDate, sourceCounts } from './news.ts'

const chip =
  'rounded-full border px-2.5 py-0.5 text-xs transition-colors aria-pressed:border-zinc-900 aria-pressed:bg-zinc-900 aria-pressed:text-white dark:aria-pressed:border-zinc-100 dark:aria-pressed:bg-zinc-100 dark:aria-pressed:text-zinc-900 border-zinc-300 text-zinc-600 hover:border-zinc-500 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-zinc-500'

export function NewsTab({ items, now }: { items: NewsItem[]; now: Date }) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const deferredQuery = useDeferredValue(query)

  const sources = useMemo(() => sourceCounts(items), [items])
  const visible = useMemo(
    () => filterItems(items, deferredQuery, selected),
    [items, deferredQuery, selected],
  )
  const groups = useMemo(() => groupByDay(visible, now), [visible, now])

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
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter headlines…"
          aria-label="Filter headlines"
          className="w-full rounded-md border border-zinc-300 bg-transparent px-3 py-1.5 text-sm outline-none placeholder:text-zinc-400 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 dark:border-zinc-700"
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
              className={chip}
              aria-pressed={selected.has(s.id)}
              onClick={() => toggleSource(s.id)}
            >
              {s.name} <span className="tabular-nums opacity-60">{s.count}</span>
            </button>
          ))}
        </div>
        <p className="text-xs text-zinc-500" aria-live="polite">
          {visible.length === items.length
            ? `${items.length} stories`
            : `${visible.length} of ${items.length} stories`}
        </p>
      </div>

      {groups.length === 0 ? (
        <p className="py-12 text-center text-sm text-zinc-500">No stories match.</p>
      ) : (
        groups.map((group) => (
          <section key={group.key} aria-labelledby={`day-${group.key}`} className="mt-5">
            <h2
              id={`day-${group.key}`}
              className="border-b border-zinc-200 pb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:border-zinc-800"
            >
              {group.label}
            </h2>
            <ul className="divide-y divide-zinc-100 dark:divide-zinc-900">
              {group.items.map((item) => (
                <NewsRow key={item.id} item={item} />
              ))}
            </ul>
          </section>
        ))
      )}
    </>
  )
}

function NewsRow({ item }: { item: NewsItem }) {
  const date = itemDate(item)
  const host = hostname(item.url)
  return (
    <li className="flex gap-3 py-1.5">
      <time
        dateTime={date.toISOString()}
        title={date.toLocaleString()}
        className="w-11 shrink-0 pt-0.5 text-xs tabular-nums text-zinc-400"
      >
        {formatTime(date)}
      </time>
      <div className="min-w-0 flex-1">
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-medium text-zinc-900 visited:text-zinc-500 hover:underline dark:text-zinc-100 dark:visited:text-zinc-500"
        >
          {item.title}
        </a>
        <span className="ml-2 whitespace-nowrap text-xs text-zinc-500">
          {item.source_name} · {host}
        </span>
        {item.summary && (
          <p className="line-clamp-1 text-xs text-zinc-500 sm:line-clamp-2">{item.summary}</p>
        )}
      </div>
    </li>
  )
}
