<script>
  import PageHero from '$lib/components/PageHero.svelte';
  /**
   * Import bulk via xlsx/csv.
   *
   * Layout:
   *   - left: entity selector + 'Scarica template' + mode selector
   *   - right: drop area + Import button + per-row report
   *
   * Uses POST /api/import/{entity} (multipart) with optional ?sheet=
   * and `mode` form field. Templates come from
   * GET /api/import/{entity}/template.
   */
  import { flash, refreshDataset, bumpMutation } from '$lib/stores';
  import { downloadUrl } from '$lib/api';
  import Button from '$lib/components/Button.svelte';

  const ENTITIES = [
    { value: 'teachers',   label: 'Docenti'   },
    { value: 'classes',    label: 'Classi'    },
    { value: 'classrooms', label: 'Aule'      },
    { value: 'subjects',   label: 'Materie'   },
    { value: 'students',   label: 'Studenti'  },
    { value: 'curricula',  label: 'Indirizzi' },
    { value: 'groups',     label: 'Gruppi'    },
  ];

  let entity = 'teachers';
  let mode = 'upsert';
  let selectedFile = null;
  let dragOver = false;
  let busy = false;
  let report = null;
  let lastWasDry = false;

  function pickFile(ev) {
    selectedFile = ev.target.files?.[0] ?? null;
    report = null;
  }

  function onDrop(ev) {
    ev.preventDefault();
    dragOver = false;
    const f = ev.dataTransfer?.files?.[0];
    if (f) {
      selectedFile = f;
      report = null;
    }
  }

  async function runImport(dry = false) {
    if (!selectedFile) {
      flash('Seleziona prima un file', 'error');
      return;
    }
    busy = true;
    report = null;
    lastWasDry = dry;
    try {
      const fd = new FormData();
      fd.append('file', selectedFile);
      fd.append('mode', mode);
      if (dry) fd.append('dry', 'true');
      const res = await fetch('/api/import/' + entity, {
        method: 'POST', body: fd,
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || j.error || ('HTTP ' + res.status));
      }
      report = await res.json();
      const ok = report.n_inserted + report.n_updated;
      flash(
        (dry ? `Anteprima ${entity}: ` : `Import ${entity}: `) +
        `${ok} righe (` +
        `${report.n_inserted} nuove, ${report.n_updated} aggiornate, ` +
        `${report.n_skipped} saltate)`,
        report.errors?.length ? 'warning' : (dry ? 'info' : 'success'),
      );
      // A dry-run writes nothing -> no need to refresh counters.
      if (!dry) {
        bumpMutation();
        await refreshDataset();
      }
    } catch (e) {
      flash('Errore import: ' + e.message, 'error');
    } finally {
      busy = false;
    }
  }

  $: templateUrl = downloadUrl('/api/import/' + entity + '/template');
</script>

<div class="space-y-5">
  <PageHero title="Import bulk">
    <p class="mt-2 max-w-[720px] text-[13px] leading-[1.55] text-ink-500">
      Carica file <code>.xlsx</code> / <code>.csv</code> per importare in
      blocco docenti, classi, aule, materie, studenti, indirizzi,
      gruppi. Se non hai un file di partenza scarica il template
      dell'entita': il foglio <strong>Istruzioni</strong> spiega ogni
      colonna, <strong>Esempi</strong> contiene una riga di esempio,
      <strong>Dati</strong> e' il foglio che l'importer legge.
    </p>
  </PageHero>

  <div class="grid md:grid-cols-2 gap-5">
    <section class="card p-4 space-y-3">
      <h2 class="!text-base">1) Configurazione</h2>

      <div class="field">
        <label>Entita'</label>
        <select bind:value={entity}>
          {#each ENTITIES as e (e.value)}
            <option value={e.value}>{e.label} ({e.value})</option>
          {/each}
        </select>
      </div>

      <div class="field">
        <label>Modalita'</label>
        <select bind:value={mode}>
          <option value="upsert">upsert (aggiunge / aggiorna)</option>
          <option value="append">append (solo nuove righe)</option>
          <option value="replace">replace (svuota la tabella prima!)</option>
        </select>
      </div>

      <div class="flex gap-2">
        <a class="btn-primary" href={templateUrl}
           title="Scarica un .xlsx con header + Istruzioni + Esempi + Dati">
          Scarica template
        </a>
      </div>
    </section>

    <section class="card p-4 space-y-3">
      <h2 class="!text-base">2) File da importare</h2>

      <div class="border-2 border-dashed rounded-md p-6 text-center
                  text-sm transition-colors"
           role="button" tabindex="-1"
           class:bg-accent-500={dragOver}
           class:bg-opacity-5={dragOver}
           class:border-accent-500={dragOver}
           class:border-ink-200={!dragOver}
           on:dragover|preventDefault={() => (dragOver = true)}
           on:dragleave={() => (dragOver = false)}
           on:drop={onDrop}>
        {#if selectedFile}
          <p class="font-medium">{selectedFile.name}</p>
          <p class="text-xs text-ink-500">
            {Math.round(selectedFile.size / 1024)} KB &middot;
            {selectedFile.type || 'tipo non rilevato'}
          </p>
          <button class="btn !text-xs mt-2"
                  on:click={() => { selectedFile = null; report = null; }}>
            Cambia file
          </button>
        {:else}
          <p class="text-ink-500">
            Trascina qui un .xlsx o .csv, oppure
          </p>
          <label class="btn-primary mt-2 inline-block cursor-pointer">
            Seleziona file
            <input type="file" hidden
                   accept=".xlsx,.xls,.xlsm,.csv,.tsv,.txt"
                   on:change={pickFile}/>
          </label>
        {/if}
      </div>

      <div class="flex gap-2">
        <Button variant="secondary" class="flex-1"
                loading={busy && lastWasDry}
                disabled={!selectedFile}
                onclick={() => runImport(true)}
                title="Simula l'import senza scrivere nulla: vedi quante righe verrebbero inserite/aggiornate e gli eventuali errori.">
          Anteprima (dry-run)
        </Button>
        <Button variant="primary" class="flex-1"
                loading={busy && !lastWasDry}
                disabled={!selectedFile}
                onclick={() => runImport(false)}>
          Importa
        </Button>
      </div>
    </section>
  </div>

  {#if report}
    <section class="card p-4">
      <h2 class="!text-base">Report import</h2>
      {#if lastWasDry}
        <div class="mt-2 text-xs rounded bg-amber-50 border border-amber-200
                    px-3 py-2 text-amber-800">
          <strong>Anteprima (dry-run)</strong>: nessuna riga e' stata scritta.
          Premi <strong>Importa</strong> per applicare le modifiche.
        </div>
      {/if}
      <div class="grid grid-cols-2 md:grid-cols-5 gap-3 mt-2 text-center">
        <div class="card !shadow-none p-2">
          <div class="text-2xl font-semibold">{report.n_total_rows}</div>
          <div class="text-xs text-ink-500">Righe lette</div>
        </div>
        <div class="card !shadow-none p-2">
          <div class="text-2xl font-semibold text-emerald-600">
            {report.n_inserted}
          </div>
          <div class="text-xs text-ink-500">Inserite</div>
        </div>
        <div class="card !shadow-none p-2">
          <div class="text-2xl font-semibold text-sky-600">
            {report.n_updated}
          </div>
          <div class="text-xs text-ink-500">Aggiornate</div>
        </div>
        <div class="card !shadow-none p-2">
          <div class="text-2xl font-semibold text-amber-600">
            {report.n_skipped}
          </div>
          <div class="text-xs text-ink-500">Saltate</div>
        </div>
        <div class="card !shadow-none p-2">
          <div class="text-2xl font-semibold text-rose-600">
            {(report.errors || []).length}
          </div>
          <div class="text-xs text-ink-500">Errori</div>
        </div>
      </div>

      {#if report.errors && report.errors.length}
        <h3 class="!text-sm mt-4">Errori riga per riga</h3>
        <div class="card !shadow-none p-2 bg-rose-50 border-rose-200
                    max-h-72 overflow-auto text-xs">
          <ul class="list-disc ml-5">
            {#each report.errors as e}
              <li>{e}</li>
            {/each}
          </ul>
        </div>
      {/if}
    </section>
  {/if}
</div>
