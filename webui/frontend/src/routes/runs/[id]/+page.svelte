<script>
  /**
   * /runs/[id] -- detailed view of a single run.
   *
   * Sections:
   *   - Header (kind, profile, status, started/finished, obj_value)
   *   - Objective chart (ECharts line, X = time, Y = SOFT)
   *   - Per-phase summary table
   *   - Sample stream (paginated table)
   *
   * Live mode: when the run is still 'running'/'pending', the page
   * polls /api/optimize/runs/{id} + /summary every 2s and merges
   * just the new samples into the chart, so the line grows live
   * without flicker.
   */
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import EChart from '$lib/components/EChart.svelte';
  import RunLogPanel from '$lib/components/RunLogPanel.svelte';
  import DiagnosticResult from
    '$lib/components/diagnostics/DiagnosticResult.svelte';

  let run = null;
  let summary = null;
  let busy = true;
  let pollTimer = null;
  let xAxis = 'time';                      // 'time' | 'step'

  // Telemetry summary is HEAVY (1 row per sample, hundreds of kB).
  // We only fetch it on demand when the user expands the chart
  // section. The lightweight `run` payload (status, progress,
  // metrics) is always loaded.
  let showChart = false;
  let summaryLoading = false;

  $: runId = Number($page.params.id);

  async function loadRun() {
    try {
      run = await api.get('/api/optimize/runs/' + runId);
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busy = false; }
  }

  async function loadSummary() {
    if (summaryLoading) return;
    summaryLoading = true;
    try {
      summary = await api.get('/api/optimize/runs/' + runId + '/summary');
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { summaryLoading = false; }
  }

  function isActive() {
    return run && (run.status === 'running' || run.status === 'pending');
  }

  // Smart polling: 2s only while the run is alive; STOPPED if
  // - the document is hidden (background tab) -- avoid burning
  //   bandwidth + backend cycles when the user is not looking
  // - the user navigates away (onDestroy clears the timer)
  // The chart-summary fetch only fires when `showChart` is true,
  // because that endpoint is heavier (full telemetry rollup).
  function _tick() {
    if (typeof document !== 'undefined' && document.hidden) return;
    if (!isActive()) return;
    loadRun();
    if (showChart) loadSummary();
  }

  onMount(async () => {
    await loadRun();
    pollTimer = setInterval(_tick, 2000);
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  // When the user expands the chart, fetch summary once now
  // (subsequent updates come from the smart-poll tick).
  async function toggleChart() {
    showChart = !showChart;
    if (showChart && !summary) await loadSummary();
  }

  function fmt(ts) {
    if (!ts) return '';
    return new Date(ts).toLocaleString();
  }

  function exportTelemetryUrl() {
    return '/api/optimize/runs/' + runId
           + '/telemetry?limit=100000';
  }

  // --- ECharts options ---
  $: objectiveOption = summary && summary.objective_series
                        && summary.objective_series.length ? {
    title: { text: 'Objective vs ' + (xAxis === 'time' ? 'tempo (s)' : 'step') },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: xAxis === 'time' ? 'value' : 'category',
      name: xAxis === 'time' ? 's' : 'step',
    },
    yAxis: { type: 'value', name: 'SOFT' },
    series: (() => {
      // Group samples by phase, draw one line per phase.
      const byPhase = {};
      for (let i = 0; i < summary.objective_series.length; i++) {
        const s = summary.objective_series[i];
        const ph = s.phase || '(unknown)';
        if (!byPhase[ph]) byPhase[ph] = [];
        byPhase[ph].push(
          xAxis === 'time' ? [s.t, s.obj] : [i, s.obj],
        );
      }
      return Object.entries(byPhase).map(([ph, data]) => ({
        type: 'line',
        name: ph,
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        data,
      }));
    })(),
    legend: { top: 24 },
  } : null;

  $: placedPct = run?.metrics?.placed_events_pct
                  ?? run?.metrics?.placed_lessons_pct ?? null;
  $: hardViolations = run?.metrics?.hard_violations_count ?? null;
</script>

<div class="space-y-5">
  <div class="flex items-baseline gap-3 flex-wrap">
    <a href="/runs" class="btn !text-xs">← Torna ai runs</a>
    <h1>Run #{runId}</h1>
    {#if run}
      <span class="pill !text-xs">{run.kind}</span>
      {#if run.status === 'done'}
        <span class="pill pill-green">done</span>
      {:else if run.status === 'failed'}
        <span class="pill pill-red">failed</span>
      {:else if run.status === 'running' || run.status === 'pending'}
        <span class="pill pill-blue">{run.status}</span>
      {:else}
        <span class="pill">{run.status}</span>
      {/if}
    {/if}
    <a class="btn !text-xs ml-auto" href={exportTelemetryUrl()}
       download={'telemetry_run_' + runId + '.json'}
       title="Scarica la serie completa di telemetria in JSON">
      Esporta telemetria (JSON)
    </a>
  </div>

  {#if busy && !run}
    <p class="text-sm text-ink-500 italic">Caricamento...</p>
  {:else if run}
    <section class="card p-4 space-y-2">
      <h2 class="!text-base">Riepilogo</h2>
      <div class="grid md:grid-cols-3 gap-3 text-sm">
        <div>
          <div class="text-ink-500 text-xs">Avviato</div>
          <div>{fmt(run.started_at)}</div>
        </div>
        <div>
          <div class="text-ink-500 text-xs">Terminato</div>
          <div>{fmt(run.finished_at) || '—'}</div>
        </div>
        <div>
          <div class="text-ink-500 text-xs">Obj finale</div>
          <div class="text-2xl font-semibold tabular-nums">
            {run.obj_value ?? '—'}
          </div>
        </div>
        {#if placedPct != null}
          <div>
            <div class="text-ink-500 text-xs">% lezioni piazzate</div>
            <div class="text-xl font-semibold">
              {Math.round(placedPct)}%
            </div>
          </div>
        {/if}
        {#if hardViolations != null}
          <div>
            <div class="text-ink-500 text-xs"># vincoli HARD violati</div>
            <span class="pill {hardViolations === 0 ? 'pill-green' : 'pill-red'}">
              {hardViolations}
            </span>
          </div>
        {/if}
        <div>
          <div class="text-ink-500 text-xs">Profilo</div>
          <div>{run.profile ?? '—'}</div>
        </div>
      </div>
      {#if run.error}
        <pre class="bg-rose-50 border border-rose-200 rounded p-2 text-xs text-rose-800 mt-2 whitespace-pre-wrap">{run.error}</pre>
      {/if}
    </section>
  {/if}

  <!-- The "telemetry" section only makes sense for SOLVER runs
       (LNS/SA/TS/ALNS/...). For diagnostic runs the result is
       already rendered above; suppress the telemetry chart
       prompt to avoid confusion. -->
  {#if !((run?.kind || '').startsWith('diag_'))}
    <section class="card p-4 space-y-2">
      <div class="flex items-baseline gap-3">
        <h2 class="!text-base">Grafico objective + statistiche stage</h2>
        <span class="text-xs text-ink-500">
          {#if summary}
            {summary.n_samples} sample,
            durata {summary.duration_s?.toFixed(1)}s
          {/if}
        </span>
        <button class="btn !text-xs ml-auto"
                on:click={toggleChart}
                disabled={summaryLoading}>
          {showChart ? 'Nascondi' : (summary ? 'Mostra' : 'Carica grafico')}
          {#if summaryLoading} ...{/if}
        </button>
      </div>
      {#if !showChart}
        <p class="text-[11px] text-ink-500 italic">
          Il grafico carica la telemetria via
          <code>/api/optimize/runs/{runId}/summary</code>
          (puo' essere pesante). Premi "Mostra" quando vuoi
          analizzarlo.
        </p>
      {/if}
    </section>
  {/if}

  {#if showChart && summary && summary.n_samples > 0}
    <section class="card p-4 space-y-2">
      <div class="flex items-baseline gap-3">
        <h2 class="!text-base">Grafico objective</h2>
        <div class="ml-auto">
          <label class="text-xs">
            <input type="radio" bind:group={xAxis} value="time"/> tempo
          </label>
          <label class="text-xs ml-2">
            <input type="radio" bind:group={xAxis} value="step"/> step
          </label>
        </div>
      </div>
      <EChart option={objectiveOption} height={360}/>
    </section>

    <section class="card p-4 space-y-2">
      <h2 class="!text-base">Statistiche per stage</h2>
      <table class="tbl text-xs">
        <thead>
          <tr>
            <th>Stage</th>
            <th class="text-right"># sample</th>
            <th class="text-right">Inizio (s)</th>
            <th class="text-right">Fine (s)</th>
            <th class="text-right">Best obj</th>
          </tr>
        </thead>
        <tbody>
          {#each summary.phases as ph (ph.phase)}
            <tr>
              <td>{ph.phase || '(unknown)'}</td>
              <td class="text-right tabular-nums">{ph.n_samples}</td>
              <td class="text-right tabular-nums">{ph.first_t.toFixed(2)}</td>
              <td class="text-right tabular-nums">{ph.last_t.toFixed(2)}</td>
              <td class="text-right tabular-nums">
                {ph.best_obj != null ? ph.best_obj.toFixed(1) : '—'}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {:else if showChart && summary}
    <section class="card p-4">
      <p class="text-sm text-ink-500 italic">
        Nessuna telemetria registrata per questo run (versione del
        solver precedente al collector, oppure run di tipo
        diagnostico — il risultato e' nelle metriche del
        riepilogo).
      </p>
    </section>
  {/if}

  <!-- For DIAGNOSTIC runs (kind starts with 'diag_'), render the
       full graphical result via the shared <DiagnosticResult>
       component. Same charts you see on /diagnostics, but
       reachable from the runs list too. -->
  {#if run && (run.kind || '').startsWith('diag_') && run.metrics}
    <section class="card p-4 space-y-2">
      <div class="flex items-baseline gap-2">
        <h2 class="!text-base">Risultato diagnostica</h2>
        <span class="text-xs text-ink-500">
          {run.kind} - generato il {fmt(run.finished_at) || '...'}
        </span>
      </div>
      <DiagnosticResult kind={run.kind} result={run.metrics}/>
      <details class="text-xs">
        <summary class="cursor-pointer text-ink-500">
          Mostra payload JSON grezzo
        </summary>
        <pre class="bg-ink-50 border border-ink-200 rounded p-2 mt-2 text-xs overflow-auto max-h-96">{JSON.stringify(run.metrics, null, 2)}</pre>
      </details>
    </section>
  {/if}

  <section class="card p-4 space-y-2">
    <h2 class="!text-base">Log</h2>
    <RunLogPanel runId={runId} title={'Run #' + runId}/>
  </section>
</div>
