import { useEffect, useState } from 'react'

const KEY = 'curatedbytes:lastVisit'

function readLastVisit(): Date | null {
  try {
    const value = localStorage.getItem(KEY)
    const date = value ? new Date(value) : null
    return date && !Number.isNaN(date.getTime()) ? date : null
  } catch {
    return null
  }
}

function writeLastVisit(value: string) {
  try {
    localStorage.setItem(KEY, value)
  } catch {
    // Storage unavailable (private mode etc.): every visit looks like the first.
  }
}

/**
 * When the reader last saw the feed, per this browser.
 *
 * The returned value is fixed for the page load, so the "new" section doesn't shift while
 * reading. `seen` (the feed's `generated_at`) is recorded as seen whenever the page is visible,
 * so a refresh that lands in a background tab still counts as new on the next visit.
 */
export function useLastVisit(seen: string | null): Date | null {
  const [lastVisit] = useState(readLastVisit)

  useEffect(() => {
    if (!seen) return
    const markSeen = () => {
      if (document.visibilityState !== 'hidden') writeLastVisit(seen)
    }
    markSeen()
    document.addEventListener('visibilitychange', markSeen)
    return () => document.removeEventListener('visibilitychange', markSeen)
  }, [seen])

  return lastVisit
}
