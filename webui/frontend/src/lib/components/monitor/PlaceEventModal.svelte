<script>
  /**
   * Rich "Piazza" modal: lets the user pick a chain of optimization
   * steps to run on the selected events.
   *
   * Steps available (toggleable + draggable):
   *   - greedy   : the targeted HARD-feasible placer in
   *                run_place_event. Fast (<1s); fills missing hours.
   *   - phase_b  : full CP-SAT timetable rebuild (with the lock_mode
   *                applied beforehand so non-targets stay put).
   *   - lns / sa / ts / ils : metaeuristiche (one or more, any order).
   *
   * On submit:
   *   1. POST /api/monitor/events/temp-lock with lock_mode -> get
   *      back the list of aids we just locked.
   *   2. For each enabled step in user order:
   *        - fire the matching endpoint (/api/optimize/place-event,
   *          /api/optimize/phase-b, /api/optimize/meta/<stage>)
   *        - wait for SSE 'end' (or status=failed)
   *        - if failed: stop the chain, surface the error.
   *   3. Always (success or failure): POST /events/lock-batch with
   *      { event_ids: locked_aids, locked: false } to revert the
   *      temp-locks.
   *
   * Each step has its own collapsible parameters block; defaults
   * mirror the per-step cards in /optimize.
   */
  import { api, waitForRun } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import RunLogPanel from '$lib/components/RunLogPanel.svelte';

  export let open = false;
  export let eventIds = [];
  export let summaries = [];
  export let onClose = () => { open = false; };
  export let onCompleted = () => {};

  // Lock mode (applied BEFORE the chain via /events/temp-lock).
  let lockMode = 'all_others_locked';

  // Step definitions. Each step has:
  //   key            stable identifier
  //   label          UI title
  //   enabled        tickbox
  //   params         per-step config object
  //   paramsOpen     whether the per-step params accordion is open
  // Order is the array order; user drags to reorder.
  function defaultSteps() {
    return [
      { key: 'greedy', label: 'Greedy placer (rapido, HARD-only)',
        enabled: true, paramsOpen: false,
        params: { prefer_pref: false } },
      { key: 'phase_b', label: 'CP-SAT (Phase B)',
        enabled: false, paramsOpen: false,
        params: { k: 4, time_a: 30, time_bridges: 30, time_cluster: 20,
                  time_ricucitura: 60, time_mono: 120, workers: 4,
                  use_decomposition: true } },
      { key: 'lns', label: 'LNS (Large Neighborhood Search)',
        enabled: false, paramsOpen: false,
        params: { budget_s: 60, workers: 4 } },
      { key: 'sa', label: 'SA (Simulated Annealing)',
        enabled: false, paramsOpen: false,
        params: { budget_s: 30, sa_T0: 10, sa_alpha: 0.995 } },
      { key: 'ts', label: 'TS (Tabu Search)',
        enabled: false, paramsOpen: false,
        params: { budget_s: 30, tabu_size: 80 } },
      { key: 'ils', label: 'ILS (Iterated Local Search)',
        enabled: false, paramsOpen: false,
        params: { budget_s: 60, n_cycles: 3, ts_budget_per_cycle: 20 } },
    ];
  }
  let steps = defaultSteps();

  // Drag-and-drop reorder
  let dragIdx = null;
  function onDragStart(i, ev) {
    dragIdx = i;
    ev.dataTransfer.effectAllowed = 'move';
    try { ev.dataTransfer.setData('text/plain', String(i)); } catch (_) {}
  }
  function onDragOver(ev) { ev.preventDefault(); }
  function onDrop(i, ev) {
    ev.preventDefault();
    if (dragIdx === null || dragIdx === i) { dragIdx = null; return; }
    const next = steps.slice();
    const [moved] = next.splice(dragIdx, 1);
    next.splice(i, 0, moved);
    steps = next;
    dragIdx = null;
  }

  // Chain runner state
  let busy = false;
  let chainCurrentRunId = null;        // run id currently being streamed
  let chainCurrentStepKey = null;
  let chainHistory = [];                // [{step, run_id, status}]
  let chainError = null;

  $: if (open) {
    busy = false;
    chainCurrentRunId = null;
    chainCurrentStepKey = null;
    chainHistory = [];
    chainError = null;
    steps = defaultSteps();
    lockMode = 'all_others_locked';
  }

  function endpointFor(stepKey, params) {
    if (stepKey === 'greedy') {
      return {
        url: '/api/optimize/place-event',
        body: {
          event_ids: eventIds,
          lock_mode: lockMode,
          prefer_pref: !!params.prefer_pref,
        },
      };
    }
    if (stepKey === 'phase_b') {
      return {
        url: '/api/optimize/phase-b',
        body: { ...params, log: false },
      };
    }
    if (['lns', 'sa', 'ts', 'ils'].includes(stepKey)) {
      return {
        url: '/api/optimize/meta/' + stepKey,
        body: { ...params, log: false },
      };
    }
    return null;
  }

  async function runChain() {
    if (eventIds.length === 0) {
      flash('Nessun evento selezionato.', 'error');
      return;
    }
    const enabled = steps.filter((s) => s.enabled);
    if (enabled.length === 0) {
      flash('Nessuno step abilitato.', 'error');
      return;
    }
    busy = true;
    chainHistory = [];
    chainError = null;
    let tempLocked = [];
    try {
      // 1. Apply temp-lock per lock_mode
      const r = await api.post('/api/monitor/events/temp-lock', {
        event_ids: eventIds,
        lock_mode: lockMode,
      });
      tempLocked = r.locked_aids || [];

      // 2. Run each enabled step in order
      for (const step of enabled) {
        chainCurrentStepKey = step.key;
        const ep = endpointFor(step.key, step.params);
        if (!ep) continue;
        const r2 = await api.post(ep.url, ep.body);
        const sub_id = r2.run_id;
        chainCurrentRunId = sub_id;
        let last_status = 'running';
        try {
          const fin = await waitForRun(sub_id, {
            onStatus: (s) => { last_status = s.status; },
          });
          last_status = fin.status;
        } catch (e) {
          last_status = 'sse_error';
        }
        chainHistory = [...chainHistory, {
          step: step.key, run_id: sub_id, status: last_status,
        }];
        if (last_status === 'failed') {
          chainError = `Step ${step.key} (run #${sub_id}) e' fallito; `
                      + 'apri il tab Runs per il dettaglio.';
          break;
        }
      }
      chainCurrentStepKey = null;
      chainCurrentRunId = null;
    } catch (e) {
      chainError = e?.message || String(e);
    } finally {
      // 3. Revert temp-lock (best effort)
      if (tempLocked.length) {
        try {
          await api.post('/api/monitor/events/lock-batch', {
            event_ids: tempLocked, locked: false,
          });
        } catch (e) {
          console.warn('Failed to revert temp-locks', tempLocked, e);
        }
      }
      busy = false;
      onCompleted();
      if (!chainError) {
        flash('Pipeline di piazzamento completata.', 'success');
      }
    }
  }
</script>

<Modal {open} title={`Piazza ${eventIds.length} eventi`} {onClose}>
  <div class="space-y-3 text-sm">
    {#if summaries.length}
      <div class="card !shadow-none p-2 bg-ink-50">
        <div class="text-xs text-ink-500 mb-1">Eventi selezionati ({summaries.length}):</div>
        <ul class="text-xs list-disc pl-5 max-h-32 overflow-y-auto">
          {#each summaries as s}
            <li><strong>{s.teacher_display}</strong>
                - {s.class_name} / {s.subject}</li>
          {/each}
        </ul>
      </div>
    {/if}

    <!-- Lock mode -->
    <details class="card p-3 bg-ink-50/40" open>
      <summary class="text-sm font-medium cursor-pointer">
        Vincolo sugli altri eventi (lock_mode)
      </summary>
      <div class="mt-2 space-y-2">
        <label class="flex items-start gap-2 text-xs">
          <input type="radio" bind:group={lockMode}
                 value="all_others_locked" class="mt-0.5"/>
          <span><strong>Tutti gli altri eventi sono lockati</strong>
            (default): solo i target vengono mossi; gli altri sono
            temporaneamente bloccati durante la pipeline e sbloccati
            alla fine.</span>
        </label>
        <label class="flex items-start gap-2 text-xs">
          <input type="radio" bind:group={lockMode}
                 value="same_class_or_teacher_movable" class="mt-0.5"/>
          <span><strong>Solo eventi della stessa classe o docente
            possono spostarsi</strong>: i siblings possono spostarsi,
            il resto della scuola resta fermo.</span>
        </label>
        <label class="flex items-start gap-2 text-xs">
          <input type="radio" bind:group={lockMode}
                 value="all_others_movable" class="mt-0.5"/>
          <span><strong>Tutti gli altri eventi possono spostarsi</strong>:
            massima liberta', massimo rimescolamento.</span>
        </label>
      </div>
    </details>

    <!-- Steps: draggable + tickable + collapsible per-step params -->
    <div class="card p-3 space-y-2">
      <div class="text-sm font-medium flex items-baseline gap-2">
        Pipeline
        <span class="text-xs font-normal text-ink-500">
          (trascina per riordinare, ticka per abilitare)
        </span>
      </div>
      {#each steps as s, i (s.key)}
        <div class="border border-ink-200 rounded bg-white"
             class:opacity-50={!s.enabled}
             class:bg-ink-50={dragIdx === i}>
          <div class="flex items-center gap-2 px-2 py-1.5"
               draggable="true"
               role="button" tabindex="-1"
               on:dragstart={(ev) => onDragStart(i, ev)}
               on:dragover={onDragOver}
               on:drop={(ev) => onDrop(i, ev)}>
            <span class="cursor-grab text-ink-400" title="Trascina per riordinare">&#x2630;</span>
            <input type="checkbox" bind:checked={s.enabled}/>
            <span class="text-sm flex-1">{s.label}</span>
            <span class="text-xs text-ink-400">{i + 1}</span>
            <button class="text-xs text-accent-500 hover:underline"
                    on:click={() => (s.paramsOpen = !s.paramsOpen)}>
              {s.paramsOpen ? 'nascondi parametri' : 'parametri'}
            </button>
          </div>
          {#if s.paramsOpen}
            <div class="border-t border-ink-200 p-2 grid grid-cols-3 gap-2">
              {#if s.key === 'greedy'}
                <label class="text-xs col-span-3 flex items-center gap-2">
                  <input type="checkbox" bind:checked={s.params.prefer_pref}/>
                  Preferisci slot PREFERRED del docente (HARD non si
                  rispettano comunque)
                </label>
              {:else if s.key === 'phase_b'}
                <div class="field"><label>K cluster</label>
                  <input type="number" bind:value={s.params.k}/></div>
                <div class="field"><label>time A</label>
                  <input type="number" bind:value={s.params.time_a}/></div>
                <div class="field"><label>time bridges</label>
                  <input type="number" bind:value={s.params.time_bridges}/></div>
                <div class="field"><label>time cluster</label>
                  <input type="number" bind:value={s.params.time_cluster}/></div>
                <div class="field"><label>time ricucitura</label>
                  <input type="number" bind:value={s.params.time_ricucitura}/></div>
                <div class="field"><label>time monolitico</label>
                  <input type="number" bind:value={s.params.time_mono}/></div>
                <div class="field"><label>workers</label>
                  <input type="number" bind:value={s.params.workers}/></div>
                <label class="text-xs col-span-3 flex items-center gap-2">
                  <input type="checkbox" bind:checked={s.params.use_decomposition}/>
                  Decomposizione spettrale
                </label>
              {:else if s.key === 'lns'}
                <div class="field"><label>budget (s)</label>
                  <input type="number" bind:value={s.params.budget_s}/></div>
                <div class="field"><label>workers</label>
                  <input type="number" bind:value={s.params.workers}/></div>
              {:else if s.key === 'sa'}
                <div class="field"><label>budget (s)</label>
                  <input type="number" bind:value={s.params.budget_s}/></div>
                <div class="field"><label>T0</label>
                  <input type="number" step="0.1" bind:value={s.params.sa_T0}/></div>
                <div class="field"><label>alpha</label>
                  <input type="number" step="0.001" bind:value={s.params.sa_alpha}/></div>
              {:else if s.key === 'ts'}
                <div class="field"><label>budget (s)</label>
                  <input type="number" bind:value={s.params.budget_s}/></div>
                <div class="field"><label>tabu size</label>
                  <input type="number" bind:value={s.params.tabu_size}/></div>
              {:else if s.key === 'ils'}
                <div class="field"><label>budget (s)</label>
                  <input type="number" bind:value={s.params.budget_s}/></div>
                <div class="field"><label>n_cycles</label>
                  <input type="number" bind:value={s.params.n_cycles}/></div>
                <div class="field"><label>ts budget/cycle</label>
                  <input type="number" bind:value={s.params.ts_budget_per_cycle}/></div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>

    <!-- Live chain progress -->
    {#if chainHistory.length || chainCurrentRunId || chainError}
      <div class="card p-3 space-y-1 bg-emerald-50/40">
        <div class="text-sm font-medium">Pipeline progress</div>
        {#each chainHistory as h}
          <div class="text-xs flex items-center gap-2">
            <span class="pill !text-[10px]">{h.step}</span>
            <span class="pill !text-[10px]"
                  class:pill-green={h.status === 'done'}
                  class:pill-red={h.status === 'failed'}>
              {h.status}
            </span>
            <a class="text-accent-500 underline text-[10px]"
               href={`/runs#${h.run_id}`} target="_blank" rel="noreferrer">
              run #{h.run_id}
            </a>
          </div>
        {/each}
        {#if chainCurrentStepKey}
          <div class="text-xs flex items-center gap-2">
            <span class="pill !text-[10px]">{chainCurrentStepKey}</span>
            <span class="pill pill-blue !text-[10px]">running</span>
          </div>
        {/if}
        {#if chainError}
          <div class="text-xs text-red-700 bg-red-50 border-red-300
                      border p-2 rounded">
            {chainError}
          </div>
        {/if}
      </div>
    {/if}

    {#if chainCurrentRunId}
      <RunLogPanel runId={chainCurrentRunId}
                   title={`Log step ${chainCurrentStepKey}`}/>
    {/if}

    <div class="flex justify-end gap-2 pt-3 border-t border-ink-100">
      <button class="btn" on:click={onClose} disabled={busy}>
        {chainHistory.length ? 'Chiudi' : 'Annulla'}
      </button>
      {#if !busy}
        <button class="btn-primary" on:click={runChain}
                disabled={eventIds.length === 0
                            || steps.filter((s) => s.enabled).length === 0}>
          Avvia pipeline
        </button>
      {:else}
        <span class="text-sm text-ink-500 italic self-center">
          esecuzione in corso...
        </span>
      {/if}
    </div>
  </div>
</Modal>
