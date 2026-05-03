<script>
  /**
   * /diagnostics tab.
   *
   * Hall pre-check is SYNC and renders inline.
   *
   * The other 4 analyses (Monte Carlo, bipartite, correlations,
   * distributions) are spawned as ASYNC RUNS that show up in the
   * /runs tab. This page polls each pending run until done and
   * then renders the result beneath its corresponding section.
   *
   * Each section also exposes the run_id as a link to /runs/[id]
   * so the user can navigate to the dedicated detail view.
   */
  import { onDestroy, onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import EChart from '$lib/components/EChart.svelte';
  import DiagnosticResult from
    '$lib/components/diagnostics/DiagnosticResult.svelte';

  // ---- Hall (now async, like the others) ----
  let hallSamples = 256;
  let hl = _emptyDiag();   // hall is just another async run now

  // ---- Async diagnostic runs ----
  // Each section keeps {runId, status, busy, result}. busy stays true
  // while either spawning or polling; result is the dict from
  // run.metrics once status='done'.
  function _emptyDiag() {
    return { runId: null, status: null, busy: false, result: null,
              error: null };
  }
  let mc = _emptyDiag();
  let bp = _emptyDiag();
  let co = _emptyDiag();
  let ds = _emptyDiag();

  // ---- Per-kind run history (DB-backed) ----
  // Each completed diagnostic run lives in the `runs` table with
  // its full `metrics_json` (the result dict). We fetch them on
  // mount and re-fetch when a new run finishes, so the history
  // travels with the SQLite database (export/import via Dashboard
  // carries it along automatically).
  const KIND_FOR = { mc: 'diag_montecarlo', bp: 'diag_bipartite',
                     co: 'diag_correlations', ds: 'diag_distributions' };
  let mcHistory = [];
  let bpHistory = [];
  let coHistory = [];
  let dsHistory = [];

  async function _fetchHistory(kind) {
    const dbKind = KIND_FOR[kind];
    if (!dbKind) return [];
    try {
      const q = `kind = ${dbKind} AND status = done`;
      const rows = await api.get(
        '/api/optimize/runs?limit=100&q=' + encodeURIComponent(q));
      return (rows || [])
        .filter((r) => r.metrics && Object.keys(r.metrics).length > 0)
        .map((r) => ({
          runId: r.id,
          when: r.finished_at || r.started_at || r.created_at,
          params: r.params || {},
          result: r.metrics,
        }));
    } catch { return []; }
  }

  async function reloadHistory(kind) {
    const list = await _fetchHistory(kind);
    if (kind === 'mc') mcHistory = list;
    else if (kind === 'bp') bpHistory = list;
    else if (kind === 'co') coHistory = list;
    else if (kind === 'ds') dsHistory = list;
  }
  async function clearHistory(kind) {
    const lists = { mc: mcHistory, bp: bpHistory,
                    co: coHistory, ds: dsHistory };
    const ids = (lists[kind] || []).map((e) => e.runId);
    if (ids.length === 0) return;
    if (!confirm(`Eliminare ${ids.length} run dalla cronologia?
Le righe verranno rimosse dalla tabella runs del database.`)) return;
    try {
      await api.post('/api/optimize/runs/delete-batch', { run_ids: ids });
      await reloadHistory(kind);
      flash(`Cronologia ${kind}: eliminati ${ids.length} run`, 'success');
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
  }
  async function deleteHistoryEntry(kind, runId) {
    try {
      await api.del('/api/optimize/runs/' + runId);
      await reloadHistory(kind);
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
  }
  function _formatTime(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleString('it-IT', {
        day: '2-digit', month: '2-digit', hour: '2-digit',
        minute: '2-digit',
      });
    } catch { return iso; }
  }

  let mcN = 100;
  let mcSeed = 0;
  let bpMode = 'classes';

  // Correlations: variable picker + custom models spec.
  // `coVariables` is loaded once from
  // /api/diagnostics/correlations/variables and drives the
  // dropdowns. `coModels` is the list the user composes; if empty
  // the backend uses the default 3-model panel.
  let coVariables = null;       // {scopes, variables_by_scope}
  let coModels = [];            // user-composed list
  function _newModel() {
    return { kind: 'ols', scope: 'teachers',
              x: 'teacher_hours', y: 'teacher_gap_count',
              label: '' };
  }

  async function loadCoVariables() {
    if (coVariables) return;
    try {
      coVariables = await api.get('/api/diagnostics/correlations/variables');
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  // Distributions: catalog from /api/diagnostics/distributions/menu.
  // dsSelected: array of distribution keys to include (empty = all).
  // dsParams:   per-key param values (typed: number for int, string CSV).
  let dsCatalog = null;          // {distributions: [{key, label, params: [...]}]}
  let dsSelected = [];           // [] = all
  let dsParams = {};             // {dist_key: {param_key: value}}

  async function loadDsCatalog() {
    if (dsCatalog) return;
    try {
      dsCatalog = await api.get('/api/diagnostics/distributions/menu');
      // Initialize params with defaults for each (so the user can
      // tweak without first ticking the box)
      const defaults = {};
      for (const d of dsCatalog.distributions || []) {
        defaults[d.key] = {};
        for (const p of d.params || []) {
          defaults[d.key][p.key] = p.default ?? '';
        }
      }
      dsParams = defaults;
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }
  function toggleDsKind(key) {
    if (dsSelected.includes(key)) {
      dsSelected = dsSelected.filter((k) => k !== key);
    } else {
      dsSelected = [...dsSelected, key];
    }
  }
  function addCoModel() {
    coModels = [...coModels, _newModel()];
  }
  function removeCoModel(i) {
    coModels = coModels.filter((_, j) => j !== i);
  }
  // When the scope of a row changes, reset x/y to defaults of that
  // scope (otherwise old keys may not exist on the new scope).
  function onCoScopeChange(i) {
    const m = { ...coModels[i] };
    const vars = (coVariables?.variables_by_scope?.[m.scope] || []);
    if (vars.length >= 2) {
      m.x = vars[0].key;
      m.y = vars[1].key;
    }
    coModels = coModels.map((mm, j) => j === i ? m : mm);
  }

  // ---- Polling ----
  let pollTimers = new Map();   // run_id -> setInterval handle
  onDestroy(() => {
    for (const t of pollTimers.values()) clearInterval(t);
    pollTimers.clear();
  });

  // Eagerly load the variable + distribution menus so the user can
  // compose a model the moment they click on the section.
  onMount(() => {
    loadCoVariables();
    loadDsCatalog();
    // Fetch the per-kind run history from the database. Travels
    // with the SQLite file: when Giovanni imports a different DB,
    // the history switches with it.
    Promise.all([reloadHistory('mc'), reloadHistory('bp'),
                 reloadHistory('co'), reloadHistory('ds')]);
  });

  async function _pollRun(runId, onUpdate) {
    try {
      const r = await api.get('/api/optimize/runs/' + runId);
      onUpdate(r);
      if (r.status === 'done' || r.status === 'failed') {
        const t = pollTimers.get(runId);
        if (t) { clearInterval(t); pollTimers.delete(runId); }
      }
    } catch { /* swallow transient poll errors */ }
  }

  function _startPolling(runId, onUpdate) {
    if (pollTimers.has(runId)) return;
    // Immediate first probe + 1s pulse
    _pollRun(runId, onUpdate);
    const t = setInterval(() => _pollRun(runId, onUpdate), 1000);
    pollTimers.set(runId, t);
  }

  // ---- Spawn helpers ----
  async function spawnRun(endpoint, body, target, onUpdate) {
    target.busy = true;
    target.status = null;
    target.result = null;
    target.error = null;
    try {
      const r = await api.post(endpoint, body);
      target.runId = r.run_id;
      target.status = 'pending';
      _startPolling(r.run_id, (run) => {
        target.status = run.status;
        if (run.status === 'done') {
          target.busy = false;
          target.result = run.metrics || null;
          onUpdate?.(run);
          // Refresh the per-kind history from the DB so the new
          // run appears in the cronologia immediately. Hall is a
          // structural diagnostic with no archived chart, so we
          // skip it here.
          let kind = null;
          if (target === mc) kind = 'mc';
          else if (target === bp) kind = 'bp';
          else if (target === co) kind = 'co';
          else if (target === ds) kind = 'ds';
          if (kind) reloadHistory(kind);
        } else if (run.status === 'failed') {
          target.busy = false;
          target.error = run.error || 'run failed';
        }
        // Force reactivity (assignment to its own ref)
        if (target === hl) hl = hl;
        else if (target === mc) mc = mc;
        else if (target === bp) bp = bp;
        else if (target === co) co = co;
        else if (target === ds) ds = ds;
      });
    } catch (e) {
      target.busy = false;
      target.error = e.message;
      flash('Errore: ' + e.message, 'error');
    }
    // Force reactivity
    if (target === hl) hl = hl;
    else if (target === mc) mc = mc;
    else if (target === bp) bp = bp;
    else if (target === co) co = co;
    else if (target === ds) ds = ds;
  }

  // ---- Run handlers ----
  const runHall = () => spawnRun(
    '/api/diagnostics/hall-check',
    { n_samples: hallSamples },     // omits `sync:true` -> async
    hl,
  );

  const runMc = () => spawnRun(
    '/api/diagnostics/montecarlo',
    { n_samples: mcN, seed: mcSeed },
    mc,
  );
  const runBp = () => spawnRun(
    '/api/diagnostics/bipartite',
    { mode: bpMode },
    bp,
  );
  const runCo = () => spawnRun(
    '/api/diagnostics/correlations',
    coModels.length ? { models: coModels } : {},
    co,
  );
  const runDs = () => {
    // Only send a body if the user actually picked something or
    // changed any param; an empty payload triggers the full
    // default behaviour (back-compat).
    const body = {};
    if (dsSelected.length) body.include = dsSelected;
    if (dsParams && Object.keys(dsParams).length) {
      // Filter out empty CSV params
      const cleaned = {};
      for (const [k, v] of Object.entries(dsParams)) {
        if (v && Object.keys(v).length) cleaned[k] = v;
      }
      if (Object.keys(cleaned).length) body.params = cleaned;
    }
    return spawnRun('/api/diagnostics/distributions', body, ds);
  };

  // ---- ECharts option builders ----
  // Pure functions: take a `result` and return the option dict.
  // Allows us to render the same chart for both the live "current"
  // result and for any past entry in the history (see below).
  function mcHistogramOptionFor(result) {
    if (!result || !result.ok) return {};
    return {
      title: { text: 'SOFT - distribuzione Monte Carlo' },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category',
               data: result.samples.map((_, i) => i + 1), name: 'sample' },
      yAxis: { type: 'value', name: 'SOFT' },
      series: [{
        type: 'bar',
        data: result.samples,
        markLine: {
          data: [
            { yAxis: result.mean, name: 'media',
              lineStyle: { color: '#3f3d8e' } },
            { yAxis: result.base_val, name: 'base',
              lineStyle: { color: '#a04425', type: 'dashed' } },
          ],
        },
      }],
    };
  }
  $: mcHistogramOption = mcHistogramOptionFor(mc.result);

  function dsTeacherOptionFor(result) {
    if (!result || !result.ok || !result.teacher_loads) return {};
    return {
      title: { text: 'Carico orario docenti' },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: result.teacher_loads.bin_edges
          .slice(0, -1)
          .map((e, i) => `${e.toFixed(0)}-${result.teacher_loads.bin_edges[i + 1].toFixed(0)}`),
        name: 'ore',
      },
      yAxis: { type: 'value', name: '# docenti' },
      series: [{ type: 'bar',
                 data: result.teacher_loads.bin_counts }],
    };
  }
  $: dsTeacherOption = dsTeacherOptionFor(ds.result);

  function dsHeatmapOptionFor(result) {
    if (!result || !result.ok || !result.subject_slot_heatmap) return {};
    const m = result.subject_slot_heatmap;
    return {
      title: { text: 'Materia x slot' },
      tooltip: { position: 'top' },
      grid: { left: '12%', right: '5%', bottom: '14%', top: '12%' },
      xAxis: { type: 'category', data: m.slots,
               splitArea: { show: true },
               axisLabel: { rotate: 60, fontSize: 8 } },
      yAxis: { type: 'category',
               data: m.matrix.map((r) => r.subject),
               splitArea: { show: true } },
      visualMap: {
        min: 0,
        max: Math.max(1, ...m.matrix.flatMap((r) => r.row)),
        calculable: true, orient: 'horizontal',
        left: 'center', bottom: '0%',
      },
      series: [{
        type: 'heatmap',
        data: m.matrix.flatMap((r, i) => r.row.map((v, j) => [j, i, v])),
        label: { show: false },
      }],
    };
  }
  $: dsHeatmapOption = dsHeatmapOptionFor(ds.result);

  function scatterOption(model) {
    if (!model || !model.scatter) return {};
    return {
      title: { text: model.label },
      tooltip: { trigger: 'item' },
      xAxis: { type: 'value' },
      yAxis: { type: 'value' },
      series: [{
        type: 'scatter',
        symbolSize: 8,
        data: model.scatter.map((p) => [p.x, p.y]),
      }],
    };
  }

  function statusPill(d) {
    if (!d.runId) return null;
    if (d.status === 'pending') return { cls: 'pill-blue', label: 'pending' };
    if (d.status === 'running') return { cls: 'pill-blue', label: 'running' };
    if (d.status === 'done') return { cls: 'pill-green', label: 'done' };
    if (d.status === 'failed') return { cls: 'pill-red', label: 'failed' };
    return null;
  }
</script>

<div class="space-y-6">
  <h1>Statistiche e diagnostica</h1>
  <p class="text-sm text-ink-500 max-w-3xl">
    Le analisi pesanti (Monte Carlo, bipartito, correlazioni,
    distribuzioni) vengono lanciate come <strong>run asincroni</strong>:
    compaiono nel tab <a href="/runs" class="text-accent-500 hover:underline">Runs</a>
    e il risultato torna qui sotto quando completato. Il pre-check
    Hall resta sincrono (&lt;100ms) per essere usato come
    "verde/rosso" prima di lanciare Phase A.
  </p>

  <!-- 1) Hall (async run, like the others) -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">1) Pre-check fattibilita' (Hall)</h2>
      <span class="pill !text-[10px]">async run</span>
      {#if statusPill(hl)}
        <span class="{statusPill(hl).cls} !text-[10px]">
          {statusPill(hl).label}
        </span>
        <a href="/runs/{hl.runId}" class="text-xs text-accent-500 hover:underline">
          run #{hl.runId}
        </a>
      {/if}
      <div class="ml-auto flex gap-2 items-end">
        <div class="field !mb-0">
          <label class="!text-[11px]">N campioni</label>
          <input type="number" min="32" max="1024"
                 bind:value={hallSamples} class="w-24"/>
        </div>
        <button class="btn-primary !text-xs" on:click={runHall}
                disabled={hl.busy}>
          {hl.busy ? '...' : 'Lancia Hall pre-check'}
        </button>
      </div>
    </div>
    {#if hl.error}
      <p class="text-xs text-rose-700">{hl.error}</p>
    {/if}
    {#if hl.result}
      <DiagnosticResult kind="diag_hall" result={hl.result}/>
    {/if}
  </section>

  <!-- 2) Monte Carlo (async run) -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">2) Sensitivity Monte Carlo</h2>
      <span class="pill !text-[10px]">async run</span>
      {#if statusPill(mc)}
        <span class="{statusPill(mc).cls} !text-[10px]">
          {statusPill(mc).label}
        </span>
        <a href="/runs/{mc.runId}" class="text-xs text-accent-500 hover:underline">
          run #{mc.runId}
        </a>
      {/if}
      <div class="ml-auto flex gap-2 items-end">
        <div class="field !mb-0">
          <label class="!text-[11px]">N campioni</label>
          <input type="number" min="10" max="500"
                 bind:value={mcN} class="w-20"/>
        </div>
        <div class="field !mb-0">
          <label class="!text-[11px]">Seed</label>
          <input type="number" bind:value={mcSeed} class="w-16"/>
        </div>
        <button class="btn-primary !text-xs" on:click={runMc}
                disabled={mc.busy}>
          {mc.busy ? '...' : 'Lancia analisi MC'}
        </button>
      </div>
    </div>
    {#if mc.error}
      <p class="text-xs text-rose-700">{mc.error}</p>
    {/if}
    {#if mc.result}
      {#if mc.result.ok}
        <div class="text-xs flex flex-wrap gap-3 text-ink-600">
          <span><strong>Base:</strong> {mc.result.base_val.toFixed(1)}</span>
          <span><strong>Media:</strong> {mc.result.mean.toFixed(1)}</span>
          <span><strong>Std:</strong> {mc.result.std.toFixed(1)}</span>
          <span><strong>CV:</strong> {(mc.result.coefficient_of_variation*100).toFixed(1)}%</span>
          <span><strong>p25:</strong> {mc.result.p25.toFixed(1)}</span>
          <span><strong>p50:</strong> {mc.result.p50.toFixed(1)}</span>
          <span><strong>p75:</strong> {mc.result.p75.toFixed(1)}</span>
        </div>
        <p class="text-xs text-ink-500 italic">{mc.result.interpretation}</p>
        <EChart option={mcHistogramOption} height={300}/>
      {:else}
        <p class="text-xs text-rose-700">{mc.result.msg}</p>
      {/if}
    {/if}
    {#if mcHistory.length > 0}
      <div class="border-t border-ink-200 pt-2 mt-2">
        <div class="flex items-baseline justify-between mb-1">
          <strong class="text-xs">Cronologia ({mcHistory.length})</strong>
          <button class="btn !text-[10px] !px-2 !py-0.5"
                  on:click={() => clearHistory('mc')}>Pulisci</button>
        </div>
        {#each mcHistory as h (h.runId)}
          <details class="border border-ink-200 rounded mb-1">
            <summary class="cursor-pointer px-2 py-1 text-xs flex
                            items-center gap-2 hover:bg-ink-50">
              <span class="pill !text-[10px]">run #{h.runId}</span>
              <span class="text-ink-500">{_formatTime(h.when)}</span>
              {#if h.result?.ok}
                <span class="text-ink-500">
                  media {h.result.mean.toFixed(1)},
                  std {h.result.std.toFixed(1)}
                </span>
              {:else}
                <span class="text-rose-700">errore</span>
              {/if}
              <button class="ml-auto btn !text-[10px] !px-1 !py-0"
                      title="Elimina dalla cronologia"
                      on:click|stopPropagation|preventDefault={() => deleteHistoryEntry('mc', h.runId)}>
                x
              </button>
            </summary>
            <div class="p-2">
              {#if h.result?.ok}
                <EChart option={mcHistogramOptionFor(h.result)}
                        height={260}
                        exportName={`mc_run_${h.runId}`}/>
              {:else}
                <p class="text-xs text-rose-700">
                  {h.result?.msg || 'risultato non disponibile'}
                </p>
              {/if}
            </div>
          </details>
        {/each}
      </div>
    {/if}
  </section>

  <!-- 3) Bipartite (async run) -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">3) Analisi bipartito</h2>
      <span class="pill !text-[10px]">async run</span>
      {#if statusPill(bp)}
        <span class="{statusPill(bp).cls} !text-[10px]">
          {statusPill(bp).label}
        </span>
        <a href="/runs/{bp.runId}" class="text-xs text-accent-500 hover:underline">
          run #{bp.runId}
        </a>
      {/if}
      <div class="ml-auto flex gap-2 items-end">
        <div class="field !mb-0">
          <label class="!text-[11px]">Mode</label>
          <select bind:value={bpMode}>
            <option value="classes">classes (nodi=classi)</option>
            <option value="teachers">teachers (nodi=docenti)</option>
          </select>
        </div>
        <button class="btn-primary !text-xs" on:click={runBp}
                disabled={bp.busy}>
          {bp.busy ? '...' : 'Analizza grafo'}
        </button>
      </div>
    </div>
    {#if bp.error}
      <p class="text-xs text-rose-700">{bp.error}</p>
    {/if}
    {#if bp.result && bp.result.ok}
      <div class="grid md:grid-cols-3 gap-3 text-sm">
        <div class="card !shadow-none p-3">
          <div class="text-3xl font-semibold">
            {bp.result.density.toFixed(3)}
          </div>
          <div class="text-xs text-ink-500">Densita'</div>
          <p class="text-[10px] text-ink-500 italic mt-1">
            {bp.result.density_interpretation}
          </p>
        </div>
        <div class="card !shadow-none p-3">
          <div class="text-3xl font-semibold">
            {bp.result.modularity.toFixed(3)}
          </div>
          <div class="text-xs text-ink-500">
            Modularita' ({bp.result.n_communities} comunita')
          </div>
          <p class="text-[10px] text-ink-500 italic mt-1">
            {bp.result.modularity_interpretation}
          </p>
        </div>
        <div class="card !shadow-none p-3">
          <div class="text-xs text-ink-500 mb-1">
            Top {bp.result.top_betweenness.length} nodi per betweenness
          </div>
          <ul class="text-xs space-y-0.5">
            {#each bp.result.top_betweenness as n, i}
              <li>
                <span class="text-ink-400">#{i + 1}</span>
                <span class="font-mono">{n.node}</span>
                = {n.betweenness.toFixed(3)}
              </li>
            {/each}
          </ul>
        </div>
      </div>
      <p class="text-[11px] text-ink-500">
        {bp.result.n_nodes} nodi, {bp.result.n_edges} archi.
      </p>
    {/if}
    {#if bpHistory.length > 0}
      <div class="border-t border-ink-200 pt-2 mt-2">
        <div class="flex items-baseline justify-between mb-1">
          <strong class="text-xs">Cronologia ({bpHistory.length})</strong>
          <button class="btn !text-[10px] !px-2 !py-0.5"
                  on:click={() => clearHistory('bp')}>Pulisci</button>
        </div>
        {#each bpHistory as h (h.runId)}
          <details class="border border-ink-200 rounded mb-1">
            <summary class="cursor-pointer px-2 py-1 text-xs flex
                            items-center gap-2 hover:bg-ink-50">
              <span class="pill !text-[10px]">run #{h.runId}</span>
              <span class="text-ink-500">{_formatTime(h.when)}</span>
              <span class="text-ink-500">
                mode {h.params?.mode || 'classes'}
                {#if h.result?.modularity !== undefined}
                  -- mod {h.result.modularity.toFixed(3)}
                {/if}
              </span>
              <button class="ml-auto btn !text-[10px] !px-1 !py-0"
                      title="Elimina dalla cronologia"
                      on:click|stopPropagation|preventDefault={() => deleteHistoryEntry('bp', h.runId)}>
                x
              </button>
            </summary>
            <div class="p-2">
              <DiagnosticResult kind="diag_bipartite" result={h.result}/>
            </div>
          </details>
        {/each}
      </div>
    {/if}
  </section>

  <!-- 4) Correlations (async run, parametrizable) -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">4) Correlazioni e regressioni</h2>
      <span class="pill !text-[10px]">async run</span>
      {#if statusPill(co)}
        <span class="{statusPill(co).cls} !text-[10px]">
          {statusPill(co).label}
        </span>
        <a href="/runs/{co.runId}" class="text-xs text-accent-500 hover:underline">
          run #{co.runId}
        </a>
      {/if}
      <button class="btn-primary !text-xs ml-auto" on:click={runCo}
              disabled={co.busy}>
        {co.busy ? '...' : (coModels.length === 0
                              ? 'Calcola (3 modelli default)'
                              : `Calcola (${coModels.length} modell${coModels.length === 1 ? 'o' : 'i'} custom)`)}
      </button>
    </div>

    <!-- Variable picker / model builder -->
    <details class="border border-ink-200 rounded p-2 bg-ink-50/40">
      <summary class="cursor-pointer text-xs font-medium">
        Personalizza modelli ({coModels.length} custom configurat{coModels.length === 1 ? 'o' : 'i'})
      </summary>
      <p class="text-[11px] text-ink-500 mt-1 mb-2">
        Se la lista qui sotto e' vuota, vengono calcolati i 3 modelli
        canonici (carico vs buchi, materie vs SOFT, saturazione vs 6a
        ora). Aggiungi righe per scegliere altre x/y, OLS o Logit, scope
        teachers o classes.
      </p>

      {#if !coVariables}
        <p class="text-[11px] text-ink-500 italic">
          Caricamento variabili...
        </p>
      {:else}
        <table class="tbl text-xs">
          <thead>
            <tr>
              <th>Tipo</th>
              <th>Scope</th>
              <th>x (predittore)</th>
              <th>y (dipendente)</th>
              <th>Etichetta (opzionale)</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {#each coModels as m, i}
              <tr>
                <td>
                  <select class="px-1 py-0.5 border border-ink-200 rounded"
                          bind:value={m.kind}>
                    <option value="ols">OLS (lineare)</option>
                    <option value="logit">Logit (binaria)</option>
                  </select>
                </td>
                <td>
                  <select class="px-1 py-0.5 border border-ink-200 rounded"
                          bind:value={m.scope}
                          on:change={() => onCoScopeChange(i)}>
                    {#each coVariables.scopes as s}
                      <option value={s}>{s}</option>
                    {/each}
                  </select>
                </td>
                <td>
                  <select class="px-1 py-0.5 border border-ink-200 rounded"
                          bind:value={m.x}>
                    {#each (coVariables.variables_by_scope[m.scope] || []) as v}
                      <option value={v.key}>{v.label} ({v.type})</option>
                    {/each}
                  </select>
                </td>
                <td>
                  <select class="px-1 py-0.5 border border-ink-200 rounded"
                          bind:value={m.y}>
                    {#each (coVariables.variables_by_scope[m.scope] || []) as v}
                      <option value={v.key}>{v.label} ({v.type})</option>
                    {/each}
                  </select>
                </td>
                <td>
                  <input class="px-1 py-0.5 border border-ink-200 rounded w-full"
                         placeholder="(auto)"
                         bind:value={m.label}/>
                </td>
                <td>
                  <button class="btn-red !text-[10px] !px-1 !py-0.5"
                          on:click={() => removeCoModel(i)}>x</button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <button class="btn !text-xs mt-2" on:click={addCoModel}>
          + Aggiungi modello
        </button>
        {#if coModels.length}
          <button class="btn !text-xs ml-2"
                  on:click={() => (coModels = [])}>
            Svuota (usa 3 default)
          </button>
        {/if}
      {/if}
    </details>

    {#if co.error}
      <p class="text-xs text-rose-700">{co.error}</p>
    {/if}
    {#if co.result}
      <DiagnosticResult kind="diag_correlations" result={co.result}/>
    {/if}
    {#if coHistory.length > 0}
      <div class="border-t border-ink-200 pt-2 mt-2">
        <div class="flex items-baseline justify-between mb-1">
          <strong class="text-xs">Cronologia ({coHistory.length})</strong>
          <button class="btn !text-[10px] !px-2 !py-0.5"
                  on:click={() => clearHistory('co')}>Pulisci</button>
        </div>
        {#each coHistory as h (h.runId)}
          <details class="border border-ink-200 rounded mb-1">
            <summary class="cursor-pointer px-2 py-1 text-xs flex
                            items-center gap-2 hover:bg-ink-50">
              <span class="pill !text-[10px]">run #{h.runId}</span>
              <span class="text-ink-500">{_formatTime(h.when)}</span>
              <span class="text-ink-500">
                {h.result?.models?.length || 0} modell{(h.result?.models?.length || 0) === 1 ? 'o' : 'i'}
              </span>
              <button class="ml-auto btn !text-[10px] !px-1 !py-0"
                      title="Elimina dalla cronologia"
                      on:click|stopPropagation|preventDefault={() => deleteHistoryEntry('co', h.runId)}>
                x
              </button>
            </summary>
            <div class="p-2">
              <DiagnosticResult kind="diag_correlations" result={h.result}/>
            </div>
          </details>
        {/each}
      </div>
    {/if}
  </section>

  <!-- 5) Distributions (async run, parametrizable) -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">5) Distribuzioni</h2>
      <span class="pill !text-[10px]">async run</span>
      {#if statusPill(ds)}
        <span class="{statusPill(ds).cls} !text-[10px]">
          {statusPill(ds).label}
        </span>
        <a href="/runs/{ds.runId}" class="text-xs text-accent-500 hover:underline">
          run #{ds.runId}
        </a>
      {/if}
      <button class="btn-primary !text-xs ml-auto" on:click={runDs}
              disabled={ds.busy}>
        {ds.busy ? '...' : (dsSelected.length === 0
                              ? 'Calcola tutte (default)'
                              : `Calcola (${dsSelected.length} selezionat${dsSelected.length === 1 ? 'a' : 'e'})`)}
      </button>
    </div>

    <!-- Distribution picker / param editor -->
    <details class="border border-ink-200 rounded p-2 bg-ink-50/40">
      <summary class="cursor-pointer text-xs font-medium">
        Personalizza distribuzioni
        ({dsSelected.length === 0 ? 'tutte di default' :
          `${dsSelected.length} ticked`})
      </summary>
      <p class="text-[11px] text-ink-500 mt-1 mb-2">
        Tickera le distribuzioni da calcolare (vuoto = tutte). I
        parametri sotto ciascuna sono usati solo se la
        distribuzione e' inclusa.
      </p>
      {#if !dsCatalog}
        <p class="text-[11px] text-ink-500 italic">
          Caricamento menu...
        </p>
      {:else}
        <div class="space-y-2">
          {#each dsCatalog.distributions as d (d.key)}
            <div class="border border-ink-200 rounded p-2 bg-white">
              <label class="flex items-center gap-2 text-xs font-medium cursor-pointer">
                <input type="checkbox"
                       checked={dsSelected.includes(d.key)}
                       on:change={() => toggleDsKind(d.key)}/>
                {d.label}
                <code class="text-ink-400 text-[10px]">{d.key}</code>
              </label>
              {#if d.params && d.params.length}
                <div class="grid grid-cols-2 md:grid-cols-3 gap-2 mt-1 text-xs">
                  {#each d.params as p (p.key)}
                    <div>
                      <label class="block text-[10px] text-ink-500">
                        {p.label}
                        <span class="text-ink-400">({p.type})</span>
                      </label>
                      {#if p.type === 'int'}
                        <input type="number"
                               class="w-full px-1 py-0.5 border border-ink-200 rounded"
                               min={p.min} max={p.max}
                               bind:value={dsParams[d.key][p.key]}/>
                      {:else}
                        <input type="text"
                               class="w-full px-1 py-0.5 border border-ink-200 rounded"
                               placeholder={p.default || ''}
                               bind:value={dsParams[d.key][p.key]}/>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
        </div>
        <div class="mt-2 flex gap-2">
          <button class="btn !text-xs"
                  on:click={() => (dsSelected = (dsCatalog.distributions || []).map((d) => d.key))}>
            Tutto
          </button>
          <button class="btn !text-xs"
                  on:click={() => (dsSelected = [])}>
            Nessuna (-> default)
          </button>
        </div>
      {/if}
    </details>

    {#if ds.error}
      <p class="text-xs text-rose-700">{ds.error}</p>
    {/if}
    {#if ds.result && ds.result.ok}
      <div class="grid md:grid-cols-2 gap-4">
        {#if ds.result.teacher_loads}
          <EChart option={dsTeacherOption} height={280}
                  exportName="distrib_teacher_loads"/>
        {/if}
        {#if ds.result.subject_slot_heatmap}
          <EChart option={dsHeatmapOption} height={280}
                  exportName="distrib_subject_slot_heatmap"/>
        {/if}
      </div>
      {#if ds.result.tests}
        <div class="text-xs text-ink-600 space-y-1 mt-2">
          {#each Object.entries(ds.result.tests) as [name, t]}
            <div>
              <strong>{name}:</strong>
              statistica = {t.statistic.toFixed(3)},
              p-value = {t.p_value.toFixed(3)} -
              <em>{t.interpretation}</em>
            </div>
          {/each}
        </div>
      {/if}
    {/if}
    {#if dsHistory.length > 0}
      <div class="border-t border-ink-200 pt-2 mt-2">
        <div class="flex items-baseline justify-between mb-1">
          <strong class="text-xs">Cronologia ({dsHistory.length})</strong>
          <button class="btn !text-[10px] !px-2 !py-0.5"
                  on:click={() => clearHistory('ds')}>Pulisci</button>
        </div>
        {#each dsHistory as h (h.runId)}
          <details class="border border-ink-200 rounded mb-1">
            <summary class="cursor-pointer px-2 py-1 text-xs flex
                            items-center gap-2 hover:bg-ink-50">
              <span class="pill !text-[10px]">run #{h.runId}</span>
              <span class="text-ink-500">{_formatTime(h.when)}</span>
              <span class="text-ink-500">
                {#if h.result?.teacher_loads}carico docenti{/if}
                {#if h.result?.teacher_loads && h.result?.subject_slot_heatmap} + {/if}
                {#if h.result?.subject_slot_heatmap}heatmap materia/slot{/if}
              </span>
              <button class="ml-auto btn !text-[10px] !px-1 !py-0"
                      title="Elimina dalla cronologia"
                      on:click|stopPropagation|preventDefault={() => deleteHistoryEntry('ds', h.runId)}>
                x
              </button>
            </summary>
            <div class="p-2">
              {#if h.result?.ok}
                <div class="grid md:grid-cols-2 gap-4">
                  {#if h.result.teacher_loads}
                    <EChart option={dsTeacherOptionFor(h.result)}
                            height={260}
                            exportName={`distrib_teacher_loads_run_${h.runId}`}/>
                  {/if}
                  {#if h.result.subject_slot_heatmap}
                    <EChart option={dsHeatmapOptionFor(h.result)}
                            height={260}
                            exportName={`distrib_subject_slot_heatmap_run_${h.runId}`}/>
                  {/if}
                </div>
                {#if h.result.tests}
                  <div class="text-xs text-ink-600 space-y-1 mt-2">
                    {#each Object.entries(h.result.tests) as [name, t]}
                      <div>
                        <strong>{name}:</strong>
                        statistica = {t.statistic.toFixed(3)},
                        p-value = {t.p_value.toFixed(3)} -
                        <em>{t.interpretation}</em>
                      </div>
                    {/each}
                  </div>
                {/if}
              {:else}
                <p class="text-xs text-rose-700">
                  {h.result?.msg || 'risultato non disponibile'}
                </p>
              {/if}
            </div>
          </details>
        {/each}
      </div>
    {/if}
  </section>
</div>
