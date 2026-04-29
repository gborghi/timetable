<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash, refreshDataset } from '$lib/stores.js';
  import Modal from '$lib/components/Modal.svelte';

  let byClass = {};
  let allTeachers = [];
  let allSubjects = [];
  let editing = null;
  let filter = '';

  onMount(async () => {
    await reload();
    allTeachers = (await api.get('/api/teachers')).map((t) => t.name);
    allSubjects = (await api.get('/api/subjects')).map((s) => s.name);
  });

  async function reload() { byClass = await api.get('/api/assignments/by-class'); }

  function startEdit(cls, row) {
    editing = {
      class_name: cls,
      subject: row.subject,
      teacher_name: row.teacher,
      hours: row.hours,
      locked: row.locked || false,
      _existing: row.id
    };
  }

  async function save() {
    try {
      const r = await api.put('/api/assignments/manual', {
        class_name: editing.class_name,
        subject: editing.subject,
        teacher_name: editing.teacher_name,
        locked: editing.locked
      });
      if (r.accepted) {
        flash('Cattedra aggiornata', 'success');
        editing = null;
        await reload();
        await refreshDataset();
      } else {
        flash('Rifiutato: ' + r.reason, 'error');
      }
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function toggleLock(id, lockedNow) {
    try {
      await api.post('/api/assignments/lock/' + id + '?locked=' + (!lockedNow));
      await reload();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  $: classNames = Object.keys(byClass).filter((c) =>
    !filter || c.toLowerCase().includes(filter.toLowerCase())
  ).sort();
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3">
    <h1>Cattedre (assegnazione docenti -&gt; classi)</h1>
    <span class="text-sm text-ink-500">{Object.keys(byClass).length} classi</span>
  </div>
  <div class="card p-3">
    <input class="w-full px-2 py-1.5 rounded-md border border-ink-200" placeholder="Filtra classe..." bind:value={filter}/>
  </div>

  <div class="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
    {#each classNames as cn}
      <div class="card p-4">
        <h3 class="mb-2">{cn}</h3>
        <table class="tbl">
          <thead><tr><th>Materia</th><th>Docente</th><th>Ore</th><th></th></tr></thead>
          <tbody>
            {#each byClass[cn] as row}
              <tr>
                <td>{row.subject}</td>
                <td>{row.teacher}</td>
                <td class="text-center">{row.hours}</td>
                <td class="whitespace-nowrap">
                  <button class="btn !text-xs !px-2 !py-1" on:click={() => startEdit(cn, row)}>cambia</button>
                  <button class="btn !text-xs !px-2 !py-1"
                    title={row.locked ? 'Sblocca' : 'Blocca'}
                    on:click={() => toggleLock(row.id, row.locked)}>
                    {row.locked ? '🔒' : '🔓'}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/each}
  </div>
</div>

<Modal open={!!editing} title="Cambia docente" onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field">
        <label>Classe</label>
        <input value={editing.class_name} disabled/>
      </div>
      <div class="field">
        <label>Materia</label>
        <input value={editing.subject} disabled/>
      </div>
      <div class="field col-span-2">
        <label>Docente</label>
        <input list="ll-t" bind:value={editing.teacher_name}/>
        <datalist id="ll-t">{#each allTeachers as t}<option value={t}/>{/each}</datalist>
      </div>
      <label class="flex items-center gap-2 col-span-2 text-sm">
        <input type="checkbox" bind:checked={editing.locked}/> Bloccare la modifica (l'ottimizzatore non potra cambiare)
      </label>
    </div>
    <div class="mt-4 text-xs text-ink-500">
      Il backend valida HARD: ore-cattedra, abilitazione materia, esistenza docente.
      Se la mossa rompe un vincolo, viene rifiutata con messaggio chiaro.
    </div>
    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary" on:click={save}>Salva</button>
    </div>
  {/if}
</Modal>
