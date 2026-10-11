import { useSyncExternalStore } from 'react'
import type { NewsItem } from './App.tsx'
import { isSafeUrl } from './news.ts'

const KEY = 'curatedbytes:saved'

/** A story saved for later. The item is copied, so it outlives its week in news.json. */
export interface SavedItem {
  item: NewsItem
  /** ISO 8601. */
  saved_at: string
}

const EMPTY: SavedItem[] = []
let cache: { raw: string | null; saved: SavedItem[] } | undefined
const listeners = new Set<() => void>()

function isSaved(entry: unknown): entry is SavedItem {
  if (typeof entry !== 'object' || entry === null) return false
  const { item, saved_at } = entry as Record<string, unknown>
  if (typeof saved_at !== 'string' || typeof item !== 'object' || item === null) return false
  const { id, title, url } = item as Record<string, unknown>
  return typeof id === 'string' && typeof title === 'string' && isSafeUrl(url)
}

function readRaw(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

/** Newest saved first. Stable between changes, as `useSyncExternalStore` requires. */
function getSnapshot(): SavedItem[] {
  const raw = readRaw()
  if (cache?.raw === raw) return cache.saved
  let saved = EMPTY
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : []
    if (Array.isArray(parsed)) saved = parsed.filter(isSaved)
  } catch {
    // Corrupt value: treat as nothing saved, and overwrite it on the next save.
  }
  cache = { raw, saved }
  return saved
}

function write(saved: SavedItem[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(saved))
  } catch {
    // Storage unavailable (private mode, quota): saving can't persist.
  }
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  // Other tabs: the storage event only fires for changes made elsewhere.
  const onStorage = (event: StorageEvent) => {
    if (event.key === KEY || event.key === null) listener()
  }
  window.addEventListener('storage', onStorage)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('storage', onStorage)
  }
}

/**
 * Ask the browser not to clear this site's storage when it frees space. Browsers decide for
 * themselves (Chrome grants it to sites you use, Firefox and Safari may ask), so it's
 * requested on a save, a user gesture, and failure just leaves storage best-effort.
 */
function requestPersistence() {
  navigator.storage?.persist?.().catch(() => {})
}

export function toggleSaved(item: NewsItem, now = new Date()) {
  const saved = getSnapshot()
  if (saved.some((s) => s.item.id === item.id)) {
    write(saved.filter((s) => s.item.id !== item.id))
  } else {
    write([{ item, saved_at: now.toISOString() }, ...saved])
    requestPersistence()
  }
}

export function removeSaved(id: string) {
  write(getSnapshot().filter((s) => s.item.id !== id))
}

/** Stories saved in this browser, newest saved first. Kept until removed. */
export function useSaved(): SavedItem[] {
  return useSyncExternalStore(subscribe, getSnapshot, () => EMPTY)
}

/** Whether one story is saved. A boolean snapshot, so only that story re-renders on a change. */
export function useIsSaved(id: string): boolean {
  return useSyncExternalStore(
    subscribe,
    () => getSnapshot().some((s) => s.item.id === id),
    () => false,
  )
}
