<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants';
  import ScheduleConflictModal from '$lib/components/schedule/ScheduleConflictModal.svelte';
  import AddEventModal from '$lib/components/schedule/AddEventModal.svelte';
  import AddLessonModal from '$lib/components/schedule/AddLessonModal.svelte';

  let summary = null;
  let listRef = null;
  let allRooms = [];
  let allTeachers = [];
  let allClasses = [];

  // Red panel: events without temporal assignment.
  let incomplete = null;     // { n_total, n_incomplete, items[] }
  let incompleteOpen = false;
  let incompleteBusy = false;

  // Add-event modal state
  let addEventOpen = false;

  // Schedule-an-unscheduled-placeholder modal state. Driven by the
  // "Modifica" button on placeholder rows in the grouped events view.
  let addLessonOpen = false;
  let addLessonPreset = {};

  // Grouped events view: one row per Lesson + placeholder per missing
  // hour. Two grouping dropdowns let the user split by any pair of
  // attributes.
  let eventRows = null;       // { items[], n_total, n_filtered, n_unscheduled }
  let eventRowsBusy = false;
  let groupBy1 = 'teacher_name';
  let groupBy2 = 'class_name';
  // Server-side query + sort (DSL, same syntax as docenti / aule /
  // classi). Sort uses the same multi-level pattern as
  // SortableQueryableList: double-click on a column label to add/remove
  // a level (max 4); click on the ▲/▼ indicator to flip direction;
  // "Reset sort" clears every level.
  let rowQuery = '';                  // current value in the input box
  let appliedQuery = '';              // last query actually sent
  // Start with NO sort levels (Cattedra-default order from the
  // backend). Double-clicking a column header adds the first level.
  let sortLevels = [];                // [{column, direction}, ...]
  const MAX_SORT_LEVELS = 3;          // per Giovanni's spec: max 3 levels
  let queryError = '';
  let showQueryHelp = false;

  // Build the sort string SYNCHRONOUSLY from the current sortLevels;
  // we deliberately DO NOT use a `$:` reactive variable here because
  // Svelte schedules reactive recomputations after the current tick,
  // which would race with `refreshEventRows()` called immediately
  // after a sortLevels reassignment.
  function buildSortString() {
    return sortLevels.map((l) => `${l.column},${l.direction}`).join(':');
  }

  // Collapsible groups: a row is shown only if both the level-1 and
  // level-2 group keys it belongs to are in `expandedG1` / `expandedG2`.
  // Expansion default = ALL collapsed; "Untoggle all" expands everything.
  let expandedG1 = new Set();
  let expandedG2 = new Set();

  // Column definitions (label + DSL key used by the backend
  // event_row_fields registry).
  const COLS = [
    { key: 'docente', label: 'Docente' },
    { key: 'classe',  label: 'Classe' },
    { key: 'materia', label: 'Materia' },
    { key: 'giorno',  label: 'Giorno' },
    { key: 'ora',     label: 'Ora' },
    { key: 'aula',    label: 'Aula' },
    { key: 'gruppo',  label: 'Gruppo' },
    { key: 'stato',   label: 'Stato' },
  ];

  // Multi-level sort: dblclick on label adds (or removes if already
  // present) the column. Single click on the small ▲/▼ next to it
  // flips direction. Three-or-more levels behave the same — we cap
  // at MAX_SORT_LEVELS so the URL stays readable.
  function onLabelDblClick(colKey) {
    const idx = sortLevels.findIndex((l) => l.column === colKey);
    if (idx >= 0) {
      sortLevels = sortLevels.filter((_, i) => i !== idx);
    } else if (sortLevels.length < MAX_SORT_LEVELS) {
      sortLevels = [...sortLevels, { column: colKey, direction: 'asc' }];
    } else {
      flash(`Massimo ${MAX_SORT_LEVELS} livelli di sort.`, 'error');
      return;
    }
    refreshEventRows();
  }
  function onIndicatorClick(colKey) {
    const idx = sortLevels.findIndex((l) => l.column === colKey);
    if (idx < 0) return;
    sortLevels = sortLevels.map((l, i) => i === idx
      ? { ...l, direction: l.direction === 'asc' ? 'desc' : 'asc' }
      : l);
    refreshEventRows();
  }
  function resetSort() {
    if (sortLevels.length === 0) return;
    sortLevels = [];
    refreshEventRows();
  }
  function resetQuery() {
    if (!rowQuery && !appliedQuery) return;
    rowQuery = '';
    appliedQuery = '';
    refreshEventRows();
  }
  function applyQuery() {
    appliedQuery = rowQuery;
    refreshEventRows();
  }

  function toggleAll() {
    expandedG1 = new Set();
    expandedG2 = new Set();
  }
  function untoggleAll() {
    expandedG1 = new Set(groupedBuckets.map((b) => b.key1));
    const all2 = new Set();
    for (const b of groupedBuckets)
      for (const sb of b.sub) all2.add(b.key1 + '|' + sb.key2);
    expandedG2 = all2;
  }
  function toggleG1(key) {
    if (expandedG1.has(key)) expandedG1.delete(key);
    else expandedG1.add(key);
    expandedG1 = expandedG1;
  }
  function toggleG2(key) {
    if (expandedG2.has(key)) expandedG2.delete(key);
    else expandedG2.add(key);
    expandedG2 = expandedG2;
  }
  // Group key options. The label is shown in the dropdown; the value
  // is the row attribute name.
  const GROUP_OPTIONS = [
    { value: 'none',           label: '— nessuno —' },
    { value: 'teacher_name',   label: 'Docente' },
    { value: 'class_name',     label: 'Classe' },
    { value: 'subject',        label: 'Materia' },
    { value: 'day_name',       label: 'Giorno' },
    { value: 'hour',           label: 'Ora' },
    { value: 'classroom_name', label: 'Aula' },
    { value: 'group_name',     label: 'Gruppo' },
    { value: 'is_scheduled',   label: 'Schedulato?' },
    { value: 'is_complete',    label: 'Completo?' },
  ];

  async function refreshEventRows() {
    eventRowsBusy = true;
    queryError = '';
    try {
      const params = new URLSearchParams();
      if (appliedQuery) params.set('q', appliedQuery);
      const sortStr = buildSortString();
      if (sortStr) params.set('sort', sortStr);
      const url = '/api/monitor/event-rows'
        + (params.toString() ? '?' + params.toString() : '');
      eventRows = await api.get(url);
    } catch (e) {
      // Preserve the previous eventRows so the user can still see the
      // existing data alongside the error -- otherwise the table
      // disappears and they think nothing happened.
      queryError = e?.message || String(e);
    } finally {
      eventRowsBusy = false;
    }
  }

  // Map a row's value for a group key into a display label + sort key.
  function groupValue(row, key) {
    if (key === 'none') return { label: '', sort: 0 };
    let raw = row[key];
    if (key === 'classroom_name' || key === 'group_name'
        || key === 'day_name') {
      if (!raw) raw = '(nessuno)';
    } else if (key === 'is_scheduled') {
      raw = raw ? 'schedulato' : 'non schedulato';
    } else if (key === 'is_complete') {
      raw = raw ? 'completo' : 'incompleto';
    } else if (key === 'hour') {
      raw = raw == null ? '(non schedulato)' : (raw + ':00');
    }
    return { label: String(raw ?? ''), sort: String(raw ?? '') };
  }

  // Two-level grouping: returns Array<{ key1, rows1, sub: Array<{key2, rows2}> }>.
  // GROUPS themselves are sorted alphabetically by their label so the
  // nest order is predictable. Leaf rows INSIDE each bucket preserve
  // the server's multi-level sort (the backend sorts the flat list
  // before we group; Map preserves insertion order).
  function groupRows(rows, k1, k2) {
    const m1 = new Map();
    for (const r of rows) {
      const v1 = groupValue(r, k1).label;
      if (!m1.has(v1)) m1.set(v1, []);
      m1.get(v1).push(r);
    }
    const buckets = Array.from(m1.entries())
      .sort((a, b) => a[0].localeCompare(b[0], 'it'))
      .map(([label1, rows1]) => {
        const m2 = new Map();
        for (const r of rows1) {
          const v2 = groupValue(r, k2).label;
          if (!m2.has(v2)) m2.set(v2, []);
          m2.get(v2).push(r);
        }
        const sub = Array.from(m2.entries())
          .sort((a, b) => a[0].localeCompare(b[0], 'it'))
          .map(([label2, rows2]) => ({ key2: label2, rows2 }));
        return { key1: label1, rows1, sub };
      });
    return buckets;
  }

  $: groupedBuckets = eventRows
    ? groupRows(eventRows.items, groupBy1, groupBy2) : [];

  // Row "id" for keyed each-blocks: lesson_id when scheduled, otherwise
  // a synthetic key based on the assignment + index.
  function rowId(r, idx) {
    return r.lesson_id != null
      ? `lesson:${r.lesson_id}`
      : `placeholder:${r.assignment_id}:${idx}`;
  }

  // Per-row actions
  async function deleteEventRow(row) {
    if (row.is_scheduled && row.lesson_id != null) {
      if (!confirm(`Eliminare la lezione di ${row.subject} `
          + `(${row.class_name}, ${row.teacher_name}) di `
          + `${row.day_name} ${row.hour}:00? `
          + `La cattedra rimane ma diventa incompleta.`)) return;
      try {
        await api.del('/api/monitor/lesson/' + row.lesson_id);
        flash('Lezione eliminata.', 'success');
        await refreshAll();
      } catch (e) {
        flash('Errore: ' + e.message, 'error');
      }
    } else {
      if (!confirm(`Eliminare l'intera cattedra di ${row.subject} `
          + `(${row.class_name}, ${row.teacher_name})? `
          + `Saranno eliminate ANCHE tutte le sue lezioni gia' schedulate.`)) return;
      try {
        await api.del('/api/monitor/event/' + row.assignment_id);
        flash('Cattedra e lezioni eliminate.', 'success');
        await refreshAll();
      } catch (e) {
        flash('Errore: ' + e.message, 'error');
      }
    }
  }

  async function modifyEventRow(row) {
    if (row.is_scheduled && row.lesson_id != null) {
      // Re-use the existing slot picker for moving a Lesson.
      await openSlotPicker({
        assignment_id: row.assignment_id,
        teacher_name:  row.teacher_name,
        teacher_display: row.teacher_display,
        class_name:    row.class_name,
        subject:       row.subject,
      }, {
        lesson_id: row.lesson_id,
        day: row.day,
        hour: row.hour,
        classroom_name: row.classroom_name || null,
      });
    } else {
      // Schedule the placeholder via AddLessonModal in mode='slot'.
      addLessonPreset = {
        class_name: row.class_name,
        teacher_name: row.teacher_name,
      };
      addLessonOpen = true;
    }
  }

  async function refreshAll() {
    await refreshSummary();
    await refreshIncomplete();
    await refreshEventRows();
  }

  // From inside the slot-picker modal, drop the Lesson's day/hour
  // binding altogether: the cattedra stays but becomes unscheduled
  // (gets a placeholder row in the grouped view + the red panel).
  // Implementation: delete the Lesson; the parent Assignment is
  // preserved.
  async function disassociateFromSlot() {
    if (!slotPicker) return;
    const lid = slotPicker.lesson?.lesson_id;
    if (lid == null) {
      flash('Lezione senza id; impossibile disassociare.', 'error');
      return;
    }
    if (!confirm('Disassociare questa lezione da '
        + slotPicker.lesson.day + '/' + slotPicker.lesson.hour
        + '? La cattedra rimane ma l\'evento diventa non schedulato.')) {
      return;
    }
    try {
      await api.del('/api/monitor/lesson/' + lid);
      flash('Lezione disassociata: cattedra preservata.', 'success');
      slotPicker = null;
      await refreshAll();
      if (listRef) await listRef.reload();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  // For each event row we keep: expanded? + lessons array.
  let expanded = new Set();
  let lessonsByEvent = {};
  let busyEvent = null;

  // Conflict modal state
  let conflictDialog = null;
  // shape: { event_id, lesson_id, day, hour, classroom_name, details:{teacher_busy,...}, original }

  // Slot picker modal state. Shape:
  //   { event_id, eventRow, lesson, teacherGrid, classGrid, roomGrid }
  // teacherGrid/classGrid/roomGrid are filtered slices of the active
  // solution's by-teacher / by-class / by-room grids for THIS lesson's
  // owner. They drive the cell coloring.
  let slotPicker = null;
  let slotPickerLoading = false;

  onMount(async () => {
    try { summary = await api.get('/api/monitor/summary'); } catch { /* */ }
    try { allRooms = (await api.get('/api/classrooms')).map((r) => r.name).sort(); }
    catch { allRooms = []; }
    try {
      const t = await api.get('/api/teachers');
      // Keep the full {name, subjects} objects so AddEventModal can
      // filter the materia dropdown by the chosen docente's
      // abilitazioni.
      allTeachers = (t || []).map((x) => ({
        name: x.name,
        subjects: x.subjects ?? [],
      })).sort((a, b) => a.name.localeCompare(b.name));
    } catch { allTeachers = []; }
    try {
      const c = await api.get('/api/classes');
      allClasses = (c || []).map((x) => x.name).sort();
    } catch { allClasses = []; }
    await refreshIncomplete();
    await refreshEventRows();
  });

  async function refreshSummary() {
    try { summary = await api.get('/api/monitor/summary'); } catch { /* */ }
  }

  async function refreshIncomplete() {
    incompleteBusy = true;
    try {
      incomplete = await api.get('/api/monitor/incomplete-events');
    } catch (e) {
      incomplete = null;
    } finally {
      incompleteBusy = false;
    }
  }

  async function toggleRow(row) {
    const id = row.assignment_id;
    if (expanded.has(id)) {
      expanded.delete(id);
      expanded = expanded;
      return;
    }
    expanded.add(id);
    expanded = expanded;
    busyEvent = id;
    try {
      const d = await api.get('/api/monitor/event/' + id + '/lessons');
      lessonsByEvent[id] = d.lessons;
      lessonsByEvent = lessonsByEvent;
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally {
      busyEvent = null;
    }
  }

  async function reloadLessonsFor(eventId) {
    try {
      const d = await api.get('/api/monitor/event/' + eventId + '/lessons');
      lessonsByEvent[eventId] = d.lessons;
      lessonsByEvent = lessonsByEvent;
    } catch { /* */ }
  }

  async function openSlotPicker(eventRow, lesson) {
    slotPickerLoading = true;
    try {
      const [td, cd, rd] = await Promise.all([
        api.get('/api/schedule/by-teacher'),
        api.get('/api/schedule/by-class'),
        api.get('/api/schedule/by-room'),
      ]);
      slotPicker = {
        event_id: eventRow.assignment_id,
        eventRow,
        lesson,
        teacherGrid: td.grid?.[eventRow.teacher_name] ?? {},
        classGrid:   cd.grid?.[eventRow.class_name]   ?? {},
        roomGrid:    lesson.classroom_name
                       ? (rd.grid?.[lesson.classroom_name] ?? {})
                       : {},
      };
    } catch (e) {
      flash('Errore caricando disponibilita: ' + e.message, 'error');
    } finally {
      slotPickerLoading = false;
    }
  }

  function slotInfo(d, h) {
    if (!slotPicker) return null;
    const tCell = slotPicker.teacherGrid?.[d]?.[h] ?? null;
    const cCell = slotPicker.classGrid?.[d]?.[h]   ?? null;
    const rList = slotPicker.roomGrid?.[d]?.[h]    ?? [];
    const lid = slotPicker.lesson.lesson_id;
    const isCurrent = (d === slotPicker.lesson.day
                       && h === slotPicker.lesson.hour);
    // teacher cell is { lesson_id, class_name, subject, classroom }
    const teacherBusy = !!tCell && tCell.lesson_id !== lid;
    // class cell is { lesson_id, teachers[], subjects[], classroom }
    const classBusy = !!cCell && cCell.lesson_id !== lid;
    // room list is [{lesson_id, class_name, subject, teacher}]
    const roomBusy = rList.some((r) => r.lesson_id !== lid);
    let status = 'free';
    if (isCurrent) status = 'current';
    else if (teacherBusy || classBusy) status = 'hard';
    else if (roomBusy) status = 'room';
    return { tCell, cCell, rList, isCurrent, teacherBusy, classBusy,
             roomBusy, status };
  }

  function slotClass(info) {
    if (!info) return '';
    if (info.status === 'current') return 'bg-sky-200 border-sky-500 ring-2 ring-sky-400';
    if (info.status === 'hard')    return 'bg-red-200 border-red-400 cursor-pointer hover:bg-red-300';
    if (info.status === 'room')    return 'bg-amber-200 border-amber-400 cursor-pointer hover:bg-amber-300';
    return 'bg-emerald-50 border-emerald-300 hover:bg-emerald-200 cursor-pointer';
  }

  function slotTitle(info, d, h) {
    if (!info) return '';
    if (info.status === 'current') return `${DAY_NAMES_IT[d]} ${h}:00 (slot attuale)`;
    const bits = [];
    if (info.teacherBusy) bits.push('docente impegnato');
    if (info.classBusy)   bits.push('classe impegnata');
    if (info.roomBusy)    bits.push('aula occupata');
    if (bits.length === 0) return `${DAY_NAMES_IT[d]} ${h}:00 - libero`;
    return `${DAY_NAMES_IT[d]} ${h}:00 - ${bits.join(', ')}`;
  }

  async function pickSlot(d, h) {
    if (!slotPicker) return;
    const info = slotInfo(d, h);
    if (info?.isCurrent) {
      slotPicker = null;
      return;
    }
    const { event_id, lesson } = slotPicker;
    slotPicker = null;
    // Re-use the existing dry-run + conflict-modal flow.
    await tryMove(event_id, lesson, d, h, lesson.classroom_name);
  }

  async function applyMove(eventId, lesson, newDay, newHour, newRoom,
                          onConflict) {
    const payload = {
      day: Number(newDay),
      hour: Number(newHour),
      classroom_name: newRoom,
      on_conflict: onConflict,
    };
    return await api.put(
      '/api/monitor/event/' + eventId + '/lesson/' + lesson.lesson_id,
      payload);
  }

  async function tryMove(eventId, lesson, newDay, newHour, newRoom) {
    try {
      // First a dry-run to check conflicts
      const dry = await applyMove(eventId, lesson, newDay, newHour, newRoom,
                                  'dry_run');
      if (dry.no_change) return;
      if (dry.ok) {
        flash('Lezione spostata.', 'success');
        await reloadLessonsFor(eventId);
        await refreshSummary();
        await refreshIncomplete();
        await refreshEventRows();
        if (listRef) await listRef.reload();
        return;
      }
      if (dry.conflict) {
        conflictDialog = {
          event_id: eventId,
          lesson,
          day: newDay,
          hour: newHour,
          classroom_name: newRoom,
          details: dry.details,
        };
      }
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function resolveConflict(strategy) {
    // strategy is 'unbind' (svincola) or 'delete' (elimina)
    if (!conflictDialog) return;
    const { event_id, lesson, day, hour, classroom_name } = conflictDialog;
    try {
      const r = await applyMove(event_id, lesson, day, hour, classroom_name,
                                strategy);
      if (r.ok) {
        flash(strategy === 'unbind'
              ? 'Lezione spostata; conflitti svincolati.'
              : 'Lezione spostata; conflitti eliminati.',
              'success');
        conflictDialog = null;
        await reloadLessonsFor(event_id);
        await refreshSummary();
        await refreshIncomplete();
        await refreshEventRows();
        if (listRef) await listRef.reload();
      } else if (r.cancelled) {
        flash('Modifica annullata.', 'success');
        conflictDialog = null;
      }
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  function rowBg(row) {
    return row.is_complete ? '' : 'background-color: #fef9c3;';
  }

  const columns = [
    { key: 'docente', label: 'Docente' },
    { key: 'classe', label: 'Classe' },
    { key: 'materia', label: 'Materia' },
    { key: 'expected_hours', label: 'Ore attese' },
    { key: 'assigned_hours', label: 'Ore assegnate' },
    { key: 'missing_hours', label: 'Ore mancanti' },
    { key: 'missing_room', label: 'Aule mancanti' },
    { key: 'gruppo', label: 'Gruppo' },
    { key: 'stato', label: 'Stato' }
  ];
  const help = {
    fields: ['docente', 'teacher', 'classe', 'class_name', 'materia',
             'subject', 'expected_hours', 'ore_attese', 'assigned_hours',
             'ore_assegnate', 'missing_hours', 'ore_mancanti',
             'missing_room', 'aule_mancanti', 'missing_group', 'is_complete',
             'completo', 'group', 'gruppo', 'status', 'stato'],
    examples: [
      'completo = 0',
      'missing_hours > 0',
      'aule_mancanti > 0',
      'materia = Matematica',
      'classe startswith 1A',
      'docente contains Rossi'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Monitor</h1>
    {#if summary}
      <span class="text-sm text-ink-500">
        {summary.n_events} eventi totali
        - <span class="pill-amber">{summary.n_incomplete} incompleti</span>
        {#if summary.n_missing_hours}
          - <span class="pill-red">{summary.n_missing_hours} senza ore</span>
        {/if}
        {#if summary.n_missing_room}
          - <span class="pill-amber">{summary.n_missing_room} senza aula</span>
        {/if}
        {#if summary.n_missing_group}
          - <span class="pill">{summary.n_missing_group} senza gruppo</span>
        {/if}
      </span>
    {/if}
  </div>

  <p class="text-xs text-ink-500">
    Click su una riga per espanderla e vedere le singole lezioni
    (giorno/ora/aula). Da li puoi spostare la lezione: se la nuova
    posizione e' in conflitto con un'altra lezione/aula apparira' un
    modal con le opzioni di risoluzione.
  </p>

  <div class="flex items-center gap-2 flex-wrap">
    <button class="btn-primary !text-xs"
            on:click={() => (addEventOpen = true)}>
      + Nuovo evento
    </button>
    <button class="btn !text-xs"
            on:click={() => (incompleteOpen = !incompleteOpen)}
            disabled={!incomplete}
            title="Mostra/nascondi pannello eventi senza assegnazione temporale">
      {#if incomplete}
        {incompleteOpen ? 'Nascondi' : 'Mostra'} pannello rosso
        ({incomplete.n_incomplete})
      {:else}
        Pannello rosso (caricamento...)
      {/if}
    </button>
    <button class="btn !text-xs" on:click={refreshIncomplete}
            disabled={incompleteBusy}>refresh</button>
  </div>

  {#if incompleteOpen && incomplete}
    <div class="card p-4 border-2 border-red-300 bg-red-50">
      <h2 class="mb-2 text-red-900">
        Eventi senza assegnazione temporale
        ({incomplete.n_incomplete} su {incomplete.n_total})
      </h2>
      <p class="text-xs text-red-700 mb-2">
        Cattedre per cui non tutte le ore attese sono state schedulate
        nella soluzione attiva. Per ognuna assegna le ore mancanti
        cliccando "+ nuovo" su uno slot libero in /schedule, oppure
        crea l'evento gia' fissato a giorno/ora con "+ Nuovo evento".
      </p>
      {#if incomplete.items.length === 0}
        <p class="text-sm text-red-600">Nessun evento incompleto: tutto a posto.</p>
      {:else}
        <table class="tbl text-xs">
          <thead>
            <tr>
              <th>Docente</th><th>Classe</th><th>Materia</th>
              <th class="text-center">Ore attese</th>
              <th class="text-center">Ore assegnate</th>
              <th class="text-center">Ore mancanti</th>
              <th>Stato</th>
            </tr>
          </thead>
          <tbody>
            {#each incomplete.items as it}
              <tr style="background-color:#fef2f2;">
                <td><strong>{it.teacher_display}</strong></td>
                <td>{it.class_name}</td>
                <td>{it.subject}</td>
                <td class="text-center">{it.expected_hours}</td>
                <td class="text-center">{it.assigned_hours}</td>
                <td class="text-center">
                  <span class="pill-red">{it.missing_hours}</span>
                </td>
                <td class="text-xs">{it.status}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}

  <!-- Grouped events view: lesson-granularity rows + placeholders for
       unscheduled hours. Two dropdowns let the user split the list by
       any pair of attributes; nested groups are collapsible (toggle
       all / untoggle all); the leaf level supports the same DSL
       query + click-to-sort headers as the docenti / aule / classi
       tabs. -->
  <!-- Grouping + collapse controls -->
  <div class="card p-3 flex items-center gap-3 flex-wrap">
    <span class="text-sm font-medium">Raggruppa per:</span>
    <select class="text-sm px-2 py-1 border border-ink-200 rounded"
            bind:value={groupBy1}>
      {#each GROUP_OPTIONS as o}<option value={o.value}>{o.label}</option>{/each}
    </select>
    <span class="text-sm">e poi per:</span>
    <select class="text-sm px-2 py-1 border border-ink-200 rounded"
            bind:value={groupBy2}>
      {#each GROUP_OPTIONS as o}<option value={o.value}>{o.label}</option>{/each}
    </select>
    <button class="btn !text-xs" on:click={toggleAll}
            title="Chiudi tutti i gruppi">Toggle all</button>
    <button class="btn !text-xs" on:click={untoggleAll}
            title="Apri tutti i gruppi">Untoggle all</button>
  </div>

  <!-- Query bar with Cerca / Reset query / Reset sort, like the
       docenti / aule / classi tabs. -->
  <div class="card p-3 flex flex-wrap gap-2 items-end">
    <div class="flex-1 min-w-64">
      <label class="text-xs text-ink-500">Query</label>
      <input class="w-full px-2 py-1.5 rounded-md border border-ink-200 font-mono text-sm"
             placeholder="es. docente contains Rossi, completo = 0, aula = LabFisica AND giorno = Lunedi"
             bind:value={rowQuery}
             on:keydown={(e) => { if (e.key === 'Enter') applyQuery(); }}/>
    </div>
    <button class="btn" on:click={applyQuery} disabled={eventRowsBusy}>
      {eventRowsBusy ? '...' : 'Cerca'}
    </button>
    <button class="btn !text-xs"
            on:click={() => (showQueryHelp = !showQueryHelp)}>?  guida</button>
    <span class="border-l border-ink-200 h-6 mx-1"></span>
    <button class="btn !text-xs" on:click={resetQuery}
            disabled={!rowQuery && !appliedQuery}
            title="Svuota la barra di ricerca">Reset query</button>
    <button class="btn !text-xs" on:click={resetSort}
            disabled={sortLevels.length === 0}
            title="Torna all'ordine originale">Reset sort</button>
    <span class="text-xs text-ink-500 ml-auto">
      {#if eventRowsBusy}
        aggiorno...
      {:else if eventRows}
        {eventRows.n_filtered ?? eventRows.n_total} / {eventRows.n_total}
        righe ({eventRows.n_unscheduled} non schedulate)
      {/if}
    </span>
  </div>

  {#if queryError}
    <div class="card p-2 text-xs text-red-700 bg-red-50 border-red-300">
      Errore query: {queryError}
    </div>
  {/if}

  {#if sortLevels.length > 0}
    <div class="card p-2 text-xs flex flex-wrap items-center gap-2 bg-accent-500/5 border-accent-500/30">
      <span class="text-ink-500">Sort attivo:</span>
      {#each sortLevels as l, i}
        <span class="pill pill-blue">
          {i + 1}. {l.column} {l.direction === 'asc' ? '▲' : '▼'}
        </span>
      {/each}
      <span class="text-ink-400 italic ml-2">
        doppio click sul nome colonna per aggiungere/rimuovere; click su ▲/▼ per invertire.
        Quando le righe sono raggruppate, il sort si applica all'interno di ogni nest.
      </span>
    </div>
  {/if}

  {#if showQueryHelp}
    <div class="card p-3 text-xs space-y-2 bg-ink-50">
      <div>
        <strong>Operatori:</strong>
        <code>= != &lt; &lt;= &gt; &gt;= contains startswith endswith in [...]</code>
      </div>
      <div>
        <strong>Logica:</strong> <code>AND</code> / <code>OR</code> /
        parentesi <code>(...)</code>.
      </div>
      <div>
        <strong>Campi disponibili:</strong>
        <code>docente, classe, materia, giorno, ora, aula, gruppo,
              schedulato, completo, stato</code>
      </div>
      <div>
        <strong>Esempi:</strong>
        <ul class="list-disc list-inside">
          <li><code>completo = 0</code></li>
          <li><code>schedulato = 0</code></li>
          <li><code>aula = LabFisica AND giorno = Lunedi</code></li>
          <li><code>docente contains Rossi</code></li>
          <li><code>materia in [Matematica, Fisica]</code></li>
        </ul>
      </div>
      <div class="text-ink-500">
        <strong>Sort multi-livello:</strong>
        doppio click sul nome di una colonna per aggiungere/rimuovere
        un livello (max {MAX_SORT_LEVELS}); click sulla freccia ▲/▼ per
        invertire. Il sort viene applicato anche dentro ogni nest del
        raggruppamento.
      </div>
    </div>
  {/if}

  {#if !eventRows}
    <div class="card p-4 text-sm text-ink-500">
      {eventRowsBusy ? 'Caricamento eventi...' : 'Nessun evento.'}
    </div>
  {:else}
    <div class="card p-2 overflow-x-auto">
      <table class="tbl text-xs w-full">
        <thead>
          <tr>
            {#each COLS as c}
              {@const idx = sortLevels.findIndex((l) => l.column === c.key)}
              {@const dir = idx >= 0 ? sortLevels[idx].direction : null}
              <th class="select-none">
                <span class="inline-flex items-center gap-1">
                  <button class="hover:text-accent-500 cursor-pointer
                                 underline decoration-dotted decoration-ink-300
                                 hover:decoration-accent-500"
                          title="Doppio click per aggiungere/rimuovere dal sort (max 3 livelli)"
                          on:dblclick={() => onLabelDblClick(c.key)}>
                    {c.label}
                  </button>
                  {#if dir}
                    <button class="text-[10px] text-accent-500"
                            title="Click per invertire direzione"
                            on:click|stopPropagation={() => onIndicatorClick(c.key)}>
                      {dir === 'asc' ? '▲' : '▼'}
                    </button>
                    {#if sortLevels.length > 1}
                      <span class="text-[9px] bg-accent-500 text-white rounded-full
                                   w-4 h-4 inline-flex items-center justify-center"
                            title="Livello {idx + 1}">
                        {idx + 1}
                      </span>
                    {/if}
                  {/if}
                </span>
              </th>
            {/each}
            <th class="text-right">Azioni</th>
          </tr>
        </thead>
        <tbody>
          {#each groupedBuckets as bucket (bucket.key1)}
            {@const g1Open = (groupBy1 === 'none') || expandedG1.has(bucket.key1)}
            {#if groupBy1 !== 'none'}
              <tr style="background-color:#e0e7ff;"
                  class="cursor-pointer"
                  on:click={() => toggleG1(bucket.key1)}>
                <td colspan="9" class="font-semibold py-1 px-2">
                  <span class="inline-block w-4 text-ink-400">
                    {g1Open ? '▼' : '▶'}
                  </span>
                  {GROUP_OPTIONS.find((o) => o.value === groupBy1)?.label || ''}:
                  {bucket.key1 || '(vuoto)'}
                  <span class="text-ink-500 font-normal text-[10px] ml-2">
                    {bucket.rows1.length} righe
                  </span>
                </td>
              </tr>
            {/if}
            {#if g1Open}
              {#each bucket.sub as sb (bucket.key1 + '|' + sb.key2)}
                {@const g2Key = bucket.key1 + '|' + sb.key2}
                {@const g2Open = (groupBy2 === 'none') || expandedG2.has(g2Key)}
                {#if groupBy1 !== 'none' && groupBy2 !== 'none'}
                  <tr style="background-color:#eef2ff;"
                      class="cursor-pointer"
                      on:click={() => toggleG2(g2Key)}>
                    <td colspan="9" class="text-[11px] pl-6 py-1">
                      <span class="inline-block w-4 text-ink-400">
                        {g2Open ? '▼' : '▶'}
                      </span>
                      {GROUP_OPTIONS.find((o) => o.value === groupBy2)?.label || ''}:
                      <strong>{sb.key2 || '(vuoto)'}</strong>
                      <span class="text-ink-400 ml-2">{sb.rows2.length}</span>
                    </td>
                  </tr>
                {/if}
                {#if g2Open}
                  {#each sb.rows2 as r, i (rowId(r, i))}
                    <tr style={r.is_scheduled
                                ? (r.is_complete ? '' : 'background-color:#fef9c3;')
                                : 'background-color:#fef2f2;'}>
                      <td>
                        <strong>{r.teacher_display}</strong>
                        <span class="text-[10px] text-ink-400">({r.teacher_name})</span>
                      </td>
                      <td>{r.class_name}</td>
                      <td>{r.subject}</td>
                      <td>{r.day_name || (r.is_scheduled ? '' : '-')}</td>
                      <td>{r.hour != null ? r.hour + ':00' : '-'}</td>
                      <td>
                        {#if r.classroom_name}
                          {r.classroom_name}
                        {:else if r.is_scheduled}
                          <span class="pill-amber !text-[10px]">no aula</span>
                        {:else}
                          <span class="text-ink-300">-</span>
                        {/if}
                      </td>
                      <td>
                        {#if r.group_name}{r.group_name}
                        {:else}<span class="text-ink-300">-</span>{/if}
                      </td>
                      <td>
                        {#if r.is_scheduled}
                          <span class="pill-green !text-[10px]">{r.status}</span>
                        {:else}
                          <span class="pill-red !text-[10px]">non schedulato</span>
                        {/if}
                      </td>
                      <td class="text-right whitespace-nowrap">
                        <button class="btn !text-[10px] !px-2 !py-0.5"
                                on:click={() => modifyEventRow(r)}
                                title={r.is_scheduled
                                  ? 'Sposta o disassocia da slot'
                                  : 'Schedula questo evento'}>
                          Modifica
                        </button>
                        <button class="btn-red !text-[10px] !px-2 !py-0.5 ml-1"
                                on:click={() => deleteEventRow(r)}
                                title={r.is_scheduled
                                  ? 'Rimuovi questa lezione (cattedra preservata)'
                                  : 'Elimina la cattedra (e tutte le sue lezioni)'}>
                          Elimina
                        </button>
                      </td>
                    </tr>
                  {/each}
                {/if}
              {/each}
            {/if}
          {/each}
          {#if eventRows.items.length === 0}
            <tr><td colspan="9" class="text-center text-ink-400 italic py-4">
              Nessun evento da mostrare con questi filtri.
            </td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<Modal open={!!slotPicker}
       title={slotPicker
         ? `Sposta ${slotPicker.eventRow.subject} (${slotPicker.eventRow.class_name}) - lezione #${slotPicker.lesson.lesson_id}`
         : ''}
       onClose={() => (slotPicker = null)}>
  {#if slotPicker}
    <div class="space-y-3">
      <p class="text-xs text-ink-500">
        Click su uno slot per spostare la lezione la'.
        Verde = libero per docente e classe;
        rosso = HARD (docente o classe gia' impegnati);
        ambra = aula occupata da un'altra lezione (verra' liberata);
        azzurro = slot attuale.
      </p>
      <div class="overflow-x-auto">
        <table class="tbl text-xs">
          <thead>
            <tr>
              <th></th>
              {#each DAYS as d}
                <th class="text-center">{DAY_NAMES_IT[d]}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each HOURS as h}
              <tr>
                <td class="text-ink-500 pr-2 font-mono">{h}:00</td>
                {#each DAYS as d}
                  {@const info = slotInfo(d, h)}
                  <td class="p-1 align-middle">
                    <button
                      class="w-full h-12 rounded border-2 transition-colors {slotClass(info)}"
                      title={slotTitle(info, d, h)}
                      disabled={info?.isCurrent}
                      on:click={() => pickSlot(d, h)}>
                      {#if info?.isCurrent}
                        <span class="text-sky-900 text-[10px] font-semibold">qui</span>
                      {:else if info?.status === 'hard'}
                        <span class="text-red-900 text-[10px]">
                          {info.teacherBusy ? 'D' : ''}{info.classBusy ? 'C' : ''}
                        </span>
                      {:else if info?.status === 'room'}
                        <span class="text-amber-900 text-[10px]">aula</span>
                      {:else}
                        <span class="text-emerald-700 text-[10px]">ok</span>
                      {/if}
                    </button>
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <div class="text-[10px] text-ink-400 flex flex-wrap gap-3">
        <span><span class="pill !text-[10px]" style="background:#a7f3d0;color:#065f46;">ok</span> libero</span>
        <span><span class="pill !text-[10px]" style="background:#fecaca;color:#991b1b;">D / C</span> docente / classe gia' impegnati (HARD)</span>
        <span><span class="pill !text-[10px]" style="background:#fde68a;color:#92400e;">aula</span> aula occupata da altra lezione</span>
        <span><span class="pill !text-[10px]" style="background:#bae6fd;color:#075985;">qui</span> slot attuale</span>
      </div>
      <div class="flex items-center justify-end gap-2">
        <button class="btn-amber !text-xs"
                on:click={disassociateFromSlot}
                title="Rimuovi il legame giorno/ora di questa lezione: la cattedra rimane ma diventa incompleta (riapparira' nel pannello rosso e fra gli eventi non schedulati)">
          Disassocia (rendi non schedulato)
        </button>
        <button class="btn" on:click={() => (slotPicker = null)}>Annulla</button>
      </div>
    </div>
  {/if}
</Modal>

<ScheduleConflictModal open={!!conflictDialog}
                       title="Conflitto sull'orario di destinazione"
                       subject={conflictDialog
                          ? `${DAY_NAMES_IT[conflictDialog.day]} ${conflictDialog.hour}:00`
                            + (conflictDialog.classroom_name ? ` - aula ${conflictDialog.classroom_name}` : '')
                          : ''}
                       details={conflictDialog?.details ?? {}}
                       onCancel={() => (conflictDialog = null)}
                       onResolve={resolveConflict}/>

<AddEventModal bind:open={addEventOpen}
               teachers={allTeachers}
               classes={allClasses}
               rooms={allRooms}
               onClose={() => (addEventOpen = false)}
               onCreated={refreshAll}/>

<AddLessonModal bind:open={addLessonOpen}
                mode="slot"
                day={1} hour={8}
                preset={addLessonPreset}
                teachers={allTeachers}
                classes={allClasses}
                rooms={allRooms}
                onClose={() => (addLessonOpen = false)}
                onCreated={refreshAll}/>
