<script>
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import { DAY_NAMES_EN, DAY_NAMES_EN_TO_IT, TEACHER_DEFAULTS } from '$lib/constants';
  import { teachers } from '$lib/services';
  import {
    subjectsQuery, classroomsQuery, classesQuery, curriculaQuery
  } from '$lib/queries';
  import Modal from '$lib/components/Modal.svelte';
  import WeeklyCalendarView from '$lib/components/WeeklyCalendarView.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import LogicalUnavailabilitiesPanel from '$lib/components/LogicalUnavailabilitiesPanel.svelte';
  import GeneralDSLPanel from '$lib/components/GeneralDSLPanel.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import BulkApplyModal from '$lib/components/BulkApplyModal.svelte';
  import ClassroomGrid from '$lib/components/ClassroomGrid.svelte';
  import EntityPreferenceGrid from '$lib/components/EntityPreferenceGrid.svelte';
  import { cloneRow } from '$lib/utils';

  let editing = null;
  let listRef = null;
  let selectedIds = [];
  let showBulk = false;
  // Mirror the list's currently-rendered rows so bulk-delete can
  // snapshot them (for UNDO) without poking at SortableQueryableList
  // internals. Updated via the onRowsChange callback below.
  let latestRows = [];

  // Lookup data via TanStack Query: cached, deduplicated across pages,
  // auto-invalidated by the global mutation counter (see
  // $lib/queries/client.ts).
  const subjectsQ = subjectsQuery.useList();
  const classroomsQ = classroomsQuery.useList();
  const classesQ = classesQuery.useList();
  const curriculaQ = curriculaQuery.useList();
  $: allSubjects = ($subjectsQ.data ?? []).map((s) => s.name).sort();
  $: allClassrooms = $classroomsQ.data ?? [];
  // For the Phase-A preference grids:
  $: classItems = ($classesQ.data ?? [])
      .map((c) => ({ key: c.name, label: c.name,
                     hint: c.curriculum ?? '' }))
      .sort((a, b) => a.label.localeCompare(b.label));
  $: curriculumItems = ($curriculaQ.data ?? [])
      .map((c) => ({ key: c.code, label: c.code,
                     hint: c.name ?? '' }))
      .sort((a, b) => a.label.localeCompare(b.label));

  // Phase-A preferences live alongside the modal's editing record but
  // are saved via dedicated endpoints AFTER the main teacher PUT
  // succeeds (see save()).
  let editingClassPrefs = [];   // [{key, state, soft_penalty}]
  let editingCurrPrefs = [];
  // 3-priority free-day preferences; mirrored as a 3-slot array
  // (priority 1..3 -> index 0..2; day=0 means "nessuno").
  let editingFreeDayPriorities = [0, 0, 0];

  async function loadPhaseAPrefs(teacher_id) {
    if (!teacher_id) {
      editingClassPrefs = [];
      editingCurrPrefs = [];
      editingFreeDayPriorities = [0, 0, 0];
      return;
    }
    try {
      const cps = await api.get(`/api/teachers/${teacher_id}/class-preferences`);
      editingClassPrefs = (cps || []).map((p) => ({
        key: p.class_name, state: p.state, soft_penalty: p.soft_penalty
      }));
    } catch { editingClassPrefs = []; }
    try {
      const cups = await api.get(`/api/teachers/${teacher_id}/curriculum-preferences`);
      editingCurrPrefs = (cups || []).map((p) => ({
        key: p.curriculum_code, state: p.state, soft_penalty: p.soft_penalty
      }));
    } catch { editingCurrPrefs = []; }
    try {
      const fdp = await api.get(
        `/api/teachers/${teacher_id}/free-day-preferences`);
      const slots = [0, 0, 0];
      for (const r of (fdp || [])) {
        const pr = Number(r.priority);
        if (pr >= 1 && pr <= 3) slots[pr - 1] = Number(r.day);
      }
      editingFreeDayPriorities = slots;
    } catch { editingFreeDayPriorities = [0, 0, 0]; }
  }

  async function savePhaseAPrefs(teacher_id) {
    if (!teacher_id) return;
    try {
      await api.put(`/api/teachers/${teacher_id}/class-preferences`,
        editingClassPrefs.map((p) => ({
          class_name: p.key, state: p.state, soft_penalty: p.soft_penalty
        }))
      );
      await api.put(`/api/teachers/${teacher_id}/curriculum-preferences`,
        editingCurrPrefs.map((p) => ({
          curriculum_code: p.key, state: p.state, soft_penalty: p.soft_penalty
        }))
      );
      const prefs = [];
      for (let i = 0; i < 3; i++) {
        const d = Number(editingFreeDayPriorities[i] || 0);
        if (d >= 1 && d <= 6) prefs.push({ day: d, priority: i + 1 });
      }
      await api.patch(
        `/api/teachers/${teacher_id}/free-day-preferences`,
        { preferences: prefs });
    } catch (e) {
      flash('Errore salvando preferenze Phase A: ' + e.message, 'error');
    }
  }

  function onClassroomPrefsChange(newPrefs) {
    editing = { ...editing, classroom_prefs: newPrefs };
  }

  function newTeacher() {
    editing = {
      _new: true,
      name: '', last_name: '', first_name: '', nickname: '',
      matricola: '', group: '',
      max_hours: TEACHER_DEFAULTS.max_hours,
      completion_hours: TEACHER_DEFAULTS.completion_hours,
      exemption_hours: TEACHER_DEFAULTS.exemption_hours,
      graduatoria_score: null,
      free_day: TEACHER_DEFAULTS.free_day,
      max_consecutive: TEACHER_DEFAULTS.max_consecutive,
      notes: '',
      pref_no_buchi_weight: TEACHER_DEFAULTS.pref_no_buchi_weight,
      pref_no_five_weight: TEACHER_DEFAULTS.pref_no_five_weight,
      pref_no_one_weight: TEACHER_DEFAULTS.pref_no_one_weight,
      preferred_days_csv: '',
      preferred_free_days: [],
      min_free_days: 1,
      subjects: [], unavailability: [],
      mandatory_free_days: [], compatible_classes: [],
      classroom_prefs: []
    };
  }

  function edit(row) {
    editing = cloneRow(row);
    if (!Array.isArray(editing.unavailability)) editing.unavailability = [];
    // Load Phase-A preferences asynchronously; the modal opens
    // immediately, prefs render once the fetch resolves.
    loadPhaseAPrefs(row.id);
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
      let savedTeacher;
      if (editing._new) savedTeacher = await teachers.create(payload);
      else savedTeacher = await teachers.update(editing.id, payload);
      // Phase-A class/curriculum preferences are saved via dedicated
      // endpoints AFTER the main teacher row exists (id needed).
      await savePhaseAPrefs(savedTeacher?.id ?? editing.id);
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

  // Strip server-computed fields from a snapshot so it can round-trip
  // through teachers.create() without the backend rejecting it.
  function _scrubTeacherSnapshot(snap) {
    delete snap.id;
    delete snap.scheduled_hours;
    delete snap.n_classes;
    delete snap.soft_penalty_total;
    return snap;
  }

  async function del(row) {
    if (!confirm('Eliminare ' + row.name + '?')) return;
    // Snapshot the row before destroying it so UNDO can rebuild it.
    const snapshot = _scrubTeacherSnapshot(cloneRow(row));
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

  // Bulk-delete: same semantics as N single deletes (loop of DELETE
  // /api/teachers/{id}), with one batch confirm and one toast UNDO that
  // recreates them all. We don't have a backend bulk-delete endpoint and
  // adding one would duplicate the cascade behaviour the per-row
  // endpoint already provides.
  let bulkDeleting = false;
  async function bulkDel() {
    if (bulkDeleting) return;
    if (selectedIds.length === 0) return;
    // Resolve selected rows from the list's current page so we can
    // snapshot them before deletion (need full payload for UNDO).
    const idSet = new Set(selectedIds.map((x) => Number(x)));
    const rows = latestRows.filter((r) => idSet.has(Number(r.id)));
    if (rows.length === 0) {
      flash('Selezione non trovata nella vista corrente. Resetta i filtri e riprova.',
            'error');
      return;
    }
    if (rows.length !== selectedIds.length) {
      // Selection includes ids that aren't on the current page (e.g.
      // user paginated). Be explicit so the user is not surprised.
      if (!confirm(`Eliminare ${rows.length} docenti? `
          + `(${selectedIds.length - rows.length} non sono nella `
          + `pagina corrente e verranno ignorati.)`)) return;
    } else {
      if (!confirm(`Eliminare ${rows.length} docenti? `
          + `L'azione cancella anche le cattedre collegate.`)) return;
    }
    bulkDeleting = true;
    const snapshots = rows.map((r) => _scrubTeacherSnapshot(cloneRow(r)));
    let okCount = 0;
    const errors = [];
    try {
      for (const r of rows) {
        try {
          await teachers.remove(r.id);
          okCount++;
        } catch (e) {
          errors.push(`${r.name}: ${e.message ?? e}`);
        }
      }
      selectedIds = [];
      await listRef.reload();
      await refreshDataset();
      const tone = errors.length ? 'warning' : 'success';
      flash(`${okCount}/${rows.length} docenti eliminati`
            + (errors.length ? ` (${errors.length} errori)` : ''),
            tone, {
        ms: 10000,
        action: {
          label: 'Annulla',
          fn: async () => {
            let restored = 0;
            for (const snap of snapshots) {
              try {
                await teachers.create(snap);
                restored++;
              } catch (e) { console.warn('UNDO create failed', e); }
            }
            await listRef.reload();
            await refreshDataset();
            flash(`Ripristinati ${restored}/${snapshots.length} docenti`,
                  restored === snapshots.length ? 'success' : 'warning');
          }
        }
      });
    } finally {
      bulkDeleting = false;
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

<div class="space-y-4" data-testid="teachers-page">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Docenti</h1>
    <button class="btn-primary ml-auto" on:click={newTeacher}
            data-testid="add-teacher-btn">+ Nuovo docente</button>
    <ImportButton entity="teachers" onDone={() => listRef?.reload()}/>
    <button class="btn !text-xs" on:click={() => (showBulk = true)}
            disabled={selectedIds.length === 0}
            title="Applica un vincolo a tutti i docenti selezionati">
      Vincolo collettivo ({selectedIds.length})
    </button>
    <button class="btn-danger !text-xs" on:click={bulkDel}
            disabled={selectedIds.length === 0 || bulkDeleting}
            title="Elimina tutti i docenti selezionati (con UNDO)">
      {bulkDeleting ? 'Eliminazione...' : `Elimina selezionati (${selectedIds.length})`}
    </button>
  </div>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/teachers"
    entity="teachers"
    {columns}
    {help}
    rowKey={(r) => r.id}
    selectable={true}
    bind:selectedIds
    onRowsChange={(rs) => (latestRows = rs)}
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
      <button class="btn !text-xs !px-2 !py-1"
              data-testid="teacher-edit-btn"
              data-teacher-id={row.id}
              on:click={() => edit(row)}>Modifica</button>
      <button class="btn-danger !text-xs !px-2 !py-1"
              data-testid="teacher-delete-btn"
              data-teacher-id={row.id}
              on:click={() => del(row)}>Elimina</button>
    </td>
  </SortableQueryableList>
</div>

<BulkApplyModal entity="teachers" bind:open={showBulk}
                {selectedIds}
                onDone={() => { selectedIds = []; listRef?.reload(); }}/>

<Modal open={!!editing} title={editing?._new ? 'Nuovo docente' : 'Modifica docente'} onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3" data-testid="teacher-form">
      <div class="field">
        <label>Cognome</label>
        <input bind:value={editing.last_name} on:input={syncName}
               data-testid="teacher-last-name-input"/>
      </div>
      <div class="field">
        <label>Nome</label>
        <input bind:value={editing.first_name} on:input={syncName}
               data-testid="teacher-first-name-input"/>
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
      <div class="field"><label>Max ore-cattedra</label><input type="number" bind:value={editing.max_hours} data-testid="teacher-max-hours-input"/></div>
      <div class="field"><label>Ore di completamento</label><input type="number" bind:value={editing.completion_hours}/></div>
      <div class="field"><label>Ore di esonero</label><input type="number" bind:value={editing.exemption_hours}/></div>
      <div class="field">
        <label title="Punteggio in graduatoria provinciale (0-300). Usato dal preset 'Anzianita' di Phase A per assegnare i docenti piu' anziani agli indirizzi pesanti.">
          Punteggio graduatoria
          <span class="text-xs text-ink-400">- opzionale, 0-300</span>
        </label>
        <input type="number" min="0" max="300" step="0.5"
               bind:value={editing.graduatoria_score}
               placeholder="(non impostato)"/>
      </div>
      <div class="field">
        <label>Giorno libero (alias di "riga rossa nella matrice")</label>
        <select value={editing.free_day || ''} on:change={onFreeDaySelect}>
          <option value="">(nessuno)</option>
          {#each DAY_NAMES_EN as d}<option value={d}>{DAY_NAMES_EN_TO_IT[d] || d}</option>{/each}
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
      <WeeklyCalendarView
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

    <!-- Giorni liberi: 3 preferenze ordinate (HARD/SOFT) + count totale HARD -->
    <div class="mt-4 card !shadow-none p-3 bg-ink-50/40 space-y-3">
      <div class="text-sm font-semibold">Giorni liberi (avanzato)</div>
      <p class="text-xs text-ink-500">
        Tre preferenze ordinate di giorno libero. Se HARD, le 6 ore
        del giorno vengono bloccate automaticamente nella matrice di
        disponibilita' (rosso). Se SOFT, il modello paga la penalty
        per ogni ora occupata in quel giorno. La 1a preferenza e'
        quella prioritaria; 2a/3a sono fallback.
      </p>
      {#each [0, 1, 2] as i}
        {@const cur = (editing.preferred_free_days ?? [])[i]
                        ?? { day: 0, is_hard: true, soft_penalty: 100 }}
        <div class="grid grid-cols-12 gap-2 items-end">
          <div class="field col-span-3">
            <label>{['Prima', 'Seconda', 'Terza'][i]} preferenza</label>
            <select value={cur.day || 0} on:change={(e) => {
              const list = [...(editing.preferred_free_days ?? [])];
              while (list.length <= i) list.push({ day: 0, is_hard: true, soft_penalty: 100 });
              list[i] = { ...list[i], day: Number(e.target.value) };
              editing = { ...editing, preferred_free_days: list.filter((x) => x.day) };
            }}>
              <option value={0}>(nessuno)</option>
              <option value={1}>Lunedi</option>
              <option value={2}>Martedi</option>
              <option value={3}>Mercoledi</option>
              <option value={4}>Giovedi</option>
              <option value={5}>Venerdi</option>
              <option value={6}>Sabato</option>
            </select>
          </div>
          {#if cur.day}
            <div class="col-span-3 flex items-center gap-3 self-center">
              <label class="flex items-center gap-1 text-xs">
                <input type="radio" checked={cur.is_hard}
                       on:change={() => {
                         const list = [...(editing.preferred_free_days ?? [])];
                         list[i] = { ...list[i], is_hard: true };
                         editing = { ...editing, preferred_free_days: list };
                       }}/>
                🟥 HARD
              </label>
              <label class="flex items-center gap-1 text-xs">
                <input type="radio" checked={!cur.is_hard}
                       on:change={() => {
                         const list = [...(editing.preferred_free_days ?? [])];
                         list[i] = { ...list[i], is_hard: false };
                         editing = { ...editing, preferred_free_days: list };
                       }}/>
                🟨 SOFT
              </label>
            </div>
            {#if !cur.is_hard}
              <div class="field col-span-2">
                <label>Penalty</label>
                <input type="number" value={cur.soft_penalty ?? 100}
                       on:input={(e) => {
                         const list = [...(editing.preferred_free_days ?? [])];
                         list[i] = { ...list[i], soft_penalty: Number(e.target.value) };
                         editing = { ...editing, preferred_free_days: list };
                       }}/>
              </div>
            {/if}
          {/if}
        </div>
      {/each}
      {#if (editing.preferred_free_days ?? []).map((p) => p.day).filter((d, i, a) => d && a.indexOf(d) !== i).length > 0}
        <div class="text-xs text-red-600">
          ⚠️ I tre giorni preferiti devono essere distinti.
        </div>
      {/if}
      <div class="field max-w-xs">
        <label>Min giorni liberi/sett. (HARD)
          <span title="Numero MINIMO di giornate libere a settimana. Default 1 (CCNL). 2-3 per docenti part-time. 0 disabilita il vincolo. Il pragma e' 'teacher_at_least_n_free_days' applicato uniformemente in Phase A, Phase B e tutti i bypass.">
            &#x2139;
          </span>
        </label>
        <input type="number" min="0" max="6"
               data-test="min-free-days"
               value={editing.min_free_days ?? 1}
               on:input={(e) => editing = { ...editing,
                 min_free_days: Math.max(0, Math.min(6, Number(e.target.value) || 0)) }}/>
        <div class="text-xs text-ink-500">
          Default 1 (CCNL italiano). 2-3 per part-time o accordi
          individuali. 0 disabilita il vincolo. Massimo 6 (teorico).
        </div>
      </div>
    </div>

    <!-- Giorni liberi: 3 priorita' SOFT (peso 30/20/10) -->
    <div class="mt-4 card !shadow-none p-3 bg-ink-50/40 space-y-3"
         data-test="free-day-priorities">
      <div class="text-sm font-semibold">
        Giorni liberi (priorita' 1-3)
      </div>
      <p class="text-xs text-ink-500">
        Tre preferenze ordinate. La 1a scelta paga 30 di penalty se
        violata, la 2a paga 20, la 3a paga 10. Il vincolo HARD
        "almeno un giorno libero" e' applicato a tutti i docenti
        indipendentemente da queste preferenze.
      </p>
      <div class="grid grid-cols-3 gap-3">
        {#each [0, 1, 2] as i}
          <div class="field">
            <label>{['1a', '2a', '3a'][i]} scelta giorno libero</label>
            <select
              data-test={`free-day-priority-${i + 1}`}
              value={editingFreeDayPriorities[i] || 0}
              on:change={(e) => {
                const next = [...editingFreeDayPriorities];
                next[i] = Number(e.target.value);
                editingFreeDayPriorities = next;
              }}>
              <option value={0}>(nessuno)</option>
              <option value={1}>Lunedi</option>
              <option value={2}>Martedi</option>
              <option value={3}>Mercoledi</option>
              <option value={4}>Giovedi</option>
              <option value={5}>Venerdi</option>
              <option value={6}>Sabato</option>
            </select>
          </div>
        {/each}
      </div>
      {@const _fdpDays = editingFreeDayPriorities.filter((d) => d)}
      {#if new Set(_fdpDays).size !== _fdpDays.length}
        <div class="text-xs text-red-600"
             data-test="free-day-priority-error">
          ⚠️ I tre giorni delle priorita' devono essere distinti.
        </div>
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

    <div class="mt-4">
      <GeneralDSLPanel scope="teacher"
                       ownerId={editing.id ?? null}
                       scopeLabel={editing.name ? `Docente ${editing.name}` : ''}/>
    </div>

    <!-- Phase-A only preferences: class + curriculum (5-state) -->
    <div class="mt-4 space-y-3 border-t border-ink-200 pt-3">
      <div class="text-xs text-ink-500 italic">
        <strong class="text-ink-700">Preferenze per Phase A</strong>
        (assegnazione docente -&gt; classe). Queste preferenze
        influenzano SOLO l'assegnazione docenti↔classi, non l'orario
        settimanale (Phase B).
      </div>
      <EntityPreferenceGrid
        items={classItems}
        value={editingClassPrefs}
        onChange={(v) => (editingClassPrefs = v)}
        title="Classi (preferenze)"
        subtitle="HARD rosso = niente assegnazione su quella classe; ENFORCED = assegnamento obbligatorio."
        collapsedByDefault={true}/>
      <EntityPreferenceGrid
        items={curriculumItems}
        value={editingCurrPrefs}
        onChange={(v) => (editingCurrPrefs = v)}
        title="Indirizzi (preferenze)"
        subtitle="Vincoli a livello di indirizzo; HARD = niente classi di quell'indirizzo."
        collapsedByDefault={true}/>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}
              data-testid="teacher-cancel-btn">Annulla</button>
      <button class="btn-primary focus-ring" on:click={save} disabled={saving}
              data-testid="teacher-save-btn">
        {saving ? 'Salvataggio...' : 'Salva'}
      </button>
    </div>
  {/if}
</Modal>
