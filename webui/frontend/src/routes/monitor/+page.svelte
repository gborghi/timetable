<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants';
  import ScheduleConflictModal from '$lib/components/schedule/ScheduleConflictModal.svelte';
  import AddEventModal from '$lib/components/schedule/AddEventModal.svelte';
  import AddLessonModal from '$lib/components/schedule/AddLessonModal.svelte';
  import GroupedEventsTable from '$lib/components/monitor/GroupedEventsTable.svelte';

  let summary = null;
  let allRooms = [];
  let allTeachers = [];
  let allClasses = [];

  // Two GroupedEventsTable instances; each has its own grouping/sort/
  // query state. We hold refresh handles so a mutation in one panel
  // can refresh the other.
  let mainTable;
  let redTable;
  let redPanelOpen = false;

  // Add-event / Add-lesson / slot-picker modal state owned at the page
  // level so per-row actions across both tables share the same dialogs.
  let addEventOpen = false;
  let addLessonOpen = false;
  let addLessonPreset = {};

  // Per-row actions delegated by GroupedEventsTable.
  async function deleteEventRow(row) {
    if (row.is_scheduled && row.lesson_id != null) {
      if (!confirm(`Eliminare la lezione di ${row.subject} `
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
      if (!confirm(`Eliminare l'intera cattedra di ${row.subject} `
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
    if (redTable) await redTable.refresh();
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
    if (!confirm(msg)) return;
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
  // Selected rows per table (independent state).
  let mainSelected = [];
  let redSelected = [];

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
    try { allRooms = (await api.get('/api/classrooms')).map((r) => r.name).sort(); }
    catch { allRooms = []; }
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
    } catch { allClasses = []; }
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
    Doppio click sul nome di una colonna per aggiungere un livello di
    sort (max 3); click sulla ▲/▼ accanto per invertire la direzione.
    Il sort si applica all'interno di ogni nest del raggruppamento e
    funziona anche senza nesting.
  </p>

  <div class="flex items-center gap-2 flex-wrap">
    <button class="btn-primary !text-xs"
            on:click={() => (addEventOpen = true)}>
      + Nuovo evento
    </button>
    <button class="btn !text-xs"
            on:click={() => (redPanelOpen = !redPanelOpen)}
            title="Mostra/nascondi pannello eventi senza assegnazione temporale">
      {redPanelOpen ? 'Nascondi' : 'Mostra'} pannello rosso
    </button>
  </div>

  {#if redPanelOpen}
    <GroupedEventsTable bind:this={redTable}
                        endpoint="/api/monitor/event-rows"
                        auxQuery="schedulato = 0"
                        redTheme={true}
                        title="Eventi senza assegnazione temporale"
                        subtitle="Cattedre per cui non tutte le ore attese sono state schedulate nella soluzione attiva. Per ognuna assegna le ore mancanti cliccando 'Modifica' qui sotto, o creane di nuove con '+ Nuovo evento'."
                        selectable={true}
                        bind:selectedIds={redSelected}
                        onModify={modifyEventRow}
                        onDelete={deleteEventRow}
                        onBulkDelete={bulkDelete}
                        onChanged={refreshAll}/>
  {/if}

  <GroupedEventsTable bind:this={mainTable}
                      endpoint="/api/monitor/event-rows"
                      auxQuery=""
                      title="Tutti gli eventi"
                      selectable={true}
                      bind:selectedIds={mainSelected}
                      onModify={modifyEventRow}
                      onDelete={deleteEventRow}
                      onBulkDelete={bulkDelete}
                      onChanged={refreshAll}/>
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
