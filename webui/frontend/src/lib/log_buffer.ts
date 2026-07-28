// Bounded log-line buffer for the streaming SSE run log.
//
// A long solve streams thousands of lines into RunLogPanel. The naive
// `lines = [...lines, l].slice(-MAX)` per incoming line reallocates the
// whole array (and re-joins the whole string) on every line -> O(n^2)
// allocation + GC churn. RunLogPanel instead batches a frame's worth of
// lines and caps them here once per flush, so the cost is O(batch) per
// animation frame rather than O(total) per line.

export const MAX_LOG_LINES = 2000;

/**
 * Append `incoming` onto `existing`, keeping at most `max` lines (the
 * most recent; oldest are dropped). Returns a NEW array (never mutates
 * its inputs) so it is safe to assign for Svelte reactivity. One
 * allocation per call.
 */
export function appendCapped(
  existing: readonly string[],
  incoming: readonly string[],
  max: number = MAX_LOG_LINES,
): string[] {
  if (max <= 0) return [];
  if (incoming.length === 0) return existing.slice();
  // A batch at least `max` long already contains the final window.
  if (incoming.length >= max) return incoming.slice(incoming.length - max);
  const merged = existing.concat(incoming);
  return merged.length > max ? merged.slice(merged.length - max) : merged;
}
