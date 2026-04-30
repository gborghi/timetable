<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash, refreshDataset } from '$lib/stores.js';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import { cloneRow } from '$lib/utils.js';

  let editing = null;
  let listRef = null;
  let allClasses = [];

  onMount(async () => {
    try {
      allClasses = await api.get('/api/classes');
    } catch { /* */ }
  });

  function newStudent() {
    editing = {
      _new: true, last_name: '', first_name: '', nickname: '',
      birth_date: null, gender: null, email: '',
      student_code: '', class_id: null, notes: ''
    };
  }

  function edit(row) { editing = cloneRow(row); }

  let saving = false;
  async function save() {
    const payload = { ...editing };
    delete payload._new; delete payload.id;
    delete payload.class_name; delete payload.n_groups;
    if (payload.class_id === '' || payload.class_id === undefined)
      payload.class_id = null;
    saving = true;
    try {
      if (editing._new) await api.post('/api/students', payload);
      else await api.put('/api/students/' + editing.id, payload);
      flash('Studente salvato', 'success');
      editing = null;
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { saving = false; }
  }

  async function del(row) {
    if (!confirm('Eliminare ' + row.last_name + ' ' + row.first_name + '?')) return;
    try {
      await api.del('/api/students/' + row.id);
      await listRef.reload();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  const columns = [
    { key: 'last_name', label: 'Cognome' },
    { key: 'first_name', label: 'Nome' },
    { key: 'nickname', label: 'Nickname' },
    { key: 'class_name', label: 'Classe' },
    { key: 'student_code', label: 'Matricola' },
    { key: 'gender', label: 'Sesso' },
    { key: 'n_groups', label: 'Gruppi' },
  ];
  const help = {
    fields: ['last_name', 'cognome', 'first_name', 'nome', 'class_name',
             'classe', 'student_code', 'matricola', 'email', 'gender', 'n_groups'],
    examples: [
      'cognome startswith Ross',
      'classe = 1A',
      'gender = F',
      'n_groups > 0'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Studenti</h1>
    <button class="btn-primary ml-auto" on:click={newStudent}>+ Nuovo studente</button>
    <ImportButton entity="students" onDone={() => listRef?.reload()}/>
  </div>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/students"
    {columns}
    {help}
    rowKey={(r) => r.id}
    let:row let:columns>
    <tr>
      <td><strong>{row.last_name}</strong></td>
      <td>{row.first_name}</td>
      <td class="text-xs">{row.nickname ?? ''}</td>
      <td>{row.class_name ?? ''}</td>
      <td>{row.student_code ?? ''}</td>
      <td class="text-center">{row.gender ?? ''}</td>
      <td class="text-center">{row.n_groups}</td>
      <td class="whitespace-nowrap">
        <button class="btn !text-xs !px-2 !py-1" on:click={() => edit(row)}>Modifica</button>
        <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(row)}>Elimina</button>
      </td>
    </tr>
  </SortableQueryableList>
</div>

<Modal open={!!editing} title={editing?._new ? 'Nuovo studente' : 'Studente'}
       onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field"><label>Cognome</label><input bind:value={editing.last_name}/></div>
      <div class="field"><label>Nome</label><input bind:value={editing.first_name}/></div>
      <div class="field col-span-2">
        <label>Nickname (mostrato nell'orario)
          <span class="text-xs text-ink-400">- default: "Cognome Nome"</span>
        </label>
        <input bind:value={editing.nickname}
               placeholder={(editing.last_name ?? '') + ' ' + (editing.first_name ?? '')}/>
      </div>
      <div class="field"><label>Data nascita</label>
        <input type="date" bind:value={editing.birth_date}/></div>
      <div class="field"><label>Sesso</label>
        <select bind:value={editing.gender}>
          <option value={null}></option>
          <option value="M">M</option>
          <option value="F">F</option>
          <option value="other">other</option>
        </select>
      </div>
      <div class="field"><label>Email</label><input bind:value={editing.email}/></div>
      <div class="field"><label>Matricola</label><input bind:value={editing.student_code}/></div>
      <div class="field col-span-2"><label>Classe</label>
        <select bind:value={editing.class_id}>
          <option value={null}>(nessuna)</option>
          {#each allClasses as c}
            <option value={c.id}>{c.name}</option>
          {/each}
        </select>
      </div>
      <div class="field col-span-2"><label>Note</label><input bind:value={editing.notes}/></div>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary focus-ring" on:click={save} disabled={saving}>
        {saving ? 'Salvataggio...' : 'Salva'}
      </button>
    </div>
  {/if}
</Modal>
