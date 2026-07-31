<script>
  import PageHero from '$lib/components/PageHero.svelte';
  import { confirmDialog } from '$lib/confirm';
  /**
   * /schedule -- timetable view + interactive editor.
   *
   * The default UI is the WeeklyCalendarView in mode='schedule':
   *   - Background: configured Tab Ore slots; non-configured hours are
   *     red while a drag is in progress (drop reject).
   *   - Foreground: each Lesson rendered as a draggable, clickable
   *     event coloured by deterministic palette (consistent across
   *     views).
   *   - Filter dropdown: Globale | Per classe | Per docente | Per aula
   *     -- combined with an autocomplete entity picker.
   *   - Click on an event -> "Lesson actions" modal (Modifica / Sposta
   *     / Svincola / Elimina).
   *   - Click on an empty configured slot -> AddLessonModal.
   *   - Drag an event onto a slot -> POST /api/lessons/{id}/move.
   *   - Pool sidebar: list of UnscheduledLessons; drag onto the
   *     calendar to POST /api/lessons/unscheduled/{id}/reschedule.
   *   - Soft-conflict preview: while dragging, every existing event
   *     sharing the dragged lesson's teacher / class / room gets an
   *     outline + badge.
   *
   * The legacy 6x6 matrix UI is preserved temporarily behind
   * `?legacy=true` so users can fall back if anything regresses; that
   * fallback will be deleted in a follow-up after the calendar UI is
   * exercised.
   */
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { api, downloadUrl } from '$lib/api';
  import { humanMetricsLine } from '$lib/metrics_labels';
  import { flash, refreshDataset } from '$lib/stores';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants';
  import WeeklyCalendarView from '$lib/components/WeeklyCalendarView.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import RoomDropdown from '$lib/components/schedule/RoomDropdown.svelte';
  import RoomClearedNoticeModal from '$lib/components/schedule/RoomClearedNoticeModal.svelte';
  import SolutionsTable from '$lib/components/schedule/SolutionsTable.svelte';
  import AddLessonModal from '$lib/components/schedule/AddLessonModal.svelte';
  import ScheduleConflictModal from '$lib/components/schedule/ScheduleConflictModal.svelte';

  // Layout: read ?legacy=true once at mount to opt into the old 6x6
  // matrix UI. Anything else -> calendar view.
  let legacyMode = false;
  $: legacyMode = $page.url.searchParams.get('legacy') === 'true';

  // --- Calendar-view state -----------------------------------------
  let view = 'global';      // 'global' | 'class' | 'teacher' | 'room'
  let entityId = '';         // selected name (when view !== 'global')
  let entityFilter = '';     // autocomplete typed text
  let workingHoursConfig = null;
  let lessons = [];          // flat list of scheduled Lessons
  let unscheduled = [];      // pool entries
  let summary = null;        // { obj_value, metrics }
  let solutions = [];
  let allRooms = [];
  // Full room objects (with capacity) for the AddLessonModal capacity
  // pre-flight. Indexed by name; populated from /api/classrooms.
  let allRoomsFull = [];
  // Map class_name -> {n_students:int}, used by AddLessonModal to warn
  // when the picked room is too small. Backend HARD-enforces; this is
  // a pure UX hint.
  let classesMeta = {};
  let teachersWithSubjects = [];
  // Lesson-actions modal state.
  let actionLesson = null;
  let actionMode = 'menu';   // menu | edit | move
  // AddLessonModal state.
  let addLessonOpen = false;
  let addLessonMode = 'slot';
  let addLessonDay = 1;
  let addLessonHour = 8;
  let addLessonPreset = {};
  // Click-to-move state (alternative to drag-drop).
  let pendingMoveLessonId = null;
  // Room-cleared notice modal.
  let roomClearedNotice = null;
  // Drop-on-occupied conflict modal state. When the backend rejects a
  // move/reschedule because the destination slot already holds rows
  // sharing teacher / class / room, we capture them here so the user
  // can pick "Sostituisci" (delete conflicts + retry) or "Annulla".
  let dropConflict = null;
  // { kind: 'move' | 'reschedule', sourceId, day, hour,
  //   subject, details: { teacher_busy, class_busy, room_busy } }

  // --- Legacy state (kept for ?legacy=true fallback) ---------------
  let classData = null;
  let teacherData = null;
  let roomData = null;
  let slotData = null;
  let selectedClass = '', selectedTeacher = '', selectedRoom = '';
  let slotDay = 1, slotHour = 8;

  $: classNames = [...new Set(lessons.map((l) => l.class_name).filter(Boolean))]
    .sort();
  $: teacherNames = [...new Set(lessons.map((l) => l.teacher_name).filter(Boolean))]
    .sort();
  $: roomNames = (() => {
    const set = new Set();
    for (const l of lessons) if (l.classroom_name) set.add(l.classroom_name);
    for (const r of allRooms) set.add(r);
    return [...set].sort();
  })();

  $: entitySource = view === 'class' ? classNames
    : view === 'teacher' ? teacherNames
    : view === 'room' ? roomNames : [];
  $: filteredEntities = entitySource.filter(
    (n) => !entityFilter || n.toLowerCase().includes(entityFilter.toLowerCase()));

  $: calendarFilter = view === 'global'
    ? { type: null, id: null }
    : { type: view, id: entityId || null };

  $: calendarTitle = view === 'global'
    ? 'Orario globale'
    : view === 'class' ? `Orario classe ${entityId || '...'}`
    : view === 'teacher' ? `Orario docente ${entityId || '...'}`
    : `Orario aula ${entityId || '...'}`;

  // Dismissible how-to strip above the calendar: the drag/click
  // affordances otherwise live only in hover tooltips.
  let helpDismissed = false;
  function dismissHelp() {
    helpDismissed = true;
    try { localStorage.setItem('pt_schedule_help_dismissed', '1'); } catch (_e) { /**/ }
  }

  onMount(async () => {
    try { helpDismissed = localStorage.getItem('pt_schedule_help_dismissed') === '1'; }
    catch (_e) { /**/ }
    if (legacyMode) {
      await loadLegacy();
      return;
    }
    await loadCalendar();
    try {
      workingHoursConfig = await api.get('/api/working-hours/config');
    } catch { /* fallback to default config in WeeklyCalendarView */ }
    try {
      solutions = await api.get('/api/schedule/solutions');
    } catch { solutions = []; }
    try {
      const rs = await api.get('/api/classrooms');
      allRoomsFull = (rs || []).slice().sort(
        (a, b) => String(a.name).localeCompare(String(b.name)));
      allRooms = allRoomsFull.map((r) => r.name);
    } catch { allRoomsFull = []; allRooms = []; }
    try {
      const cs = await api.get('/api/classes');
      classesMeta = Object.fromEntries(
        (cs || []).map((c) => [c.name, { n_students: c.n_students }]));
    } catch { classesMeta = {}; }
    try {
      const t = await api.get('/api/teachers');
      teachersWithSubjects = (t || []).map((x) => ({
        name: x.name, subjects: x.subjects ?? [],
      })).sort((a, b) => a.name.localeCompare(b.name));
    } catch { teachersWithSubjects = []; }
  });

  async function loadCalendar() {
    try {
      const [r, u, summaryData] = await Promise.all([
        api.get('/api/lessons'),
        api.get('/api/lessons/unscheduled'),
        api.get('/api/schedule/by-class').catch(() => null),
      ]);
      lessons = r.lessons || [];
      unscheduled = u.lessons || [];
      summary = summaryData
        ? { obj_value: summaryData.obj_value, metrics: summaryData.metrics }
        : null;
      // Default entity selection so the autocomplete starts useful.
      if (view === 'class' && !entityId && classNames.length) {
        entityId = classNames[0];
      } else if (view === 'teacher' && !entityId && teacherNames.length) {
        entityId = teacherNames[0];
      } else if (view === 'room' && !entityId && roomNames.length) {
        entityId = roomNames[0];
      }
    } catch (e) {
      flash('Errore caricamento orario: ' + e.message, 'error');
      lessons = [];
      unscheduled = [];
    }
  }

  function onSelectView(v) {
    view = v;
    entityId = '';
    entityFilter = '';
    if (v === 'class' && classNames.length) entityId = classNames[0];
    if (v === 'teacher' && teacherNames.length) entityId = teacherNames[0];
    if (v === 'room' && roomNames.length) entityId = roomNames[0];
  }

  // The "cerca" box only *filters* the list; picking a datalist suggestion
  // (or typing a full name) used to leave the shown timetable unchanged
  // because it never set `entityId` (which drives the view). Commit the
  // search to the actual selection: an exact match wins; on `change`
  // (Enter / blur) a unique remaining candidate is selected too.
  function commitEntitySearch(strict) {
    const q = entityFilter.trim().toLowerCase();
    if (!q) return;
    const exact = entitySource.find((n) => n.toLowerCase() === q);
    if (exact) { if (exact !== entityId) entityId = exact; return; }
    if (!strict && filteredEntities.length === 1) {
      entityId = filteredEntities[0];
    }
  }

  // ---- Lesson actions modal --------------------------------------
  function onLessonClick(l) {
    actionLesson = l;
    actionMode = 'menu';
  }
  function closeActions() {
    actionLesson = null;
    actionMode = 'menu';
    pendingMoveLessonId = null;
  }
  function startEdit() { actionMode = 'edit'; }
  function startMove() {
    pendingMoveLessonId = actionLesson?.id ?? null;
    actionLesson = null;
    actionMode = 'menu';
    flash('Click su uno slot vuoto per spostare la lezione', 'success');
  }
  async function svincolaLesson() {
    if (!actionLesson) return;
    if (!await confirmDialog('Svincolare questa lezione? Verra messa nel pool '
                 + 'unscheduled e non occupera piu lo slot.')) return;
    try {
      await api.post('/api/lessons/' + actionLesson.id + '/unschedule');
      flash('Lezione svincolata', 'success');
      closeActions();
      await loadCalendar();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }
  async function eliminaLesson() {
    if (!actionLesson) return;
    if (!await confirmDialog('Eliminare definitivamente questa lezione?')) return;
    const snap = { ...actionLesson };
    try {
      await api.del('/api/lessons/' + snap.id);
      closeActions();
      await loadCalendar();
      await refreshDataset();
      // UNDO recreates the lesson via /api/schedule/lesson. Only offered
      // for class-bound lessons (the add endpoint takes class_name, not a
      // group); the slot was just freed so on_conflict='dry_run' creates it.
      const canUndo = !!snap.class_name && snap.day != null
        && snap.hour != null;
      flash('Lezione eliminata', 'success',
        canUndo ? { action: {
          label: 'Annulla',
          fn: async () => {
            try {
              const r = await api.post('/api/schedule/lesson', {
                class_name: snap.class_name,
                teacher_name: snap.teacher_name,
                subject: snap.subject ?? null,
                classroom_name: snap.classroom_name ?? null,
                day: snap.day, hour: snap.hour,
                on_conflict: 'dry_run',
                cotaught_with: snap.cotaught_with
                  ? String(snap.cotaught_with).split(',').filter(Boolean)
                  : [],
              });
              await loadCalendar();
              await refreshDataset();
              if (r && r.conflict) {
                flash('Ripristino non riuscito: lo slot e di nuovo occupato.',
                      'warning');
              } else {
                flash('Eliminazione annullata', 'success');
              }
            } catch (e) {
              flash('Annullamento fallito: ' + (e.message || e), 'error');
            }
          },
        } } : undefined);
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }
  async function setLessonRoom(lessonId, roomName) {
    try {
      const url = '/api/schedule/lesson/' + lessonId + '/classroom'
        + (roomName ? '?classroom_name=' + encodeURIComponent(roomName) : '');
      await api.put(url);
      flash('Aula aggiornata', 'success');
      // Refresh local state without closing the modal so the user
      // sees the new value reflected.
      await loadCalendar();
      // Re-bind actionLesson to the (possibly modified) row.
      if (actionLesson) {
        const fresh = lessons.find((l) => l.id === actionLesson.id);
        if (fresh) actionLesson = fresh;
      }
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  // ---- Drag-drop / pool drop -------------------------------------
  // Optimistically reposition a lesson in the local array so the drop
  // reads as instant. `lessons` is reassigned (not mutated) so Svelte
  // re-renders and WeeklyCalendarView recomputes its soft-conflict
  // overlays from the new positions. Returns nothing; pair every
  // optimistic move with a revert on rejection.
  function _optimisticMove(lessonId, day, hour) {
    lessons = lessons.map(
      (l) => (l.id === lessonId ? { ...l, day, hour } : l));
  }

  async function onLessonMove(lessonId, day, hour) {
    // Remember the origin slot so an accepted move can be undone and a
    // rejected one reverted.
    const _src0 = lessons.find((l) => l.id === lessonId);
    const _oldDay = _src0?.day, _oldHour = _src0?.hour;
    // Optimistic: show the lesson at the target slot immediately. The
    // reconciling loadCalendar() on the accept path (and the revert on
    // the reject paths) keep the array truthful, so a wrong guess is
    // self-correcting -- worst case matches the old full-reload flow.
    _optimisticMove(lessonId, day, hour);
    try {
      const r = await api.post('/api/lessons/' + lessonId + '/move',
                                { day, hour });
      if (r && r.accepted === false && r.conflicts) {
        // Snap back before prompting the "Sostituisci o annulla" modal.
        _optimisticMove(lessonId, _oldDay, _oldHour);
        const src = lessons.find((l) => l.id === lessonId);
        const head = src
          ? `${src.class_name} / ${src.teacher_name}`
          : `lezione #${lessonId}`;
        dropConflict = {
          kind: 'move',
          sourceId: lessonId,
          day, hour,
          subject: `${head} -> ${DAY_NAMES_IT[day]} ${hour}:00`,
          details: r.conflicts,
        };
        return;
      }
      if (r && r.accepted === false) {
        _optimisticMove(lessonId, _oldDay, _oldHour);  // snap back
        flash('Mossa rifiutata: ' + (r.reason || 'vincolo violato'), 'error');
      } else {
        // Offer UNDO only for a clean move (not when a room was cleared --
        // moving back would not un-clear it, so the undo would be partial).
        const canUndo = r && r.accepted && !r.room_cleared
          && _oldDay != null && _oldHour != null
          && !(_oldDay === day && _oldHour === hour);
        flash(r?.reason || 'Lezione spostata', 'success',
          canUndo ? { action: {
            label: 'Annulla',
            fn: async () => {
              try {
                await api.post('/api/lessons/' + lessonId + '/move',
                                { day: _oldDay, hour: _oldHour });
                await loadCalendar();
                await refreshDataset();
                flash('Spostamento annullato', 'success');
              } catch (e) {
                flash('Annullamento fallito: ' + (e.message || e), 'error');
              }
            },
          } } : undefined);
        if (r && r.accepted && r.room_cleared) {
          roomClearedNotice = {
            room: r.cleared_room, day, hour,
            class_name: r.class_name || '', teacher: r.teacher_name || '',
            subject: r.subject || '',
          };
        }
      }
      await loadCalendar();
      await refreshDataset();
    } catch (e) {
      _optimisticMove(lessonId, _oldDay, _oldHour);  // network error: snap back
      flash('Errore: ' + e.message, 'error');
    }
  }
  async function onUnscheduledDrop(unschedId, day, hour) {
    try {
      const r = await api.post(
        '/api/lessons/unscheduled/' + unschedId + '/reschedule',
        { day, hour });
      if (r && r.accepted === false && r.conflicts) {
        const src = unscheduled.find((u) => u.id === unschedId);
        dropConflict = {
          kind: 'reschedule',
          sourceId: unschedId,
          day, hour,
          subject: src
            ? `${src.class_name} / ${src.teacher_name} -> `
              + `${DAY_NAMES_IT[day]} ${hour}:00`
            : `${DAY_NAMES_IT[day]} ${hour}:00`,
          details: r.conflicts,
        };
        return;
      }
      flash('Lezione ripiazzata', 'success');
      await loadCalendar();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }
  // "Sostituisci": DELETE every conflicting lesson, then retry the
  // original move/reschedule POST. The backend's _resolve_conflicts
  // is only wired to /api/schedule/lesson; for our drop flow the
  // frontend orchestrates the deletion+retry to keep both endpoints
  // free of resolution-strategy plumbing.
  async function resolveDropConflict() {
    if (!dropConflict) return;
    const dc = dropConflict;
    dropConflict = null;
    const ids = new Set();
    for (const bucket of ['teacher_busy', 'class_busy', 'room_busy']) {
      for (const r of (dc.details?.[bucket] || [])) {
        if (r.lesson_id != null) ids.add(r.lesson_id);
      }
    }
    try {
      if (ids.size) {
        // One round-trip instead of N serial DELETEs (each of which used
        // to also trigger a full timetable reload).
        await api.post('/api/lessons/bulk-delete', { ids: [...ids] });
      }
      if (dc.kind === 'move') {
        await onLessonMove(dc.sourceId, dc.day, dc.hour);
      } else {
        await onUnscheduledDrop(dc.sourceId, dc.day, dc.hour);
      }
    } catch (e) {
      flash('Errore risoluzione conflitto: ' + e.message, 'error');
      await loadCalendar();
      await refreshDataset();
    }
  }
  function cancelDropConflict() { dropConflict = null; }
  function onSlotClick(day, hour) {
    if (pendingMoveLessonId) {
      const id = pendingMoveLessonId;
      pendingMoveLessonId = null;
      onLessonMove(id, day, hour);
      return;
    }
    addLessonMode = view === 'class' ? 'class'
      : view === 'teacher' ? 'teacher'
      : view === 'room' ? 'room' : 'slot';
    addLessonDay = day;
    addLessonHour = hour;
    addLessonPreset = view === 'class' && entityId ? { class_name: entityId }
      : view === 'teacher' && entityId ? { teacher_name: entityId }
      : view === 'room' && entityId ? { classroom_name: entityId }
      : {};
    addLessonOpen = true;
  }

  // ---- Solutions / exports ---------------------------------------
  async function activateSolution(id) {
    try {
      await api.post('/api/schedule/solutions/' + id + '/activate');
      flash('Soluzione attivata', 'success');
      solutions = await api.get('/api/schedule/solutions');
      await loadCalendar();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }
  async function delSolution(id) {
    if (!await confirmDialog('Eliminare questa soluzione?')) return;
    try {
      await api.del('/api/schedule/solutions/' + id);
      solutions = await api.get('/api/schedule/solutions');
      await loadCalendar();
    } catch (e) { flash(e.message, 'error'); }
  }

  // ---- Legacy fallback ------------------------------------------
  async function loadLegacy() {
    try {
      classData = await api.get('/api/schedule/by-class');
      if (classData?.classes?.length) selectedClass = classData.classes[0];
      teacherData = await api.get('/api/schedule/by-teacher');
      if (teacherData?.teachers?.length)
        selectedTeacher = teacherData.teachers[0];
      roomData = await api.get('/api/schedule/by-room');
      if (roomData?.rooms?.length && !selectedRoom)
        selectedRoom = roomData.rooms[0];
    } catch (e) {
      flash('Nessuna soluzione attiva: ' + e.message, 'error');
    }
  }
  function loadSlot() {
    api.get(`/api/schedule/by-slot?day=${slotDay}&hour=${slotHour}`)
      .then((d) => slotData = d)
      .catch((e) => flash(e.message, 'error'));
  }
</script>

<div data-testid="schedule-page">
  <PageHero title="Orario"
            description="L'orario della soluzione attiva. Trascina una lezione per spostarla: i conflitti vengono segnalati prima di salvare. Le lezioni svincolate restano nel pool a destra finche' non le ripiazzi.">
    <svelte:fragment slot="chips">
      {#if !legacyMode && summary}
        <span class="text-[11.5px] text-ink-500" data-testid="schedule-obj-value">
          <span class="eyebrow mr-1">obj</span><span class="num">{summary.obj_value}</span>
          {#if humanMetricsLine(summary.metrics)}
            <span class="text-ink-300 mx-1">·</span>{humanMetricsLine(summary.metrics)}
          {/if}
        </span>
      {:else if legacyMode && classData}
        <span class="text-[11.5px] text-ink-500" data-testid="schedule-obj-value">
          <span class="eyebrow mr-1">obj</span><span class="num">{classData.obj_value}</span>
          {#if humanMetricsLine(classData.metrics)}
            <span class="text-ink-300 mx-1">·</span>{humanMetricsLine(classData.metrics)}
          {/if}
        </span>
      {/if}
      {#if !legacyMode && lessons.length}
        <span class="pill-green"><span class="num">{lessons.length}</span> lezioni</span>
        {#if unscheduled.length}
          <span class="pill-amber"><span class="num">{unscheduled.length}</span> svincolate</span>
        {/if}
      {/if}
    </svelte:fragment>

    <svelte:fragment slot="actions">
      <a class="btn-primary"
         href={downloadUrl('/api/schedule/export/xlsx-classes')}
         data-testid="schedule-export-xlsx-classes">xlsx classi</a>
      <a class="btn"
         href={downloadUrl('/api/schedule/export/xlsx-teachers')}
         data-testid="schedule-export-xlsx-teachers">xlsx docenti</a>
      <a class="btn"
         href={downloadUrl('/api/schedule/export/pdf-classes')}
         data-testid="schedule-export-pdf-classes">pdf classi</a>
      <a class="btn"
         href={downloadUrl('/api/schedule/export/pdf-teachers')}
         data-testid="schedule-export-pdf-teachers">pdf docenti</a>
      {#if !legacyMode}
        <a class="btn" href="?legacy=true"
           data-testid="schedule-legacy-link">vista legacy</a>
      {:else}
        <a class="btn" href="/schedule"
           data-testid="schedule-calendar-link">vista calendario</a>
      {/if}
    </svelte:fragment>
  </PageHero>

  <div class="space-y-4">

  {#if legacyMode}
    <!-- The legacy 6x6 matrix UI is intentionally minimal here: it
         exists as a safety net only. Most users see the calendar. -->
    <div class="card p-4">
      <p class="text-sm text-ink-500 mb-3">
        Vista legacy (matrice 6x6). La nuova vista calendario e
        disponibile rimuovendo <code>?legacy=true</code> dall'URL.
      </p>
      {#if classData}
        <div class="flex gap-2 mb-2">
          <select bind:value={selectedClass}
                  class="px-2 py-1 rounded border border-ink-200">
            {#each classData.classes as c}<option>{c}</option>{/each}
          </select>
        </div>
        {#if selectedClass && classData.grid[selectedClass]}
          <div class="overflow-auto">
            <table class="tbl text-xs">
              <thead><tr>
                <th></th>
                {#each DAYS as d}<th>{DAY_NAMES_IT[d]}</th>{/each}
              </tr></thead>
              <tbody>
                {#each HOURS as h}
                  <tr>
                    <td>{h}:00</td>
                    {#each DAYS as d}
                      {@const cell = classData.grid[selectedClass][d][h]}
                      <td class="p-1">
                        {#if cell}
                          <div class="font-semibold">{cell.subjects.join('+')}</div>
                          <div class="text-[10px] text-ink-500">{cell.teachers.join(' + ')}</div>
                        {:else}-{/if}
                      </td>
                    {/each}
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      {/if}
    </div>
  {:else}
    {#if lessons.length === 0}
      <div class="card p-6 text-center text-ink-500"
           data-testid="schedule-empty-state">
        Nessuna soluzione attiva. Vai al
        <a class="text-accent-500 underline" href="/optimize">Workflow</a>
        e lancia almeno la Phase B, oppure importa un pickle dalla
        <a class="text-accent-500 underline" href="/">Dashboard</a>.
      </div>
    {/if}

    <div class="card px-3.5 py-2.5 flex items-center gap-3 flex-wrap"
         data-testid="schedule-view-bar">
      <span class="eyebrow">Vista</span>
      <div class="flex gap-1">
        <button class="btn !text-xs"
                class:bg-ink-100={view === 'global'}
                on:click={() => onSelectView('global')}
                data-testid="schedule-view-global">Globale</button>
        <button class="btn !text-xs"
                class:bg-ink-100={view === 'class'}
                on:click={() => onSelectView('class')}
                data-testid="schedule-view-classes">Per classe</button>
        <button class="btn !text-xs"
                class:bg-ink-100={view === 'teacher'}
                on:click={() => onSelectView('teacher')}
                data-testid="schedule-view-teachers">Per docente</button>
        <button class="btn !text-xs"
                class:bg-ink-100={view === 'room'}
                on:click={() => onSelectView('room')}
                data-testid="schedule-view-rooms">Per aula</button>
      </div>
      {#if view !== 'global'}
        <div class="flex items-center gap-2 ml-2">
          <input type="text" placeholder="cerca..."
                 bind:value={entityFilter}
                 list="schedule-entity-list"
                 on:input={() => commitEntitySearch(true)}
                 on:change={() => commitEntitySearch(false)}
                 class="px-2 py-1 rounded border border-ink-200 text-sm"
                 data-testid="schedule-entity-filter"/>
          <datalist id="schedule-entity-list">
            {#each filteredEntities as n}<option value={n}></option>{/each}
          </datalist>
          <select bind:value={entityId}
                  class="px-2 py-1 rounded border border-ink-200 text-sm"
                  data-testid="schedule-entity-select">
            {#each filteredEntities as n}<option value={n}>{n}</option>{/each}
          </select>
        </div>
      {/if}
      {#if pendingMoveLessonId}
        <span class="ml-auto px-2 py-1 rounded bg-amber-100 border border-amber-300 text-xs"
              data-testid="schedule-pending-move">
          Modalita sposta -- click su uno slot vuoto per confermare
          <button class="ml-2 underline"
                  on:click={() => (pendingMoveLessonId = null)}>annulla</button>
        </span>
      {/if}
    </div>

    {#if lessons.length > 0 || unscheduled.length > 0}
      <div class="card p-2"
           data-testid="schedule-calendar-card">
        {#if !helpDismissed}
          <div class="mb-2 flex items-start gap-2 rounded bg-accent-50 border border-accent-200 px-3 py-2 text-xs text-ink-600"
               data-testid="schedule-help">
            <span class="flex-1">
              <strong>Come si usa:</strong>
              trascina una lezione su uno slot vuoto per spostarla ·
              click su una lezione per le azioni (sposta, elimina, svincola) ·
              trascina dal pool a destra per ripiazzare una lezione svincolata.
            </span>
            <button type="button" class="text-ink-400 hover:text-ink-600"
                    on:click={dismissHelp} aria-label="Nascondi aiuto">✕</button>
          </div>
        {/if}
        <WeeklyCalendarView mode="schedule"
                            title={calendarTitle}
                            config={workingHoursConfig}
                            {lessons}
                            unscheduled_lessons={unscheduled}
                            filter_by={calendarFilter}
                            on_lesson_click={onLessonClick}
                            on_slot_click={onSlotClick}
                            on_lesson_move={onLessonMove}
                            on_unscheduled_drop={onUnscheduledDrop}/>
      </div>
    {/if}
  {/if}
  </div>

  <!-- Lesson-actions modal: shown after a lesson click (calendar mode) -->
  <Modal open={actionLesson !== null && actionMode === 'menu'}
         title="Azioni lezione"
         onClose={closeActions}>
    {#if actionLesson}
      <div class="space-y-3" data-testid="schedule-actions-modal">
        <div class="text-sm">
          <div><strong>Classe:</strong> {actionLesson.class_name}</div>
          <div><strong>Docente:</strong> {actionLesson.teacher_name}</div>
          <div><strong>Materia:</strong> {actionLesson.subject || '-'}</div>
          <div><strong>Aula:</strong> {actionLesson.classroom_name || '-'}</div>
          <div><strong>Slot:</strong> {DAY_NAMES_IT[actionLesson.day]}
            {actionLesson.hour}:00</div>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <button class="btn"
                  on:click={startEdit}
                  data-testid="schedule-action-edit">Modifica</button>
          <button class="btn"
                  on:click={startMove}
                  data-testid="schedule-action-move">Sposta</button>
          <button class="btn"
                  on:click={svincolaLesson}
                  data-testid="schedule-action-unschedule">Svincola</button>
          <button class="btn !bg-rose-50 !border-rose-200 !text-rose-700"
                  on:click={eliminaLesson}
                  data-testid="schedule-action-delete">Elimina</button>
        </div>
      </div>
    {/if}
  </Modal>

  <Modal open={actionLesson !== null && actionMode === 'edit'}
         title="Modifica aula"
         onClose={closeActions}>
    {#if actionLesson}
      <div class="space-y-3" data-testid="schedule-edit-modal">
        <div class="text-sm">
          {actionLesson.class_name} -- {actionLesson.subject || ''}
          ({actionLesson.teacher_name}) @
          {DAY_NAMES_IT[actionLesson.day]} {actionLesson.hour}:00
        </div>
        <div class="field">
          <label for="schedule-edit-room">Aula</label>
          <RoomDropdown lessonId={actionLesson.id}
                        currentRoom={actionLesson.classroom_name}
                        {allRooms}
                        isBusy={() => false}
                        onChange={setLessonRoom}/>
        </div>
        <div class="flex justify-end pt-3 border-t border-ink-100">
          <button class="btn" on:click={closeActions}
                  data-testid="schedule-edit-close">Chiudi</button>
        </div>
      </div>
    {/if}
  </Modal>

  <RoomClearedNoticeModal notice={roomClearedNotice}
                          onClose={() => (roomClearedNotice = null)}/>

  <AddLessonModal bind:open={addLessonOpen}
                  mode={addLessonMode}
                  day={addLessonDay}
                  hour={addLessonHour}
                  preset={addLessonPreset}
                  teachers={teachersWithSubjects}
                  classes={classNames}
                  rooms={allRoomsFull.length ? allRoomsFull : allRooms}
                  {classesMeta}
                  onClose={() => (addLessonOpen = false)}
                  onCreated={async () => { await loadCalendar();
                    await refreshDataset(); }}/>

  <SolutionsTable {solutions}
                  onActivate={activateSolution}
                  onDelete={delSolution}/>

  <ScheduleConflictModal open={dropConflict !== null}
                         title="Slot di destinazione occupato"
                         subject={dropConflict?.subject || ''}
                         details={dropConflict?.details
                                  || { teacher_busy: [],
                                       class_busy: [],
                                       room_busy: [] }}
                         showUnbind={false}
                         deleteLabel="Sostituisci"
                         onCancel={cancelDropConflict}
                         onResolve={resolveDropConflict}/>
</div>

<style>
  /* Tighten the gap between the calendar card and the surrounding
     spacing so the calendar can use the full width. */
  :global(.weekly-calendar) { padding: 4px; }
</style>
