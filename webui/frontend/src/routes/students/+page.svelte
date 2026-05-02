<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import TagPicker from '$lib/components/TagPicker.svelte';
  import ManageTagsModal from '$lib/components/ManageTagsModal.svelte';
  import { cloneRow } from '$lib/utils';
  import {
    students as studentsSvc,
    studentTags as tagSvc,
    classes as classesSvc,
  } from '$lib/services';

  // Stable color hash mirroring TagPicker's palette
  const PALETTE = [
    'bg-emerald-100 text-emerald-700 border-emerald-200',
    'bg-sky-100 text-sky-700 border-sky-200',
    'bg-violet-100 text-violet-700 border-violet-200',
    'bg-amber-100 text-amber-700 border-amber-200',
    'bg-rose-100 text-rose-700 border-rose-200',
    'bg-teal-100 text-teal-700 border-teal-200',
    'bg-indigo-100 text-indigo-700 border-indigo-200',
    'bg-lime-100 text-lime-700 border-lime-200',
    'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200',
    'bg-cyan-100 text-cyan-700 border-cyan-200',
    'bg-orange-100 text-orange-700 border-orange-200',
    'bg-pink-100 text-pink-700 border-pink-200',
  ];
  function tagColor(name) {
    const s = String(name || '');
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return PALETTE[h % PALETTE.length];
  }

  let editing = null;
  let listRef = null;
  let allClasses = [];
  let allTagNames = [];
  let showTagsModal = false;

  onMount(async () => {
    try {
      allClasses = await classesSvc.list();
    } catch { /* */ }
    await reloadTags();
  });

  async function reloadTags() {
    try {
      const ts = await tagSvc.list();
      allTagNames = ts.map((t) => t.name).sort();
    } catch { /* */ }
  }

  function newStudent() {
    editing = {
      _new: true, last_name: '', first_name: '', nickname: '',
      birth_date: null, gender: null, email: '',
      student_code: '', class_id: null, notes: '',
      tags: [],
    };
  }

  function edit(row) {
    editing = cloneRow(row);
    if (!Array.isArray(editing.tags)) editing.tags = [];
  }
  function onTagsChange(next) {
    editing = { ...editing, tags: next };
  }

  let saving = false;
  async function save() {
    const payload = { ...editing };
    delete payload._new; delete payload.id;
    delete payload.class_name; delete payload.n_groups;
    if (payload.class_id === '' || payload.class_id === undefined)
      payload.class_id = null;
    saving = true;
    try {
      if (editing._new) await studentsSvc.create(payload);
      else await studentsSvc.update(editing.id, payload);
      flash('Studente salvato', 'success');
      editing = null;
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { saving = false; }
  }

  async function del(row) {
    if (!confirm('Eliminare ' + row.last_name + ' ' + row.first_name + '?')) return;
    const snapshot = cloneRow(row);
    delete snapshot.id;
    delete snapshot.class_name;
    delete snapshot.n_groups;
    try {
      await studentsSvc.remove(row.id);
      await listRef.reload();
      flash('Studente eliminato', 'success', {
        ms: 8000,
        action: {
          label: 'Annulla',
          fn: async () => {
            try {
              await studentsSvc.create(snapshot);
              await listRef.reload();
              flash('Eliminazione annullata', 'success');
            } catch (e) {
              flash('Annullamento fallito: ' + e.message, 'error');
            }
          }
        }
      });
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
    { key: 'tags', label: 'Tag', sortable: false,
      render: (r) => (r.tags || []).join(', ') || '-' },
  ];
  const help = {
    fields: ['last_name', 'cognome', 'first_name', 'nome', 'class_name',
             'classe', 'student_code', 'matricola', 'email', 'gender',
             'n_groups', 'tags', 'tag'],
    examples: [
      'cognome startswith Ross',
      'classe = 1A',
      'gender = F',
      'n_groups > 0',
      'has_tag(BES)',
      'tag(debito_matematica_4) AND classe startswith 4'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Studenti</h1>
    <button class="btn ml-auto" on:click={() => (showTagsModal = true)}
            title="Crea, rinomina o elimina i tag degli studenti">
      Gestisci tag
    </button>
    <button class="btn-primary" on:click={newStudent}>+ Nuovo studente</button>
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
      <td>
        {#if (row.tags || []).length === 0}
          <span class="text-ink-400">-</span>
        {:else}
          <div class="flex flex-wrap gap-1">
            {#each row.tags as t (t)}
              <span class="inline-flex items-center px-1.5 py-0.5 rounded-full
                           border text-[10px] font-medium {tagColor(t)}">#{t}</span>
            {/each}
          </div>
        {/if}
      </td>
      <td class="whitespace-nowrap">
        <button class="btn !text-xs !px-2 !py-1" on:click={() => edit(row)}>Modifica</button>
        <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(row)}>Elimina</button>
      </td>
    </tr>
  </SortableQueryableList>
</div>

<ManageTagsModal bind:open={showTagsModal}
                 service={tagSvc}
                 title="Gestisci tag studenti"
                 countField="n_students"
                 countLabelSingular="studente"
                 countLabelPlural="studenti"
                 namePlaceholder="es. debito_matematica_4"
                 descPlaceholder="Studenti delle quarte con debito in matematica"
                 onClose={() => (showTagsModal = false)}
                 onChanged={async () => { await reloadTags(); listRef?.reload(); }}/>

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

    <div class="mt-4 field">
      <div class="flex items-baseline gap-3 mb-1">
        <label class="!mb-0">Tag</label>
        <span class="text-[11px] text-ink-500">
          Etichette libere (es. <code>BES</code>, <code>DSA</code>,
          <code>debito_matematica_4</code>, <code>studente_atleta</code>).
          Usabili dal DSL come <code>"BES" in s.tags</code> o
          <code>has_tag(BES)</code> nelle query.
        </span>
        <button type="button" class="btn !text-xs !px-2 !py-0.5 ml-auto"
                on:click={() => (showTagsModal = true)}>Gestisci tag...</button>
      </div>
      <TagPicker
        value={editing.tags || []}
        suggestions={allTagNames}
        onChange={onTagsChange}/>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary focus-ring" on:click={save} disabled={saving}>
        {saving ? 'Salvataggio...' : 'Salva'}
      </button>
    </div>
  {/if}
</Modal>
