<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash, refreshDataset } from '$lib/stores.js';
  import Modal from '$lib/components/Modal.svelte';
  import AvailabilityMatrix from '$lib/components/AvailabilityMatrix.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import LogicalUnavailabilitiesPanel from '$lib/components/LogicalUnavailabilitiesPanel.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import BulkApplyModal from '$lib/components/BulkApplyModal.svelte';

  let editing = null;
  let allSubjects = [];
  let allCurricula = [];
  let listRef = null;
  let selectedIds = [];
  let showBulk = false;

  onMount(async () => {
    try {
      allSubjects = (await api.get('/api/subjects')).map((s) => s.name).sort();
      allCurricula = await api.get('/api/curricula');
    } catch { /* */ }
  });

  function newClass() {
    editing = {
      _new: true,
      name: '', nickname: '', year: 1, section: '', curriculum: '', curriculum_id: null,
      n_students: 22, notes: '',
      hard_entry_at_8: true, hard_exit_after_12: true,
      hard_no_holes: true, hard_dual_math: true,
      hard_dual_italian: true, hard_motorie_pairs: true,
      hard_max_6_per_day: true, soft_minimize_sixth_weight: 50,
      subjects: [], unavailability: []
    };
  }
  function edit(row) { editing = JSON.parse(JSON.stringify(row)); }

  function applyCurriculumGrid() {
    if (!editing.curriculum_id) return;
    const c = allCurricula.find((x) => x.id === editing.curriculum_id);
    if (!c) return;
    const yearHours = (c.hours || []).filter((h) => Number(h.year) === Number(editing.year));
    if (yearHours.length === 0) {
      flash(`L'indirizzo ${c.code} non ha ore definite per l'anno ${editing.year}`,
            'warning');
      return;
    }
    editing.subjects = yearHours.map((h) => ({
      subject: h.subject, hours_per_week: h.hours_per_week
    }));
    if (!editing.curriculum) editing.curriculum = c.code;
  }
  function addSubject() {
    editing.subjects = [...editing.subjects, { subject: '', hours_per_week: 1 }];
  }
  function delSubject(i) { editing.subjects = editing.subjects.filter((_, idx) => idx !== i); }
  function onMatrixChange(newCells) {
    editing = { ...editing, unavailability: newCells };
  }

  let saving = false;
  async function save() {
    const payload = { ...editing };
    delete payload._new; delete payload.id;
    delete payload.ore_totali; delete payload.n_subjects;
    saving = true;
    try {
      if (editing._new) await api.post('/api/classes', payload);
      else await api.put('/api/classes/' + editing.id, payload);
      flash('Salvato', 'success');
      editing = null;
      await listRef.reload();
      await refreshDataset();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally {
      saving = false;
    }
  }

  async function del(row) {
    if (!confirm('Eliminare ' + row.name + '?')) return;
    try {
      await api.del('/api/classes/' + row.id);
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  const columns = [
    { key: 'name', label: 'Nome' },
    { key: 'year', label: 'Anno' },
    { key: 'section', label: 'Sez.' },
    { key: 'curriculum', label: 'Indirizzo' },
    { key: 'n_students', label: 'Studenti' },
    { key: 'ore_totali', label: 'Ore/sett.',
      render: (r) => (r.subjects || []).reduce((s, x) => s + Number(x.hours_per_week || 0), 0) },
  ];
  const help = {
    fields: ['name', 'year', 'anno', 'section', 'sezione', 'curriculum',
             'indirizzo', 'n_students', 'ore_totali', 'n_subjects'],
    examples: [
      'anno = 3',
      'indirizzo contains scientifico',
      'ore_totali > 30',
      'name startswith 1',
      'unavailable_on(domenica)'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Classi</h1>
    <button class="btn-primary ml-auto" on:click={newClass}>+ Nuova classe</button>
    <ImportButton entity="classes" onDone={() => listRef?.reload()}/>
    <button class="btn !text-xs" on:click={() => (showBulk = true)}
            disabled={selectedIds.length === 0}
            title="Applica un vincolo a tutte le classi selezionate">
      Vincolo collettivo ({selectedIds.length})
    </button>
  </div>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/classes"
    {columns}
    {help}
    rowKey={(r) => r.id}
    selectable={true}
    bind:selectedIds
    let:row let:columns>
    <td><strong>{row.name}</strong></td>
    <td class="text-center">{row.year}</td>
    <td>{row.section ?? ''}</td>
    <td>{row.curriculum ?? ''}</td>
    <td class="text-center">{row.n_students}</td>
    <td class="text-center">
      {(row.subjects || []).reduce((s, x) => s + Number(x.hours_per_week || 0), 0)}
    </td>
    <td class="whitespace-nowrap">
      <button class="btn !text-xs !px-2 !py-1" on:click={() => edit(row)}>Modifica</button>
      <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(row)}>Elimina</button>
    </td>
  </SortableQueryableList>
</div>

<BulkApplyModal entity="classes" bind:open={showBulk}
                {selectedIds}
                onDone={() => { selectedIds = []; listRef?.reload(); }}/>

<Modal open={!!editing} title={editing?._new ? 'Nuova classe' : 'Modifica classe'} onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field"><label>Nome</label><input bind:value={editing.name}/></div>
      <div class="field">
        <label>Nickname (mostrato nell'orario)
          <span class="text-xs text-ink-400">- default: nome</span>
        </label>
        <input bind:value={editing.nickname} placeholder={editing.name ?? ''}/>
      </div>
      <div class="field"><label>Anno</label><input type="number" min="1" max="5" bind:value={editing.year}/></div>
      <div class="field"><label>Sezione</label><input bind:value={editing.section}/></div>
      <div class="field">
        <label>Indirizzo</label>
        <div class="flex gap-2">
          <select bind:value={editing.curriculum_id}
                  on:change={() => {
                    const c = allCurricula.find((x) => x.id === editing.curriculum_id);
                    if (c) editing.curriculum = c.code;
                  }}
                  class="flex-1 px-2 py-1 border border-ink-200 rounded">
            <option value={null}>(nessuno)</option>
            {#each allCurricula as c}
              <option value={c.id}>{c.code} - {c.name}</option>
            {/each}
          </select>
          <button class="btn !text-xs !px-2 !py-1"
                  on:click={applyCurriculumGrid}
                  disabled={!editing.curriculum_id}
                  title="Carica il monte-ore dell'indirizzo per l'anno selezionato">
            Importa griglia
          </button>
        </div>
        <input class="mt-1 text-xs" placeholder="(stringa libera, opzionale)"
               bind:value={editing.curriculum}/>
      </div>
      <div class="field"><label>N. studenti</label><input type="number" bind:value={editing.n_students}/></div>
      <div class="field"><label>Note</label><input bind:value={editing.notes}/></div>
    </div>

    <div class="mt-4">
      <h3 class="mb-2">Vincoli HARD</h3>
      <div class="grid grid-cols-2 gap-2 text-sm">
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_entry_at_8}/> Ingresso alle 8:00</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_exit_after_12}/> Uscita non prima delle 12</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_no_holes}/> No buchi nella giornata</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_dual_math}/> Doppia ora consecutiva di Mat</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_dual_italian}/> Doppia ora di Italiano</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_motorie_pairs}/> Sc. motorie a coppie</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_max_6_per_day}/> Max 6 ore/giorno</label>
      </div>
    </div>

    <div class="mt-4 field">
      <label>Peso minimizzazione 6^a ora (SOFT)</label>
      <input type="number" bind:value={editing.soft_minimize_sixth_weight}/>
    </div>

    <div class="mt-4">
      <h3 class="mb-2">Materie e ore settimanali</h3>
      <table class="tbl">
        <thead><tr><th>Materia</th><th>Ore/sett.</th><th></th></tr></thead>
        <tbody>
          {#each editing.subjects as s, i}
            <tr>
              <td>
                <input list="subj-{i}" class="w-full px-2 py-1 border border-ink-200 rounded" bind:value={s.subject}/>
                <datalist id="subj-{i}">{#each allSubjects as sn}<option value={sn}/>{/each}</datalist>
              </td>
              <td class="w-24"><input type="number" min="0" max="10" bind:value={s.hours_per_week} class="w-full px-2 py-1 border border-ink-200 rounded"/></td>
              <td><button class="btn-danger !text-xs !px-2 !py-1" on:click={() => delSubject(i)}>x</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <button class="btn !text-xs !px-2 !py-1 mt-2" on:click={addSubject}>+ Materia</button>
    </div>

    <div class="mt-4">
      <AvailabilityMatrix
        title="Disponibilita oraria della classe"
        value={editing.unavailability || []}
        onChange={onMatrixChange}/>
    </div>

    <div class="mt-4">
      <LogicalUnavailabilitiesPanel entityType="classes" entityId={editing.id ?? null}/>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary focus-ring" on:click={save} disabled={saving}>
        {saving ? 'Salvataggio...' : 'Salva'}
      </button>
    </div>
  {/if}
</Modal>
