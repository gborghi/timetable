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
  import { onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import EChart from '$lib/components/EChart.svelte';

  // ---- Hall (sync) ----
  let busyHall = false;
  let hallReport = null;
  let hallSamples = 256;

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

  let mcN = 100;
  let mcSeed = 0;
  let bpMode = 'classes';

  // ---- Polling ----
  let pollTimers = new Map();   // run_id -> setInterval handle
  onDestroy(() => {
    for (const t of pollTimers.values()) clearInterval(t);
    pollTimers.clear();
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
        } else if (run.status === 'failed') {
          target.busy = false;
          target.error = run.error || 'run failed';
        }
        // Force reactivity (assignment to its own ref)
        if (target === mc) mc = mc;
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
    if (target === mc) mc = mc;
    else if (target === bp) bp = bp;
    else if (target === co) co = co;
    else if (target === ds) ds = ds;
  }

  // ---- Run handlers ----
  async function runHall() {
    busyHall = true;
    try {
      hallReport = await api.post('/api/diagnostics/hall-check',
                                   { n_samples: hallSamples });
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyHall = false; }
  }

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
    {},
    co,
  );
  const runDs = () => spawnRun(
    '/api/diagnostics/distributions',
    {},
    ds,
  );

  // ---- ECharts options ----
  $: mcHistogramOption = mc.result && mc.result.ok ? {
    title: { text: 'SOFT — distribuzione Monte Carlo' },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: mc.result.samples.map((_, i) => i + 1),
      name: 'sample',
    },
    yAxis: { type: 'value', name: 'SOFT' },
    series: [
      {
        type: 'bar',
        data: mc.result.samples,
        markLine: {
          data: [
            { yAxis: mc.result.mean, name: 'media',
              lineStyle: { color: '#3f3d8e' } },
            { yAxis: mc.result.base_val, name: 'base',
              lineStyle: { color: '#a04425', type: 'dashed' } },
          ],
        },
      },
    ],
  } : {};

  $: dsTeacherOption = ds.result && ds.result.ok ? {
    title: { text: 'Carico orario docenti' },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: ds.result.teacher_loads.bin_edges
        .slice(0, -1)
        .map((e, i) => `${e.toFixed(0)}-${ds.result.teacher_loads.bin_edges[i + 1].toFixed(0)}`),
      name: 'ore',
    },
    yAxis: { type: 'value', name: '# docenti' },
    series: [{ type: 'bar', data: ds.result.teacher_loads.bin_counts }],
  } : {};

  $: dsHeatmapOption = ds.result && ds.result.ok ? {
    title: { text: 'Materia x slot' },
    tooltip: { position: 'top' },
    grid: { left: '12%', right: '5%', bottom: '14%', top: '12%' },
    xAxis: {
      type: 'category',
      data: ds.result.subject_slot_heatmap.slots,
      splitArea: { show: true },
      axisLabel: { rotate: 60, fontSize: 8 },
    },
    yAxis: {
      type: 'category',
      data: ds.result.subject_slot_heatmap.matrix.map((m) => m.subject),
      splitArea: { show: true },
    },
    visualMap: {
      min: 0,
      max: Math.max(
        1,
        ...ds.result.subject_slot_heatmap.matrix.flatMap((m) => m.row),
      ),
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: '0%',
    },
    series: [{
      type: 'heatmap',
      data: ds.result.subject_slot_heatmap.matrix.flatMap((m, i) =>
        m.row.map((v, j) => [j, i, v]),
      ),
      label: { show: false },
    }],
  } : {};

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

  <!-- 1) Hall (sync) -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">1) Pre-check fattibilita' (Hall)</h2>
      <span class="pill pill-amber !text-[10px]">sync, &lt;100ms</span>
      <div class="ml-auto flex gap-2 items-end">
        <div class="field !mb-0">
          <label class="!text-[11px]">N campioni</label>
          <input type="number" min="32" max="1024"
                 bind:value={hallSamples} class="w-24"/>
        </div>
        <button class="btn-primary !text-xs" on:click={runHall}
                disabled={busyHall}>
          {busyHall ? '...' : 'Lancia Hall pre-check'}
        </button>
      </div>
    </div>
    {#if hallReport}
      <div class="text-sm">
        <div class={hallReport.ok ? 'text-emerald-700' : 'text-rose-700'}>
          <strong>{hallReport.ok ? 'Feasible (Hall OK)' : 'INFEASIBILE'}</strong>
          - {hallReport.n_classes} classi, {hallReport.n_teachers} docenti
          - domanda {hallReport.stats.total_demand_hours}h vs supply
          {hallReport.stats.total_supply_hours}h
        </div>
        {#if hallReport.violations.length}
          <table class="tbl mt-2 text-xs">
            <thead><tr><th>Tipo</th><th>Messaggio</th></tr></thead>
            <tbody>
              {#each hallReport.violations as v}
                <tr><td class="font-mono">{v.kind}</td><td>{v.msg ?? ''}</td></tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>
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
  </section>

  <!-- 4) Correlations (async run) -->
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
        {co.busy ? '...' : 'Calcola correlazioni'}
      </button>
    </div>
    {#if co.error}
      <p class="text-xs text-rose-700">{co.error}</p>
    {/if}
    {#if co.result && co.result.ok}
      <table class="tbl text-xs">
        <thead>
          <tr>
            <th>Modello</th>
            <th>n</th>
            <th>coef</th>
            <th>p-value</th>
            <th>R^2 / pseudo</th>
            <th>Interpretazione</th>
          </tr>
        </thead>
        <tbody>
          {#each co.result.models as m}
            <tr>
              <td>{m.label || m.name}</td>
              <td>{m.n ?? '-'}</td>
              <td>{m.coef !== undefined ? m.coef.toFixed(3) : '-'}</td>
              <td>{m.p_value !== undefined ? m.p_value.toFixed(3) : '-'}</td>
              <td>{m.r2 !== undefined ? m.r2.toFixed(3) :
                    m.pseudo_r2 !== undefined ? m.pseudo_r2.toFixed(3) : '-'}</td>
              <td class="text-[11px]">{m.interpretation || m.warn || m.error || ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="grid md:grid-cols-2 gap-3 mt-2">
        {#each co.result.models.filter((m) => m.scatter) as m}
          <EChart option={scatterOption(m)} height={240}/>
        {/each}
      </div>
    {/if}
  </section>

  <!-- 5) Distributions (async run) -->
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
        {ds.busy ? '...' : 'Calcola distribuzioni'}
      </button>
    </div>
    {#if ds.error}
      <p class="text-xs text-rose-700">{ds.error}</p>
    {/if}
    {#if ds.result && ds.result.ok}
      <div class="grid md:grid-cols-2 gap-4">
        <EChart option={dsTeacherOption} height={280}/>
        <EChart option={dsHeatmapOption} height={280}/>
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
  </section>
</div>
