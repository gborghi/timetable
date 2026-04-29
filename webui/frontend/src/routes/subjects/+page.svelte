<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash } from '$lib/stores.js';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import ClassroomGrid from '$lib/components/ClassroomGrid.svelte';

  let editing = null;
  let weights = [];
  let allClassrooms = [];
  let editWeights = false;
  let listRef = null;

  onMount(async () => {
    try { weights = await api.get('/api/subjects/group-weights'); } catch { /* */ }
    try { allClassrooms = await api.get('/api/classrooms'); } catch { /* */ }
  });

  function newSubject() {
    editing = {
      _new: true, name: '', pretty_name: '', notes: '',
      distribute_days_weight: 0, dual_hours_weight: 0,
      no_sixth_hour_weight: 0,
      preferred_band_start: null, preferred_band_end: null,
      preferred_band_weight: 0,
      classroom_prefs: []
    };
  }
  function edit(row) {
    editing = JSON.parse(JSON.stringify(row));
    if (!Array.isArray(editing.classroom_prefs)) editing.classroom_prefs = [];
  }
  function onClassroomPrefsChange(newPrefs) {
    editing = { ...editing, classroom_prefs: newPrefs };
  }

  async function save() {
    const payload = { ...editing };
    delete payload._new;
    const id = editing.id;
    delete payload.id;
    try {
      if (editing._new) await api.post('/api/subjects', payload);
      else await api.put('/api/subjects/' + id, payload);
      flash('Salvato', 'success');
      editing = null;
      await listRef.reload();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }
  async function del(row) {
    if (!confirm('Eliminare ' + row.name + '?')) return;
    try { await api.del('/api/subjects/' + row.id); await listRef.reload(); }
    catch (e) { flash('Errore: ' + e.message, 'error'); }
  }
  function addWeightRow() { weights = [...weights, { id: undefined, subject: '', group_name: '', weight: 1 }]; }
  function delWeightRow(i) { weights = weights.filter((_, idx) => idx !== i); }
  async function saveWeights() {
    try {
      await api.put('/api/subjects/group-weights', weights.map((w) => ({
        subject: w.subject, group_name: w.group_name, weight: Number(w.weight)
      })));
      flash('Pesi salvati', 'success');
      weights = await api.get('/api/subjects/group-weights');
      editWeights = false;
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  const columns = [
    { key: 'name', label: 'Nome' },
    { key: 'pretty_name', label: 'Pretty name' },
    { key: 'distribute_days_weight', label: 'Dist. giorni' },
    { key: 'dual_hours_weight', label: 'Doppie ore' },
    { key: 'no_sixth_hour_weight', label: 'No 6^a ora' }
  ];
  const help = {
    fields: ['name', 'pretty_name', 'distribute_days_weight',
             'dual_hours_weight', 'no_sixth_hour_weight'],
    examples: [
      'name = Matematica',
      'name contains lab',
      'no_sixth_hour_weight > 50',
      'name in [Italiano, Matematica]'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Materie</h1>
    <button class="btn ml-auto" on:click={() => (editWeights = !editWeights)}>
      {editWeights ? 'Vista materie' : 'Pesi cl. concorso'}
    </button>
    {#if !editWeights}
      <button class="btn-primary" on:click={newSubject}>+ Nuova materia</button>
      <ImportButton entity="subjects" onDone={() => listRef?.reload()}/>
    {:else}
      <button class="btn-primary" on:click={saveWeights}>Salva tutti</button>
    {/if}
  </div>

  {#if !editWeights}
    <SortableQueryableList
      bind:this={listRef}
      endpoint="/api/subjects"
      {columns}
      {help}
      rowKey={(r) => r.id}
      let:row let:columns>
      <tr>
        <td><strong>{row.name}</strong></td>
        <td>{row.pretty_name ?? ''}</td>
        <td class="text-center">{row.distribute_days_weight}</td>
        <td class="text-center">{row.dual_hours_weight}</td>
        <td class="text-center">{row.no_sixth_hour_weight}</td>
        <td class="whitespace-nowrap">
          <button class="btn !text-xs !px-2 !py-1" on:click={() => edit(row)}>Modifica</button>
          <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(row)}>Elimina</button>
        </td>
      </tr>
    </SortableQueryableList>
  {:else}
    <div class="card overflow-x-auto p-3">
      <p class="text-sm text-ink-500 mb-2">
        Mappa <strong>materia -&gt; classe di concorso -&gt; peso</strong>.
        Tutte le righe vengono sostituite al salvataggio.
      </p>
      <table class="tbl">
        <thead><tr><th>Materia</th><th>Cl. concorso</th><th>Peso</th><th></th></tr></thead>
        <tbody>
          {#each weights as w, i}
            <tr>
              <td><input class="w-full px-2 py-1 border border-ink-200 rounded" bind:value={w.subject}/></td>
              <td><input class="w-full px-2 py-1 border border-ink-200 rounded" bind:value={w.group_name}/></td>
              <td class="w-32"><input type="number" class="w-full px-2 py-1 border border-ink-200 rounded" bind:value={w.weight}/></td>
              <td><button class="btn-danger !text-xs !px-2 !py-1" on:click={() => delWeightRow(i)}>x</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <button class="btn !text-xs !px-2 !py-1 mt-2" on:click={addWeightRow}>+ Riga</button>
    </div>
  {/if}
</div>

<Modal open={!!editing} title={editing?._new ? 'Nuova materia' : 'Modifica materia'} onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field"><label>Nome (chiave)</label><input bind:value={editing.name}/></div>
      <div class="field"><label>Pretty name</label><input bind:value={editing.pretty_name}/></div>
      <div class="field col-span-2"><label>Note</label><input bind:value={editing.notes}/></div>
      <div class="field"><label>Peso "spalmare su pi giorni"</label><input type="number" bind:value={editing.distribute_days_weight}/></div>
      <div class="field"><label>Peso "doppie ore consecutive"</label><input type="number" bind:value={editing.dual_hours_weight}/></div>
      <div class="field"><label>Peso "no 6^a ora"</label><input type="number" bind:value={editing.no_sixth_hour_weight}/></div>
      <div class="grid grid-cols-3 gap-2 col-span-2 items-end">
        <div class="field"><label>Fascia: ora inizio</label><input type="number" min="8" max="13" bind:value={editing.preferred_band_start}/></div>
        <div class="field"><label>Ora fine</label><input type="number" min="8" max="13" bind:value={editing.preferred_band_end}/></div>
        <div class="field"><label>Peso fascia</label><input type="number" bind:value={editing.preferred_band_weight}/></div>
      </div>
    </div>

    <div class="mt-4 border-t border-ink-200 pt-3">
      <ClassroomGrid
        classrooms={allClassrooms}
        value={editing.classroom_prefs ?? []}
        onChange={onClassroomPrefsChange}
        title="Aule per questa materia"/>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary" on:click={save}>Salva</button>
    </div>
  {/if}
</Modal>
