<script>
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import { humanMetricsLine } from '$lib/metrics_labels';
  import { confirmDialog } from '$lib/confirm';
  import { datasetState, datasetEverLoaded, flash, refreshDataset, bumpMutation,
           workingHoursConfig, loadWorkingHoursConfig } from '$lib/stores';
  import { statoTappe } from '$lib/tappe';
  import PageHero from '$lib/components/PageHero.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import RunLogPanel from '$lib/components/RunLogPanel.svelte';
  import OnboardingChecklist from '$lib/components/dashboard/OnboardingChecklist.svelte';
  import EntityGraph from '$lib/components/dashboard/EntityGraph.svelte';
  import DbImportExportCard from '$lib/components/dashboard/DbImportExportCard.svelte';
  import ConstraintsImportExportCard from '$lib/components/dashboard/ConstraintsImportExportCard.svelte';
  import DecorIcon from '$lib/components/DecorIcon.svelte';
  import Button from '$lib/components/Button.svelte';

  // Graph panel: hidden by default; user clicks "Visualizza grafo" to
  // render. Mode toggle: classes-as-nodes vs teachers-as-nodes.
  let showGraph = false;
  let graphMode = 'classes';   // 'classes' | 'teachers'

  let availableProfiles = [];
  // Two independent dropdowns: section 1 ("Importa un profilo gia` calcolato")
  // pulls names from the on-disk pickle layout; section 2 ("Genera scuola
  // di test") uses the engine's hardcoded mock profile names. Sharing the
  // same variable made section 1 silently POST profile='small' (the
  // default) when 'small' wasn't actually on disk -> 404 and an empty UI.
  let importProfile = '';
  let mockProfile = 'small';
  let useOptimized = true;
  let importCurricula = true;
  let importClassrooms = true;
  let importStudents = true;
  let mockMode = 'aggregated';
  let mockMargin = 0.05;
  let baseMaxHours = 18;
  let busyImport = false;
  let busyMock = false;
  let runId = null;

  onMount(async () => {
    // Le quattro card di tappa hanno bisogno delle Ore per sapere se la
    // tappa 1 e' completa: il layout non le carica.
    if ($workingHoursConfig == null) loadWorkingHoursConfig();
    try {
      availableProfiles = await api.get('/api/dataset/available-profiles');
      // Default to the first available profile so the bind:value matches
      // an actual <option> -- otherwise the dropdown displays the first
      // option visually but submits the (stale) initial value.
      if (availableProfiles.length > 0) {
        importProfile = availableProfiles[0].name;
      }
    } catch (e) {
      flash('Errore caricando profili: ' + e.message, 'error');
    }
  });

  // Il percorso in quattro tappe, con lo stato calcolato dai dati reali
  // (stessa logica dei nove passi del checklist: vedi $lib/tappe).
  $: tappe = statoTappe($datasetState, $workingHoursConfig);
  $: tappaCorrente = tappe.find((t) => t.corrente) ?? null;

  async function importPickle() {
    if (!importProfile) {
      flash('Nessun profilo disponibile da importare', 'error');
      return;
    }
    busyImport = true;
    try {
      const res = await api.post('/api/dataset/import-profile', {
        profile: importProfile,
        use_optimized: useOptimized,
        import_curricula: importCurricula,
        import_classrooms: importClassrooms,
        import_students: importStudents
      });
      runId = res.run_id;
      flash('Import lanciato (run #' + runId + ')', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally {
      busyImport = false;
    }
  }

  async function generateMock() {
    busyMock = true;
    try {
      const res = await api.post('/api/dataset/mock', {
        profile: mockProfile, mode: mockMode,
        margin: mockMargin, base_max_hours: baseMaxHours,
        custom_curricula: null
      });
      runId = res.run_id;
      flash('Mock generation lanciata (run #' + runId + ')', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally {
      busyMock = false;
    }
  }

  async function autoGenerateClassrooms() {
    // Use proportional defaults from the backend; the user can fine-tune
    // counts in the Aule page before regenerating.
    try {
      const sug = await api.get('/api/classrooms/suggested-counts');
      if (sug.n_classes === 0) {
        flash('Importa o genera prima una scuola', 'error');
        return;
      }
      const r = await api.post('/api/classrooms/auto-generate', {});
      flash('Aule generate: ' + r.created + ' (su ' + r.n_classes
            + ' classi). Apri la pagina Aule per personalizzare.',
            'success');
      await refreshDataset();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function clearAll() {
    if (!(await confirmDialog(
      'Cancella TUTTO il database: classi, docenti, aule, cattedre, '
      + 'vincoli e soluzioni. L\'operazione non è reversibile.',
      { title: 'Reset del database', confirmLabel: 'Cancella tutto' }))) return;
    try {
      await api.post('/api/dataset/clear?scope=all');
      await refreshDataset();
      flash('DB resettato', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  // SSE end-of-run hook: the worker thread wrote to the DB outside
  // the HTTP request lifecycle. Bump the mutationCounter to invalidate
  // every cached query; refreshDataset to repopulate the header pills
  // and Stato corrente cards.
  //
  // Belt-and-suspenders: re-poll a few times after the SSE end, in
  // case the underlying SQLite commit hasn't fully landed yet (the
  // worker thread + the main event loop see the same DB but the
  // ENGINE pool can briefly serve a connection with stale views).
  function onEnd() {
    bumpMutation();
    refreshDataset();
    // Re-poll at 250ms / 750ms / 1500ms / 3000ms after the end event.
    [250, 750, 1500, 3000].forEach((ms) => {
      setTimeout(() => { bumpMutation(); refreshDataset(); }, ms);
    });
  }

  // While a run is in progress, poll dataset/state every ~1.5s so the
  // header pills and Stato corrente cards reflect partial progress
  // (e.g. the assignment step writes Assignments before phase B even
  // starts).
  let runPollTimer = null;
  $: if (runId) startRunPolling();
  function startRunPolling() {
    if (runPollTimer) clearInterval(runPollTimer);
    runPollTimer = setInterval(() => refreshDataset(), 1500);
  }
  function stopRunPolling() {
    if (runPollTimer) { clearInterval(runPollTimer); runPollTimer = null; }
  }
  // Critical: clean up the polling timer when the user navigates
  // away from the dashboard. Without this, every visit to / with
  // runId set spawns another 1.5s polling timer that survives the
  // unmount, eventually accumulating into a "stuck" feel after
  // 3-4 tab switches.
  onDestroy(stopRunPolling);
  // Stop polling shortly after onEnd runs (the post-end retries above
  // cover the trailing window).
  function onEndAndStop() {
    onEnd();
    setTimeout(stopRunPolling, 4000);
  }

  // Le sette righe del riquadro "Scuola attiva", nell'ordine del design.
  $: statRows = [
    ['Classi',    $datasetState.classes],
    ['Docenti',   $datasetState.teachers],
    ['Materie',   $datasetState.subjects],
    ['Aule',      $datasetState.classrooms],
    ['Studenti',  $datasetState.students ?? 0],
    ['Cattedre',  $datasetState.assignments],
    ['Soluzioni', $datasetState.solutions],
  ];
</script>

<PageHero
  eyebrow={null}
  title="Il tuo orario, in quattro tappe"
  description={tappaCorrente
    ? `Sei alla tappa ${tappaCorrente.n}. Ogni tappa raccoglie le pagine che servono: puoi tornare indietro in qualsiasi momento senza perdere il lavoro fatto.`
    : 'Tutte le tappe sono complete: la scuola ha un orario. Da qui puoi rigenerarlo, modificarlo o gestire assenze e supplenze.'} />

<div class="space-y-6">
  <!-- ========== Il percorso + la scuola attiva ========== -->
  <section class="grid gap-4 lg:grid-cols-[1fr_270px] items-start">
    <div class="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
      {#each tappe as t}
        <a href={t.href}
           class="card relative flex flex-col gap-1 overflow-hidden p-4 pt-[18px]
                  transition-colors hover:border-ink-300 focus-ring
                  {t.corrente ? 'border-[1.5px] border-accent-500' : ''}
                  {!t.completa && !t.corrente
                     ? 'border-dashed border-line-dash bg-paper-soft' : ''}"
           data-testid="tappa-card"
           data-tappa={t.n}>
          <!-- Barra superiore: verde = fatta, oro = in corso, niente = da fare -->
          {#if t.completa}
            <span class="absolute inset-x-0 top-0 h-[3px] bg-[#2f6b3e]" aria-hidden="true"></span>
          {:else if t.corrente}
            <span class="absolute inset-x-0 top-0 h-[3px] bg-gold" aria-hidden="true"></span>
          {/if}

          <div class="flex items-center gap-2">
            {#if t.completa}
              <span class="inline-flex h-[17px] w-[17px] shrink-0 items-center
                           justify-center rounded-full bg-[#e6f0e8] text-[10px]
                           text-[#2f6b3e]" aria-hidden="true">✓</span>
            {:else}
              <span class="inline-flex h-[17px] w-[17px] shrink-0 items-center
                           justify-center rounded-full text-[10px] font-medium
                           {t.corrente ? 'bg-accent-100 text-accent-700'
                                       : 'bg-ink-100 text-ink-400'}"
                    aria-hidden="true">{t.n}</span>
            {/if}
            <span class="eyebrow">
              {t.corrente ? 'Tappa corrente' : `Tappa ${t.n}`}
            </span>
          </div>

          <h2 class="!text-[15px]">{t.label}</h2>
          <p class="text-[11.5px] leading-snug text-ink-400">{t.blurb}</p>
          <p class="mt-1 font-mono text-[10.5px] tabular-nums
                    {t.corrente ? 'text-accent-500 font-medium' : 'text-ink-300'}">
            {t.corrente ? 'Continua →' : t.meta}
          </p>
        </a>
      {/each}
    </div>

    <div class="card p-4" data-testid="scuola-attiva">
      <h2 class="!text-[15px]">Scuola attiva</h2>
      <dl class="mt-3 space-y-1">
        {#each statRows as [label, value]}
          <div class="flex items-baseline justify-between border-b border-ink-100 pb-1">
            <dt class="text-[11.5px] text-ink-500">{label}</dt>
            {#if $datasetEverLoaded}
              <dd class="font-mono text-[12.5px] tabular-nums">{value}</dd>
            {:else}
              <dd aria-hidden="true">
                <span class="inline-block h-3 w-6 animate-pulse rounded bg-ink-200"></span>
              </dd>
            {/if}
          </div>
        {/each}
      </dl>

      {#if $datasetState.active_solution}
        {@const sol = $datasetState.active_solution}
        {@const feasible = sol.metrics?.feasible}
        <div class="mt-3 space-y-1.5">
          {#if feasible != null}
            <span class={feasible ? 'pill-green' : 'pill-red'}
                  title="Fattibilita della soluzione attiva rispetto ai vincoli hard">
              {feasible ? '✓ Fattibile' : '✗ Non fattibile'}
            </span>
          {/if}
          <p class="text-[11.5px] text-ink-500">
            {sol.name} <span class="text-ink-300">({sol.kind})</span>
          </p>
          <p class="font-mono text-[11px] text-ink-500">obj={sol.obj_value}</p>
          {#if humanMetricsLine(sol.metrics)}
            <p class="text-[11px] leading-snug text-ink-400">{humanMetricsLine(sol.metrics)}</p>
          {/if}
        </div>
      {:else}
        <p class="mt-3 text-[11.5px] text-ink-400">
          Nessuna soluzione attiva.
        </p>
      {/if}
    </div>
  </section>

  <OnboardingChecklist />

  {#if runId}
    <RunLogPanel {runId} title="Output run #{runId}" onEnd={onEndAndStop} />
  {/if}

  <!-- ========== Strumenti: aperti solo quando servono ========== -->
  <section class="space-y-3">
    <p class="eyebrow">Strumenti — servono raramente</p>

    <Panel id="carica-scuola" open={true}
           title="Carica o genera una scuola"
           subtitle="importa un profilo o crea una scuola fittizia">
      <div class="grid gap-6 md:grid-cols-2">
        <div data-testid="dashboard-import-card">
          <div class="mb-3 flex items-baseline gap-2">
            <span class="font-mono text-[11px] text-ink-300">01</span>
            <h3>Importa un profilo già calcolato</h3>
          </div>
          <div class="space-y-3">
            <div class="field">
              <label>Profilo</label>
              {#if availableProfiles.length === 0}
                <div class="flex items-center gap-3" data-testid="dashboard-no-profiles">
                  <DecorIcon name="building" size={44} class="shrink-0 opacity-80" />
                  <p class="text-xs text-ink-500 italic">
                    Nessun profilo precalcolato trovato in
                    <code>engine/scripts/data/&lt;profile&gt;/</code>.
                    Genera una scuola fittizia qui accanto per popolare il DB.
                  </p>
                </div>
              {:else}
                <select bind:value={importProfile}
                        data-testid="dashboard-import-profile-select">
                  {#each availableProfiles as p}
                    <option value={p.name}
                            data-testid="dashboard-import-profile-option">{p.name}{p.has_optimized_solution ? '  (con soluzione ottimizzata)' : ''}</option>
                  {/each}
                </select>
              {/if}
            </div>
            <label class="flex items-center gap-2 text-[12.5px]">
              <input type="checkbox" bind:checked={useOptimized} />
              Usa la soluzione ottimizzata se disponibile
            </label>

            <div class="space-y-1 rounded-lg border border-ink-200 bg-paper-band p-2.5">
              <div class="eyebrow mb-1.5">Pool dati da generare insieme al profilo</div>
              <label class="flex items-center gap-2 text-[12.5px]">
                <input type="checkbox" bind:checked={importCurricula}/>
                Indirizzi (curricula): seed dei monte-ore mock + linkaggio classi
              </label>
              <label class="flex items-center gap-2 text-[12.5px]">
                <input type="checkbox" bind:checked={importClassrooms}/>
                Aule: una per classe + lab/palestre/biblioteca proporzionali
              </label>
              <label class="flex items-center gap-2 text-[12.5px]">
                <input type="checkbox" bind:checked={importStudents}/>
                Studenti: ~22 per classe (Faker, deterministico)
              </label>
            </div>

            <div class="flex items-center gap-3">
              <Button variant="primary"
                      loading={busyImport}
                      disabled={availableProfiles.length === 0}
                      onclick={importPickle}
                      data-testid="dashboard-import-btn">
                Importa
              </Button>
              <button class="btn" on:click={autoGenerateClassrooms}>
                Rigenera solo aule
              </button>
            </div>
          </div>
        </div>

        <div data-testid="dashboard-mock-card">
          <div class="mb-3 flex items-baseline gap-2">
            <span class="font-mono text-[11px] text-ink-300">02</span>
            <h3>Genera una scuola di test</h3>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div class="field">
              <label>Profilo</label>
              <select bind:value={mockProfile}
                      data-testid="dashboard-mock-profile-select">
                <option value="small">small</option>
                <option value="medium">medium</option>
                <option value="big">big</option>
                <option value="huge">huge</option>
                <option value="superhuge">superhuge</option>
              </select>
            </div>
            <div class="field">
              <label>Modalita</label>
              <select bind:value={mockMode}>
                <option value="aggregated">aggregated</option>
                <option value="tight">tight</option>
                <option value="legacy">legacy</option>
              </select>
            </div>
            <div class="field">
              <label>Margin (%)</label>
              <input type="number" min="0" max="1" step="0.01" bind:value={mockMargin}/>
            </div>
            <div class="field">
              <label>Ore-cattedra base</label>
              <input type="number" bind:value={baseMaxHours}/>
            </div>
          </div>
          <div class="mt-4 flex items-center gap-2.5">
            <Button variant="primary" loading={busyMock} onclick={generateMock}>
              Genera
            </Button>
            <span class="text-[11.5px] text-ink-300">
              Sostituisce classi e docenti del DB.
            </span>
          </div>
        </div>
      </div>
    </Panel>

    <Panel id="backup-db" title="Backup del database"
           subtitle="esporta o ripristina .zip">
      <DbImportExportCard />
    </Panel>

    <Panel id="travaso-vincoli" title="Travaso vincoli"
           subtitle="riporta i vincoli su un altro anno scolastico">
      <ConstraintsImportExportCard />
    </Panel>

    <Panel id="grafo-scuola" title="Grafo della scuola"
           subtitle="chi condivide cosa">
      <p class="max-w-3xl text-[11.5px] leading-snug text-ink-400">
        In modalita' "Classi" ogni classe e' un nodo e gli archi rappresentano
        docenti condivisi (lo spessore e' proporzionale al numero di docenti in
        comune); in modalita' "Docenti" ogni docente e' un nodo e gli archi
        rappresentano classi condivise.
      </p>

      <div class="mt-3 flex flex-wrap items-center gap-2">
        <div class="inline-flex overflow-hidden rounded-[7px] border border-ink-200 text-[11px]">
          {#each [['classes', 'Classi (nodi)'], ['teachers', 'Docenti (nodi)']] as [mode, label], i}
            <button type="button"
                    class="px-3 py-1.5 transition-colors focus-ring
                           {graphMode === mode ? 'bg-accent-500 text-white'
                                               : 'bg-white text-ink-500 hover:bg-ink-50'}
                           {i > 0 ? 'border-l border-ink-200' : ''}"
                    aria-pressed={graphMode === mode}
                    on:click={() => (graphMode = mode)}>{label}</button>
          {/each}
        </div>
        <button class="btn !text-[11px]"
                aria-expanded={showGraph}
                on:click={() => (showGraph = !showGraph)}>
          {showGraph ? 'Nascondi grafo' : 'Visualizza grafo'}
        </button>
        <span class="text-[11px] text-ink-300">
          {graphMode === 'classes'
            ? 'Archi spessi = molti docenti condivisi.'
            : 'Archi spessi = molte classi condivise.'}
        </span>
      </div>

      {#if showGraph}
        <div class="mt-3">
          <EntityGraph mode={graphMode} height={560} />
        </div>
      {/if}
    </Panel>

    <Panel id="zona-pericolosa" tone="danger" title="Zona pericolosa"
           subtitle="operazioni non reversibili">
      <div class="flex flex-wrap items-center gap-3">
        <button class="btn-danger" on:click={clearAll}>Reset DB</button>
        <span class="text-[11.5px] text-ink-500">
          Cancella classi, docenti, aule, cattedre, vincoli e soluzioni.
          Fai prima un backup dal pannello qui sopra.
        </span>
      </div>
    </Panel>
  </section>
</div>
