<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { datasetState, flash, refreshDataset } from '$lib/stores';
  import RunLogPanel from '$lib/components/RunLogPanel.svelte';

  let availableProfiles = [];
  let selectedProfile = 'small';
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
    try {
      availableProfiles = await api.get('/api/dataset/available-profiles');
    } catch (e) {
      flash('Errore caricando profili: ' + e.message, 'error');
    }
  });

  async function importPickle() {
    busyImport = true;
    try {
      const res = await api.post('/api/dataset/import-profile', {
        profile: selectedProfile,
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
        profile: selectedProfile, mode: mockMode,
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
    if (!confirm('Sicuro? Cancella TUTTO (classi, docenti, soluzioni, ecc.).')) return;
    try {
      await api.post('/api/dataset/clear?scope=all');
      await refreshDataset();
      flash('DB resettato', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  function onEnd() { refreshDataset(); }
</script>

<div class="space-y-6">
  <section class="card p-5">
    <div class="flex items-baseline justify-between">
      <h1>Dashboard</h1>
      <button class="btn-danger !text-xs !px-2 !py-1" on:click={clearAll}>Reset DB</button>
    </div>
    <p class="text-sm text-ink-500 mt-1">
      Punto di partenza: importa un dataset esistente da <code>experiments/</code>
      o genera una scuola fittizia. Da qui poi puoi modificare CRUD,
      lanciare l'ottimizzazione, e visualizzare l'orario.
    </p>
  </section>

  <section class="grid md:grid-cols-2 gap-6">
    <div class="card p-5">
      <h2 class="mb-3">1) Importa un profilo gia\` calcolato</h2>
      <div class="space-y-3">
        <div class="field">
          <label>Profilo</label>
          <select bind:value={selectedProfile}>
            {#each availableProfiles as p}
              <option value={p.name}>{p.name}{p.has_optimized_solution ? '  (con soluzione ottimizzata)' : ''}</option>
            {/each}
          </select>
        </div>
        <label class="flex items-center gap-2 text-sm">
          <input type="checkbox" bind:checked={useOptimized} />
          Usa la soluzione ottimizzata se disponibile
        </label>

        <div class="space-y-1 border border-ink-200 rounded p-2 bg-ink-50">
          <div class="text-xs font-semibold text-ink-500 mb-1">
            Pool dati da generare insieme al profilo:
          </div>
          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" bind:checked={importCurricula}/>
            Indirizzi (curricula): seed dei monte-ore mock + linkaggio classi
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" bind:checked={importClassrooms}/>
            Aule: una per classe + lab/palestre/biblioteca proporzionali
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" bind:checked={importStudents}/>
            Studenti: ~22 per classe (Faker, deterministico)
          </label>
        </div>

        <div class="flex items-center gap-3">
          <button class="btn-primary" on:click={importPickle} disabled={busyImport}>
            Importa
          </button>
          <button class="btn" on:click={autoGenerateClassrooms}>
            Rigenera solo aule
          </button>
        </div>
      </div>
    </div>

    <div class="card p-5">
      <h2 class="mb-3">2) Genera scuola di test</h2>
      <div class="grid grid-cols-2 gap-3">
        <div class="field">
          <label>Profilo</label>
          <select bind:value={selectedProfile}>
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
      <div class="mt-4">
        <button class="btn-primary" on:click={generateMock} disabled={busyMock}>
          Genera
        </button>
        <span class="text-xs text-ink-500 ml-2">
          Sostituisce classi/docenti del DB.
        </span>
      </div>
    </div>
  </section>

  {#if runId}
    <RunLogPanel {runId} title="Output run #{runId}" onEnd={onEnd} />
  {/if}

  <section class="card p-5">
    <h2 class="mb-2">Stato corrente</h2>
    <div class="grid grid-cols-2 md:grid-cols-7 gap-3 text-center">
      <div class="card !shadow-none p-3">
        <div class="text-3xl font-semibold">{$datasetState.classes}</div>
        <div class="text-xs text-ink-500">Classi</div>
      </div>
      <div class="card !shadow-none p-3">
        <div class="text-3xl font-semibold">{$datasetState.teachers}</div>
        <div class="text-xs text-ink-500">Docenti</div>
      </div>
      <div class="card !shadow-none p-3">
        <div class="text-3xl font-semibold">{$datasetState.subjects}</div>
        <div class="text-xs text-ink-500">Materie</div>
      </div>
      <div class="card !shadow-none p-3">
        <div class="text-3xl font-semibold">{$datasetState.classrooms}</div>
        <div class="text-xs text-ink-500">Aule</div>
      </div>
      <div class="card !shadow-none p-3">
        <div class="text-3xl font-semibold">{$datasetState.students ?? 0}</div>
        <div class="text-xs text-ink-500">Studenti</div>
      </div>
      <div class="card !shadow-none p-3">
        <div class="text-3xl font-semibold">{$datasetState.assignments}</div>
        <div class="text-xs text-ink-500">Cattedre</div>
      </div>
      <div class="card !shadow-none p-3">
        <div class="text-3xl font-semibold">{$datasetState.solutions}</div>
        <div class="text-xs text-ink-500">Soluzioni</div>
      </div>
    </div>
    {#if $datasetState.active_solution}
      <div class="mt-4 text-sm">
        Soluzione attiva: <strong>{$datasetState.active_solution.name}</strong>
        ({$datasetState.active_solution.kind}) -
        obj=<code>{$datasetState.active_solution.obj_value}</code>
        - metriche {JSON.stringify($datasetState.active_solution.metrics)}
      </div>
    {/if}
  </section>
</div>
