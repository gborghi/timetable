<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash, refreshDataset } from '$lib/stores.js';
  import { DAY_NAMES_EN, TEACHER_DEFAULTS } from '$lib/constants.js';
  import { teachers, subjects as subjectsSvc, classrooms as classroomsSvc } from '$lib/services';
  import Modal from '$lib/components/Modal.svelte';
  import AvailabilityMatrix from '$lib/components/AvailabilityMatrix.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import LogicalUnavailabilitiesPanel from '$lib/components/LogicalUnavailabilitiesPanel.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import BulkApplyModal from '$lib/components/BulkApplyModal.svelte';
  import ClassroomGrid from '$lib/components/ClassroomGrid.svelte';
  import { cloneRow } from '$lib/utils.js';

  let editing = null;
  let allSubjects = [];
  let allClassrooms = [];
  let listRef = null;
  let selectedIds = [];
  let showBulk = false;

  function onClassroomPrefsChange(newPrefs) {
    editing = { ...editing, classroom_prefs: newPrefs };
  }

  onMount(async () => {
    try {
      const subs = await subjectsSvc.list();
      allSubjects = subs.map((s) => s.name).sort();
    } catch { /* */ }
    try {
      allClassrooms = await classroomsSvc.list();
    } catch { /* */ }
  });

  function newTeacher() {
    editing = {
      _new: true,
      name: '', last_name: '', first_name: '', nickname: '',
      matricola: '', group: '',
      max_hours: TEACHER_DEFAULTS.max_hours,
      completion_hours: TEACHER_DEFAULTS.completion_hours,
      exemption_hours: TEACHER_DEFAULTS.exemption_hours,
      free_day: TEACHER_DEFAULTS.free_day,
      max_consecutive: TEACHER_DEFAULTS.max_consecutive,
      notes: '',
      pref_no_buchi_weight: TEACHER_DEFAULTS.pref_no_buchi_weight,
      pref_no_five_weight: TEACHER_DEFAULTS.pref_no_five_weight,
      pref_no_one_weight: TEACHER_DEFAULTS.pref_no_one_weight,
      preferred_days_csv: '',
      subjects: [], unavailability: [],
      mandatory_free_days: [], compatible_classes: [],
      classroom_prefs: []
    };
  }

  function edit(row) {
    editing = cloneRow(row);
    if (!Array.isArray(editing.unavailability)) editing.unavailability = [];
    if (!editing.last_name && !editing.first_name && editing.name) {
      // back-fill split fields from the legacy 'name' column
      const parts = editing.name.trim().split(/\s+/);
      if (parts.length >= 2) {
        editing.last_name = parts[parts.length - 1];
        editing.first_name = parts.slice(0, -1).join(' ');
      } else {
        editing.last_name = editing.name;
        editing.first_name = '';
      }
    }
  }

  // Auto-build the canonical 'name' = '<last_name> <first_name>' when the user
  // edits either field, unless they have already overridden it manually.
  function syncName() {
    const ln = (editing.last_name || '').trim();
    const fn = (editing.first_name || '').trim();
    const composed = ln && fn ? `${ln} ${fn}` : (ln || fn);
    if (composed) editing.name = composed;
    if (!editing.nickname) editing.nickname = composed;
  }

  // Map free_day name <-> day number (1..6)
  const DAY_NAME_TO_INT = {
    Monday: 1, Tuesday: 2, Wednesday: 3,
    Thursday: 4, Friday: 5, Saturday: 6
  };
  const INT_TO_DAY_NAME = ['', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const HOURS_FULL = [8, 9, 10, 11, 12, 13];

  function hardCellsForDay(d) {
    return HOURS_FULL.map((h) => ({
      day: d, hour: h, state: 'hard', soft_penalty: 0,
      reason: 'giorno libero'
    }));
  }

  // When the user picks a different free_day from the select, rewrite the
  // matrix: drop the old day's HARD-auto cells, add the new day's HARD cells.
  function onFreeDaySelect(ev) {
    const newName = ev.target.value;
    const newD = DAY_NAME_TO_INT[newName] || null;
    const oldD = DAY_NAME_TO_INT[editing.free_day] || null;
    if (newD === oldD) return;
    let cells = (editing.unavailability || []).filter(
      (c) => oldD === null || c.day !== oldD
    );
    if (newD) cells = [...cells, ...hardCellsForDay(newD)];
    editing = { ...editing, free_day: newName, unavailability: cells };
  }

  // When the user mutates the matrix manually, derive free_day:
  //  - if all 6 hours of some day are HARD red -> set free_day to that day
  //  - if the previously-set free_day no longer has 6 HARD cells -> clear it
  function syncFreeDayFromMatrix() {
    if (!editing) return;
    const cells = editing.unavailability || [];
    const isHardCount = {};
    for (const c of cells) {
      if (c.state === 'hard') {
        isHardCount[c.day] = (isHardCount[c.day] || 0) + 1;
      }
    }
    // Find a day that is fully hard
    const fullyHard = Object.entries(isHardCount)
      .filter(([_, n]) => n >= 6)
      .map(([d, _]) => Number(d));
    if (fullyHard.length === 1) {
      editing = { ...editing, free_day: INT_TO_DAY_NAME[fullyHard[0]] };
    } else if (fullyHard.length === 0) {
      const cur = DAY_NAME_TO_INT[editing.free_day];
      if (cur && (isHardCount[cur] || 0) < 6) {
        editing = { ...editing, free_day: '' };
      }
    }
    // If multiple full-hard days, leave free_day untouched (ambiguous).
  }

  let saving = false;
  async function save() {
    const payload = { ...editing };
    delete payload._new;
    delete payload.id;
    delete payload.scheduled_hours;
    delete payload.n_classes;
    delete payload.soft_penalty_total;
    saving = true;
    try {
      if (editing._new) await teachers.create(payload);
      else await teachers.update(editing.id, payload);
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
    // Snapshot the row before destroying it so UNDO can rebuild it.
    const snapshot = cloneRow(row);
    delete snapshot.id;
    delete snapshot.scheduled_hours;
    delete snapshot.n_classes;
    delete snapshot.soft_penalty_total;
    try {
      await teachers.remove(row.id);
      await listRef.reload();
      await refreshDataset();
      flash('Docente eliminato', 'success', {
        ms: 8000,
        action: {
          label: 'Annulla',
          fn: async () => {
            try {
              await teachers.create(snapshot);
              await listRef.reload();
              await refreshDataset();
              flash('Eliminazione annullata', 'success');
            } catch (e) {
              flash('Annullamento fallito: ' + e.message, 'error');
            }
          }
        }
      });
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  function onMatrixChange(newCells) {
    // reassign `editing` so Svelte 4 sees the change and re-renders.
    editing = { ...editing, unavailability: newCells };
    syncFreeDayFromMatrix();
  }

  const columns = [
    { key: 'last_name', label: 'Cognome' },
    { key: 'first_name', label: 'Nome' },
    { key: 'nickname', label: 'Nickname' },
    { key: 'group', label: 'Cl. concorso' },
    { key: 'subjects', label: 'Materie', sortable: false,
      render: (r) => (r.subjects || []).join(', ') },
    { key: 'max_hours', label: 'Max ore' },
    { key: 'free_day', label: 'Giorno libero' },
    { key: 'n_classes', label: 'N. classi' },
    { key: 'scheduled_hours', label: 'Ore-cattedra' },
    { key: 'soft_penalty_total', label: 'Soft tot.' }
  ];
  const help = {
    fields: ['name', 'cognome_nome', 'matricola', 'group', 'classe_di_concorso',
             'max_hours', 'max_ore', 'free_day', 'giorno_libero', 'subjects',
             'materia', 'n_classes', 'scheduled_hours', 'ore_cattedra',
             'soft_penalty_total', 'n_unavail'],
    examples: [
      'group = A026',
      'classe_di_concorso in [A026, A027]',
      'max_ore >= 18 AND group = A026',
      'cognome_nome startswith B',
      'free_day = Wednesday',
      'unavailable_on(saturday, 11)',
      'unavailable_on(martedi)',
      'soft_penalty_total > 50'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Docenti</h1>
    <button class="btn-primary ml-auto" on:click={newTeacher}>+ Nuovo docente</button>
    <ImportButton entity="teachers" onDone={() => listRef?.reload()}/>
    <button class="btn !text-xs" on:click={() => (showBulk = true)}
            disabled={selectedIds.length === 0}
            title="Applica un vincolo a tutti i docenti selezionati">
      Vincolo collettivo ({selectedIds.length})
    </button>
  </div>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/teachers"
    {columns}
    {help}
    rowKey={(r) => r.id}
    selectable={true}
    bind:selectedIds
    let:row let:columns>
    <td><strong>{row.last_name ?? row.name}</strong>
      {#if row.matricola}<span class="text-xs text-ink-500"> ({row.matricola})</span>{/if}
    </td>
    <td>{row.first_name ?? ''}</td>
    <td class="text-xs">{row.nickname ?? ''}</td>
    <td>{row.group ?? ''}</td>
    <td class="text-xs">{(row.subjects || []).join(', ')}</td>
    <td class="text-center">{row.max_hours}</td>
    <td>{row.free_day ?? ''}</td>
    <td class="text-center">{row.n_classes}</td>
    <td class="text-center">{row.scheduled_hours}</td>
    <td class="text-center text-xs">{row.soft_penalty_total}</td>
    <td class="whitespace-nowrap">
      <button class="btn !text-xs !px-2 !py-1" on:click={() => edit(row)}>Modifica</button>
      <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(row)}>Elimina</button>
    </td>
  </SortableQueryableList>
</div>

<BulkApplyModal entity="teachers" bind:open={showBulk}
                {selectedIds}
                onDone={() => { selectedIds = []; listRef?.reload(); }}/>

<Modal open={!!editing} title={editing?._new ? 'Nuovo docente' : 'Modifica docente'} onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field">
        <label>Cognome</label>
        <input bind:value={editing.last_name} on:input={syncName}/>
      </div>
      <div class="field">
        <label>Nome</label>
        <input bind:value={editing.first_name} on:input={syncName}/>
      </div>
      <div class="field col-span-2">
        <label>Nickname (mostrato nell'orario)
          <span class="text-xs text-ink-400">- default: "Cognome Nome"</span>
        </label>
        <input bind:value={editing.nickname}
               placeholder={(editing.last_name ?? '') + ' ' + (editing.first_name ?? '')}/>
      </div>
      <div class="field"><label>Matricola</label><input bind:value={editing.matricola}/></div>
      <div class="field"><label>Classe di concorso</label><input bind:value={editing.group}/></div>
      <div class="field"><label>Max ore-cattedra</label><input type="number" bind:value={editing.max_hours}/></div>
      <div class="field"><label>Ore di completamento</label><input type="number" bind:value={editing.completion_hours}/></div>
      <div class="field"><label>Ore di esonero</label><input type="number" bind:value={editing.exemption_hours}/></div>
      <div class="field">
        <label>Giorno libero (alias di "riga rossa nella matrice")</label>
        <select value={editing.free_day || ''} on:change={onFreeDaySelect}>
          <option value="">(nessuno)</option>
          {#each DAY_NAMES_EN as d}<option value={d}>{d}</option>{/each}
        </select>
      </div>
      <div class="field"><label>Max ore consecutive</label><input type="number" bind:value={editing.max_consecutive}/></div>
      <div class="field col-span-2">
        <label>Materie insegnate</label>
        <select multiple class="h-32" bind:value={editing.subjects}>
          {#each allSubjects as s}<option value={s}>{s}</option>{/each}
        </select>
      </div>
    </div>

    <div class="mt-4">
      <AvailabilityMatrix
        title="Disponibilita oraria del docente"
        value={editing.unavailability}
        onChange={onMatrixChange}/>
      {#if editing.free_day}
        <p class="text-xs text-ink-500 mt-1">
          Le 6 ore del giorno libero ({editing.free_day}) sono pre-impostate
          a HARD (rosso) automaticamente.
        </p>
      {/if}
    </div>

    <div class="mt-4 grid grid-cols-3 gap-3">
      <div class="field"><label>Peso "no buchi"</label><input type="number" bind:value={editing.pref_no_buchi_weight}/></div>
      <div class="field"><label>Peso "no 5 ore"</label><input type="number" bind:value={editing.pref_no_five_weight}/></div>
      <div class="field"><label>Peso "no 1 ora isolata"</label><input type="number" bind:value={editing.pref_no_one_weight}/></div>
    </div>

    <div class="mt-4">
      <ClassroomGrid
        classrooms={allClassrooms}
        value={editing.classroom_prefs ?? []}
        onChange={onClassroomPrefsChange}
        title="Aule per questo docente"/>
    </div>

    <div class="mt-4">
      <LogicalUnavailabilitiesPanel entityType="teachers" entityId={editing.id ?? null}/>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary focus-ring" on:click={save} disabled={saving}>
        {saving ? 'Salvataggio...' : 'Salva'}
      </button>
    </div>
  {/if}
</Modal>
