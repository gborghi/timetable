// TanStack Query client + sensible defaults for piTantum.
//
// Section 1.2 P2 of docs/improvements.md.
//
// Why TanStack Query: navigation between Teachers / Classes / Schedule
// pages currently re-fetches the same lists every time. Caching them
// with stale-while-revalidate gives instant navigation, automatic
// refetch when the user comes back to a tab, and a clean
// invalidate-on-mutation pattern that pairs perfectly with the
// existing `bumpMutation()` store.

import { QueryClient } from "@tanstack/svelte-query";
import { mutationCounter } from "../stores";

/**
 * Single shared client. Defaults:
 * - staleTime: 30s -- fresh enough for UI-driven workflows; below the
 *   backend's TTL cache window so we don't outpace it.
 * - gcTime:    5min -- keep cache around when navigating back.
 * - refetchOnWindowFocus: true -- if the user alt-tabs back, refresh.
 * - retry: 1 -- the api.ts wrapper already retries 5xx for GETs.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
    mutations: {
      retry: 0,
    },
  },
});

/**
 * Subscribe to the global mutationCounter store: every time the
 * MutationBumpMiddleware on the backend (or an explicit
 * bumpMutation() call) records a write, we invalidate ALL queries.
 * That's broader than strictly necessary but keeps the wiring trivial
 * -- if a per-resource invalidation is later required, it can replace
 * this without restructuring the hooks.
 */
let lastSeen = -1;
mutationCounter.subscribe((n) => {
  if (n === lastSeen) return;
  lastSeen = n;
  if (n > 0) {
    // Don't invalidate on initial subscription tick (n === 0).
    void queryClient.invalidateQueries();
  }
});
