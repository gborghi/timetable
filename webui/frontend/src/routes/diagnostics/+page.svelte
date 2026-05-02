<script>
  /**
   * /diagnostics tab: pre-check, Monte Carlo sensitivity, bipartite
   * graph metrics, correlations + regressions, distributions.
   *
   * All endpoints live under /api/diagnostics/. Charts use the
   * shared <EChart> component (lazy-loaded). The Hall section is
   * intentionally redundant with the inline button on PhaseACard:
   * here it carries a more detailed report.
   */
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import EChart from '$lib/components/EChart.svelte';

  // ---- State ----
  let busyHall = false;
  let hallReport = null;
  let hallSamples = 256;

  let busyMc = false;
  let mcReport = null;
  let mcN = 100;
  let mcSeed = 0;

  let busyBp = false;
  let bpReport = null;
  let bpMode = 'classes';

  let busyCo = false;
  let coReport = null;

  let busyDs = false;
  let dsReport = null;

  // ---- Run handlers ----
  async function runHall() {
    busyHall = true;
    try {
      hallReport = await api.post('/api/diagnostics/hall-check',
                                   { n_samples: hallSamples });
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyHall = false; }
  }
  async function runMc() {
    busyMc = true;
    try {
      mcReport = await api.post('/api/diagnostics/montecarlo',
                                 { n_samples: mcN, seed: mcSeed });
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyMc = false; }
  }
  async function runBp() {
    busyBp = true;
    try {
      bpReport = await api.post('/api/diagnostics/bipartite',
                                 { mode: bpMode });
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyBp = false; }
  }
  async function runCo() {
    busyCo = true;
    try {
      coReport = await api.post('/api/diagnostics/correlations', {});
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyCo = false; }
  }
  async function runDs() {
    busyDs = true;
    try {
      dsReport = await api.post('/api/diagnostics/distributions', {});
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyDs = false; }
  }

  // ---- ECharts options ----
  $: mcHistogramOption = mcReport && mcReport.ok ? {
    title: { text: 'SOFT — distribuzione Monte Carlo' },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: mcReport.samples.map((_, i) => i + 1),
      name: 'sample',
    },
    yAxis: { type: 'value', name: 'SOFT' },
    series: [
      {
        type: 'bar',
        data: mcReport.samples,
        markLine: {
          data: [
            { yAxis: mcReport.mean, name: 'media',
              lineStyle: { color: '#3f3d8e' } },
            { yAxis: mcReport.base_val, name: 'base',
              lineStyle: { color: '#a04425', type: 'dashed' } },
          ],
        },
      },
    ],
  } : {};

  $: dsTeacherOption = dsReport && dsReport.ok ? {
    title: { text: 'Carico orario docenti' },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: dsReport.teacher_loads.bin_edges
        .slice(0, -1)
        .map((e, i) => `${e.toFixed(0)}-${dsReport.teacher_loads.bin_edges[i + 1].toFixed(0)}`),
      name: 'ore',
    },
    yAxis: { type: 'value', name: '# docenti' },
    series: [{ type: 'bar', data: dsReport.teacher_loads.bin_counts }],
  } : {};

  $: dsHeatmapOption = dsReport && dsReport.ok ? {
    title: { text: 'Materia x slot' },
    tooltip: { position: 'top' },
    grid: { left: '12%', right: '5%', bottom: '14%', top: '12%' },
    xAxis: {
      type: 'category',
      data: dsReport.subject_slot_heatmap.slots,
      splitArea: { show: true },
      axisLabel: { rotate: 60, fontSize: 8 },
    },
    yAxis: {
      type: 'category',
      data: dsReport.subject_slot_heatmap.matrix.map((m) => m.subject),
      splitArea: { show: true },
    },
    visualMap: {
      min: 0,
      max: Math.max(
        1,
        ...dsReport.subject_slot_heatmap.matrix.flatMap((m) => m.row),
      ),
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: '0%',
    },
    series: [{
      type: 'heatmap',
      data: dsReport.subject_slot_heatmap.matrix.flatMap((m, i) =>
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
</script>

<div class="space-y-6">
  <h1>Statistiche e diagnostica</h1>
  <p class="text-sm text-ink-500 max-w-3xl">
    Analisi statistiche del modello e della soluzione attiva.
    Pre-check di fattibilita', sensitivity Monte Carlo, struttura del
    grafo classe x docente, correlazioni, distribuzioni e
    goodness-of-fit. Endpoint sotto <code>/api/diagnostics/</code>.
  </p>

  <!-- 1) Hall -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">1) Pre-check fattibilita' (Hall)</h2>
      <span class="pill pill-amber !text-[10px]">diagnostico</span>
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

  <!-- 2) Monte Carlo -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">2) Sensitivity Monte Carlo</h2>
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
                disabled={busyMc}>
          {busyMc ? '...' : 'Lancia analisi MC'}
        </button>
      </div>
    </div>
    {#if mcReport && mcReport.ok}
      <div class="text-xs flex flex-wrap gap-3 text-ink-600">
        <span><strong>Base:</strong> {mcReport.base_val.toFixed(1)}</span>
        <span><strong>Media:</strong> {mcReport.mean.toFixed(1)}</span>
        <span><strong>Std:</strong> {mcReport.std.toFixed(1)}</span>
        <span><strong>CV:</strong> {(mcReport.coefficient_of_variation*100).toFixed(1)}%</span>
        <span><strong>p25:</strong> {mcReport.p25.toFixed(1)}</span>
        <span><strong>p50:</strong> {mcReport.p50.toFixed(1)}</span>
        <span><strong>p75:</strong> {mcReport.p75.toFixed(1)}</span>
      </div>
      <p class="text-xs text-ink-500 italic">{mcReport.interpretation}</p>
      <EChart option={mcHistogramOption} height={300}/>
    {:else if mcReport}
      <p class="text-xs text-rose-700">{mcReport.msg}</p>
    {/if}
  </section>

  <!-- 3) Bipartite -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">3) Analisi bipartito (modularita' / betweenness / densita')</h2>
      <div class="ml-auto flex gap-2 items-end">
        <div class="field !mb-0">
          <label class="!text-[11px]">Mode</label>
          <select bind:value={bpMode}>
            <option value="classes">classes (nodi=classi)</option>
            <option value="teachers">teachers (nodi=docenti)</option>
          </select>
        </div>
        <button class="btn-primary !text-xs" on:click={runBp}
                disabled={busyBp}>
          {busyBp ? '...' : 'Analizza grafo'}
        </button>
      </div>
    </div>
    {#if bpReport && bpReport.ok}
      <div class="grid md:grid-cols-3 gap-3 text-sm">
        <div class="card !shadow-none p-3">
          <div class="text-3xl font-semibold">
            {bpReport.density.toFixed(3)}
          </div>
          <div class="text-xs text-ink-500">Densita'</div>
          <p class="text-[10px] text-ink-500 italic mt-1">
            {bpReport.density_interpretation}
          </p>
        </div>
        <div class="card !shadow-none p-3">
          <div class="text-3xl font-semibold">
            {bpReport.modularity.toFixed(3)}
          </div>
          <div class="text-xs text-ink-500">
            Modularita' ({bpReport.n_communities} comunita')
          </div>
          <p class="text-[10px] text-ink-500 italic mt-1">
            {bpReport.modularity_interpretation}
          </p>
        </div>
        <div class="card !shadow-none p-3">
          <div class="text-xs text-ink-500 mb-1">
            Top {bpReport.top_betweenness.length} nodi per
            betweenness
          </div>
          <ul class="text-xs space-y-0.5">
            {#each bpReport.top_betweenness as n, i}
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
        {bpReport.n_nodes} nodi, {bpReport.n_edges} archi.
        Per la visualizzazione del grafo annotato vedere il pannello
        "Grafo della scuola" sulla Dashboard.
      </p>
    {:else if bpReport}
      <p class="text-xs text-rose-700">{bpReport.msg ?? 'errore'}</p>
    {/if}
  </section>

  <!-- 4) Correlations -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">4) Correlazioni e regressioni</h2>
      <button class="btn-primary !text-xs ml-auto" on:click={runCo}
              disabled={busyCo}>
        {busyCo ? '...' : 'Calcola correlazioni'}
      </button>
    </div>
    {#if coReport && coReport.ok}
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
          {#each coReport.models as m}
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
        {#each coReport.models.filter((m) => m.scatter) as m}
          <EChart option={scatterOption(m)} height={240}/>
        {/each}
      </div>
    {:else if coReport}
      <p class="text-xs text-rose-700">{coReport.msg}</p>
    {/if}
  </section>

  <!-- 5) Distributions -->
  <section class="card p-4 space-y-2">
    <div class="flex items-baseline gap-2 flex-wrap">
      <h2 class="!text-base">5) Distribuzioni</h2>
      <button class="btn-primary !text-xs ml-auto" on:click={runDs}
              disabled={busyDs}>
        {busyDs ? '...' : 'Calcola distribuzioni'}
      </button>
    </div>
    {#if dsReport && dsReport.ok}
      <div class="grid md:grid-cols-2 gap-4">
        <EChart option={dsTeacherOption} height={280}/>
        <EChart option={dsHeatmapOption} height={280}/>
      </div>
      {#if dsReport.tests}
        <div class="text-xs text-ink-600 space-y-1 mt-2">
          {#each Object.entries(dsReport.tests) as [name, t]}
            <div>
              <strong>{name}:</strong>
              statistica = {t.statistic.toFixed(3)},
              p-value = {t.p_value.toFixed(3)} -
              <em>{t.interpretation}</em>
            </div>
          {/each}
        </div>
      {/if}
    {:else if dsReport}
      <p class="text-xs text-rose-700">{dsReport.msg}</p>
    {/if}
  </section>
</div>
