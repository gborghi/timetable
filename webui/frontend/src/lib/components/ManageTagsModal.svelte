<script>
  /**
   * Global CRUD for ClassroomTag.
   *
   * Props:
   *   open: boolean
   *   onClose: () => void
   *   onChanged: () => void   - called after any successful change
   *
   * Uses /api/classroom-tags. List entries include n_classrooms so the
   * user knows how many rooms reference a tag before deleting it.
   */
  import Modal from '$lib/components/Modal.svelte';
  import { classroomTags as tagSvc } from '$lib/services';
  import { flash } from '$lib/stores';

  export let open = false;
  export let onClose = () => { open = false; };
  export let onChanged = () => {};

  let rows = [];
  let busy = false;
  let newName = '';
  let newDesc = '';

  $: if (open) load();

  async function load() {
    busy = true;
    try {
      rows = await tagSvc.list();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busy = false; }
  }

  async function add() {
    const name = (newName || '').trim().toLowerCase();
    if (!name) return;
    try {
      await tagSvc.create({ name, description: newDesc || null });
      newName = ''; newDesc = '';
      await load();
      onChanged();
      flash('Tag creato', 'success');
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function rename(row, value) {
    const name = (value || '').trim().toLowerCase();
    if (!name || name === row.name) return;
    try {
      await tagSvc.update(row.id, { name });
      await load();
      onChanged();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function saveDesc(row, value) {
    if ((value || '') === (row.description || '')) return;
    try {
      await tagSvc.update(row.id, { description: value || null });
      await load();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function del(row) {
    let q = 'Eliminare il tag #' + row.name + '?';
    if (row.n_classrooms) {
      q += ' Verra rimosso da ' + row.n_classrooms + ' aul' +
           (row.n_classrooms === 1 ? 'a.' : 'e.');
    }
    if (!confirm(q)) return;
    try {
      await tagSvc.remove(row.id);
      await load();
      onChanged();
      flash('Tag eliminato', 'success');
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }
</script>

<Modal {open} title="Gestisci tag aule" onClose={onClose}>
  <div class="space-y-4">
    <div class="card p-3 bg-ink-50/50 border-ink-100">
      <div class="grid grid-cols-[1fr_2fr_auto] gap-2 items-end">
        <div class="field"><label>Nome nuovo tag</label>
          <input bind:value={newName} placeholder="es. proiettore"/></div>
        <div class="field"><label>Descrizione (opzionale)</label>
          <input bind:value={newDesc} placeholder="Aule con videoproiettore"/></div>
        <button class="btn-primary" on:click={add} disabled={busy || !newName.trim()}>
          + Aggiungi
        </button>
      </div>
      <p class="text-[11px] text-ink-500 mt-2">
        Il nome viene salvato in minuscolo. I tag sono condivisi tra tutte
        le aule; quando elimini un tag viene rimosso anche dalle aule
        che lo usano.
      </p>
    </div>

    <table class="tbl">
      <thead>
        <tr>
          <th>Tag</th>
          <th>Descrizione</th>
          <th class="w-20 text-center">Aule</th>
          <th class="w-24"></th>
        </tr>
      </thead>
      <tbody>
        {#if rows.length === 0}
          <tr><td colspan="4" class="text-center text-ink-500 py-3">
            {busy ? 'Caricamento...' : 'Nessun tag definito.'}
          </td></tr>
        {/if}
        {#each rows as row (row.id)}
          <tr>
            <td>
              <input class="w-full px-2 py-1 border border-ink-200 rounded"
                     value={row.name}
                     on:change={(e) => rename(row, e.currentTarget.value)}/>
            </td>
            <td>
              <input class="w-full px-2 py-1 border border-ink-200 rounded"
                     value={row.description || ''}
                     on:change={(e) => saveDesc(row, e.currentTarget.value)}/>
            </td>
            <td class="text-center text-sm">{row.n_classrooms ?? 0}</td>
            <td>
              <button class="btn-danger !text-xs !px-2 !py-1"
                      on:click={() => del(row)}>Elimina</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>

    <div class="flex justify-end">
      <button class="btn" on:click={onClose}>Chiudi</button>
    </div>
  </div>
</Modal>
