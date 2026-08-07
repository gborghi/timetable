# Frontend Architecture

## State management pattern (audit F5)

piTantum uses a two-tier state model:

### Tier 1: Server state — TanStack Query

All data that originates from the REST API (teachers, classes, subjects, etc.)
is managed by **TanStack Query** (`@tanstack/svelte-query`).

- **Stale time:** 30 s (avoids re-fetch storms on tab switches)
- **Refetch on window focus:** off (single-user desktop app)
- **Cache invalidation:** selective, driven by `mutationCounter` — only the
  resources touched by a mutation are invalidated, not the entire cache
- **Query hooks:** defined in `src/lib/queries/`, one hook per resource
  (e.g., `useTeachers`, `useClasses`)

See `src/lib/queries/client.ts` for the `QueryClient` setup and
`src/lib/queries/index.ts` for the hook catalogue.

### Tier 2: UI state — Svelte stores

Transient client-only state lives in Svelte writable/derived stores
(`src/lib/stores.ts`):

| Store | Purpose |
|---|---|
| `datasetState` | Header pill counters (n teachers, n classes, etc.) |
| `toast` | Notification messages |
| `mutationCounter` | Write counter for selective cache invalidation |
| `lastMutatedResources` | Set of resource names touched by last mutation |
| `datasetLoading` / `datasetEverLoaded` | Skeleton-vs-spinner distinction |
| `datasetEmpty` | Derived: true when all counters are zero |
| `workingHoursConfig` | Live-synced Tab Ore config, propagated to calendars |
| `networkOnline` | Offline banner with periodic health-check ping |
| `confirmRequest` | Custom branded confirm/prompt dialog (replaces window.confirm) |

### Data flow

```
REST API ──(TanStack Query)──▶ query cache ──▶ components
    ▲                              │
    │                         mutations invalidate
    │                              │
    └────────── POST/PUT/DELETE ───┘
                  ▲
    stores.ts ────┘ mutationCounter bump triggers selective refetch
```

### Component sizing guideline

When a component exceeds 300 lines, extract:
1. **Business logic** → `src/lib/logic/<feature>.ts` (pure functions, testable with `node:test`)
2. **Sub-components** → `src/lib/components/<feature>/` (one concern per component)
3. **Stores** → `src/lib/stores/<feature>.ts` (if the state is shared across pages)
