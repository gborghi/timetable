<script>
  /**
   * Dashboard card: Import / Export constraint records.
   *
   * Mirrors DbImportExportCard.svelte but for constraints only,
   * leaving the rest of the DB untouched. Backend endpoints:
   *   POST /api/dashboard/constraints/import-stress  body {profile}
   *   POST /api/dashboard/constraints/import-file    multipart upload
   *   GET  /api/dashboard/constraints/export?format=json|xlsx
   *   DELETE /api/dashboard/constraints/all?confirm=true
   *
   * The card stays visually consistent with the existing Database
   * card: same shadowless inner cards on `bg-ink-50/40`.
   */
  import { api } from '$lib/api';
  import { flash, refreshDataset, bumpMutation } from '$lib/stores';

  const PROFILES = ['small', 'medium', 'big', 'huge', 'superhuge', 'mega'];

  let profile = 'small';
  let busy = false;
  let lastReport = null;       // last import report
  let importInput;
  let dropActive = false;

  async function importStress() {
    if (!confirm(
      `Importare i vincoli del profilo "${profile}" nel DB corrente?\n`
      + `I vincoli esistenti NON vengono cancellati: i nuovi si `
      + `aggiungono.`
    )) return;
    busy = true;
    lastReport = null;
    try {
      const r = await api.post(
        '/api/dashboard/constraints/import-stress',
        { profile });
      lastReport = { ...r, source: `stress/${profile}` };
      flash(
        `Importati ${r.n_loaded}/${r.n_total} vincoli del profilo `
        + `${r.profile} (${r.intentional_conflicts} conflitti `
        + `intenzionali). Errori: ${r.n_errors}.`,
        r.n_errors === 0 ? 'success' : 'info');
      bumpMutation();
      await refreshDataset();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }

  async function importFromFile(file) {
    if (!file) return;
    busy = true;
    lastReport = null;
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(
        '/api/dashboard/constraints/import-file',
        { method: 'POST', body: fd });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || j.error || ('HTTP ' + res.status));
      }
      const r = await res.json();
      lastReport = { ...r, source: file.name };
      flash(
        `Da "${file.name}": ${r.n_loaded}/${r.n_total} vincoli `
        + `importati, ${r.n_errors} errori.`,
        r.n_errors === 0 ? 'success' : 'info');
      bumpMutation();
      await refreshDataset();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }

  async function importFromInput(ev) {
    const f = ev.target.files?.[0];
    if (!f) return;
    await importFromFile(f);
    ev.target.value = '';
  }

  function onDrop(ev) {
    ev.preventDefault();
    dropActive = false;
    const f = ev.dataTransfer?.files?.[0];
    if (f) importFromFile(f);
  }

  function onDragOver(ev) { ev.preventDefault(); dropActive = true; }
  function onDragLeave() { dropActive = false; }

  function downloadExport(fmt) {
    const url = '/api/dashboard/constraints/export?format=' + fmt;
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    a.click();
  }

  // ----- Vincoli language (guided xlsx) -----
  let lastVincoliReport = null;

  function downloadVincoliTemplate() {
    const a = document.createElement('a');
    a.href = '/api/dashboard/constraints/template-vincoli';
    a.rel = 'noopener';
    a.click();
  }

  async function importVincoli(file) {
    if (!file) return;
    busy = true;
    lastVincoliReport = null;
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(
        '/api/dashboard/constraints/import-vincoli',
        { method: 'POST', body: fd });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || j.error || ('HTTP ' + res.status));
      }
      const r = await res.json();
      lastVincoliReport = { ...r, source: file.name };
      const nerr = (r.parse_errors?.length || 0)
        + (r.create_errors?.length || 0);
      flash(
        `Vincoli da "${file.name}": ${r.n_created} creati `
        + `(${r.n_intents} righe valide, ${nerr} problemi).`,
        nerr ? 'info' : 'success');
      bumpMutation();
      await refreshDataset();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }

  async function importVincoliInput(ev) {
    const f = ev.target.files?.[0];
    if (!f) return;
    await importVincoli(f);
    ev.target.value = '';
  }

  async function deleteAll() {
    if (!confirm(
      'Cancellare TUTTI i vincoli dal DB corrente?\n\n'
      + 'Questa azione svuota le tabelle: '
      + 'logical_unavailabilities, curriculum_logical_constraints, '
      + 'teacher/class/classroom_unavailability, coteaching_rules e '
      + 'le room preferences. NON e\' reversibile (a meno di '
      + 'ripristinare uno snapshot DB).'
    )) return;
    if (!confirm('Sei davvero sicuro? Doppia conferma richiesta.')) return;
    busy = true;
    try {
      const res = await fetch(
        '/api/dashboard/constraints/all?confirm=true',
        { method: 'DELETE' });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || ('HTTP ' + res.status));
      }
      const r = await res.json();
      lastReport = { ...r, source: 'delete-all', kind: 'delete' };
      flash(`Eliminati ${r.n_deleted} vincoli da ${
        Object.keys(r.by_table).length} tabelle.`, 'success');
      bumpMutation();
      await refreshDataset();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }
</script>

<section class="card p-5">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h2>Import / Export vincoli</h2>
    <span class="text-xs text-ink-500 max-w-2xl">
      Carica un dataset di stress preconfezionato, importa un file
      JSON / xlsx custom, oppure esporta i vincoli correnti per
      backup/condivisione. Le operazioni qui non toccano docenti,
      classi, aule o cattedre.
    </span>
  </div>

  <div class="mt-4 grid md:grid-cols-2 gap-4">
    <!-- Stress profile -->
    <div class="card !shadow-none p-3 bg-ink-50/40 space-y-2">
      <h3 class="!text-base">Stress dataset</h3>
      <p class="text-[11px] text-ink-500">
        Carica un profilo curato dal repository
        (<code>experiments/stress_constraints/</code>). Ogni profilo
        contiene un insieme realistico di vincoli docenti / aule /
        relazionali, incluse coppie deliberatamente in conflitto per
        testare l'estrattore di unsat core.
      </p>
      <div class="flex flex-wrap gap-2 items-center">
        <label class="text-xs">
          Profilo
          <select bind:value={profile} disabled={busy}
                  class="ml-1 border border-ink-300 rounded px-2 py-1 text-sm">
            {#each PROFILES as p}
              <option value={p}>{p}</option>
            {/each}
          </select>
        </label>
        <button class="btn-primary !text-sm"
                on:click={importStress} disabled={busy}>
          {busy ? 'in corso...' : 'Importa stress'}
        </button>
      </div>
    </div>

    <!-- Custom file -->
    <div class="card !shadow-none p-3 bg-ink-50/40 space-y-2">
      <h3 class="!text-base">File custom (JSON / xlsx)</h3>
      <div on:dragover={onDragOver}
           on:dragleave={onDragLeave}
           on:drop={onDrop}
           class="border-2 border-dashed rounded p-4 text-center text-xs cursor-pointer
                  {dropActive
                    ? 'border-emerald-500 bg-emerald-50'
                    : 'border-ink-300 bg-ink-50/30'}">
        Trascina qui un file <code>.json</code> o <code>.xlsx</code>
        oppure
        <button class="btn !text-xs ml-1"
                on:click={() => importInput.click()}
                disabled={busy}>
          Sfoglia
        </button>
        <input type="file" accept=".json,.xlsx"
               bind:this={importInput}
               on:change={importFromInput}
               disabled={busy}
               class="hidden"/>
      </div>
      <p class="text-[11px] text-ink-500">
        JSON: lista di record con campi <code>kind, scope, owner_name,
        level, expression, soft_penalty?, description?</code>. xlsx:
        intestazioni nella prima riga con gli stessi nomi colonna. I
        record con DSL invalido o owner_name non risolvibile vengono
        scartati e riportati nel report sotto.
      </p>
    </div>
  </div>

  <!-- Guided Vincoli language (xlsx) -->
  <div class="mt-4 card !shadow-none p-3 bg-indigo-50/40 space-y-2
              border-indigo-200">
    <h3 class="!text-base">Vincoli guidati (xlsx) — linguaggio Vincoli</h3>
    <p class="text-[11px] text-ink-500">
      Compila il foglio <strong>Vincoli</strong> del template con un
      vocabolario semplice (<code>indisponibilita</code>,
      <code>giorno_libero</code>, <code>max_ore_giorno</code>,
      <code>no_pomeriggio</code>, <code>no_giorni_consecutivi</code>,
      <code>compresenza</code>, ...) oppure usa <code>raw_dsl</code> per
      un'espressione DSL libera. Ogni riga diventa un vincolo.
    </p>
    <div class="flex flex-wrap gap-2 items-center">
      <button class="btn !text-sm" on:click={downloadVincoliTemplate}>
        Scarica template vincoli
      </button>
      <label class="btn-primary !text-sm cursor-pointer">
        Carica vincoli (xlsx)
        <input type="file" accept=".xlsx,.json"
               on:change={importVincoliInput}
               disabled={busy} class="hidden"/>
      </label>
    </div>
    {#if lastVincoliReport}
      {@const nerr = (lastVincoliReport.parse_errors?.length || 0)
        + (lastVincoliReport.create_errors?.length || 0)}
      <div class="text-xs mt-1">
        <strong>{lastVincoliReport.n_created}</strong> vincoli creati da
        {lastVincoliReport.n_intents} righe valide
        ({lastVincoliReport.parse_errors?.length || 0} errori di formato,
        {lastVincoliReport.create_errors?.length || 0} errori di creazione).
        {#if nerr}
          <details class="mt-1">
            <summary class="text-red-700 cursor-pointer">Mostra problemi</summary>
            <ul class="text-[11px] text-red-700 mt-1 space-y-0.5
                       max-h-48 overflow-y-auto">
              {#each lastVincoliReport.parse_errors || [] as e}
                <li>riga {e.row} ({e.tipo}): {e.error}</li>
              {/each}
              {#each lastVincoliReport.create_errors || [] as e}
                <li>intent {e.intent}: {e.error}</li>
              {/each}
            </ul>
          </details>
        {/if}
      </div>
    {/if}
  </div>

  <div class="mt-4 grid md:grid-cols-2 gap-4">
    <!-- Export -->
    <div class="card !shadow-none p-3 bg-ink-50/40 space-y-2">
      <h3 class="!text-base">Export</h3>
      <div class="flex flex-wrap gap-2">
        <button class="btn-primary !text-sm"
                on:click={() => downloadExport('json')}>
          Esporta JSON
        </button>
        <button class="btn !text-sm"
                on:click={() => downloadExport('xlsx')}>
          Esporta xlsx
        </button>
      </div>
      <p class="text-[11px] text-ink-500">
        Produce un dump dei vincoli correnti nel formato accettato
        dall'import (round-trip).
      </p>
    </div>

    <!-- Wipe -->
    <div class="card !shadow-none p-3 bg-red-50/40 space-y-2 border-red-200">
      <h3 class="!text-base text-red-900">Wipe</h3>
      <p class="text-[11px] text-red-800">
        Cancella tutti i vincoli (logical, matrix, coteach, room
        preferences). Utile per ricominciare da zero un esperimento.
        Doppia conferma richiesta.
      </p>
      <button class="btn-danger !text-sm"
              on:click={deleteAll} disabled={busy}>
        Cancella tutti i vincoli
      </button>
    </div>
  </div>

  <!-- Last report -->
  {#if lastReport}
    <div class="mt-4 card !shadow-none p-3 bg-ink-50/40">
      <h3 class="!text-base">Ultimo report</h3>
      <p class="text-xs text-ink-600">
        Sorgente: <code>{lastReport.source}</code>
        {#if lastReport.profile}
          (profilo {lastReport.profile})
        {/if}
      </p>
      {#if lastReport.kind === 'delete'}
        <p class="text-xs">
          <strong>{lastReport.n_deleted}</strong> vincoli cancellati.
        </p>
        <ul class="text-[11px] text-ink-600 mt-1 space-y-0.5">
          {#each Object.entries(lastReport.by_table) as [tbl, n]}
            <li><code>{tbl}</code>: {n}</li>
          {/each}
        </ul>
      {:else}
        <p class="text-xs">
          {lastReport.n_loaded ?? 0} importati,
          {lastReport.n_errors ?? 0} errori
          {#if lastReport.n_total != null}
            (totali: {lastReport.n_total})
          {/if}
          {#if lastReport.intentional_conflicts != null}
            · <span class="text-amber-700">
              {lastReport.intentional_conflicts} conflitti intenzionali
            </span>
          {/if}
        </p>
        {#if lastReport.by_category}
          <p class="text-[11px] text-ink-500 mt-1">
            Per categoria: teacher={lastReport.by_category.teacher},
            classroom={lastReport.by_category.classroom},
            relational={lastReport.by_category.relational}
          </p>
        {/if}
        {#if lastReport.errors && lastReport.errors.length}
          <details class="mt-2">
            <summary class="text-xs text-red-700 cursor-pointer">
              {lastReport.errors.length} errori (mostra)
            </summary>
            <ul class="text-[11px] text-red-700 mt-1 space-y-1
                       max-h-48 overflow-y-auto">
              {#each lastReport.errors as e}
                <li>
                  <strong>idx={e.idx}</strong>:
                  {e.error}
                </li>
              {/each}
            </ul>
          </details>
        {/if}
        {#if lastReport.results && lastReport.results.length}
          <details class="mt-2">
            <summary class="text-xs text-ink-600 cursor-pointer">
              Dettaglio per record ({lastReport.results.length})
            </summary>
            <ul class="text-[11px] text-ink-700 mt-1 space-y-0.5
                       max-h-48 overflow-y-auto">
              {#each lastReport.results as r}
                <li>
                  <code>{r.dataset_id || '?'}</code>:
                  {#if r.ok}
                    <span class="text-emerald-700">ok</span>
                    db_id={r.db_id}
                  {:else}
                    <span class="text-red-700">err: {r.error}</span>
                  {/if}
                </li>
              {/each}
            </ul>
          </details>
        {/if}
      {/if}
    </div>
  {/if}
</section>
