<script>
  // Reusable Excel/CSV import button. Drops a file picker + posts to
  // /api/import/{entity}; offers a "Scarica template" link.
  //
  // Props:
  //   entity:   one of teachers/subjects/classes/classrooms/curricula/students/groups
  //   label:    button label (default 'Importa Excel/CSV')
  //   onDone:   callback invoked after a successful import (e.g. to refresh the list)

  import { api, downloadUrl } from '../api';
  import { flash } from '../stores';

  export let entity = 'teachers';
  export let label = 'Importa Excel/CSV';
  export let onDone = () => {};

  let busy = false;
  let report = null;
  let fileInput;
  let mode = 'upsert';

  async function onPick(ev) {
    const file = ev.target.files?.[0];
    ev.target.value = '';
    if (!file) return;
    busy = true;
    report = null;
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('mode', mode);
      const res = await fetch('/api/import/' + entity, {
        method: 'POST', body: fd
      });
      if (!res.ok) {
        let msg = `${res.status} ${res.statusText}`;
        try { const j = await res.json(); if (j.detail) msg = j.detail; }
        catch { /* */ }
        throw new Error(msg);
      }
      report = await res.json();
      const ok = report.n_inserted + report.n_updated;
      flash(`Import ${entity}: ${ok} righe (` +
            `${report.n_inserted} nuove, ${report.n_updated} aggiornate, ` +
            `${report.n_skipped} saltate)`,
            report.errors?.length ? 'warning' : 'success');
      onDone(report);
    } catch (e) {
      flash('Errore import: ' + e.message, 'error');
    } finally {
      busy = false;
    }
  }
</script>

<div class="inline-flex items-center gap-2">
  <select bind:value={mode}
          class="text-xs px-2 py-1 border border-ink-200 rounded"
          title="upsert: aggiunge/aggiorna; replace: svuota la tabella prima">
    <option value="upsert">upsert</option>
    <option value="append">append</option>
    <option value="replace">replace (svuota!)</option>
  </select>
  <button class="btn !text-xs" on:click={() => fileInput.click()} disabled={busy}>
    {busy ? '...' : label}
  </button>
  <a class="btn !text-xs" href={downloadUrl(`/api/import/${entity}/template`)}
     title="Scarica un template .xlsx con le colonne attese">
    Template
  </a>
  <input type="file" hidden accept=".xlsx,.xls,.xlsm,.csv,.tsv,.txt"
         bind:this={fileInput} on:change={onPick}/>
</div>

{#if report && report.errors?.length}
  <div class="card !shadow-none p-2 text-xs bg-amber-50 border-amber-300 mt-2">
    <strong>Avvisi import:</strong>
    <ul class="list-disc ml-5">
      {#each report.errors.slice(0, 8) as e}<li>{e}</li>{/each}
      {#if report.errors.length > 8}<li>... +{report.errors.length - 8}</li>{/if}
    </ul>
  </div>
{/if}
