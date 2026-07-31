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
  let cgMode = 'iterative-diversified';
  // 'iterative-diversified' | 'branch-and-price' | 'auto'
  let cgGranularity = 'auto';
  // 9 values: 'auto' | 'teacher' | 'teacher-day' | 'teacher-class' |
  // 'teacher-class-subject' | 'teacher-subject' | 'class' | 'class-day' |
  // 'day' | 'curriculum'
  let cgBranching = 'ryan_foster'; // 'variable' | 'ryan_foster'
  let cgMaxIterations = 100;
  let cgBpMaxIterations = 8;
  let cgPricerTimeLimit = 5.0;
  let cgPricerWorkers = 2;
  let cgParallel = true;

  let busyLag = false;
  let lagBudget = 60;
  let lagMaxIter = 8;
  let lagTolerance = 0.01;
  let lagAlpha0 = 1.0;

  async function runHall() {
    busyHall = true;
    try {
      hallReport = await api.post('/api/diagnostics/hall-check',
                                   { n_samples: hallSamples, sync: true });
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
        mode: cgMode,
        granularity: cgGranularity,
        branching_strategy: cgBranching,
        max_iterations: cgMaxIterations,
        bp_max_iterations: cgBpMaxIterations,
        pricer_time_limit: cgPricerTimeLimit,
        pricer_workers: cgPricerWorkers,
        parallel: cgParallel,
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

<!-- Senza card propria: il titolo e la cornice li mette il <Panel>
     "Tecniche avanzate" che avvolge questo componente in /optimize. -->
<div class="space-y-4" data-testid="advanced-techniques-card">
  <p class="text-[11.5px] text-ink-400 max-w-[76ch]">
    ALNS, VNS, Hall's theorem pre-check e Column Generation. Vedere
    <code>docs/optimization_strategies.md</code> per dettagli e
    quando usarle.
  </p>

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
               data-testid="adv-hall-samples"
               class="w-24"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runHall}
              data-testid="adv-hall-run"
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
        <input type="number" bind:value={alnsBudget}
               data-testid="adv-alns-budget" class="w-24"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">T0</label>
        <input type="number" step="0.1" bind:value={alnsT0}
               data-testid="adv-alns-t0" class="w-20"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">alpha</label>
        <input type="number" step="0.001" bind:value={alnsAlpha}
               data-testid="adv-alns-alpha" class="w-24"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runAlns}
              data-testid="adv-alns-run"
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
        <input type="number" bind:value={vnsBudget}
               data-testid="adv-vns-budget" class="w-24"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runVns}
              data-testid="adv-vns-run"
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
        <input type="number" bind:value={lagBudget}
               data-testid="adv-lag-budget" class="w-24"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Max iter</label>
        <input type="number" bind:value={lagMaxIter}
               data-testid="adv-lag-max-iter" class="w-16"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Tolleranza</label>
        <input type="number" step="0.001"
               bind:value={lagTolerance}
               data-testid="adv-lag-tolerance" class="w-24"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">alpha0</label>
        <input type="number" step="0.1"
               bind:value={lagAlpha0}
               data-testid="adv-lag-alpha0" class="w-20"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runLagrangian}
              data-testid="adv-lag-run"
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
      Decomposizione Dantzig-Wolfe: master LP + sottoproblemi CP-SAT
      a granularita' configurabile (9 opzioni). <em>Mode</em> sceglie
      tra <em>iterative-diversified</em> (master LP + pattern
      enrichment + completion fallback, sempre HARD=100%) e
      <em>branch-and-price</em> (vero BP con sub-CP-SAT pricing dei
      duali). <em>Auto</em> sceglie modalita' e granularita' in base
      alla taglia della scuola. Vedi
      <code>docs/optimization_strategies.md &sect;4</code>.
    </p>
    <div class="grid grid-cols-2 gap-2 mb-2">
      <div class="field !mb-0">
        <label class="!text-[11px]">Modalita'</label>
        <select bind:value={cgMode} data-testid="adv-cg-mode" class="w-full">
          <option value="iterative-diversified">Iterative-diversified (default)</option>
          <option value="branch-and-price">Branch-and-Price (sub-CP-SAT pricing)</option>
          <option value="auto">Auto (per taglia scuola)</option>
        </select>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Granularita' sub-problema</label>
        <select bind:value={cgGranularity}
                data-testid="adv-cg-granularity" class="w-full"
                title="Selettore granularita' di pricing per BP. Le granularita' teacher-based generano pattern per docente; class-based per classe; 'day' e 'curriculum' sono globali. 'auto' sceglie in base alla taglia.">
          <optgroup label="Auto">
            <option value="auto">Auto (suggerita dalla taglia)</option>
          </optgroup>
          <optgroup label="Teacher-based">
            <option value="teacher">Per docente</option>
            <option value="teacher-day">Per docente / giorno</option>
            <option value="teacher-class">Per docente / classe</option>
            <option value="teacher-class-subject">Per docente / classe / materia</option>
            <option value="teacher-subject">Per docente / materia</option>
          </optgroup>
          <optgroup label="Class-based">
            <option value="class">Per classe (orario completo)</option>
            <option value="class-day">Per classe / giorno</option>
          </optgroup>
          <optgroup label="Globali">
            <option value="day">Per giorno (tutti docenti+classi)</option>
            <option value="curriculum">Per indirizzo / curriculum</option>
          </optgroup>
        </select>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Branching strategy</label>
        <select bind:value={cgBranching}
                data-testid="adv-cg-branching" class="w-full">
          <option value="ryan_foster">Ryan-Foster</option>
          <option value="variable">Variable branching</option>
        </select>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Max iterazioni (ID)</label>
        <input type="number" bind:value={cgMaxIterations} class="w-full"
               title="Max iterazioni della pipeline iterative-diversified."/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">BP max iter</label>
        <input type="number" bind:value={cgBpMaxIterations} class="w-full"
               title="Max iterazioni del loop branch-and-price (master + pricing)."/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Pricer time limit (s)</label>
        <input type="number" step="0.5" bind:value={cgPricerTimeLimit}
               class="w-full"
               title="Tempo CPU max per ogni sub-problema CP-SAT di pricing."/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Pricer workers</label>
        <input type="number" bind:value={cgPricerWorkers} class="w-full"
               title="Worker CP-SAT per ogni sub-problema di pricing."/>
      </div>
      <label class="flex items-center gap-2 text-xs self-end pb-1">
        <input type="checkbox" bind:checked={cgParallel}/>
        Sub-problemi paralleli
      </label>
    </div>
    <div class="flex gap-2 items-end flex-wrap">
      <div class="field !mb-0">
        <label class="!text-[11px]">Budget (s)</label>
        <input type="number" bind:value={cgBudget}
               data-testid="adv-cg-budget" class="w-24"/>
      </div>
      <div class="field !mb-0">
        <label class="!text-[11px]">Pattern/docente (seed)</label>
        <input type="number" bind:value={cgPatternsPerTeacher}
               data-testid="adv-cg-patterns" class="w-20"/>
      </div>
      <button class="btn-primary !text-xs" on:click={runCg}
              data-testid="adv-cg-run"
              disabled={busyCg}>
        {busyCg ? '...' : 'Avvia Column Generation'}
      </button>
    </div>
  </div>
</div>
