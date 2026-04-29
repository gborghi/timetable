<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash, refreshDataset } from '$lib/stores.js';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';

  let editing = null;
  let listRef = null;
  let allStudents = [];
  let allSubjects = [];
  let memberFilter = '';

  onMount(async () => {
    try {
      allStudents = await api.get('/api/students');
      allSubjects = (await api.get('/api/subjects')).map((s) => s.name).sort();
    } catch { /* */ }
  });

  async function reloadStudents() {
    allStudents = await api.get('/api/students');
  }

  function newGroup() {
    editing = {
      _new: true, name: '', nickname: '', kind: 'splitting',
      description: '', notes: '',
      student_ids: [], subject_hours: []
    };
  }

  function edit(row) { editing = JSON.parse(JSON.stringify(row)); }

  function toggleStudent(sid) {
    if (editing.student_ids.includes(sid)) {
      editing.student_ids = editing.student_ids.filter((x) => x !== sid);
    } else {
      editing.student_ids = [...editing.student_ids, sid];
    }
  }

  function addSubjectHours() {
    editing.subject_hours = [...editing.subject_hours,
                              { subject: '', hours_per_week: 1 }];
  }
  function delSubjectHours(i) {
    editing.subject_hours = editing.subject_hours.filter((_, idx) => idx !== i);
  }

  $: filteredStudents = allStudents.filter((s) => {
    if (!memberFilter) return true;
    const t = memberFilter.toLowerCase();
    return (s.last_name || '').toLowerCase().includes(t)
        || (s.first_name || '').toLowerCase().includes(t)
        || (s.class_name || '').toLowerCase().includes(t)
        || (s.student_code || '').toLowerCase().includes(t);
  });

  async function save() {
    const payload = { ...editing };
    delete payload._new; delete payload.id;
    delete payload.n_students; delete payload.n_classes_touched;
    try {
      if (editing._new) await api.post('/api/groups', payload);
      else await api.put('/api/groups/' + editing.id, payload);
      flash('Gruppo salvato', 'success');
      editing = null;
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function del(row) {
    if (!confirm('Eliminare gruppo ' + row.name + '?')) return;
    try {
      await api.del('/api/groups/' + row.id);
      await listRef.reload();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  const columns = [
    { key: 'name', label: 'Nome' },
    { key: 'kind', label: 'Tipo' },
    { key: 'n_students', label: 'Studenti' },
    { key: 'n_classes_touched', label: 'Classi coinvolte' },
    { key: 'n_subjects', label: 'Materie' },
  ];
  const help = {
    fields: ['name', 'kind', 'description', 'n_students', 'n_classes_touched', 'n_subjects'],
    examples: [
      'kind = language',
      'name contains spagnolo',
      'n_students >= 10'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Gruppi articolati</h1>
    <button class="btn-primary ml-auto" on:click={newGroup}>+ Nuovo gruppo</button>
    <ImportButton entity="groups" onDone={() => listRef?.reload()}/>
  </div>

  <p class="text-xs text-ink-500">
    Un gruppo articolato raggruppa studenti (anche da classi diverse) che
    fanno una o piu' materie insieme: seconda lingua, IRC vs Alternativa,
    recupero/potenziamento, classe frazionata, ecc.
  </p>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/groups"
    {columns}
    {help}
    rowKey={(r) => r.id}
    let:row let:columns>
    <tr>
      <td><strong>{row.name}</strong></td>
      <td><span class="pill pill-blue">{row.kind}</span></td>
      <td class="text-center">{row.n_students}</td>
      <td class="text-center">{row.n_classes_touched}</td>
      <td class="text-center">{(row.subject_hours || []).length}</td>
      <td class="whitespace-nowrap">
        <button class="btn !text-xs !px-2 !py-1" on:click={() => edit(row)}>Modifica</button>
        <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(row)}>Elimina</button>
      </td>
    </tr>
  </SortableQueryableList>
</div>

<Modal open={!!editing} title={editing?._new ? 'Nuovo gruppo' : 'Gruppo: ' + (editing?.name || '')}
       onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field"><label>Nome</label><input bind:value={editing.name}/></div>
      <div class="field">
        <label>Nickname
          <span class="text-xs text-ink-400">- default: nome</span>
        </label>
        <input bind:value={editing.nickname} placeholder={editing.name ?? ''}/>
      </div>
      <div class="field"><label>Tipo</label>
        <select bind:value={editing.kind}>
          <option value="splitting">splitting (frazionamento classe)</option>
          <option value="language">language (seconda lingua)</option>
          <option value="religion">religion (IRC / alternativa)</option>
          <option value="support">support (recupero/potenziamento)</option>
          <option value="other">other</option>
        </select>
      </div>
      <div class="field col-span-2"><label>Descrizione</label>
        <input bind:value={editing.description}/></div>
    </div>

    <div class="mt-4 grid grid-cols-2 gap-4">
      <div class="space-y-2">
        <h3 class="!text-base">Studenti del gruppo
          <span class="text-xs text-ink-500">({editing.student_ids.length} selezionati)</span>
        </h3>
        <input class="w-full px-2 py-1 border border-ink-200 rounded text-sm"
               placeholder="Filtra per cognome/classe/matricola"
               bind:value={memberFilter}/>
        <div class="card !shadow-none p-2 max-h-72 overflow-auto text-xs">
          {#each filteredStudents as s (s.id)}
            <label class="flex items-center gap-2 py-0.5 hover:bg-ink-50">
              <input type="checkbox" checked={editing.student_ids.includes(s.id)}
                     on:change={() => toggleStudent(s.id)}/>
              <span>{s.last_name} {s.first_name}
                <span class="text-ink-400">({s.class_name ?? '-'} {s.student_code ? '#' + s.student_code : ''})</span>
              </span>
            </label>
          {/each}
          {#if filteredStudents.length === 0}
            <div class="text-ink-400 italic p-2">Nessuno studente trovato. Importa o crea studenti prima.</div>
          {/if}
        </div>
      </div>

      <div class="space-y-2">
        <h3 class="!text-base">Materie e ore del gruppo</h3>
        <table class="tbl text-sm">
          <thead><tr><th>Materia</th><th>Ore/sett.</th><th></th></tr></thead>
          <tbody>
            {#each editing.subject_hours as sh, i}
              <tr>
                <td>
                  <input list="g-subj-{i}" class="w-full px-2 py-1 border border-ink-200 rounded"
                         bind:value={sh.subject}/>
                  <datalist id="g-subj-{i}">
                    {#each allSubjects as sn}<option value={sn}/>{/each}
                  </datalist>
                </td>
                <td class="w-20">
                  <input type="number" min="0" max="10" bind:value={sh.hours_per_week}
                         class="w-full px-2 py-1 border border-ink-200 rounded"/>
                </td>
                <td>
                  <button class="btn-danger !text-xs !px-2 !py-1"
                          on:click={() => delSubjectHours(i)}>x</button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <button class="btn !text-xs !px-2 !py-1" on:click={addSubjectHours}>+ Materia</button>
      </div>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary" on:click={save}>Salva</button>
    </div>
  {/if}
</Modal>
