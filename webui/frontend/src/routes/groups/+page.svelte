<script>
  import DecorIcon from '$lib/components/DecorIcon.svelte';
  import { confirmDialog } from '$lib/confirm';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import { cloneRow } from '$lib/utils';
  import {
    groups as groupsSvc,
    students as studentsSvc,
    studentTags as studentTagsSvc,
    subjects as subjectsSvc,
  } from '$lib/services';

  let editing = null;
  let listRef = null;
  let allStudents = [];
  let allSubjects = [];
  let allTagNames = [];
  let memberFilter = '';
  let tagFilter = '';
  let tagFilterMode = 'any_of';   // 'any_of' | 'all_of'
  let tagPreviewBusy = false;

  onMount(async () => {
    try {
      allStudents = await studentsSvc.list();
      allSubjects = (await subjectsSvc.list()).map((s) => s.name).sort();
      allTagNames = (await studentTagsSvc.list()).map((t) => t.name).sort();
    } catch { /* */ }
  });

  async function precompileFromTags() {
    const list = (tagFilter || '')
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    if (list.length === 0) {
      flash('Indica almeno un tag (separa con virgola)', 'error');
      return;
    }
    tagPreviewBusy = true;
    try {
      const q = tagFilterMode === 'all_of'
        ? { all_of: list }
        : { any_of: list };
      const matches = await studentsSvc.byTags(q);
      const ids = matches.map((m) => m.id);
      const merged = Array.from(new Set([...editing.student_ids, ...ids]));
      editing = { ...editing, student_ids: merged };
      flash(
        'Aggiunti ' + ids.length + ' studenti (totale: '
        + merged.length + ')',
        'success',
      );
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { tagPreviewBusy = false; }
  }

  async function clearMembers() {
    if (editing.student_ids.length === 0) return;
    if (!await confirmDialog('Rimuovere tutti i ' + editing.student_ids.length
                 + ' membri attualmente selezionati?')) return;
    editing = { ...editing, student_ids: [] };
  }

  async function reloadStudents() {
    allStudents = await studentsSvc.list();
  }

  function newGroup() {
    editing = {
      _new: true, name: '', nickname: '', kind: 'splitting',
      description: '', notes: '',
      student_ids: [], subject_hours: []
    };
  }

  function edit(row) { editing = cloneRow(row); }

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

  let saving = false;
  async function save() {
    const payload = { ...editing };
    delete payload._new; delete payload.id;
    delete payload.n_students; delete payload.n_classes_touched;
    saving = true;
    try {
      if (editing._new) await groupsSvc.create(payload);
      else await groupsSvc.update(editing.id, payload);
      flash('Gruppo salvato', 'success');
      editing = null;
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { saving = false; }
  }

  async function del(row) {
    if (!await confirmDialog('Eliminare gruppo ' + row.name + '?')) return;
    try {
      await groupsSvc.remove(row.id);
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

<div class="space-y-4" data-testid="groups-page">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1 class="flex items-center gap-2"><DecorIcon name="group" size={26} class="shrink-0" /> Gruppi articolati</h1>
    <button class="btn-primary ml-auto" on:click={newGroup}
            data-testid="add-group-btn">+ Nuovo gruppo</button>
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
    entity="groups"
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
        <button class="btn !text-xs !px-2 !py-1"
                data-testid="group-edit-btn"
                data-group-id={row.id}
                on:click={() => edit(row)}>Modifica</button>
        <button class="btn-danger !text-xs !px-2 !py-1"
                data-testid="group-delete-btn"
                data-group-id={row.id}
                on:click={() => del(row)}>Elimina</button>
      </td>
    </tr>
  </SortableQueryableList>
</div>

<Modal open={!!editing} title={editing?._new ? 'Nuovo gruppo' : 'Gruppo: ' + (editing?.name || '')}
       onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3" data-testid="group-form">
      <div class="field"><label>Nome</label><input bind:value={editing.name} data-testid="group-name-input"/></div>
      <div class="field">
        <label>Nickname
          <span class="text-xs text-ink-400">- default: nome</span>
        </label>
        <input bind:value={editing.nickname} placeholder={editing.name ?? ''}/>
      </div>
      <div class="field"><label>Tipo</label>
        <select bind:value={editing.kind} data-testid="group-kind-select">
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

        <details class="text-xs border border-ink-200 rounded p-2 bg-ink-50/40">
          <summary class="cursor-pointer font-medium">Precompila da tag studenti</summary>
          <div class="mt-2 grid grid-cols-[1fr_auto_auto] gap-1.5 items-end">
            <div>
              <label class="block mb-0.5 text-[11px] text-ink-500">
                Tag (separa con virgola)
              </label>
              <input class="w-full px-2 py-1 border border-ink-200 rounded"
                     list="all-student-tags"
                     placeholder="es. debito_matematica_4, BES"
                     bind:value={tagFilter}/>
              <datalist id="all-student-tags">
                {#each allTagNames as t}<option value={t}></option>{/each}
              </datalist>
            </div>
            <div>
              <label class="block mb-0.5 text-[11px] text-ink-500">Logica</label>
              <select class="px-2 py-1 border border-ink-200 rounded"
                      bind:value={tagFilterMode}>
                <option value="any_of">qualunque (OR)</option>
                <option value="all_of">tutti (AND)</option>
              </select>
            </div>
            <button type="button" class="btn !text-xs"
                    disabled={tagPreviewBusy}
                    on:click={precompileFromTags}>
              {tagPreviewBusy ? '...' : 'Aggiungi'}
            </button>
          </div>
          <p class="text-[10px] text-ink-500 mt-1">
            Aggiunge gli studenti che hanno (almeno uno / tutti) i tag
            indicati, mantenendo quelli gia' selezionati. I tag NON
            sostituiscono il gruppo: il gruppo resta l'unita'
            operativa di scheduling.
          </p>
        </details>

        <div class="flex gap-2 items-center">
          <input class="flex-1 px-2 py-1 border border-ink-200 rounded text-sm"
                 placeholder="Filtra per cognome/classe/matricola"
                 bind:value={memberFilter}/>
          <button type="button" class="btn !text-xs"
                  on:click={clearMembers}
                  disabled={editing.student_ids.length === 0}>
            Svuota
          </button>
        </div>
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
                    {#each allSubjects as sn}<option value={sn}></option>{/each}
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
      <button class="btn" on:click={() => (editing = null)}
              data-testid="group-cancel-btn">Annulla</button>
      <button class="btn-primary focus-ring" on:click={save} disabled={saving}
              data-testid="group-save-btn">
        {saving ? 'Salvataggio...' : 'Salva'}
      </button>
    </div>
  {/if}
</Modal>
