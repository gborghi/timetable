<script>
  /**
   * Card grouping the 4 advanced optimization techniques:
   *   - Hall's theorem pre-check (synchronous diagnostic)
   *   - ALNS (adaptive LNS)
   *   - VNS  (variable neighbourhood search)
   *   - Column Generation skeleton
   *
   * Each technique has its own row with config inputs + "Avvia" button.
   * Hall is sync (no run id); the others spawn a /runs entry.
   */
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';

  export let onRunStarted = (runId) => {};

  let busyHall = false;
  let hallReport = null;
  let hallSamples = 256;

  let busyAlns = false;
  let alnsBudget = 60;
  let alnsT0 = 5;
  let alnsAlpha = 0.995;

  let busyVns = false;
  let vnsBudget = 60;

  let busyCg = false;
  let cgBudget = 60;
  let cgPatternsPerTeacher = 3;

  let busyLag = false;
  let lagBudget = 60;
  let lagMaxIter = 8;
  let lagTolerance = 0.01;
  let lagAlpha0 = 1.0;

  async function runHall() {
    busyHall = true;
    try {
      hallReport = await api.post('/api/diagnostics/hall-check',
                                   { n_samples: hallSamples });
      const status = hallReport.ok ? 'success' : 'warning';
      const msg = hallReport.ok
        ? `Hall OK: ${hallReport.n_classes} classi, `
          + `${hallReport.n_teachers} docenti, nessuna violazione`
        : `Hall: ${hallReport.violations.length} violazioni`;
      flash(msg, status);
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyHall = false; }
  }

  async function runAlns() {
    busyAlns = true;
    try {
      const r = await api.post('/api/optimize/meta/alns', {
        budget_s: alnsBudget,
        alns_T0: alnsT0,
        alns_alpha: alnsAlpha,
      });
      flash('ALNS run #' + r.run_id + ' avviato', 'success');
      onRunStarted(r.run_id);
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyAlns = false; }
  }

  async function runVns() {
    busyVns = true;
    try {
      const r = await api.post('/api/optimize/meta/vns', {
        budget_s: vnsBudget,
      });
      flash('VNS run #' + r.run_id + ' avviato', 'success');
      onRunStarted(r.run_id);
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyVns = false; }
  }

  async function runCg() {
    busyCg = true;
    try {
      const r = await api.post('/api/optimize/column-generation', {
        time_budget_s: cgBudget,
        patterns_per_teacher: cgPatternsPerTeacher,
      });
      flash('Column Generation run #' + r.run_id + ' avviato', 'success');
      onRunStarted(r.run_id);
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyCg = false; }
  }

  async function runLagrangian() {
    busyLag = true;
    try {
      const r = await api.post('/api/optimize/meta/lagrangian', {
        budget_s: lagBudget,
        lagrangian_max_iter: lagMaxIter,
        lagrangian_tolerance: lagTolerance,
        lagrangian_alpha_0: lagAlpha0,
      });
      flash('Lagrangian run #' + r.run_id + ' avviato', 'success');
      onRunStarted(r.run_id);
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyLag = false; }
  }
</script>

<div class="card p-5 space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h2>Tecniche avanzate</h2>
    <span class="text-xs text-ink-500 max-w-2xl">
      ALNS, VNS, Hall's theorem pre-check e Column Generation. Vedere
      <code>docs/optimization_strategies.md</code> per dettagli e
      quando usarle.
    </span>
  </div>

  <!-- Hall pre-check -->
  <div class="border border-ink-200 rounded p-3 bg-ink-50/40">
    <div class="flex items-baseline gap-2 mb-2">
      <h3 class="!text-sm">Hall's theorem pre-check</h3>
      <span class="pill pill-amber !text-[10px]">diagnostico, sync</span>
    </div>
    <p class="text-[11px] text-ink-500 mb-2">
      Verifica strutturale prima di Phase A: per ogni materia controlla
      che la capacita' dei docenti qualificati copra la domanda; campiona
      sottoinsiemi di docenti per verificare la condizione di Hall.
    </p>
    <div class="flex gap-2 items-end">
      <div class="field !mb-0">
        <label class="!text-[11px]">N campioni</label>
        <input type="number" min="16" max="1024"
               bind:value={hallSamples}
               class="w-24"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runHall}
              disabled={busyHall}>
        {busyHall ? '...' : 'Pre-check fattibilita strutturale'}
      </button>
    </div>
    {#if hallReport}
      <div class="mt-2 text-xs">
        <div>
          <strong>{hallReport.ok ? 'Feasible (Hall OK)' : 'INFEASIBILE'}</strong>
          - {hallReport.n_classes} classi, {hallReport.n_teachers} docenti
          - domanda {hallReport.stats.total_demand_hours}h vs supply
          {hallReport.stats.total_supply_hours}h
        </div>
        {#if hallReport.violations.length}
          <ul class="list-disc ml-5 mt-1 text-rose-700">
            {#each hallReport.violations as v}
              <li>{v.msg}</li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  </div>

  <!-- ALNS -->
  <div class="border border-ink-200 rounded p-3 bg-ink-50/40">
    <div class="flex items-baseline gap-2 mb-2">
      <h3 class="!text-sm">ALNS (Adaptive LNS)</h3>
      <span class="pill !text-[10px]">meta</span>
    </div>
    <p class="text-[11px] text-ink-500 mb-2">
      6 destroy + 3 repair operators selezionati con roulette wheel
      sopra exponentially-decayed scores; acceptance SA-like
      (T0, alpha geometricamente decrescente). Sostituisce o segue
      LNS classico.
    </p>
    <div class="flex gap-2 items-end flex-wrap">
      <div class="field !mb-0">
        <label class="!text-[11px]">Budget (s)</label>
        <input type="number" bind:value={alnsBudget} class="w-24"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">T0</label>
        <input type="number" step="0.1" bind:value={alnsT0} class="w-20"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">alpha</label>
        <input type="number" step="0.001" bind:value={alnsAlpha}
               class="w-24"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runAlns}
              disabled={busyAlns}>
        {busyAlns ? '...' : 'Avvia ALNS'}
      </button>
    </div>
  </div>

  <!-- VNS -->
  <div class="border border-ink-200 rounded p-3 bg-ink-50/40">
    <div class="flex items-baseline gap-2 mb-2">
      <h3 class="!text-sm">VNS (Variable Neighbourhood Search)</h3>
      <span class="pill !text-[10px]">meta</span>
    </div>
    <p class="text-[11px] text-ink-500 mb-2">
      Cicla 4 vicinati di dimensione crescente: 1-swap, 2-swap,
      3-chain, k-opt (k=4..6). Tipica rifinitura post-TS. Termina
      quando un intero ciclo passa senza miglioramento.
    </p>
    <div class="flex gap-2 items-end flex-wrap">
      <div class="field !mb-0">
        <label class="!text-[11px]">Budget (s)</label>
        <input type="number" bind:value={vnsBudget} class="w-24"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runVns}
              disabled={busyVns}>
        {busyVns ? '...' : 'Avvia VNS'}
      </button>
    </div>
  </div>

  <!-- Lagrangian Relaxation -->
  <div class="border border-ink-200 rounded p-3 bg-ink-50/40">
    <div class="flex items-baseline gap-2 mb-2">
      <h3 class="!text-sm">Lagrangian Relaxation</h3>
      <span class="pill !text-[10px]">subgradient ascent</span>
    </div>
    <p class="text-[11px] text-ink-500 mb-2">
      Rilassa i ponti inter-cluster e dualizza con multipliers
      lambda; aggiornamento via subgradient ascent
      (lambda_{`{k+1}`} = lambda_k + alpha_k * g_k, alpha_k =
      alpha_0 / (1 + k)). Skeleton + refinement via SA per
      iterazione.
    </p>
    <div class="flex gap-2 items-end flex-wrap">
      <div class="field !mb-0">
        <label class="!text-[11px]">Budget (s)</label>
        <input type="number" bind:value={lagBudget} class="w-24"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Max iter</label>
        <input type="number" bind:value={lagMaxIter} class="w-16"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Tolleranza</label>
        <input type="number" step="0.001"
               bind:value={lagTolerance} class="w-24"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">alpha0</label>
        <input type="number" step="0.1"
               bind:value={lagAlpha0} class="w-20"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runLagrangian}
              disabled={busyLag}>
        {busyLag ? '...' : 'Avvia Lagrangian'}
      </button>
    </div>
  </div>

  <!-- Column Generation -->
  <div class="border border-ink-200 rounded p-3 bg-ink-50/40">
    <div class="flex items-baseline gap-2 mb-2">
      <h3 class="!text-sm">Column Generation</h3>
      <span class="pill pill-blue !text-[10px]">phase B alternativo</span>
    </div>
    <p class="text-[11px] text-ink-500 mb-2">
      Decomposizione Dantzig-Wolfe: master LP (scipy.linprog HiGHS) +
      sottoproblema per docente. Skeleton funzionante (1 iterazione);
      consigliato solo per istanze molto grandi (>200 classi).
    </p>
    <div class="flex gap-2 items-end flex-wrap">
      <div class="field !mb-0">
        <label class="!text-[11px]">Budget (s)</label>
        <input type="number" bind:value={cgBudget} class="w-24"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Pattern/docente</label>
        <input type="number" bind:value={cgPatternsPerTeacher}
               class="w-20"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runCg}
              disabled={busyCg}>
        {busyCg ? '...' : 'Avvia Column Generation'}
      </button>
    </div>
  </div>
</div>
