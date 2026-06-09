<script>
  import DecorIcon from '$lib/components/DecorIcon.svelte';
  /**
   * Runs tab — global view of every optimization run launched in this
   * dataset. Per Giovanni's spec each row shows:
   *   - kind / nome / profilo
   *   - traffic-light pill: green=done, red=failed, blue=running
   *   - progress bar (animates while running)
   *   - started/finished timestamps
   *   - obj_value + first metrics inline
   * Click expands a row to show: full params, full metrics, error
   * trace if failed. "Mostra log" toggles a live RunLogPanel.
   *
   * Plus, per the latest spec:
   *   - Multi-level sort headers (dblclick label adds level)
   *   - DSL query bar with Cerca / Reset
   *   - Checkbox column + select-all
   *   - Delete button per row (dialog: "stai cancellandone N
   *     selezionati o solo questo?")
   *   - Bulk delete -> POST /api/optimize/runs/delete-batch
   *
   * Auto-poll every 2s (always; the endpoint is just a SELECT).
   */
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import RunLogPanel from '$lib/components/RunLogPanel.svelte';
  import { pipelineStepLabel } from '$lib/pipeline_labels';

  let runs = [];
  let busy = false;
  let expanded = new Set();
  let logFor = null;
  let pollTimer = null;
  let elapsedTimer = null;
  let now = Date.now();
  let limit = 200;

  // Sort + query state (DSL same shape as docenti / aule / classi).
  let rowQuery = '';
  let appliedQuery = '';
  let sortLevels = [];     // [{column, direction}]
  let queryError = '';
  let showHelp = false;
  const MAX_SORT_LEVELS = 3;

  const COLS = [
    { key: 'id',          label: '#' },
    { key: 'kind',        label: 'Tipo' },
    { key: 'name',        label: 'Nome' },
    { key: 'status',      label: 'Stato' },
    { key: 'progress',    label: 'Avanzamento' },
    { key: 'started_at',  label: 'Avviato' },
    { key: 'obj_value',   label: 'Obj' },
    { key: 'solution_id', label: 'Sol.' },
  ];

  // Selection
  let selected = new Set();   // run ids

  function buildSortString() {
    return sortLevels.map((l) => `${l.column},${l.direction}`).join(':');
  }

  // Stable equality for the fields that actually change while a run
  // is alive. We keep the OLD object reference when nothing
  // interesting changed -- this prevents Svelte from re-rendering
  // sub-trees (and avoids the "buttons glitch" Giovanni saw on long
  // pipelines, see RunDetail spec).
  function _runShallowEqual(a, b) {
    if (!a || !b) return false;
    return (
      a.status === b.status
      && a.progress === b.progress
      && a.obj_value === b.obj_value
      && a.solution_id === b.solution_id
      && a.error === b.error
      && a.finished_at === b.finished_at
      && a.current_step === b.current_step
      && JSON.stringify(a.metrics || null)
         === JSON.stringify(b.metrics || null)
    );
  }

  function _mergeRuns(prev, incoming) {
    // Build by-id map of previous rows
    const prevById = new Map(prev.map((r) => [r.id, r]));
    const out = new Array(incoming.length);
    for (let i = 0; i < incoming.length; i++) {
      const fresh = incoming[i];
      const old = prevById.get(fresh.id);
      // Reuse old reference if nothing relevant changed -- this is
      // what prevents the Svelte each-block from invalidating the
      // sub-tree (and the buttons inside it).
      out[i] = old && _runShallowEqual(old, fresh) ? old : fresh;
    }
    return out;
  }

  async function refresh({ silent = false } = {}) {
    if (!silent) busy = true;
    queryError = '';
    try {
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      if (appliedQuery) params.set('q', appliedQuery);
      const sortStr = buildSortString();
      if (sortStr) params.set('sort', sortStr);
      params.set('_t', String(Date.now()));
      const incoming = await api.get(
        '/api/optimize/runs?' + params.toString(),
      );
      runs = _mergeRuns(runs, incoming);
    } catch (e) {
      queryError = e?.message || String(e);
    } finally {
      busy = false;
    }
  }

  function _hasActive() {
    return runs.some((r) => r.status === 'running' || r.status === 'pending');
  }

  let _polling_fast = true;

  function _scheduleNextPoll() {
    if (pollTimer) clearInterval(pollTimer);
    const fast = _hasActive();
    _polling_fast = fast;
    pollTimer = setInterval(_pollTick, fast ? 2000 : 30000);
  }

  async function _pollTick() {
    await refresh({ silent: true });
    // If the active-state changed since last tick, reschedule with
    // the right cadence. This is what gives us "fast while a run
    // is alive, idle 30s otherwise" without spawning extra timers.
    if (_hasActive() !== _polling_fast) {
      _scheduleNextPoll();
    }
  }

  onMount(async () => {
    await refresh();
    _scheduleNextPoll();
    elapsedTimer = setInterval(() => { now = Date.now(); }, 1000);
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
    if (elapsedTimer) clearInterval(elapsedTimer);
  });

  // Sort interaction
  function onLabelDblClick(colKey) {
    const idx = sortLevels.findIndex((l) => l.column === colKey);
    if (idx >= 0) {
      sortLevels = sortLevels.filter((_, i) => i !== idx);
    } else if (sortLevels.length < MAX_SORT_LEVELS) {
      sortLevels = [...sortLevels, { column: colKey, direction: 'asc' }];
    } else {
      flash(`Massimo ${MAX_SORT_LEVELS} livelli di sort.`, 'error');
      return;
    }
    refresh();
  }
  function onIndicatorClick(colKey) {
    const idx = sortLevels.findIndex((l) => l.column === colKey);
    if (idx < 0) return;
    sortLevels = sortLevels.map((l, i) => i === idx
      ? { ...l, direction: l.direction === 'asc' ? 'desc' : 'asc' } : l);
    refresh();
  }
  function resetSort() {
    if (sortLevels.length === 0) return;
    sortLevels = [];
    refresh();
  }
  function applyQuery() {
    appliedQuery = rowQuery;
    refresh();
  }
  function resetQuery() {
    if (!rowQuery && !appliedQuery) return;
    rowQuery = '';
    appliedQuery = '';
    refresh();
  }

  // Selection helpers
  function toggleSel(id) {
    if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    selected = selected;
  }
  function selectAllVisible() {
    selected = new Set(runs.map((r) => r.id));
  }
  function clearSelection() { selected = new Set(); }

  async function killRun(r) {
    if (!confirm(`Interrompere run #${r.id} (${r.kind})?`)) return;
    try {
      await api.post('/api/optimize/runs/' + r.id + '/cancel', {});
      flash(`Run #${r.id} richiesta cancellazione`, 'success');
      await refresh({ silent: true });
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  // Per-row + bulk delete. If the user clicks "Elimina" on a row
  // that's part of a multi-selection, we ask whether they meant the
  // whole batch or just that one row.
  async function deleteRun(r) {
    const isPartOfBatch = selected.size > 1 && selected.has(r.id);
    if (isPartOfBatch) {
      const ans = confirm(
        `Eliminare TUTTI i ${selected.size} run selezionati?\n\n`
        + `(annulla -> elimina solo run #${r.id})`
      );
      if (ans) return bulkDelete([...selected]);
      // user said "no" -> just this one
    }
    if (r.status === 'running' || r.status === 'pending') {
      flash('Run ancora attivo: non si puo\' eliminare.', 'error');
      return;
    }
    if (!confirm(`Eliminare run #${r.id} (${r.kind})?`)) return;
    try {
      await api.del('/api/optimize/runs/' + r.id);
      flash('Run eliminato.', 'success');
      selected.delete(r.id); selected = selected;
      await refresh();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
  }

  async function bulkDelete(ids) {
    if (!ids || ids.length === 0) return;
    if (!confirm(`Eliminare ${ids.length} run selezionati?`)) return;
    try {
      const r = await api.post('/api/optimize/runs/delete-batch',
                                { run_ids: ids });
      let msg = `${r.deleted} run eliminati.`;
      if (r.skipped_active && r.skipped_active.length) {
        msg += ` ${r.skipped_active.length} ancora attivi non sono `
              + 'stati toccati.';
      }
      flash(msg, 'success');
      clearSelection();
      await refresh();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
  }

  // Display helpers
  function semaforo(status) {
    if (status === 'done') return { cls: 'pill-green', label: '✓ success' };
    if (status === 'failed') return { cls: 'pill-red',   label: '✗ error' };
    if (status === 'running') return { cls: 'pill-blue', label: '● running' };
    return { cls: 'pill', label: status };
  }
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
  function toggle(id) {
    if (expanded.has(id)) expanded.delete(id);
    else expanded.add(id);
    expanded = expanded;
  }
</script>

<div class="space-y-4" data-testid="runs-page">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1 class="flex items-center gap-2"><DecorIcon name="trophy" size={26} class="shrink-0" /> Runs</h1>
    <span class="text-sm text-ink-500">{runs.length} run nel dataset</span>
    <button class="btn !text-xs ml-auto" on:click={refresh} disabled={busy}
            data-testid="runs-refresh-btn">
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
    Storia di ogni esecuzione (mock-import, Phase A, Phase B,
    metaeuristiche, classroom-assignment, place-event). Doppio click su
    un'intestazione di colonna per aggiungerla al sort (max 3 livelli);
    click sulla freccia per invertire la direzione. Query DSL come nelle
    altre tab. Selezionando piu' righe ed eliminando, il delete si
    applica a tutto il batch.
  </p>

  <!-- Query bar -->
  <div class="card p-3 flex flex-wrap gap-2 items-end">
    <div class="flex-1 min-w-64">
      <label class="text-xs text-ink-500">Query</label>
      <input class="w-full px-2 py-1.5 rounded-md border border-ink-200 font-mono text-sm"
             placeholder="es. tipo = phase_b AND stato = done, errore contains Timeout"
             bind:value={rowQuery}
             on:keydown={(e) => { if (e.key === 'Enter') applyQuery(); }}/>
    </div>
    <button class="btn" on:click={applyQuery} disabled={busy}>
      {busy ? '...' : 'Cerca'}
    </button>
    <button class="btn !text-xs"
            on:click={() => (showHelp = !showHelp)}>?  guida</button>
    <span class="border-l border-ink-200 h-6 mx-1"></span>
    <button class="btn !text-xs" on:click={resetQuery}
            disabled={!rowQuery && !appliedQuery}>Reset query</button>
    <button class="btn !text-xs" on:click={resetSort}
            disabled={sortLevels.length === 0}>Reset sort</button>
  </div>

  {#if queryError}
    <div class="card p-2 text-xs text-red-700 bg-red-50 border-red-300">
      Errore query: {queryError}
    </div>
  {/if}

  {#if sortLevels.length > 0}
    <div class="card p-2 text-xs flex flex-wrap items-center gap-2 bg-accent-500/5 border-accent-500/30">
      <span class="text-ink-500">Sort attivo:</span>
      {#each sortLevels as l, i}
        <span class="pill pill-blue">{i + 1}. {l.column}
          {l.direction === 'asc' ? '▲' : '▼'}</span>
      {/each}
    </div>
  {/if}

  {#if showHelp}
    <div class="card p-3 text-xs space-y-1 bg-ink-50">
      <div><strong>Operatori:</strong>
        <code>= != &lt; &lt;= &gt; &gt;= contains startswith endswith in [...]</code></div>
      <div><strong>Logica:</strong> <code>AND</code> / <code>OR</code> / parentesi.</div>
      <div><strong>Campi:</strong>
        <code>id, kind/tipo, name/nome, profile/profilo, status/stato,
              progress, obj_value/obj, solution_id, started_at,
              finished_at, error/errore</code></div>
      <div><strong>Esempi:</strong>
        <ul class="list-disc list-inside">
          <li><code>stato = done</code></li>
          <li><code>tipo = phase_b AND obj &lt; 1000</code></li>
          <li><code>errore contains Timeout</code></li>
          <li><code>kind in [lns, sa, ts, ils]</code></li>
        </ul></div>
    </div>
  {/if}

  <!-- Bulk toolbar -->
  {#if selected.size > 0}
    <div class="card p-2 bg-accent-500/5 border-accent-500/30 flex items-center gap-2 flex-wrap">
      <span class="pill pill-blue">{selected.size} selezionati</span>
      <button class="btn !text-xs" on:click={clearSelection}>
        Deseleziona
      </button>
      <button class="btn-red !text-xs"
              on:click={() => bulkDelete([...selected])}>
        Elimina selezionati
      </button>
    </div>
  {/if}

  <div class="card p-2 overflow-x-auto">
    <table class="tbl text-xs w-full">
      <thead>
        <tr>
          <th class="w-6 text-center">
            <input type="checkbox"
                   checked={runs.length > 0 && selected.size === runs.length}
                   on:click={(e) => e.target.checked
                                      ? selectAllVisible()
                                      : clearSelection()}/>
          </th>
          {#each COLS as c}
            {@const idx = sortLevels.findIndex((l) => l.column === c.key)}
            {@const dir = idx >= 0 ? sortLevels[idx].direction : null}
            <th class="select-none">
              <span class="inline-flex items-center gap-1">
                <button class="hover:text-accent-500 cursor-pointer
                               underline decoration-dotted decoration-ink-300"
                        title="Doppio click per aggiungere/rimuovere dal sort"
                        on:dblclick={() => onLabelDblClick(c.key)}>
                  {c.label}
                </button>
                {#if dir}
                  <button class="text-[10px] text-accent-500"
                          title="Inverti direzione"
                          on:click|stopPropagation={() => onIndicatorClick(c.key)}>
                    {dir === 'asc' ? '▲' : '▼'}
                  </button>
                  {#if sortLevels.length > 1}
                    <span class="text-[9px] bg-accent-500 text-white rounded-full
                                 w-4 h-4 inline-flex items-center justify-center">
                      {idx + 1}
                    </span>
                  {/if}
                {/if}
              </span>
            </th>
          {/each}
          <th>Durata</th>
          <th>Metriche</th>
          <th class="text-right">Azioni</th>
        </tr>
      </thead>
      <tbody>
        {#if runs.length === 0}
          <tr><td colspan="12" class="text-center text-ink-400 italic py-6">
            Nessun run. Lancia un'ottimizzazione dal Workflow o dal
            Monitor (Piazza).
          </td></tr>
        {/if}
        {#each runs as r (r.id)}
          {@const sem = semaforo(r.status)}
          <tr class="hover:bg-ink-50"
              class:bg-blue-50={selected.has(r.id)}>
            <td class="w-6 text-center">
              <input type="checkbox" checked={selected.has(r.id)}
                     on:click|stopPropagation={() => toggleSel(r.id)}/>
            </td>
            <td class="text-ink-400 cursor-pointer"
                on:click={() => toggle(r.id)}>
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
                <div class="w-32 h-2 rounded bg-ink-100 overflow-hidden">
                  <div class="h-full transition-[width] duration-300 ease-out"
                       class:bg-emerald-500={r.status === 'done'}
                       class:bg-red-500={r.status === 'failed'}
                       class:bg-accent-500={r.status === 'running'
                                              || r.status === 'pending'}
                       style="width: {Math.round((r.progress || 0) * 100)}%">
                  </div>
                </div>
                <span class="text-[10px] text-ink-500 tabular-nums">
                  {Math.round((r.progress || 0) * 100)}%
                </span>
                {#if r.current_step
                      && (r.status === 'running' || r.status === 'pending')}
                  <div class="text-[10px] text-accent-700 italic mt-0.5
                              max-w-[180px] truncate"
                       title={pipelineStepLabel(r.current_step)}>
                    in corso: {pipelineStepLabel(r.current_step)}
                  </div>
                {:else if r.current_step && r.status === 'failed'}
                  <div class="text-[10px] text-red-700 italic mt-0.5
                              max-w-[180px] truncate"
                       title={'Fallito durante: '
                               + pipelineStepLabel(r.current_step)}>
                    fallito su: {pipelineStepLabel(r.current_step)}
                  </div>
                {/if}
              {/if}
            </td>
            <td class="text-[10px]">{fmtTime(r.started_at)}</td>
            <td class="text-right">{r.obj_value ?? ''}</td>
            <td class="text-[10px]">{r.solution_id ?? ''}</td>
            <td class="text-[10px]">{elapsed(r, now)}</td>
            <td class="text-[10px] text-ink-500">
              {r.metrics
                ? Object.entries(r.metrics).slice(0, 4)
                    .map(([k, v]) => `${k}=${v}`).join(' · ')
                : ''}
            </td>
            <td class="whitespace-nowrap text-right">
              <a class="btn !text-[10px] !px-2 !py-0.5 mr-1"
                 href={'/runs/' + r.id}
                 on:click|stopPropagation
                 title="Apri il dettaglio con grafico objective e telemetria">
                detail
              </a>
              <button class="btn !text-[10px] !px-2 !py-0.5"
                      on:click|stopPropagation={() => (logFor = logFor === r.id ? null : r.id)}>
                {logFor === r.id ? 'nascondi log' : 'log'}
              </button>
              {#if r.status === 'running' || r.status === 'pending'}
                <button class="btn-red !text-[10px] !px-2 !py-0.5 ml-1"
                        on:click|stopPropagation={() => killRun(r)}
                        title="Interrompi questo run">
                  Kill
                </button>
              {:else}
                <button class="btn-red !text-[10px] !px-2 !py-0.5 ml-1"
                        on:click|stopPropagation={() => deleteRun(r)}
                        title="Elimina questo run (o tutti i selezionati)">
                  Elimina
                </button>
              {/if}
            </td>
          </tr>
          {#if expanded.has(r.id)}
            <tr style="background-color:#f9fafb;">
              <td colspan="12" class="p-3">
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
              <td colspan="12" class="p-3">
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
