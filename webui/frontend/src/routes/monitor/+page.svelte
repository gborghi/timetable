<script>
  import DecorIcon from '$lib/components/DecorIcon.svelte';
  import { confirmDialog } from '$lib/confirm';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants';
  import ScheduleConflictModal from '$lib/components/schedule/ScheduleConflictModal.svelte';
  import AddEventModal from '$lib/components/schedule/AddEventModal.svelte';
  import AddLessonModal from '$lib/components/schedule/AddLessonModal.svelte';
  import GroupedEventsTable from '$lib/components/monitor/GroupedEventsTable.svelte';
  import PlaceEventModal from '$lib/components/monitor/PlaceEventModal.svelte';
  import BulkEventsModal from '$lib/components/monitor/BulkEventsModal.svelte';

  let summary = null;
  let allRooms = [];
  // Full room objects (with capacity) -- forwarded to AddEventModal
  // for the classroom-too-small pre-flight warning.
  let allRoomsFull = [];
  // Map class_name -> {n_students:int} for the same warning.
  let classesMeta = {};
  let allTeachers = [];
  let allClasses = [];

  // Single GroupedEventsTable instance driven by a segmented-control
  // tab filter (Tutti / Incompleti / Lockati). Each tab composes a
  // different `auxQuery` that's ANDed into the user's DSL query.
  let mainTable;
  let activeTab = 'all';   // 'all' | 'incomplete' | 'unscheduled' | 'locked'

  // Map a tab key into the auxQuery DSL fragment.
  // - incomplete = qualunque manchi (ore, aule, gruppo)
  // - unscheduled = solo le righe placeholder senza giorno/ora
  // - locked = is_locked=1
  $: tabAuxQuery = {
    all: '',
    incomplete: 'completo = 0',
    unscheduled: 'schedulato = 0',
    locked: 'is_locked = 1',
  }[activeTab];

  // Place-event modal state
  let placeOpen = false;
  let placeIds = [];
  let placeSummaries = [];

  // Bulk-apply modal state (set/clear classroom + set lock).
  let bulkApplyOpen = false;
  let bulkApplyRows = [];

  // Add-event / Add-lesson / slot-picker modal state owned at the page
  // level so per-row actions across both tables share the same dialogs.
  let addEventOpen = false;
  let addLessonOpen = false;
  let addLessonPreset = {};

  // Per-row actions delegated by GroupedEventsTable.
  async function deleteEventRow(row) {
    if (row.is_scheduled && row.lesson_id != null) {
      if (!await confirmDialog(`Eliminare la lezione di ${row.subject} `
          + `(${row.class_name}, ${row.teacher_name}) di `
          + `${row.day_name} ${row.hour}:00? `
          + `La cattedra rimane ma diventa incompleta.`)) return;
      try {
        await api.del('/api/monitor/lesson/' + row.lesson_id);
        flash('Lezione eliminata.', 'success');
      } catch (e) {
        flash('Errore: ' + e.message, 'error');
      }
    } else {
      if (!await confirmDialog(`Eliminare l'intera cattedra di ${row.subject} `
          + `(${row.class_name}, ${row.teacher_name})? `
          + `Saranno eliminate ANCHE tutte le sue lezioni gia' schedulate.`)) return;
      try {
        await api.del('/api/monitor/event/' + row.assignment_id);
        flash('Cattedra e lezioni eliminate.', 'success');
      } catch (e) {
        flash('Errore: ' + e.message, 'error');
      }
    }
    await refreshAll();
  }

  async function modifyEventRow(row) {
    if (row.is_scheduled && row.lesson_id != null) {
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
      addLessonPreset = {
        class_name: row.class_name,
        teacher_name: row.teacher_name,
      };
      addLessonOpen = true;
    }
  }

  async function refreshAll() {
    await refreshSummary();
    if (mainTable) await mainTable.refresh();
  }

  // Per-row Dissocia: rimuove SOLO questa singola lezione dal suo
  // slot temporale. La cattedra resta; missing_hours +1. Per le righe
  // placeholder (gia' non schedulate) e' un no-op informativo.
  async function dissociateRow(row) {
    if (!row.is_scheduled || row.lesson_id == null) {
      flash('Evento gia\' non schedulato (nessuno slot da rimuovere).',
            'info');
      return;
    }
    if (!await confirmDialog(`Dissociare la lezione di ${row.subject} `
        + `(${row.class_name}, ${row.teacher_name}) di `
        + `${row.day_name} ${row.hour}:00? `
        + `La cattedra resta; questa singola ora torna fra le mancanti.`)) {
      return;
    }
    try {
      await api.del('/api/monitor/lesson/' + row.lesson_id);
      flash('Lezione dissociata.', 'success');
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
    await refreshAll();
  }

  // Per-row Lock toggle.
  async function lockToggleRow(row) {
    const newState = !(row.is_locked || row.locked);
    try {
      await api.post('/api/monitor/event/' + row.assignment_id + '/lock',
                      { locked: newState });
      flash(newState ? 'Evento bloccato.' : 'Evento sbloccato.', 'success');
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
    await refreshAll();
  }

  // Per-row Piazza: open the modal with this single event preselected.
  function placeRow(row) {
    placeIds = [row.assignment_id];
    placeSummaries = [{
      teacher_display: row.teacher_display,
      class_name: row.class_name,
      subject: row.subject,
    }];
    placeOpen = true;
  }

  // Bulk Dissocia: rimuove le SINGOLE lezioni schedulate selezionate
  // (placeholder ignorate). La cattedra resta in ogni caso.
  async function bulkDissociate(rows) {
    if (rows.length === 0) return;
    const lessonRows = rows.filter((r) => r.is_scheduled
                                            && r.lesson_id != null);
    const skipped = rows.length - lessonRows.length;
    if (lessonRows.length === 0) {
      flash('Nessuna lezione schedulata da dissociare nella selezione.',
            'info');
      return;
    }
    let msg = `Dissociare ${lessonRows.length} singole lezioni? `
            + `Le cattedre restano; le ore tornano fra le mancanti.`;
    if (skipped > 0) msg += `\n(${skipped} placeholder verranno ignorate)`;
    if (!await confirmDialog(msg)) return;
    let okCount = 0;
    for (const r of lessonRows) {
      try {
        await api.del('/api/monitor/lesson/' + r.lesson_id);
        okCount++;
      } catch (e) {
        console.warn('bulk dissociate failed for lesson', r.lesson_id, e);
      }
    }
    flash(`${okCount}/${lessonRows.length} lezioni dissociate.`, 'success');
    await refreshAll();
  }

  async function bulkLock(rows) {
    if (rows.length === 0) return;
    const aids = Array.from(new Set(rows.map((r) => r.assignment_id)));
    try {
      // locked=null -> backend computes the toggle (lock all if any is
      // unlocked, else unlock all).
      const r = await api.post('/api/monitor/events/lock-batch',
                                { event_ids: aids, locked: null });
      flash(`${r.n_assignments} eventi `
            + (r.locked ? 'bloccati.' : 'sbloccati.'), 'success');
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
    await refreshAll();
  }

  // Bulk apply (BulkEventsModal): set/clear classroom + set lock with
  // dry-run conflict review. The modal handles the verify -> apply flow.
  function bulkApply(rows) {
    if (rows.length === 0) return;
    bulkApplyRows = rows;
    bulkApplyOpen = true;
  }

  function bulkPlace(rows) {
    if (rows.length === 0) return;
    const seen = new Set();
    const ids = [];
    const summ = [];
    for (const r of rows) {
      if (seen.has(r.assignment_id)) continue;
      seen.add(r.assignment_id);
      ids.push(r.assignment_id);
      summ.push({
        teacher_display: r.teacher_display,
        class_name: r.class_name,
        subject: r.subject,
      });
    }
    placeIds = ids;
    placeSummaries = summ;
    placeOpen = true;
  }

  // Bulk delete handler shared by both tables. The parent owns the
  // confirm dialog so the user gets ONE confirmation for the whole
  // batch, not one per row.
  async function bulkDelete(rows) {
    if (rows.length === 0) return;
    const nLessons = rows.filter((r) => r.is_scheduled
                                       && r.lesson_id != null).length;
    const nPlaceholders = rows.length - nLessons;
    const parts = [];
    if (nLessons) parts.push(`${nLessons} lezioni`);
    if (nPlaceholders) parts.push(`${nPlaceholders} cattedre`
                                   + ` (con TUTTE le loro lezioni)`);
    const msg = `Eliminare ${parts.join(' + ')}? L'azione non e' reversibile.`;
    if (!await confirmDialog(msg)) return;
    let okCount = 0;
    for (const r of rows) {
      try {
        if (r.is_scheduled && r.lesson_id != null) {
          await api.del('/api/monitor/lesson/' + r.lesson_id);
        } else {
          await api.del('/api/monitor/event/' + r.assignment_id);
        }
        okCount++;
      } catch (e) {
        console.warn('bulk delete failed for row', r, e);
      }
    }
    flash(`${okCount}/${rows.length} righe eliminate.`, 'success');
    await refreshAll();
  }
  // Selected rows for the (single) tabbed table.
  let mainSelected = [];

  async function disassociateFromSlot() {
    if (!slotPicker) return;
    const lid = slotPicker.lesson?.lesson_id;
    if (lid == null) {
      flash('Lezione senza id; impossibile disassociare.', 'error');
      return;
    }
    if (!await confirmDialog('Disassociare questa lezione da '
        + slotPicker.lesson.day + '/' + slotPicker.lesson.hour
        + '? La cattedra rimane ma l\'evento diventa non schedulato.')) {
      return;
    }
    try {
      await api.del('/api/monitor/lesson/' + lid);
      flash('Lezione disassociata: cattedra preservata.', 'success');
      slotPicker = null;
      await refreshAll();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  // Conflict modal state
  let conflictDialog = null;
  // shape: { event_id, lesson_id, day, hour, classroom_name, details:{teacher_busy,...}, original }

  // Slot picker modal state.
  let slotPicker = null;
  let slotPickerLoading = false;

  onMount(async () => {
    try { summary = await api.get('/api/monitor/summary'); } catch { /* */ }
    try {
      const rs = await api.get('/api/classrooms');
      allRoomsFull = (rs || []).slice().sort(
        (a, b) => String(a.name).localeCompare(String(b.name)));
      allRooms = allRoomsFull.map((r) => r.name);
    } catch { allRooms = []; allRoomsFull = []; }
    try {
      const t = await api.get('/api/teachers');
      allTeachers = (t || []).map((x) => ({
        name: x.name,
        subjects: x.subjects ?? [],
      })).sort((a, b) => a.name.localeCompare(b.name));
    } catch { allTeachers = []; }
    try {
      const c = await api.get('/api/classes');
      allClasses = (c || []).map((x) => x.name).sort();
      classesMeta = Object.fromEntries(
        (c || []).map((x) => [x.name, { n_students: x.n_students }]));
    } catch { allClasses = []; classesMeta = {}; }
  });

  async function refreshSummary() {
    try { summary = await api.get('/api/monitor/summary'); } catch { /* */ }
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
      const dry = await applyMove(eventId, lesson, newDay, newHour, newRoom,
                                  'dry_run');
      if (dry.no_change) return;
      if (dry.ok) {
        flash('Lezione spostata.', 'success');
        await refreshAll();
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
        await refreshAll();
      } else if (r.cancelled) {
        flash('Modifica annullata.', 'success');
        conflictDialog = null;
      }
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }
</script>

<div class="space-y-4" data-testid="monitor-page">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1 class="flex items-center gap-2"><DecorIcon name="bell" size={26} class="shrink-0" /> Eventi</h1>
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
    Doppio click sul nome di una colonna per aggiungere un livello di
    sort (max 3); click sulla ▲/▼ accanto per invertire la direzione.
    Il sort si applica all'interno di ogni nest del raggruppamento e
    funziona anche senza nesting.
  </p>

  <div class="flex items-center gap-2 flex-wrap">
    <button class="btn-primary !text-xs"
            on:click={() => (addEventOpen = true)}
            data-testid="monitor-add-event-btn">
      + Nuovo evento
    </button>
  </div>

  <!-- Segmented control: Tutti / Incompleti / Lockati. Each tab
       composes a different auxQuery into the table; Reset query
       still works (it clears only the user-typed query). -->
  <div class="card p-2 flex items-center gap-1 flex-wrap"
       data-testid="monitor-tabs">
    <button class="btn !text-xs"
            class:!bg-accent-500={activeTab === 'all'}
            class:!text-white={activeTab === 'all'}
            on:click={() => (activeTab = 'all')}
            data-testid="monitor-tab-all">
      Tutti
      {#if summary?.n_rows != null}
        <span class="ml-1 pill !text-[10px]">{summary.n_rows}</span>
      {/if}
    </button>
    <button class="btn !text-xs"
            class:!bg-amber-500={activeTab === 'incomplete'}
            class:!text-white={activeTab === 'incomplete'}
            on:click={() => (activeTab = 'incomplete')}
            title="Eventi con almeno una mancanza (ore, aula, gruppo)"
            data-testid="monitor-tab-incomplete">
      Incompleti
      {#if summary?.n_incomplete != null}
        <span class="ml-1 pill pill-amber !text-[10px]">{summary.n_incomplete}</span>
      {/if}
    </button>
    <button class="btn !text-xs"
            class:!bg-red-500={activeTab === 'unscheduled'}
            class:!text-white={activeTab === 'unscheduled'}
            on:click={() => (activeTab = 'unscheduled')}
            title="Solo eventi senza assegnazione temporale (placeholder)"
            data-testid="monitor-tab-unscheduled">
      Senza orario
      {#if summary?.n_rows_unscheduled != null}
        <span class="ml-1 pill pill-red !text-[10px]">{summary.n_rows_unscheduled}</span>
      {/if}
    </button>
    <button class="btn !text-xs"
            class:!bg-amber-600={activeTab === 'locked'}
            class:!text-white={activeTab === 'locked'}
            on:click={() => (activeTab = 'locked')}
            title="Eventi marcati is_locked = 1: non si muovono durante l'ottimizzazione"
            data-testid="monitor-tab-locked">
      🔒 Lockati
      {#if summary?.n_rows_locked != null}
        <span class="ml-1 pill pill-amber !text-[10px]">{summary.n_rows_locked}</span>
      {/if}
    </button>
  </div>

  {#key activeTab}
    <GroupedEventsTable bind:this={mainTable}
                        endpoint="/api/monitor/event-rows"
                        auxQuery={tabAuxQuery}
                        redTheme={activeTab === 'unscheduled'}
                        title={activeTab === 'incomplete'
                                ? 'Eventi incompleti'
                                : (activeTab === 'unscheduled'
                                    ? 'Eventi senza assegnazione temporale'
                                    : (activeTab === 'locked'
                                        ? 'Eventi bloccati'
                                        : 'Tutti gli eventi'))}
                        subtitle={activeTab === 'incomplete'
                                ? 'Eventi con almeno una mancanza: ore non schedulate, aula assente, o gruppo mancante.'
                                : (activeTab === 'unscheduled'
                                    ? 'Cattedre per cui non tutte le ore attese sono state schedulate. Usa "Piazza" per collocarle.'
                                    : (activeTab === 'locked'
                                        ? 'Cattedre marcate come bloccate: non si muovono durante Phase B / metaeuristiche.'
                                        : ''))}
                        selectable={true}
                        bind:selectedIds={mainSelected}
                        onModify={modifyEventRow}
                        onDelete={deleteEventRow}
                        onDissociate={dissociateRow}
                        onLockToggle={lockToggleRow}
                        onPlace={placeRow}
                        onBulkDelete={bulkDelete}
                        onBulkDissociate={bulkDissociate}
                        onBulkLock={bulkLock}
                        onBulkPlace={bulkPlace}
                        onBulkApply={bulkApply}
                        onChanged={refreshAll}/>
  {/key}
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
               rooms={allRoomsFull.length ? allRoomsFull : allRooms}
               {classesMeta}
               onClose={() => (addEventOpen = false)}
               onCreated={refreshAll}/>

<AddLessonModal bind:open={addLessonOpen}
                mode="slot"
                day={1} hour={8}
                preset={addLessonPreset}
                teachers={allTeachers}
                classes={allClasses}
                rooms={allRoomsFull.length ? allRoomsFull : allRooms}
                {classesMeta}
                onClose={() => (addLessonOpen = false)}
                onCreated={refreshAll}/>

<PlaceEventModal bind:open={placeOpen}
                 eventIds={placeIds}
                 summaries={placeSummaries}
                 onClose={() => (placeOpen = false)}
                 onCompleted={refreshAll}/>

<BulkEventsModal bind:open={bulkApplyOpen}
                 selectedRows={bulkApplyRows}
                 rooms={allRooms}
                 onDone={refreshAll}/>
