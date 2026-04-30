<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import { OPTIMIZE_DEFAULTS } from '$lib/constants';
  import RunLogPanel from '$lib/components/RunLogPanel.svelte';
  import PhaseACard from '$lib/components/optimize/PhaseACard.svelte';

  let runId = null;
  let runs = [];
  let lastRefresh = 0;

  // Parameters per step
  let step1 = { ...OPTIMIZE_DEFAULTS };
  let step1import = { profile: 'small', use_optimized: true };
  let step2 = { time_limit_s: 30, workers: 8, log: true };
  let step3 = {
    k: 4, time_a: 60, time_bridges: 30, time_cluster: 20,
    time_ricucitura: 60, time_mono: 120, workers: 8, log: false,
    use_decomposition: true
  };
  let step4 = { budget_s: 60, workers: 4, log: true,
                n_cycles: 3, ts_budget_per_cycle: 20,
                sa_T0: 10, sa_alpha: 0.995, tabu_size: 80 };
  let stepRooms = { time_limit_s: 30, workers: 4, log: true, prefer_home: true };
  let stepFull = {
    profile: 'small', workers: 8, time_assign: 30,
    phase_b: { ...step3 },
    budget_lns: 60, budget_sa: 30, budget_ts: 30, budget_ils: 60
  };

  onMount(reloadRuns);
  async function reloadRuns() {
    try { runs = (await api.get('/api/optimize/runs?limit=15')); }
    catch (e) { flash('Backend non raggiungibile: ' + e.message, 'error'); }
  }

  async function go(path, payload) {
    try {
      const r = await api.post(path, payload);
      runId = r.run_id;
      flash('Run #' + runId + ' avviato', 'success');
      reloadRuns();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  function onEnd() {
    refreshDataset();
    reloadRuns();
  }

  // Step shortcuts
  const launchMock = () => go('/api/dataset/mock', step1);
  const launchImport = () => go('/api/dataset/import-profile', step1import);
  const launchAssignment = () => go('/api/optimize/assignment', step2);
  const launchPhaseB = () => go('/api/optimize/phase-b', step3);
  const launchMeta = (stage) => go('/api/optimize/meta/' + stage, step4);
  const launchRooms = () => go('/api/optimize/rooms', stepRooms);
  const launchFull = () => go('/api/optimize/full-pipeline', stepFull);
</script>

<div class="space-y-6">
  <h1>Workflow di ottimizzazione</h1>

  <p class="text-sm text-ink-500 max-w-3xl">
    Ogni step puo essere lanciato singolarmente o in catena. Tra uno step e l'altro
    puoi tornare alle pagine CRUD per modificare a mano vincoli, cattedre, e singole
    lezioni. Il log live arriva via SSE dal backend.
  </p>

  <div class="grid lg:grid-cols-2 gap-6">
    <!-- Step 1 -->
    <div class="card p-5">
      <h2 class="mb-3">1) Genera / carica scuola</h2>
      <div class="grid grid-cols-2 gap-3">
        <div class="field">
          <label>Profilo (mock)</label>
          <select bind:value={step1.profile}>
            <option value="small">small</option>
            <option value="medium">medium</option>
            <option value="big">big</option>
            <option value="huge">huge</option>
            <option value="superhuge">superhuge</option>
          </select>
        </div>
        <div class="field">
          <label>Mode</label>
          <select bind:value={step1.mode}>
            <option value="aggregated">aggregated</option>
            <option value="tight">tight</option>
            <option value="legacy">legacy</option>
          </select>
        </div>
        <div class="field">
          <label>Margin</label>
          <input type="number" step="0.01" bind:value={step1.margin}/>
        </div>
        <div class="field">
          <label>Ore-cattedra base</label>
          <input type="number" bind:value={step1.base_max_hours}/>
        </div>
      </div>
      <div class="flex gap-2 mt-3">
        <button class="btn-primary" on:click={launchMock}>Genera mock</button>
        <button class="btn" on:click={launchImport}>Importa pickle ({step1import.profile})</button>
      </div>
    </div>

    <!-- Step 2: Phase A with criterion selector + custom DSL -->
    <PhaseACard
      bind:time_limit_s={step2.time_limit_s}
      bind:workers={step2.workers}
      bind:log={step2.log}
      onLaunch={(p) => go('/api/optimize/assignment', p)}
    />

    <!-- Step 3 -->
    <div class="card p-5">
      <h2 class="mb-3">3) Schedulazione orario (Phase B)</h2>
      <div class="grid grid-cols-3 gap-3">
        <div class="field"><label>K cluster</label><input type="number" bind:value={step3.k}/></div>
        <div class="field"><label>time A (day_count)</label><input type="number" bind:value={step3.time_a}/></div>
        <div class="field"><label>time bridges</label><input type="number" bind:value={step3.time_bridges}/></div>
        <div class="field"><label>time cluster</label><input type="number" bind:value={step3.time_cluster}/></div>
        <div class="field"><label>time ricucitura</label><input type="number" bind:value={step3.time_ricucitura}/></div>
        <div class="field"><label>time monolitico</label><input type="number" bind:value={step3.time_mono}/></div>
        <div class="field"><label>workers</label><input type="number" bind:value={step3.workers}/></div>
        <label class="flex gap-2 text-sm col-span-3"><input type="checkbox" bind:checked={step3.use_decomposition}/> Decomposizione spettrale</label>
      </div>
      <button class="btn-primary mt-3" on:click={launchPhaseB}>Avvia Phase B</button>
    </div>

    <!-- Step 4-7 metaheuristics -->
    <div class="card p-5">
      <h2 class="mb-3">4-7) Metaeuristiche</h2>
      <div class="grid grid-cols-3 gap-3">
        <div class="field"><label>Budget (s)</label><input type="number" bind:value={step4.budget_s}/></div>
        <div class="field"><label>Workers</label><input type="number" bind:value={step4.workers}/></div>
        <div class="field"><label>SA T0</label><input type="number" step="0.1" bind:value={step4.sa_T0}/></div>
        <div class="field"><label>SA alpha</label><input type="number" step="0.001" bind:value={step4.sa_alpha}/></div>
        <div class="field"><label>TS tabu size</label><input type="number" bind:value={step4.tabu_size}/></div>
        <div class="field"><label>ILS cycles</label><input type="number" bind:value={step4.n_cycles}/></div>
      </div>
      <div class="flex gap-2 mt-3">
        <button class="btn-primary" on:click={() => launchMeta('lns')}>4) LNS</button>
        <button class="btn-primary" on:click={() => launchMeta('sa')}>5) SA</button>
        <button class="btn-primary" on:click={() => launchMeta('ts')}>6) TS</button>
        <button class="btn-primary" on:click={() => launchMeta('ils')}>7) ILS</button>
      </div>
    </div>

    <!-- Step rooms -->
    <div class="card p-5">
      <h2 class="mb-3">8) Assegna aule</h2>
      <div class="grid grid-cols-2 gap-3">
        <div class="field"><label>Time-limit (s)</label><input type="number" bind:value={stepRooms.time_limit_s}/></div>
        <div class="field"><label>Workers</label><input type="number" bind:value={stepRooms.workers}/></div>
        <label class="flex gap-2 text-sm col-span-2"><input type="checkbox" bind:checked={stepRooms.prefer_home}/> Preferisci aula della classe</label>
      </div>
      <button class="btn-primary mt-3" on:click={launchRooms}>Avvia</button>
    </div>

    <!-- Step full -->
    <div class="card p-5">
      <h2 class="mb-3">9) Pipeline completa</h2>
      <p class="text-xs text-ink-500 mb-3">
        Esegue 2 -&gt; 3 -&gt; 4 -&gt; 5 -&gt; 6 -&gt; 7 in sequenza sulla scuola
        attualmente in DB. La step "Aule" non e inclusa per default; lanciala
        a parte dopo la pipeline.
      </p>
      <div class="grid grid-cols-3 gap-3">
        <div class="field"><label>Profilo (etichetta)</label><input bind:value={stepFull.profile}/></div>
        <div class="field"><label>Workers</label><input type="number" bind:value={stepFull.workers}/></div>
        <div class="field"><label>Time assignment</label><input type="number" bind:value={stepFull.time_assign}/></div>
        <div class="field"><label>Budget LNS</label><input type="number" bind:value={stepFull.budget_lns}/></div>
        <div class="field"><label>Budget SA</label><input type="number" bind:value={stepFull.budget_sa}/></div>
        <div class="field"><label>Budget TS</label><input type="number" bind:value={stepFull.budget_ts}/></div>
        <div class="field"><label>Budget ILS</label><input type="number" bind:value={stepFull.budget_ils}/></div>
      </div>
      <button class="btn-primary mt-3" on:click={launchFull}>Avvia pipeline completa</button>
    </div>
  </div>

  {#if runId}
    <RunLogPanel {runId} title="Run #{runId}" onEnd={onEnd}/>
  {/if}

  <section class="card p-5">
    <div class="flex items-baseline justify-between mb-3">
      <h2>Cronologia run</h2>
      <button class="btn !text-xs !px-2 !py-1" on:click={reloadRuns}>Refresh</button>
    </div>
    <div class="overflow-x-auto">
      <table class="tbl">
        <thead>
          <tr>
            <th>#</th><th>Tipo</th><th>Stato</th><th>Obj</th>
            <th>Metriche</th><th>Avviato</th><th>Durata</th><th>Sol.</th><th></th>
          </tr>
        </thead>
        <tbody>
          {#each runs as r}
            <tr>
              <td>#{r.id}</td>
              <td><span class="pill">{r.kind}</span></td>
              <td>
                <span class="pill"
                  class:pill-green={r.status === 'done'}
                  class:pill-red={r.status === 'failed'}
                  class:pill-blue={r.status === 'running'}>{r.status}</span>
              </td>
              <td>{r.obj_value ?? ''}</td>
              <td class="text-xs">{r.metrics ? Object.entries(r.metrics).map(([k,v]) => `${k}=${v}`).join(' ') : ''}</td>
              <td class="text-xs">{r.started_at?.split('T')[1]?.split('.')[0] ?? ''}</td>
              <td class="text-xs">
                {#if r.started_at && r.finished_at}
                  {Math.round((Date.parse(r.finished_at) - Date.parse(r.started_at)) / 1000)}s
                {/if}
              </td>
              <td class="text-xs">{r.solution_id ?? ''}</td>
              <td><button class="btn !text-xs !px-2 !py-1" on:click={() => (runId = r.id)}>log</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>
</div>
