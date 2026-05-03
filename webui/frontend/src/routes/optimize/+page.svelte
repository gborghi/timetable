<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import { OPTIMIZE_DEFAULTS } from '$lib/constants';
  import RunLogPanel from '$lib/components/RunLogPanel.svelte';
  import PhaseACard from '$lib/components/optimize/PhaseACard.svelte';
  import AdvancedTechniquesCard from
    '$lib/components/optimize/AdvancedTechniquesCard.svelte';

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
    use_decomposition: true,
    optimize_rooms: false,
    rooms_time_limit_s: 30,
    rooms_prefer_home: true,
  };
  let step4 = { budget_s: 60, workers: 4, log: true,
                n_cycles: 3, ts_budget_per_cycle: 20,
                sa_T0: 10, sa_alpha: 0.995, tabu_size: 80,
                optimize_rooms: false,
                rooms_time_limit_s: 30,
                rooms_prefer_home: true };
  let stepRooms = { time_limit_s: 30, workers: 4, log: true, prefer_home: true };

  // Decomposition strategies (card 10).
  let decompTemporal = {
    pre_distribution_time: 30, day_time: 30,
    parallel_workers: 6, max_iterations: 3,
  };
  let decompMetis = {
    k: 0,                    // 0 means auto (sqrt(n_classes))
    imbalance: 1.05,
    time_per_cluster: 60, time_bridges: 60,
  };
  let decompCurriculum = {
    min_cluster_size: 3,
    time_per_cluster: 60, time_bridges: 60,
    manual_groupings: '',  // user-provided JSON like {"linguistico":"_misto"}
  };
  let decompRecommendation = null;
  let decompRecommendationLoading = false;
  let decompRecommendationError = '';
  async function fetchDecompRecommendation() {
    decompRecommendationLoading = true;
    decompRecommendationError = '';
    try {
      decompRecommendation = await api.get(
        '/api/optimize/decomposition/recommend');
    } catch (e) {
      decompRecommendationError = e.message || String(e);
    } finally {
      decompRecommendationLoading = false;
    }
  }
  async function launchDecomposition(method, params) {
    try {
      const r = await api.post(
        '/api/optimize/decomposition/' + method, params || {});
      runId = r.run_id;
      flash('Run #' + runId + ' avviato', 'success');
      reloadRuns();
    } catch (e) {
      // Backend returns 501 for methods whose solve-loop wiring is on
      // the roadmap; surface that as a clear, non-scary toast.
      flash('Decomposizione ' + method + ': ' + (e.message || e), 'error');
    }
  }
  // Pipeline (card 9): user-defined ordered list of {key,label,enabled}.
  // Drag a row to reorder; tick to include/exclude. Each phase_b/meta
  // step honours its OWN optimize_rooms toggle on cards 3 / 4-7 -- the
  // pipeline itself does not have a separate rooms toggle.
  const PIPELINE_LABEL = {
    hall_check: 'Pre-check Hall (diagnostico)',
    phase_a: '2) Assegnazione (Phase A)',
    decomp_spectral:   '3a) Decomposizione spettrale',
    decomp_temporal:   '3b) Decomposizione temporale (per giorno)',
    decomp_metis:      '3c) Decomposizione METIS (k-way)',
    decomp_curriculum: '3d) Decomposizione per curriculum',
    phase_b: '3) Schedulazione orario (Phase B)',
    cg:      'Column Generation (alternativo a Phase B)',
    lagrangian: 'Lagrangian Relaxation (subgradient)',
    lns:     '4) LNS',
    alns:    '4-bis) ALNS (Adaptive LNS)',
    sa:      '5) SA',
    ts:      '6) TS',
    vns:     '6-bis) VNS (Variable Neighbourhood Search)',
    ils:     '7) ILS',
    rooms:   '8) Assegna aule (indipendente)',
  };
  // Default pipeline. Order:
  //   - Hall pre-check (ON, optional structural diagnostic)
  //   - phase_a, phase_b (ON)
  //   - lns + alns (ON; ALNS replaces or follows LNS)
  //   - sa, ts (ON)
  //   - vns (OFF; rifinitura, attivabile per qualita' massima)
  //   - ils (ON)
  //   - cg, rooms (OFF; specialised stages)
  let pipelineList = [
    { key: 'hall_check',        enabled: true  },
    { key: 'phase_a',           enabled: true  },
    { key: 'decomp_spectral',   enabled: true  },
    { key: 'decomp_temporal',   enabled: false },
    { key: 'decomp_metis',      enabled: false },
    { key: 'decomp_curriculum', enabled: false },
    { key: 'phase_b',           enabled: true  },
    { key: 'cg',                enabled: false },
    { key: 'lns',               enabled: true  },
    { key: 'alns',              enabled: true  },
    { key: 'sa',                enabled: true  },
    { key: 'ts',                enabled: true  },
    { key: 'vns',               enabled: false },
    { key: 'lagrangian',        enabled: false },
    { key: 'ils',               enabled: true  },
    { key: 'rooms',             enabled: false },
  ];
  let stepFull = {
    profile: '', workers: 8, time_assign: 30,
    budget_lns: 60, budget_sa: 30, budget_ts: 30, budget_ils: 60,
  };

  // Active dataset profile -- read on mount + after each operation
  // so the pipeline label/profile reflects the actual school in DB.
  let activeProfile = '';

  // Drag-and-drop state for the pipeline list (HTML5 native).
  let dragSrcIdx = null;
  function onDragStart(i, ev) {
    dragSrcIdx = i;
    ev.dataTransfer.effectAllowed = 'move';
    // Required for Firefox to actually start the drag
    try { ev.dataTransfer.setData('text/plain', String(i)); } catch (_) {}
  }
  function onDragOver(ev) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'move'; }
  function onDrop(i, ev) {
    ev.preventDefault();
    if (dragSrcIdx === null || dragSrcIdx === i) { dragSrcIdx = null; return; }
    const next = pipelineList.slice();
    const [moved] = next.splice(dragSrcIdx, 1);
    next.splice(i, 0, moved);
    pipelineList = next;
    dragSrcIdx = null;
  }
  function onDragEnd() { dragSrcIdx = null; }

  onMount(async () => {
    await Promise.all([reloadRuns(), reloadActiveProfile()]);
    // Fire-and-forget: best-effort recommendation fetch. If the
    // school has no Phase A yet the endpoint returns 409 and we
    // surface that gracefully in the card.
    fetchDecompRecommendation();
  });
  async function reloadRuns() {
    try { runs = (await api.get('/api/optimize/runs?limit=15')); }
    catch (e) { flash('Backend non raggiungibile: ' + e.message, 'error'); }
  }
  async function reloadActiveProfile() {
    try {
      const s = await api.get('/api/dataset/state');
      activeProfile = s.last_profile || '';
      // Default the pipeline label to the active profile name when
      // the user hasn't picked one explicitly. This makes the run
      // entry in /runs show the right school name (e.g. "huge")
      // instead of stale 'small' default.
      if (activeProfile && !stepFull.profile) {
        stepFull.profile = activeProfile;
      }
    } catch (_) { /* swallow */ }
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
    reloadActiveProfile();
  }

  // Step shortcuts
  const launchMock = () => go('/api/dataset/mock', step1);
  const launchImport = () => go('/api/dataset/import-profile', step1import);
  const launchAssignment = () => go('/api/optimize/assignment', step2);
  const launchPhaseB = () => go('/api/optimize/phase-b', step3);
  const launchMeta = (stage) => go('/api/optimize/meta/' + stage, step4);
  const launchRooms = () => go('/api/optimize/rooms', stepRooms);
  const launchFull = () => {
    const steps = pipelineList.filter((it) => it.enabled).map((it) => it.key);
    if (steps.length === 0) {
      flash('Pipeline vuota: tickare almeno uno step.', 'error');
      return;
    }
    const payload = {
      ...stepFull,
      // Use the ACTUAL active profile from /api/dataset/state for
      // the run label, falling back to whatever the user typed in
      // the field (or the active profile if both are empty).
      profile: stepFull.profile || activeProfile || 'unknown',
      steps,
      // Phase B inside the pipeline reuses step3 (so its rooms toggle
      // and parameters come from card 3).
      phase_b: { ...step3 },
      // Meta steps share one rooms toggle on card 4-7.
      meta_optimize_rooms: !!step4.optimize_rooms,
      meta_rooms_time_limit_s: step4.rooms_time_limit_s,
      meta_rooms_prefer_home: !!step4.rooms_prefer_home,
    };
    go('/api/optimize/full-pipeline', payload);
  };
</script>

<div class="space-y-6">
  <h1>Workflow di ottimizzazione</h1>

  <p class="text-sm text-ink-500 max-w-3xl">
    Ogni step puo essere lanciato singolarmente o in catena. Tra uno step e l'altro
    puoi tornare alle pagine CRUD per modificare a mano vincoli, cattedre, e singole
    lezioni. Il log live arriva via SSE dal backend.
  </p>

  <!-- CSS columns layout: cards still take half-width on lg+ but
       each one keeps its NATURAL height instead of being stretched
       to match its row sibling. The browser packs cards vertically
       column-by-column, top-to-bottom, like a Pinterest board.
       Each direct child is `break-inside: avoid` so a single card
       never splits across columns. -->
  <div class="columns-1 lg:columns-2 gap-6 [&>*]:break-inside-avoid [&>*]:mb-6">
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
      <div class="mt-3 p-3 rounded border border-ink-200 bg-ink-50/40 space-y-2">
        <label class="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" bind:checked={step3.optimize_rooms}/>
          Ottimizza aule insieme a questo step
        </label>
        <p class="text-xs text-ink-500">
          Quando attivo, dopo Phase B la lezioni-aule (step 8) viene
          eseguita sulla soluzione appena prodotta -- utile per palestre
          e laboratori la cui capienza puo' rendere infeasibile la
          schedulazione.
        </p>
        <div class="grid grid-cols-2 gap-3">
          <div class="field">
            <label>Time-limit aule (s)</label>
            <input type="number" bind:value={step3.rooms_time_limit_s}
                   disabled={!step3.optimize_rooms}/>
          </div>
          <label class="flex items-center gap-2 text-sm self-end pb-2">
            <input type="checkbox" bind:checked={step3.rooms_prefer_home}
                   disabled={!step3.optimize_rooms}/>
            Preferisci aula della classe
          </label>
        </div>
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
      <div class="mt-3 p-3 rounded border border-ink-200 bg-ink-50/40 space-y-2">
        <label class="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" bind:checked={step4.optimize_rooms}/>
          Ottimizza aule insieme a questo step
        </label>
        <p class="text-xs text-ink-500">
          Quando attivo, dopo OGNI metaeuristica lanciata da qui (sia
          singolarmente sia dentro la pipeline) la lezioni-aule (step 8)
          viene eseguita sulla nuova soluzione attiva.
        </p>
        <div class="grid grid-cols-2 gap-3">
          <div class="field">
            <label>Time-limit aule (s)</label>
            <input type="number" bind:value={step4.rooms_time_limit_s}
                   disabled={!step4.optimize_rooms}/>
          </div>
          <label class="flex items-center gap-2 text-sm self-end pb-2">
            <input type="checkbox" bind:checked={step4.rooms_prefer_home}
                   disabled={!step4.optimize_rooms}/>
            Preferisci aula della classe
          </label>
        </div>
      </div>
      <div class="flex gap-2 mt-3">
        <button class="btn-primary" on:click={() => launchMeta('lns')}>4) LNS</button>
        <button class="btn-primary" on:click={() => launchMeta('sa')}>5) SA</button>
        <button class="btn-primary" on:click={() => launchMeta('ts')}>6) TS</button>
        <button class="btn-primary" on:click={() => launchMeta('ils')}>7) ILS</button>
      </div>
    </div>

    <!-- Step 4-bis: advanced techniques -->
    <AdvancedTechniquesCard
      onRunStarted={(rid) => { runId = rid; reloadRuns(); }}/>

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

    <!-- Card 10: Decomposition strategies -->
    <div class="card p-5">
      <h2 class="mb-1">10) Strategie di decomposizione</h2>
      <p class="text-xs text-ink-500 mb-3">
        Quattro strategie ortogonali per spezzare il problema di
        Phase B in sotto-problemi piu' piccoli. Ognuna restituisce
        cluster di classi e una lista di docenti-ponte. Si possono
        combinare nella pipeline: prima la primaria (spettrale,
        METIS o per curriculum), poi la temporale per parallelizzare
        sui sei giorni.
      </p>

      <!-- Suggerimento: auto-detect -->
      <div class="rounded border border-ink-200 bg-ink-50/40 p-3 mb-3">
        <div class="flex items-baseline justify-between gap-2 mb-1">
          <strong class="text-sm">Suggerimento (auto-detect)</strong>
          <button class="btn !text-xs !px-2 !py-1"
                  on:click={fetchDecompRecommendation}
                  disabled={decompRecommendationLoading}>
            {decompRecommendationLoading ? '...' : 'Ricalcola'}
          </button>
        </div>
        {#if decompRecommendationError}
          <p class="text-xs text-red-600">{decompRecommendationError}</p>
        {:else if !decompRecommendation && !decompRecommendationLoading}
          <p class="text-xs text-ink-500">
            Nessun dato ancora. Esegui Phase A oppure premi
            <em>Ricalcola</em>.
          </p>
        {:else if decompRecommendation}
          <p class="text-xs">
            <strong>Strategia primaria consigliata:</strong>
            <code class="pill pill-blue">{decompRecommendation.primary_strategy}</code>
            {#if decompRecommendation.combine_with_temporal}
              + temporale
            {/if}
            <span class="text-ink-500 ml-2">
              modularita {decompRecommendation.modularity}, densita {decompRecommendation.density}
            </span>
          </p>
          <p class="text-xs text-ink-500 mt-1">
            {decompRecommendation.motivation}
          </p>
        {/if}
      </div>

      <!-- Spectral (already wired through Phase B) -->
      <div class="rounded border border-ink-200 p-3 mb-3">
        <div class="flex items-baseline justify-between mb-1">
          <strong class="text-sm">3a) Decomposizione spettrale</strong>
          <span class="text-[10px] text-ink-500">grafo bipartito + Laplaciano</span>
        </div>
        <p class="text-xs text-ink-500 mb-2">
          Identifica cluster naturali nel grafo classe-docente
          attraverso il vettore di Fiedler. Brilla quando la
          modularita' e' alta (sopra 0.30). I parametri sono
          quelli della card 3 (Phase B).
        </p>
        <p class="text-[11px] text-ink-500">
          Avvio: dalla card 3 con
          <code>Decomposizione spettrale</code> ticked.
        </p>
      </div>

      <!-- Temporal -->
      <div class="rounded border border-ink-200 p-3 mb-3">
        <div class="flex items-baseline justify-between mb-1">
          <strong class="text-sm">3b) Decomposizione temporale (per giorno)</strong>
          <span class="text-[10px] text-ink-500">parallelizza sui 6 giorni</span>
        </div>
        <p class="text-xs text-ink-500 mb-2">
          Spezza il problema lungo l'asse del tempo: ciascun giorno
          della settimana diventa un sotto-problema separato,
          risolvibile in parallelo. Sempre applicabile, ortogonale
          alle altre strategie.
        </p>
        <div class="grid grid-cols-2 gap-3">
          <div class="field"><label>time pre-distribuzione (s)</label>
            <input type="number" bind:value={decompTemporal.pre_distribution_time}/></div>
          <div class="field"><label>time per giorno (s)</label>
            <input type="number" bind:value={decompTemporal.day_time}/></div>
          <div class="field"><label>workers paralleli</label>
            <input type="number" bind:value={decompTemporal.parallel_workers}/></div>
          <div class="field"><label>max iterazioni</label>
            <input type="number" bind:value={decompTemporal.max_iterations}/></div>
        </div>
        <button class="btn-primary !text-xs mt-2"
                on:click={() => launchDecomposition('temporal', decompTemporal)}>
          Avvia stage standalone
        </button>
      </div>

      <!-- METIS -->
      <div class="rounded border border-ink-200 p-3 mb-3">
        <div class="flex items-baseline justify-between mb-1">
          <strong class="text-sm">3c) Decomposizione METIS (k-way)</strong>
          <span class="text-[10px] text-ink-500">richiede pymetis</span>
        </div>
        <p class="text-xs text-ink-500 mb-2">
          Partitioning bilanciato attraverso multilevel matching.
          Funziona bene su grafi densi privi di cluster naturali,
          dove la spettrale fatica.
        </p>
        <div class="grid grid-cols-2 gap-3">
          <div class="field"><label>k (0 = auto sqrt(n))</label>
            <input type="number" bind:value={decompMetis.k}/></div>
          <div class="field"><label>tolleranza sbilanciamento</label>
            <input type="number" step="0.01" bind:value={decompMetis.imbalance}/></div>
          <div class="field"><label>time per cluster (s)</label>
            <input type="number" bind:value={decompMetis.time_per_cluster}/></div>
          <div class="field"><label>time bridges (s)</label>
            <input type="number" bind:value={decompMetis.time_bridges}/></div>
        </div>
        <button class="btn-primary !text-xs mt-2"
                on:click={() => launchDecomposition('metis', decompMetis)}>
          Avvia stage standalone
        </button>
      </div>

      <!-- Curriculum -->
      <div class="rounded border border-ink-200 p-3">
        <div class="flex items-baseline justify-between mb-1">
          <strong class="text-sm">3d) Decomposizione per curriculum</strong>
          <span class="text-[10px] text-ink-500">un cluster per indirizzo</span>
        </div>
        <p class="text-xs text-ink-500 mb-2">
          Partiziona le classi per indirizzo di studio
          (curriculum_id). Cluster prevedibili e interpretabili.
          I curricula con poche classi vengono accorpati in
          <code>_misto</code>.
        </p>
        <div class="grid grid-cols-2 gap-3">
          <div class="field"><label>min classi per cluster</label>
            <input type="number" bind:value={decompCurriculum.min_cluster_size}/></div>
          <div class="field"><label>time per cluster (s)</label>
            <input type="number" bind:value={decompCurriculum.time_per_cluster}/></div>
          <div class="field"><label>time bridges (s)</label>
            <input type="number" bind:value={decompCurriculum.time_bridges}/></div>
          <div class="field"><label>raggruppamenti manuali (JSON)</label>
            <input type="text" placeholder='{"linguistico":"_misto"}'
                   bind:value={decompCurriculum.manual_groupings}/></div>
        </div>
        <button class="btn-primary !text-xs mt-2"
                on:click={() => launchDecomposition('curriculum', decompCurriculum)}>
          Avvia stage standalone
        </button>
      </div>
    </div>

    <!-- Step 9: pipeline (draggable + tickable) -->
    <div class="card p-5">
      <h2 class="mb-3">9) Pipeline completa</h2>
      <p class="text-xs text-ink-500 mb-3">
        Trascina le righe per riordinare gli step e usa la spunta per
        includere o escludere uno step dalla pipeline. La pipeline esegue
        gli step abilitati nell'ordine indicato.
        Le quattro decomposizioni (3a-3d) sono mutuamente
        combinabili: tipicamente si abilita una primaria fra
        <em>spettrale</em>, <em>METIS</em> e <em>per curriculum</em>,
        eventualmente affiancata dalla <em>temporale</em> per
        parallelizzare sui sei giorni.
        <strong>Assegna aule (step 8)</strong> e' presente nella lista
        come step opzionale: se ticked viene eseguito come elemento
        indipendente nel punto in cui appare nell'ordine. In
        alternativa, per piegare l'assegnazione aule INSIEME al CP-SAT
        o alle metaeuristiche, ticka "Ottimizza aule insieme a questo
        step" sulle card 3 (Phase B) e 4-7 (Metaeuristiche).
      </p>
      <div class="grid grid-cols-3 gap-3">
        <div class="field">
          <label>Profilo (etichetta)
            {#if activeProfile}
              <span class="text-[10px] text-ink-500">
                — attivo: <code>{activeProfile}</code>
              </span>
            {/if}
          </label>
          <input bind:value={stepFull.profile}
                 placeholder={activeProfile || '(scuola attiva)'}/>
        </div>
        <div class="field"><label>Workers</label><input type="number" bind:value={stepFull.workers}/></div>
        <div class="field"><label>Time assignment</label><input type="number" bind:value={stepFull.time_assign}/></div>
        <div class="field"><label>Budget LNS</label><input type="number" bind:value={stepFull.budget_lns}/></div>
        <div class="field"><label>Budget SA</label><input type="number" bind:value={stepFull.budget_sa}/></div>
        <div class="field"><label>Budget TS</label><input type="number" bind:value={stepFull.budget_ts}/></div>
        <div class="field"><label>Budget ILS</label><input type="number" bind:value={stepFull.budget_ils}/></div>
      </div>

      <ul class="mt-4 divide-y divide-ink-200 border border-ink-200 rounded select-none">
        {#each pipelineList as item, i (item.key)}
          <li class="flex items-center gap-3 px-3 py-2 bg-white"
              class:opacity-50={!item.enabled}
              class:bg-ink-50={dragSrcIdx === i}
              draggable="true"
              on:dragstart={(ev) => onDragStart(i, ev)}
              on:dragover={onDragOver}
              on:drop={(ev) => onDrop(i, ev)}
              on:dragend={onDragEnd}>
            <span class="cursor-grab text-ink-400 text-lg leading-none"
                  title="Trascina per riordinare">&#x2630;</span>
            <input type="checkbox" bind:checked={item.enabled}/>
            <span class="text-sm flex-1">{PIPELINE_LABEL[item.key]}</span>
            <span class="text-xs text-ink-400">{i + 1}</span>
          </li>
        {/each}
      </ul>

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
