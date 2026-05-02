<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import { ROOM_KINDS } from '$lib/constants';
  import Modal from '$lib/components/Modal.svelte';
  import AvailabilityMatrix from '$lib/components/AvailabilityMatrix.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import LogicalUnavailabilitiesPanel from '$lib/components/LogicalUnavailabilitiesPanel.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import BulkApplyModal from '$lib/components/BulkApplyModal.svelte';
  import ClassroomTagPicker from '$lib/components/ClassroomTagPicker.svelte';
  import ManageTagsModal from '$lib/components/ManageTagsModal.svelte';
  import { cloneRow } from '$lib/utils';
  import {
    classrooms as classroomsSvc,
    classroomTags as tagSvc,
    subjects as subjectsSvc,
    classes as classesSvc,
  } from '$lib/services';

  // colour helper shared with the picker
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
  let allSubjects = [];
  let allClasses = [];
  let allTagNames = [];
  let listRef = null;
  let selectedIds = [];
  let showBulk = false;
  let showTagsModal = false;

  let showGenPanel = false;
  let suggested = null;
  let genCounts = {
    lab_fisica: 1, lab_chimica: 1, lab_informatica: 1, lab_linguistico: 1,
    palestra: 1, biblioteca: 1, aula_speciale: 1
  };
  let busyGen = false;

  onMount(async () => {
    try {
      allSubjects = (await subjectsSvc.list()).map((s) => s.name).sort();
      allClasses = (await classesSvc.list()).map((c) => c.name).sort();
    } catch { /* */ }
    await reloadTags();
  });

  async function reloadTags() {
    try {
      const ts = await tagSvc.list();
      allTagNames = ts.map((t) => t.name).sort();
    } catch { /* */ }
  }

  async function loadSuggested() {
    try {
      suggested = await classroomsSvc.suggestedCounts();
      genCounts = { ...suggested.counts };
      showGenPanel = true;
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function runGenerate() {
    if (listRef && listRef.rows && listRef.rows.length > 0
        && !confirm('Sostituire le aule esistenti con la nuova configurazione?')) return;
    busyGen = true;
    try {
      const payload = {
        n_lab_fisica: Number(genCounts.lab_fisica),
        n_lab_chimica: Number(genCounts.lab_chimica),
        n_lab_informatica: Number(genCounts.lab_informatica),
        n_lab_linguistico: Number(genCounts.lab_linguistico),
        n_palestra: Number(genCounts.palestra),
        n_biblioteca: Number(genCounts.biblioteca),
        n_aula_speciale: Number(genCounts.aula_speciale)
      };
      const r = await classroomsSvc.autoGenerate(payload);
      flash('Aule generate: ' + r.created + ' (su ' + r.n_classes + ' classi)', 'success');
      showGenPanel = false;
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyGen = false; }
  }

  function newRoom() {
    editing = {
      _new: true, name: '', kind: 'standard',
      capacity: 30, multi_class: false, multi_class_max: 1,
      multi_class_pref: 1, multi_class_pref_weight: 10,
      notes: '',
      subject_prefs: [], class_prefs: [], unavailability: [],
      tags: [],
    };
  }
  function edit(row) { editing = cloneRow(row);
    if (!Array.isArray(editing.unavailability)) editing.unavailability = [];
    if (!Array.isArray(editing.tags)) editing.tags = [];
  }
  function onTagsChange(next) {
    editing = { ...editing, tags: next };
  }
  function addSubjectPref() { editing.subject_prefs = [...editing.subject_prefs, { subject: '', weight: 10, required: false }]; }
  function delSubjectPref(i) { editing.subject_prefs = editing.subject_prefs.filter((_, idx) => idx !== i); }
  function addClassPref() { editing.class_prefs = [...editing.class_prefs, { class_name: '', weight: 20, is_home: false }]; }
  function delClassPref(i) { editing.class_prefs = editing.class_prefs.filter((_, idx) => idx !== i); }
  function onMatrixChange(newCells) {
    editing = { ...editing, unavailability: newCells };
  }

  async function save() {
    const payload = { ...editing };
    delete payload._new; delete payload.id;
    try {
      if (editing._new) await classroomsSvc.create(payload);
      else await classroomsSvc.update(editing.id, payload);
      flash('Salvato', 'success');
      editing = null;
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function del(row) {
    if (!confirm('Eliminare ' + row.name + '?')) return;
    try {
      await classroomsSvc.remove(row.id);
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  $: totalIfApplied = (suggested?.n_classes || 0)
    + Number(genCounts.lab_fisica || 0) + Number(genCounts.lab_chimica || 0)
    + Number(genCounts.lab_informatica || 0) + Number(genCounts.lab_linguistico || 0)
    + Number(genCounts.palestra || 0) + Number(genCounts.biblioteca || 0)
    + Number(genCounts.aula_speciale || 0);

  const columns = [
    { key: 'name', label: 'Nome' },
    { key: 'kind', label: 'Tipo' },
    { key: 'capacity', label: 'Capienza' },
    { key: 'multi_class', label: 'Multi-classe',
      render: (r) => r.multi_class ? `max ${r.multi_class_max} (pref ${r.multi_class_pref})` : 'no' },
    { key: 'tags', label: 'Tag', sortable: false,
      render: (r) => (r.tags || []).join(', ') || '-' },
  ];
  const help = {
    fields: ['name', 'kind', 'tipo', 'capacity', 'capienza',
             'multi_class', 'multi_classe', 'tags', 'tag'],
    examples: [
      'tipo = palestra',
      'tipo in [lab_fisica, lab_chimica]',
      'capienza >= 25 AND tipo contains lab',
      'multi_class = 1',
      'has_tag(matematica)',
      'tag(scientifico) AND tipo = standard',
      'unavailable_on(giovedi, 13)'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Aule</h1>
    <button class="btn ml-auto" on:click={loadSuggested}>Genera aule...</button>
    <button class="btn" on:click={() => (showTagsModal = true)}
            title="Crea, rinomina o elimina i tag delle aule">
      Gestisci tag
    </button>
    <button class="btn-primary" on:click={newRoom}>+ Nuova aula</button>
    <ImportButton entity="classrooms" onDone={() => listRef?.reload()}/>
    <button class="btn !text-xs" on:click={() => (showBulk = true)}
            disabled={selectedIds.length === 0}
            title="Applica un vincolo a tutte le aule selezionate">
      Vincolo collettivo ({selectedIds.length})
    </button>
  </div>

  {#if showGenPanel && suggested}
    <div class="card p-5 border-accent-500/40 bg-accent-500/5">
      <div class="flex items-baseline gap-3 mb-3">
        <h2>Parametri generazione aule</h2>
        <span class="text-sm text-ink-500">
          Classi attualmente nel DB: <strong>{suggested.n_classes}</strong>
          - parametri suggeriti compilati di conseguenza
        </span>
        <button class="btn !text-xs !px-2 !py-1 ml-auto" on:click={() => showGenPanel = false}>chiudi</button>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="field"><label>Lab fisica</label><input type="number" min="0" bind:value={genCounts.lab_fisica}/><span class="text-[10px] text-ink-500">{suggested.rules.lab_fisica}</span></div>
        <div class="field"><label>Lab chimica</label><input type="number" min="0" bind:value={genCounts.lab_chimica}/><span class="text-[10px] text-ink-500">{suggested.rules.lab_chimica}</span></div>
        <div class="field"><label>Lab informatica</label><input type="number" min="0" bind:value={genCounts.lab_informatica}/><span class="text-[10px] text-ink-500">{suggested.rules.lab_informatica}</span></div>
        <div class="field"><label>Lab linguistico</label><input type="number" min="0" bind:value={genCounts.lab_linguistico}/><span class="text-[10px] text-ink-500">{suggested.rules.lab_linguistico}</span></div>
        <div class="field"><label>Palestre</label><input type="number" min="0" bind:value={genCounts.palestra}/><span class="text-[10px] text-ink-500">{suggested.rules.palestra}</span></div>
        <div class="field"><label>Biblioteche</label><input type="number" min="0" bind:value={genCounts.biblioteca}/><span class="text-[10px] text-ink-500">{suggested.rules.biblioteca}</span></div>
        <div class="field"><label>Aule speciali</label><input type="number" min="0" bind:value={genCounts.aula_speciale}/><span class="text-[10px] text-ink-500">{suggested.rules.aula_speciale}</span></div>
        <div class="field">
          <label>Aule totali se generate</label>
          <div class="px-2 py-1.5 rounded-md bg-white border border-ink-200 font-semibold">{totalIfApplied}</div>
          <span class="text-[10px] text-ink-500">{suggested.n_classes} standard + extra</span>
        </div>
      </div>
      <div class="mt-3 flex gap-2 items-center">
        <button class="btn-primary" on:click={runGenerate} disabled={busyGen}>
          {busyGen ? 'Generazione in corso...' : 'Genera aule'}
        </button>
        <button class="btn !text-xs" on:click={() => (genCounts = { ...suggested.counts })}>
          Ripristina suggeriti
        </button>
      </div>
    </div>
  {/if}

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/classrooms"
    {columns}
    {help}
    rowKey={(r) => r.id}
    selectable={true}
    bind:selectedIds
    let:row let:columns>
    <td><strong>{row.name}</strong></td>
    <td><span class="pill">{row.kind}</span></td>
    <td class="text-center">{row.capacity}</td>
    <td class="text-center">
      {#if row.multi_class}max {row.multi_class_max} (pref {row.multi_class_pref}){:else}no{/if}
    </td>
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
  </SortableQueryableList>
</div>

<BulkApplyModal entity="classrooms" bind:open={showBulk}
                {selectedIds}
                onDone={() => { selectedIds = []; listRef?.reload(); }}/>

<ManageTagsModal bind:open={showTagsModal}
                 onClose={() => (showTagsModal = false)}
                 onChanged={async () => { await reloadTags(); listRef?.reload(); }}/>

<Modal open={!!editing} title={editing?._new ? 'Nuova aula' : 'Modifica aula'} onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field"><label>Nome / codice</label><input bind:value={editing.name}/></div>
      <div class="field"><label>Tipo</label>
        <select bind:value={editing.kind}>{#each ROOM_KINDS as k}<option value={k.value}>{k.label}</option>{/each}</select>
      </div>
      <div class="field"><label>Capienza</label><input type="number" bind:value={editing.capacity}/></div>
      <div class="field"><label>Note</label><input bind:value={editing.notes}/></div>
    </div>

    <div class="mt-4 grid grid-cols-3 gap-3 items-end">
      <label class="flex gap-2 text-sm"><input type="checkbox" bind:checked={editing.multi_class}/> Multi-classe</label>
      <div class="field"><label>Max classi simultanee (HARD)</label><input type="number" bind:value={editing.multi_class_max}/></div>
      <div class="field"><label>Preferito (SOFT)</label><input type="number" bind:value={editing.multi_class_pref}/></div>
      <div class="field"><label>Peso preferenza concorrenza</label><input type="number" bind:value={editing.multi_class_pref_weight}/></div>
    </div>

    <div class="mt-4 field">
      <div class="flex items-baseline gap-3 mb-1">
        <label class="!mb-0">Tag</label>
        <span class="text-[11px] text-ink-500">
          Etichette libere usabili dal DSL (es. <code>"matematica" in l.classroom.tags</code>).
          I nuovi tag vengono creati automaticamente al salvataggio.
        </span>
        <button type="button" class="btn !text-xs !px-2 !py-0.5 ml-auto"
                on:click={() => (showTagsModal = true)}>Gestisci tag...</button>
      </div>
      <ClassroomTagPicker
        value={editing.tags || []}
        suggestions={allTagNames}
        onChange={onTagsChange}/>
    </div>

    <div class="mt-4">
      <h3 class="mb-2">Materie ammesse</h3>
      <table class="tbl">
        <thead><tr><th>Materia</th><th>Peso</th><th>HARD?</th><th></th></tr></thead>
        <tbody>
          {#each editing.subject_prefs as s, i}
            <tr>
              <td>
                <input list="sub-{i}" bind:value={s.subject} class="w-full px-2 py-1 border border-ink-200 rounded"/>
                <datalist id="sub-{i}">{#each allSubjects as ss}<option value={ss}/>{/each}</datalist>
              </td>
              <td class="w-24"><input type="number" bind:value={s.weight} class="w-full px-2 py-1 border border-ink-200 rounded"/></td>
              <td class="w-20 text-center"><input type="checkbox" bind:checked={s.required}/></td>
              <td><button class="btn-danger !text-xs !px-2 !py-1" on:click={() => delSubjectPref(i)}>x</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <button class="btn !text-xs !px-2 !py-1 mt-2" on:click={addSubjectPref}>+ Materia</button>
    </div>

    <div class="mt-4">
      <h3 class="mb-2">Classi affezionate</h3>
      <table class="tbl">
        <thead><tr><th>Classe</th><th>Peso</th><th>Home?</th><th></th></tr></thead>
        <tbody>
          {#each editing.class_prefs as c, i}
            <tr>
              <td>
                <input list="cls-{i}" bind:value={c.class_name} class="w-full px-2 py-1 border border-ink-200 rounded"/>
                <datalist id="cls-{i}">{#each allClasses as cn}<option value={cn}/>{/each}</datalist>
              </td>
              <td class="w-24"><input type="number" bind:value={c.weight} class="w-full px-2 py-1 border border-ink-200 rounded"/></td>
              <td class="w-20 text-center"><input type="checkbox" bind:checked={c.is_home}/></td>
              <td><button class="btn-danger !text-xs !px-2 !py-1" on:click={() => delClassPref(i)}>x</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <button class="btn !text-xs !px-2 !py-1 mt-2" on:click={addClassPref}>+ Classe</button>
    </div>

    <div class="mt-4">
      <AvailabilityMatrix
        title="Disponibilita oraria dell'aula"
        value={editing.unavailability}
        onChange={onMatrixChange}/>
    </div>

    <div class="mt-4">
      <LogicalUnavailabilitiesPanel entityType="classrooms" entityId={editing.id ?? null}/>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary" on:click={save}>Salva</button>
    </div>
  {/if}
</Modal>
