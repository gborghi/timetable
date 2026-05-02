<script>
  /**
   * Renders the result of a diagnostic run, dispatching on `kind`:
   *
   *   diag_montecarlo     -> histogram + stats line
   *   diag_bipartite      -> 3 stat cards
   *   diag_correlations   -> table + scatter plots per model
   *   diag_distributions  -> teacher-load histogram + heatmap +
   *                          KS / chi-square
   *
   * Used by:
   *   - /diagnostics page (under each section, when the run finishes)
   *   - /runs/[id] page (so clicking "detail" on a diag run shows
   *     the same graphs without going back to /diagnostics)
   *
   * Props:
   *   kind:   string   the run.kind (e.g. 'diag_montecarlo')
   *   result: dict     the run.metrics dict (already parsed)
   */
  import EChart from '$lib/components/EChart.svelte';

  export let kind = '';
  export let result = null;

  function _scatterOption(model) {
    if (!model || !model.scatter) return {};
    return {
      title: { text: model.label || model.name },
      tooltip: { trigger: 'item' },
      xAxis: { type: 'value', name: model.x_label || '' },
      yAxis: { type: 'value', name: model.y_label || '' },
      series: [{
        type: 'scatter',
        symbolSize: 8,
        data: model.scatter.map((p) => [p.x, p.y]),
      }],
    };
  }

  // ---- Monte Carlo ----
  $: mcOption = (kind === 'diag_montecarlo' && result && result.ok) ? {
    title: { text: 'SOFT - distribuzione Monte Carlo' },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: (result.samples || []).map((_, i) => i + 1),
      name: 'sample',
    },
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
  } : null;

  // ---- Distributions ----
  $: dsTeacherOption = (kind === 'diag_distributions' && result
                         && result.ok && result.teacher_loads) ? {
    title: { text: 'Carico orario docenti' },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: result.teacher_loads.bin_edges
        .slice(0, -1)
        .map((e, i) =>
          `${e.toFixed(0)}-${result.teacher_loads.bin_edges[i + 1].toFixed(0)}`,
        ),
      name: 'ore',
    },
    yAxis: { type: 'value', name: '# docenti' },
    series: [{ type: 'bar', data: result.teacher_loads.bin_counts }],
  } : null;

  $: dsHeatmapOption = (kind === 'diag_distributions' && result
                        && result.ok && result.subject_slot_heatmap) ? {
    title: { text: 'Materia x slot' },
    tooltip: { position: 'top' },
    grid: { left: '12%', right: '5%', bottom: '14%', top: '12%' },
    xAxis: {
      type: 'category',
      data: result.subject_slot_heatmap.slots,
      splitArea: { show: true },
      axisLabel: { rotate: 60, fontSize: 8 },
    },
    yAxis: {
      type: 'category',
      data: result.subject_slot_heatmap.matrix.map((m) => m.subject),
      splitArea: { show: true },
    },
    visualMap: {
      min: 0,
      max: Math.max(
        1,
        ...result.subject_slot_heatmap.matrix.flatMap((m) => m.row),
      ),
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: '0%',
    },
    series: [{
      type: 'heatmap',
      data: result.subject_slot_heatmap.matrix.flatMap((m, i) =>
        m.row.map((v, j) => [j, i, v]),
      ),
      label: { show: false },
    }],
  } : null;
</script>

{#if !result}
  <p class="text-sm text-ink-500 italic">Nessun risultato.</p>
{:else if kind === 'diag_hall'}
  <div class="text-sm">
    <div class={result.ok ? 'text-emerald-700' : 'text-rose-700'}>
      <strong>{result.ok ? 'Feasible (Hall OK)' : 'INFEASIBILE'}</strong>
      - {result.n_classes} classi, {result.n_teachers} docenti
      - domanda {result.stats?.total_demand_hours}h / supply
      {result.stats?.total_supply_hours}h
    </div>
    {#if result.violations && result.violations.length}
      <table class="tbl mt-2 text-xs">
        <thead><tr><th>Tipo</th><th>Messaggio</th></tr></thead>
        <tbody>
          {#each result.violations as v}
            <tr>
              <td class="font-mono">{v.kind}</td>
              <td>{v.msg ?? ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
{:else if kind === 'diag_montecarlo'}
  {#if result.ok}
    <div class="text-xs flex flex-wrap gap-3 text-ink-600 mb-2">
      <span><strong>Base:</strong> {result.base_val.toFixed(1)}</span>
      <span><strong>Media:</strong> {result.mean.toFixed(1)}</span>
      <span><strong>Std:</strong> {result.std.toFixed(1)}</span>
      <span><strong>CV:</strong>
        {(result.coefficient_of_variation * 100).toFixed(1)}%</span>
      <span><strong>p25:</strong> {result.p25.toFixed(1)}</span>
      <span><strong>p50:</strong> {result.p50.toFixed(1)}</span>
      <span><strong>p75:</strong> {result.p75.toFixed(1)}</span>
    </div>
    <p class="text-xs text-ink-500 italic mb-2">{result.interpretation}</p>
    <EChart option={mcOption} height={300}/>
  {:else}
    <p class="text-xs text-rose-700">{result.msg ?? 'errore'}</p>
  {/if}

{:else if kind === 'diag_bipartite'}
  {#if result.ok}
    <div class="grid md:grid-cols-3 gap-3 text-sm">
      <div class="card !shadow-none p-3">
        <div class="text-3xl font-semibold">
          {result.density.toFixed(3)}
        </div>
        <div class="text-xs text-ink-500">Densita'</div>
        <p class="text-[10px] text-ink-500 italic mt-1">
          {result.density_interpretation}
        </p>
      </div>
      <div class="card !shadow-none p-3">
        <div class="text-3xl font-semibold">
          {result.modularity.toFixed(3)}
        </div>
        <div class="text-xs text-ink-500">
          Modularita' ({result.n_communities} comunita')
        </div>
        <p class="text-[10px] text-ink-500 italic mt-1">
          {result.modularity_interpretation}
        </p>
      </div>
      <div class="card !shadow-none p-3">
        <div class="text-xs text-ink-500 mb-1">
          Top {result.top_betweenness.length} betweenness
        </div>
        <ul class="text-xs space-y-0.5">
          {#each result.top_betweenness as n, i}
            <li>
              <span class="text-ink-400">#{i + 1}</span>
              <span class="font-mono">{n.node}</span>
              = {n.betweenness.toFixed(3)}
            </li>
          {/each}
        </ul>
      </div>
    </div>
    <p class="text-[11px] text-ink-500 mt-2">
      {result.n_nodes} nodi, {result.n_edges} archi.
    </p>
  {:else}
    <p class="text-xs text-rose-700">{result.msg ?? 'errore'}</p>
  {/if}

{:else if kind === 'diag_correlations'}
  {#if result.ok}
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
        {#each result.models as m}
          <tr>
            <td>{m.label || m.name}</td>
            <td>{m.n ?? '-'}</td>
            <td>{m.coef !== undefined ? m.coef.toFixed(3) : '-'}</td>
            <td>{m.p_value !== undefined ? m.p_value.toFixed(3) : '-'}</td>
            <td>{m.r2 !== undefined ? m.r2.toFixed(3)
                  : m.pseudo_r2 !== undefined ? m.pseudo_r2.toFixed(3)
                  : '-'}</td>
            <td class="text-[11px]">{m.interpretation || m.warn || m.error || ''}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="grid md:grid-cols-2 gap-3 mt-2">
      {#each (result.models || []).filter((m) => m.scatter) as m}
        <EChart option={_scatterOption(m)} height={240}/>
      {/each}
    </div>
  {:else}
    <p class="text-xs text-rose-700">{result.msg ?? 'errore'}</p>
  {/if}

{:else if kind === 'diag_distributions'}
  {#if result.ok}
    <div class="grid md:grid-cols-2 gap-4">
      {#if dsTeacherOption}
        <EChart option={dsTeacherOption} height={280}/>
      {/if}
      {#if dsHeatmapOption}
        <EChart option={dsHeatmapOption} height={280}/>
      {/if}
    </div>
    {#if result.tests}
      <div class="text-xs text-ink-600 space-y-1 mt-2">
        {#each Object.entries(result.tests) as [name, t]}
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
    <p class="text-xs text-rose-700">{result.msg ?? 'errore'}</p>
  {/if}

{:else}
  <pre class="bg-ink-50 border border-ink-200 rounded p-2 text-xs overflow-auto max-h-96">{JSON.stringify(result, null, 2)}</pre>
{/if}
