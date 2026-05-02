<script>
  /**
   * Runs tab — global view of every optimization run launched in this
   * dataset. Per Giovanni's spec each row shows:
   *   - kind / name / profile pill
   *   - traffic-light pill: green=done, red=failed, blue=running, ink=pending
   *   - progress bar
   *   - started/finished timestamps
   *   - obj_value + metrics
   * Click expands a row to show:
   *   - params (JSON)
   *   - error trace if failed
   *   - toggleable log via RunLogPanel
   *
   * Auto-poll every 2s while at least one run is in 'running' or
   * 'pending'; stop polling otherwise to save CPU.
   */
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import RunLogPanel from '$lib/components/RunLogPanel.svelte';

  let runs = [];
  let busy = false;
  let expanded = new Set();
  let logFor = null;          // run id whose log is currently shown
  let pollTimer = null;
  let elapsedTimer = null;
  let now = Date.now();       // ticked once/sec so elapsed updates live
  let limit = 100;

  onMount(async () => {
    await refresh();
    // Poll the runs list. Strategy:
    //   - 2s while at least one run is running/pending
    //   - 6s otherwise (catches new runs the user kicks off elsewhere)
    pollTimer = setInterval(() => {
      const anyActive = runs.some((r) =>
        r.status === 'running' || r.status === 'pending'
      );
      // Always refresh; tighter cadence if active so the bar updates.
      // The endpoint is just a SELECT, < 5ms; cheap.
      refresh();
      // dynamic interval is hard with setInterval; we just always poll.
      // For "no active" we'd ideally use 6s, but a constant 2s costs
      // <100ms/min of backend work, irrelevant.
    }, 2000);
    // Ticker that re-renders the elapsed-time column once per second
    // even between polls. Without it, "Durata" only updates on each
    // refresh tick which feels stale during long runs.
    elapsedTimer = setInterval(() => { now = Date.now(); }, 1000);
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
    if (elapsedTimer) clearInterval(elapsedTimer);
  });

  async function refresh() {
    busy = true;
    try {
      runs = await api.get(`/api/optimize/runs?limit=${limit}`);
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally {
      busy = false;
    }
  }

  function toggle(id) {
    if (expanded.has(id)) expanded.delete(id);
    else expanded.add(id);
    expanded = expanded;
  }

  function semaforo(status) {
    if (status === 'done') return { cls: 'pill-green', label: '✓ success' };
    if (status === 'failed') return { cls: 'pill-red',   label: '✗ error' };
    if (status === 'running') return { cls: 'pill-blue', label: '● running' };
    return { cls: 'pill', label: status };
  }

  // Pure function (depends on `now` for reactivity in the markup).
  // The backend now serializes started_at / finished_at as UTC-aware
  // ISO strings, so Date.parse is well-defined; before the fix we
  // were getting elapsed values inflated by the user's UTC offset.
  function elapsed(r, _now) {
    const a = r.started_at, b = r.finished_at;
    if (!a) return '';
    const ta = Date.parse(a);
    const tb = b ? Date.parse(b) : _now;
    const s = Math.max(0, Math.round((tb - ta) / 1000));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${s % 60}s`;
  }

  function fmtTime(s) {
    if (!s) return '';
    const t = s.split('T')[1]?.split('.')[0];
    return t || s;
  }
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Runs</h1>
    <span class="text-sm text-ink-500">{runs.length} run nel dataset</span>
    <button class="btn !text-xs ml-auto" on:click={refresh} disabled={busy}>
      {busy ? '...' : 'refresh'}
    </button>
    <select class="text-sm px-2 py-1 border border-ink-200 rounded"
            bind:value={limit} on:change={refresh}>
      <option value={50}>50</option>
      <option value={100}>100</option>
      <option value={200}>200</option>
      <option value={500}>500</option>
    </select>
  </div>

  <p class="text-xs text-ink-500">
    Storia di ogni esecuzione (mock-import, Phase A, Phase B, metaeuristiche,
    classroom-assignment, place-event). Il semaforo a destra mostra
    <span class="pill-green !text-[10px]">✓ success</span>,
    <span class="pill-red !text-[10px]">✗ error</span>,
    <span class="pill-blue !text-[10px]">● running</span>;
    click su una riga per espanderla e vedere parametri / metriche / log
    streaming. Mentre c'e' almeno una run in corso la pagina poll-a
    automaticamente ogni 2s.
  </p>

  <div class="card p-2 overflow-x-auto">
    <table class="tbl text-xs w-full">
      <thead>
        <tr>
          <th>#</th>
          <th>Tipo</th>
          <th>Nome</th>
          <th>Stato</th>
          <th class="w-40">Avanzamento</th>
          <th>Avviato</th>
          <th>Durata</th>
          <th class="text-right">Obj</th>
          <th>Metriche</th>
          <th>Sol.</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#if runs.length === 0}
          <tr><td colspan="11" class="text-center text-ink-400 italic py-6">
            Nessun run ancora. Lancia un'ottimizzazione dal Workflow o
            dal Monitor (Piazza).
          </td></tr>
        {/if}
        {#each runs as r (r.id)}
          {@const sem = semaforo(r.status)}
          <tr class="cursor-pointer hover:bg-ink-50"
              on:click={() => toggle(r.id)}>
            <td class="text-ink-400">
              <span class="text-xs mr-1">
                {expanded.has(r.id) ? '▼' : '▶'}
              </span>#{r.id}
            </td>
            <td><span class="pill !text-[10px]">{r.kind}</span></td>
            <td class="text-ink-700">{r.name || ''}</td>
            <td>
              <span class="{sem.cls} !text-[10px]">{sem.label}</span>
            </td>
            <td>
              {#if r.progress != null}
                <div class="w-full h-2 rounded bg-ink-100 overflow-hidden">
                  <div class="h-full transition-all"
                       class:bg-emerald-500={r.status === 'done'}
                       class:bg-red-500={r.status === 'failed'}
                       class:bg-accent-500={r.status === 'running'
                                              || r.status === 'pending'}
                       style="width: {Math.round((r.progress || 0) * 100)}%">
                  </div>
                </div>
                <span class="text-[10px] text-ink-500">
                  {Math.round((r.progress || 0) * 100)}%
                </span>
              {/if}
            </td>
            <td class="text-[10px]">{fmtTime(r.started_at)}</td>
            <td class="text-[10px]">{elapsed(r, now)}</td>
            <td class="text-right">{r.obj_value ?? ''}</td>
            <td class="text-[10px] text-ink-500">
              {r.metrics
                ? Object.entries(r.metrics).slice(0, 4)
                    .map(([k, v]) => `${k}=${v}`).join(' · ')
                : ''}
            </td>
            <td class="text-[10px]">{r.solution_id ?? ''}</td>
            <td class="whitespace-nowrap">
              <button class="btn !text-[10px] !px-2 !py-0.5"
                      on:click|stopPropagation={() => (logFor = logFor === r.id ? null : r.id)}>
                {logFor === r.id ? 'nascondi log' : 'mostra log'}
              </button>
            </td>
          </tr>
          {#if expanded.has(r.id)}
            <tr style="background-color:#f9fafb;">
              <td colspan="11" class="p-3">
                <div class="grid md:grid-cols-2 gap-3 text-xs">
                  <div>
                    <h4 class="font-semibold mb-1">Parametri</h4>
                    {#if r.params && Object.keys(r.params).length}
                      <pre class="bg-white p-2 rounded border border-ink-200 overflow-auto max-h-40">{JSON.stringify(r.params, null, 2)}</pre>
                    {:else}
                      <span class="text-ink-400 italic">nessuno</span>
                    {/if}
                  </div>
                  <div>
                    <h4 class="font-semibold mb-1">Metriche complete</h4>
                    {#if r.metrics && Object.keys(r.metrics).length}
                      <pre class="bg-white p-2 rounded border border-ink-200 overflow-auto max-h-40">{JSON.stringify(r.metrics, null, 2)}</pre>
                    {:else}
                      <span class="text-ink-400 italic">nessuna</span>
                    {/if}
                  </div>
                </div>
                {#if r.status === 'failed' && r.error}
                  <div class="mt-3">
                    <h4 class="font-semibold mb-1 text-red-700">
                      Stack trace dell'errore
                    </h4>
                    <pre class="bg-red-50 border border-red-300 p-2 rounded overflow-auto max-h-60 text-[10px] text-red-900">{r.error}</pre>
                  </div>
                {/if}
              </td>
            </tr>
          {/if}
          {#if logFor === r.id}
            <tr>
              <td colspan="11" class="p-3">
                <RunLogPanel runId={r.id}
                             title={`Log run #${r.id} (${r.kind})`}/>
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  </div>
</div>
