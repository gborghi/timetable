<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants';
  import ScheduleConflictModal from '$lib/components/schedule/ScheduleConflictModal.svelte';
  import AddEventModal from '$lib/components/schedule/AddEventModal.svelte';

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
      allTeachers = (t || []).map((x) => x.name).sort();
    } catch { allTeachers = []; }
    try {
      const c = await api.get('/api/classes');
      allClasses = (c || []).map((x) => x.name).sort();
    } catch { allClasses = []; }
    await refreshIncomplete();
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

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/monitor/events"
    {columns}
    {help}
    rowKey={(r) => r.assignment_id}
    let:row let:columns>
    <tr style={rowBg(row)} class="cursor-pointer"
        on:click={() => toggleRow(row)}>
      <td>
        <span class="text-xs text-ink-400 mr-1">
          {expanded.has(row.assignment_id) ? '▼' : '▶'}
        </span>
        <strong>{row.teacher_display}</strong>
        <span class="text-[10px] text-ink-400">({row.teacher_name})</span>
      </td>
      <td>{row.class_name}</td>
      <td>{row.subject}</td>
      <td class="text-center">{row.expected_hours}</td>
      <td class="text-center">{row.assigned_hours}</td>
      <td class="text-center">
        {#if row.missing_hours > 0}
          <span class="pill-red">{row.missing_hours}</span>
        {:else}<span class="text-ink-300">-</span>{/if}
      </td>
      <td class="text-center">
        {#if row.missing_room > 0}
          <span class="pill-amber">{row.missing_room}</span>
        {:else}<span class="text-ink-300">-</span>{/if}
      </td>
      <td class="text-xs">
        {#if row.group_name}{row.group_name}
        {:else if row.missing_group}<span class="pill-amber">manca</span>
        {:else}<span class="text-ink-300">-</span>{/if}
      </td>
      <td class="text-xs">
        {#if row.is_complete}<span class="pill-green">ok</span>
        {:else}{row.status}{/if}
      </td>
    </tr>
    {#if expanded.has(row.assignment_id)}
      <tr style="background-color:#f9fafb;">
        <td colspan={columns.length + 1} class="p-2">
          {#if busyEvent === row.assignment_id && !lessonsByEvent[row.assignment_id]}
            <span class="text-xs text-ink-400 italic">caricamento...</span>
          {:else if lessonsByEvent[row.assignment_id]?.length === 0}
            <span class="text-xs text-ink-400 italic">nessuna lezione assegnata in questa cattedra</span>
          {:else if lessonsByEvent[row.assignment_id]}
            <table class="tbl text-xs w-full">
              <thead>
                <tr>
                  <th>#</th><th>Giorno / Ora</th><th>Aula</th><th></th>
                </tr>
              </thead>
              <tbody>
                {#each lessonsByEvent[row.assignment_id] as l}
                  <tr>
                    <td class="text-ink-400">#{l.lesson_id}</td>
                    <td>
                      <button class="btn !text-xs !px-2 !py-1"
                        on:click|stopPropagation={() => openSlotPicker(row, l)}
                        disabled={slotPickerLoading}
                        title="Apri matrice giorni/ore con disponibilita"
                      >{DAY_NAMES_IT[l.day]} {l.hour}:00</button>
                    </td>
                    <td>
                      <select class="text-xs px-1 py-0.5 border border-ink-200 rounded"
                        on:click|stopPropagation
                        on:change={(e) => tryMove(
                          row.assignment_id, l, l.day, l.hour,
                          e.target.value || null)}
                        value={l.classroom_name || ''}>
                        <option value="">(nessuna)</option>
                        {#each allRooms as r}<option value={r}>{r}</option>{/each}
                      </select>
                    </td>
                    <td>
                      {#if !l.classroom_name}
                        <span class="pill-amber !text-[10px]">no aula</span>
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        </td>
      </tr>
    {/if}
  </SortableQueryableList>
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
      <div class="flex justify-end">
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
               onCreated={async () => {
                 await refreshSummary();
                 await refreshIncomplete();
                 if (listRef) await listRef.reload();
               }}/>
