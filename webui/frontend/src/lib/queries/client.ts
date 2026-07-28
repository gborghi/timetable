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

import { get } from "svelte/store";
import { QueryClient } from "@tanstack/svelte-query";
import { mutationCounter, lastMutatedResources } from "../stores";

/**
 * Single shared client. Defaults:
 * - staleTime: 30s -- fresh enough for UI-driven workflows; below the
 *   backend's TTL cache window so we don't outpace it.
 * - gcTime:    5min -- keep cache around when navigating back.
 * - refetchOnWindowFocus: false -- alt-tabbing back used to refetch
 *   *every* mounted query at once (subjects + classes + classrooms +
 *   curricula on a single page), a refetch storm on a big school. Rely
 *   on staleTime + explicit invalidation instead.
 * - retry: 1 -- the api.ts wrapper already retries 5xx for GETs.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
    mutations: {
      retry: 0,
    },
  },
});

/**
 * Subscribe to the global mutationCounter store: every recorded write
 * (backend MutationBumpMiddleware or an explicit bumpMutation()) either
 * invalidates the specific resource key(s) the caller reported, or --
 * when none were reported (legacy call sites) -- falls back to
 * invalidating everything. This keeps the common single-resource write
 * from re-fetching every unrelated list on a big school.
 */
let lastSeen = -1;
mutationCounter.subscribe((n) => {
  if (n === lastSeen) return;
  lastSeen = n;
  if (n <= 0) return;   // skip the initial subscription tick (n === 0)
  const resources = get(lastMutatedResources);
  if (resources && resources.length) {
    for (const key of resources) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  } else {
    void queryClient.invalidateQueries();
  }
});
