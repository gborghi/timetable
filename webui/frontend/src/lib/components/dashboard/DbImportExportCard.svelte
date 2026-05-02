<script>
  /**
   * Dashboard card: Import / Export DB + snapshot management.
   *
   * Backend endpoints (see docs/api.md):
   *   GET  /api/dashboard/export-db          (?schema_only=true to omit data)
   *   POST /api/dashboard/import-db          (multipart upload)
   *   POST /api/dashboard/snapshot/create
   *   GET  /api/dashboard/snapshot/list
   *   POST /api/dashboard/snapshot/restore/{filename}
   *   DELETE /api/dashboard/snapshot/{filename}
   */
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, refreshDataset, bumpMutation } from '$lib/stores';

  let snapshots = [];
  let busy = false;
  let importInput;

  onMount(reloadSnapshots);

  async function reloadSnapshots() {
    try {
      snapshots = await api.get('/api/dashboard/snapshot/list');
    } catch (e) {
      flash('Errore caricando snapshot: ' + e.message, 'error');
    }
  }

  function downloadExport(schemaOnly) {
    const url = '/api/dashboard/export-db'
      + (schemaOnly ? '?schema_only=true' : '');
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    a.click();
  }

  async function importFile(ev) {
    const f = ev.target.files?.[0];
    if (!f) return;
    if (!confirm(
      'Questa operazione cancella i dati correnti del DB e li sostituisce '
      + 'con il contenuto di "' + f.name + '". Procedere?'
    )) {
      ev.target.value = '';
      return;
    }
    busy = true;
    try {
      const fd = new FormData();
      fd.append('file', f);
      const res = await fetch('/api/dashboard/import-db', {
        method: 'POST', body: fd,
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || j.error || ('HTTP ' + res.status));
      }
      const body = await res.json();
      flash('Import completato (schema ' + (body.schema_version || '?')
            + ').', 'success');
      bumpMutation();
      await refreshDataset();
      await reloadSnapshots();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busy = false; ev.target.value = ''; }
  }

  async function makeSnapshot() {
    busy = true;
    try {
      const res = await api.post('/api/dashboard/snapshot/create', {});
      flash('Snapshot creato: ' + res.filename
            + ' (' + Math.round(res.size_bytes / 1024) + ' KB)',
            'success');
      await reloadSnapshots();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busy = false; }
  }

  async function restore(s) {
    if (!confirm(
      'Ripristinare lo snapshot "' + s.filename + '"? '
      + 'I dati correnti del DB verranno sostituiti.'
    )) return;
    busy = true;
    try {
      const res = await api.post(
        '/api/dashboard/snapshot/restore/'
        + encodeURIComponent(s.filename),
        {},
      );
      flash('Snapshot ripristinato (schema '
            + (res.schema_version || '?') + ').', 'success');
      bumpMutation();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busy = false; }
  }

  async function del(s) {
    if (!confirm('Eliminare lo snapshot "' + s.filename + '"?')) return;
    try {
      await api.del('/api/dashboard/snapshot/'
                    + encodeURIComponent(s.filename));
      await reloadSnapshots();
      flash('Snapshot eliminato', 'success');
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  function fmtBytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024*1024) return Math.round(n/1024) + ' KB';
    return (n / (1024*1024)).toFixed(1) + ' MB';
  }
</script>

<section class="card p-5">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h2>Import / Export database</h2>
    <span class="text-xs text-ink-500 max-w-2xl">
      Esporta tutto lo stato del DB in un file .zip (raw SQLite +
      CSV per tabella + metadata.json) o caricane uno per
      ripristinarlo. Gli snapshot timestampati sono conservati in
      <code>webui/data/snapshots/</code>.
    </span>
  </div>

  <div class="mt-4 grid md:grid-cols-2 gap-4">
    <div class="card !shadow-none p-3 bg-ink-50/40 space-y-2">
      <h3 class="!text-base">Export</h3>
      <div class="flex flex-wrap gap-2 items-center">
        <button class="btn-primary" on:click={() => downloadExport(false)}>
          Esporta DB completo
        </button>
        <button class="btn !text-xs" on:click={() => downloadExport(true)}
                title="Esporta solo lo schema (vincoli + struttura), senza dati di scheduling">
          Solo schema
        </button>
      </div>
      <p class="text-[11px] text-ink-500">
        Il file include database.db (SQLite raw), tables/*.csv per
        ogni tabella, e metadata.json con
        <code>schema_version</code> + sha256 per integrita'.
      </p>
    </div>

    <div class="card !shadow-none p-3 bg-ink-50/40 space-y-2">
      <h3 class="!text-base">Import</h3>
      <input type="file" accept=".zip"
             bind:this={importInput}
             on:change={importFile}
             disabled={busy}
             class="text-sm"/>
      <p class="text-[11px] text-ink-500">
        Sostituisce il DB corrente con quello del .zip. Una copia
        del DB pre-import viene salvata accanto come
        <code>timetable.db.pre_import_backup</code>.
      </p>
    </div>
  </div>

  <div class="mt-5 space-y-2">
    <div class="flex items-baseline gap-3">
      <h3 class="!text-base">Snapshot locali</h3>
      <span class="text-xs text-ink-500">
        ({snapshots.length} salvat{snapshots.length === 1 ? 'o' : 'i'})
      </span>
      <button class="btn-primary !text-xs ml-auto"
              on:click={makeSnapshot}
              disabled={busy}>
        Crea snapshot
      </button>
      <button class="btn !text-xs"
              on:click={reloadSnapshots}
              disabled={busy}>
        Aggiorna lista
      </button>
    </div>
    {#if snapshots.length === 0}
      <p class="text-xs text-ink-500 italic">
        Nessuno snapshot salvato. Premi "Crea snapshot" per produrre
        un backup timestampato del DB corrente.
      </p>
    {:else}
      <table class="tbl text-sm">
        <thead>
          <tr>
            <th>Filename</th>
            <th>Modificato</th>
            <th class="text-right">Dimensione</th>
            <th class="w-44"></th>
          </tr>
        </thead>
        <tbody>
          {#each snapshots as s (s.filename)}
            <tr>
              <td><code>{s.filename}</code></td>
              <td class="text-xs">{s.modified_at}</td>
              <td class="text-right">{fmtBytes(s.size_bytes)}</td>
              <td class="whitespace-nowrap">
                <button class="btn !text-xs !px-2 !py-1"
                        on:click={() => restore(s)}
                        disabled={busy}>
                  Ripristina
                </button>
                <button class="btn-danger !text-xs !px-2 !py-1"
                        on:click={() => del(s)}
                        disabled={busy}>
                  Elimina
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</section>
