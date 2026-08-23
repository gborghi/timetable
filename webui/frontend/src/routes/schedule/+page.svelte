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
  import { writable } from 'svelte/store';
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
  // Vista e conflitto in store: in Svelte 5 le assegnazioni a `let`
  // dentro handler/async a volte non invalidano il template (e
  // history.replaceState faceva remountare la pagina su uno stato
  // vecchio). Lo store aggiorna sempre i sottoscrittori.
  const VIEW_VALUES = ['global', 'class', 'teacher', 'room'];
  const viewStore = writable('global');
  const entityIdStore = writable('');
  const dropConflictStore = writable(null);
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
  // dropConflict vive in dropConflictStore.
  // { kind: 'move' | 'reschedule', sourceId, day, hour,
  //   subject, details: { teacher_busy, class_busy, room_busy } }
  // While Sostituisci is in flight, ignore a second "slot occupato"
  // so the modal cannot reopen on the retry /move.
  let dropResolveInFlight = false;
  let ignoreConflictsUntil = 0;
  let conflictEpoch = 0;

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

  $: entitySource = $viewStore === 'class' ? classNames
    : $viewStore === 'teacher' ? teacherNames
    : $viewStore === 'room' ? roomNames : [];
  $: filteredEntities = entitySource.filter(
    (n) => !entityFilter || n.toLowerCase().includes(entityFilter.toLowerCase()));

  $: calendarFilter = $viewStore === 'global'
    ? { type: null, id: null }
    : { type: $viewStore, id: $entityIdStore || null };

  // Filter here (not only inside WeeklyCalendarView): Svelte 5
  // `export let` + `$:` on the child can keep the previous lesson
  // list after the title has already switched.
  $: visibleLessons = (() => {
    const t = calendarFilter.type;
    const id = calendarFilter.id;
    if (!t || !id) return lessons;
    return lessons.filter((l) => {
      if (t === 'class') return l.class_name === id;
      if (t === 'teacher') return l.teacher_name === id;
      if (t === 'room') return l.classroom_name === id;
      return true;
    });
  })();

  $: calendarTitle = $viewStore === 'global'
    ? 'Orario globale'
    : $viewStore === 'class' ? `Orario classe ${$entityIdStore || '...'}`
    : $viewStore === 'teacher' ? `Orario docente ${$entityIdStore || '...'}`
    : `Orario aula ${$entityIdStore || '...'}`;

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
    ignoreConflictsUntil = 0;
    dropResolveInFlight = false;
    dropConflictStore.set(null);
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
      if ($viewStore !== 'global' && !$entityIdStore) {
        entityIdStore.set(defaultEntityFor($viewStore));
      }
    } catch (e) {
      flash('Errore caricamento orario: ' + e.message, 'error');
      lessons = [];
      unscheduled = [];
    }
  }

  function defaultEntityFor(nextView) {
    if (nextView === 'class') return classNames[0] || '';
    if (nextView === 'teacher') return teacherNames[0] || '';
    if (nextView === 'room') return roomNames[0] || '';
    return '';
  }

  function selectView(nextView) {
    const next = VIEW_VALUES.includes(nextView) ? nextView : 'global';
    entityFilter = '';
    viewStore.set(next);
    entityIdStore.set(next === 'global' ? '' : defaultEntityFor(next));
  }

  function onViewBarClick(ev) {
    const el = ev.target;
    const btn = (el && el.nodeType === 1 ? el : el?.parentElement)
      ?.closest?.('[data-view]');
    if (!btn) return;
    ev.preventDefault();
    selectView(btn.getAttribute('data-view'));
  }

  function onEntityIdChange(nextId) {
    entityIdStore.set(nextId || '');
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
    if (exact) { if (exact !== $entityIdStore) onEntityIdChange(exact); return; }
    if (!strict && filteredEntities.length === 1) {
      onEntityIdChange(filteredEntities[0]);
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
  async function togglePin() {
    if (!actionLesson) return;
    const next = !actionLesson.locked;
    try {
      // Per-slot pin (finding 26): POST /api/schedule/lessons/{id}/pin.
      // This is the lesson lock (Lesson.locked = immovable hour), NOT the
      // cattedra lock on /assignments (Assignment.locked = confirmed WHO).
      await api.post('/api/schedule/lessons/' + actionLesson.id + '/pin'
                     + '?locked=' + next);
      flash(next ? 'Lezione bloccata in questo slot'
                 : 'Lezione sbloccata', 'success');
      closeActions();
      await loadCalendar();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
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
              } else if (r && r.hard_violation) {
                flash('Ripristino non riuscito: ' + (r.reason || 'vincolo HARD'),
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

  const movingLessonIds = new Set();
  async function onLessonMove(lessonId, day, hour) {
    // A synthetic Cypress drag can deliver drop twice; a second in-flight
    // /move would reopen the conflict modal after Sostituisci closed it.
    if (movingLessonIds.has(lessonId)) return;
    movingLessonIds.add(lessonId);
    const moveEpoch = conflictEpoch;
    try {
    // Remember the origin slot so an accepted move can be undone and a
    // rejected one reverted.
    const _src0 = lessons.find((l) => l.id === lessonId);
    const _oldDay = _src0?.day, _oldHour = _src0?.hour;
    // Optimistic: show the lesson at the target slot immediately. The
    // reconciling loadCalendar() on the accept path (and the revert on
    // the reject paths) keep the array truthful, so a wrong guess is
    // self-correcting -- worst case matches the old full-reload flow.
    _optimisticMove(lessonId, day, hour);
    let _didUnlock = false;
    try {
      let r = await api.post('/api/lessons/' + lessonId + '/move',
                                { day, hour });
      if (r && r.accepted === false && r.needs_unlock) {
        // Pinned lesson: snap back and ASK before unpinning. A pin is the
        // school's own earlier choice, so only an explicit confirmation
        // revokes it -- unlike a HARD refusal, which has no override.
        _optimisticMove(lessonId, _oldDay, _oldHour);
        const ok = await confirmDialog(
          'Questa lezione risulta bloccata in questo slot. '
          + 'Spostarla comporta lo sblocco. Procedere?',
          { title: 'Lezione bloccata', confirmLabel: 'Sblocca e sposta',
            danger: false });
        if (!ok) return;
        _optimisticMove(lessonId, day, hour);
        _didUnlock = true;
        r = await api.post('/api/lessons/' + lessonId + '/move',
                            { day, hour, unlock: true });
      }
      if (r && r.accepted === false && r.conflicts) {
        // Snap back before prompting the "Sostituisci o annulla" modal.
        _optimisticMove(lessonId, _oldDay, _oldHour);
        if (dropResolveInFlight || $dropConflictStore
            || Date.now() < ignoreConflictsUntil
            || moveEpoch !== conflictEpoch) {
          flash('Mossa rifiutata: ' + (r.reason || 'vincolo violato'), 'error');
          return;
        }
        const src = lessons.find((l) => l.id === lessonId);
        const head = src
          ? `${src.class_name} / ${src.teacher_name}`
          : `lezione #${lessonId}`;
        dropConflictStore.set({
          kind: 'move',
          sourceId: lessonId,
          day, hour,
          subject: `${head} -> ${DAY_NAMES_IT[day]} ${hour}:00`,
          details: r.conflicts,
          swapWith: r.swap_with ?? null,
          originDay: _oldDay,
          originHour: _oldHour,
        });
        // Hold the in-flight lock until the modal closes, otherwise a
        // second synthetic drop can POST /move again and reopen it.
        return 'conflict';
      }
      if (r && r.accepted === false) {
        _optimisticMove(lessonId, _oldDay, _oldHour);  // snap back
        flash('Mossa rifiutata: ' + (r.reason || 'vincolo violato'), 'error');
      } else {
        // Offer UNDO only for a clean move (not when a room was cleared,
        // nor when we unpinned to make the move -- moving back would
        // restore neither, so the undo would be partial either way).
        const canUndo = r && r.accepted && !r.room_cleared && !_didUnlock
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
    } finally {
      if (!$dropConflictStore) movingLessonIds.delete(lessonId);
    }
  }
  async function onUnscheduledDrop(unschedId, day, hour) {
    try {
      const r = await api.post(
        '/api/lessons/unscheduled/' + unschedId + '/reschedule',
        { day, hour });
      if (r && r.accepted === false) {
        if (r.conflicts) {
          if (dropResolveInFlight || Date.now() < ignoreConflictsUntil) {
            flash(r.reason || 'Spostamento rifiutato', 'error');
            return;
          }
          const src = unscheduled.find((u) => u.id === unschedId);
          dropConflictStore.set({
            kind: 'reschedule',
            sourceId: unschedId,
            day, hour,
            subject: src
              ? `${src.class_name} / ${src.teacher_name} -> `
                + `${DAY_NAMES_IT[day]} ${hour}:00`
              : `${DAY_NAMES_IT[day]} ${hour}:00`,
            details: r.conflicts,
          });
          return;
        }
        // No `conflicts` payload means the slot was free but the HARD
        // gate refused it (teacher unavailable, hole, logical rule).
        // Nothing to resolve -- just say why. Reporting success here
        // told the user the lesson had been placed when it had not.
        flash(r.reason || 'Spostamento rifiutato', 'error');
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
  async function retryAfterReplace(kind, sourceId, day, hour) {
    // Dopo Sostituisci gli occupanti sono gia' cancellati. Un secondo
    // rifiuto HARD (disponibilita', buco, vincolo logico) non e' piu'
    // "slot occupato": mostriamo il motivo e NON riapriamo la stessa
    // modale, altrimenti Cypress (e l'utente) restano chiusi in un
    // loop Sostituisci -> retry -> conflitto.
    try {
      if (kind === 'move') {
        const r = await api.post('/api/lessons/' + sourceId + '/move',
                                 { day, hour });
        if (r && r.accepted === false) {
          flash('Mossa rifiutata: ' + (r.reason || 'vincolo violato'), 'error');
        } else {
          flash(r?.reason || 'Lezione spostata', 'success');
          if (r && r.accepted && r.room_cleared) {
            roomClearedNotice = {
              room: r.cleared_room, day, hour,
              class_name: r.class_name || '', teacher: r.teacher_name || '',
              subject: r.subject || '',
            };
          }
        }
      } else {
        const r = await api.post(
          '/api/lessons/unscheduled/' + sourceId + '/reschedule',
          { day, hour });
        if (r && r.accepted === false) {
          flash(r.reason || 'Spostamento rifiutato', 'error');
        } else {
          flash('Lezione ripiazzata', 'success');
        }
      }
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
    await loadCalendar();
    await refreshDataset();
  }

  async function resolveDropSwap() {
    if (!$dropConflictStore || dropResolveInFlight) return;
    const dc = $dropConflictStore;
    if (dc.kind !== 'move' || dc.swapWith == null) return;
    conflictEpoch += 1;
    dropResolveInFlight = true;
    ignoreConflictsUntil = Date.now() + 30_000;
    dropConflictStore.set(null);
    try {
      const r = await api.post('/api/lessons/' + dc.sourceId + '/swap',
                               { other_id: dc.swapWith });
      if (r && r.accepted === false && r.needs_unlock) {
        const ok = await confirmDialog(
          'Una delle due lezioni e bloccata. Scambiarle le sblocca. Procedere?',
          { title: 'Lezione bloccata', confirmLabel: 'Sblocca e scambia',
            danger: false });
        if (!ok) {
          await loadCalendar();
          return;
        }
        const r2 = await api.post('/api/lessons/' + dc.sourceId + '/swap',
                                  { other_id: dc.swapWith, unlock: true });
        if (r2 && r2.accepted === false) {
          flash('Scambio rifiutato: ' + (r2.reason || 'vincolo violato'),
                'error');
        } else {
          flash(r2?.reason || 'Lezioni scambiate', 'success');
        }
      } else if (r && r.accepted === false) {
        flash('Scambio rifiutato: ' + (r.reason || 'vincolo violato'),
              'error');
      } else {
        const canUndo = r && r.accepted && !r.room_cleared
          && dc.originDay != null && dc.originHour != null;
        flash(r?.reason || 'Lezioni scambiate', 'success',
          canUndo ? { action: {
            label: 'Annulla',
            fn: async () => {
              try {
                await api.post('/api/lessons/' + dc.sourceId + '/swap',
                                { other_id: dc.swapWith });
                await loadCalendar();
                await refreshDataset();
                flash('Scambio annullato', 'success');
              } catch (e) {
                flash('Annullamento fallito: ' + (e.message || e), 'error');
              }
            },
          } } : undefined);
      }
      await loadCalendar();
      await refreshDataset();
    } catch (e) {
      flash('Errore scambio: ' + e.message, 'error');
      await loadCalendar();
      await refreshDataset();
    } finally {
      dropResolveInFlight = false;
      dropConflictStore.set(null);
      movingLessonIds.delete(dc.sourceId);
    }
  }

  async function resolveDropConflict(strategy) {
    if (strategy === 'swap') {
      await resolveDropSwap();
      return;
    }
    if (!$dropConflictStore || dropResolveInFlight) return;
    const dc = $dropConflictStore;
    conflictEpoch += 1;
    dropResolveInFlight = true;
    ignoreConflictsUntil = Date.now() + 30_000;
    dropConflictStore.set(null);
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
        let r = await api.post('/api/lessons/bulk-delete', { ids: [...ids] });
        if (r && r.needs_force) {
          // Some victims are pinned. The modal already marks them
          // '[bloccata]', but destroying a pin deserves the same
          // confirmation moving one gets.
          if (!await confirmDialog(r.reason + '\n\nProcedere?')) {
            await loadCalendar();
            return;
          }
          r = await api.post('/api/lessons/bulk-delete',
                             { ids: [...ids], force: true });
        }
      }
      await retryAfterReplace(dc.kind, dc.sourceId, dc.day, dc.hour);
    } catch (e) {
      flash('Errore risoluzione conflitto: ' + e.message, 'error');
      await loadCalendar();
      await refreshDataset();
    } finally {
      dropResolveInFlight = false;
      dropConflictStore.set(null);
      movingLessonIds.delete(dc.sourceId);
    }
  }
  function cancelDropConflict() {
    const id = $dropConflictStore?.sourceId;
    conflictEpoch += 1;
    dropConflictStore.set(null);
    ignoreConflictsUntil = Date.now() + 2000;
    if (id != null) movingLessonIds.delete(id);
  }
  function onSlotClick(day, hour) {
    if (pendingMoveLessonId) {
      const id = pendingMoveLessonId;
      pendingMoveLessonId = null;
      onLessonMove(id, day, hour);
      return;
    }
    addLessonMode = $viewStore === 'class' ? 'class'
      : $viewStore === 'teacher' ? 'teacher'
      : $viewStore === 'room' ? 'room' : 'slot';
    addLessonDay = day;
    addLessonHour = hour;
    addLessonPreset = $viewStore === 'class' && $entityIdStore
      ? { class_name: $entityIdStore }
      : $viewStore === 'teacher' && $entityIdStore
        ? { teacher_name: $entityIdStore }
      : $viewStore === 'room' && $entityIdStore
        ? { classroom_name: $entityIdStore }
      : {};
    addLessonOpen = true;
  }

  // ---- Solutions / exports ---------------------------------------
  async function activateSolution(id, force = false) {
    try {
      await api.post('/api/schedule/solutions/' + id + '/activate'
                     + (force ? '?force=true' : ''));
      flash(force ? 'Soluzione attivata (con riserva)' : 'Soluzione attivata',
            force ? 'warning' : 'success');
      solutions = await api.get('/api/schedule/solutions');
      await loadCalendar();
      await refreshDataset();
    } catch (e) {
      // 409 = the gate refused an incomplete/infeasible solution. It is
      // the school's timetable, so the school may overrule it -- but it
      // has to be told what it is overruling first.
      if (e.status === 409 && !force) {
        if (await confirmDialog(e.message + '\n\nAttivarla comunque?')) {
          await activateSolution(id, true);
        }
        return;
      }
      flash('Errore: ' + e.message, 'error');
    }
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
        e lancia almeno la Phase B, oppure importa uno snapshot SQLite
        dalla
        <a class="text-accent-500 underline" href="/">Dashboard</a>.
      </div>
    {/if}

    <div class="card px-3.5 py-2.5 flex flex-col gap-2"
         data-testid="schedule-view-bar"
         data-active-view={$viewStore}>
      <div class="flex items-center gap-3 flex-wrap">
      <span class="eyebrow">Vista</span>
      <div class="flex gap-1" aria-label="Vista orario"
           data-testid="schedule-view-buttons"
           on:click={onViewBarClick}>
        <button type="button" class="btn !text-xs"
                class:bg-ink-100={$viewStore === 'global'}
                aria-pressed={$viewStore === 'global'}
                data-view="global"
                data-testid="schedule-view-global">Globale</button>
        <button type="button" class="btn !text-xs"
                class:bg-ink-100={$viewStore === 'class'}
                aria-pressed={$viewStore === 'class'}
                data-view="class"
                data-testid="schedule-view-classes">Per classe</button>
        <button type="button" class="btn !text-xs"
                class:bg-ink-100={$viewStore === 'teacher'}
                aria-pressed={$viewStore === 'teacher'}
                data-view="teacher"
                data-testid="schedule-view-teachers">Per docente</button>
        <button type="button" class="btn !text-xs"
                class:bg-ink-100={$viewStore === 'room'}
                aria-pressed={$viewStore === 'room'}
                data-view="room"
                data-testid="schedule-view-rooms">Per aula</button>
      </div>
      {#if pendingMoveLessonId}
        <span class="ml-auto px-2 py-1 rounded bg-amber-100 border border-amber-300 text-xs"
              data-testid="schedule-pending-move">
          Modalita sposta -- click su uno slot vuoto per confermare
          <button class="ml-2 underline"
                  on:click={() => (pendingMoveLessonId = null)}>annulla</button>
        </span>
      {/if}
      </div>
      {#if $viewStore !== 'global'}
        <div class="flex items-center gap-2"
             data-testid="schedule-entity-controls">
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
          <select value={$entityIdStore}
                  on:change={(e) => onEntityIdChange(e.currentTarget.value)}
                  class="px-2 py-1 rounded border border-ink-200 text-sm"
                  data-testid="schedule-entity-select">
            {#each filteredEntities as n}<option value={n}>{n}</option>{/each}
          </select>
        </div>
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
        {#key `${$viewStore}:${$entityIdStore}`}
        <WeeklyCalendarView mode="schedule"
                            title={calendarTitle}
                            config={workingHoursConfig}
                            lessons={visibleLessons}
                            unscheduled_lessons={unscheduled}
                            filter_by={calendarFilter}
                            on_lesson_click={onLessonClick}
                            on_slot_click={onSlotClick}
                            on_lesson_move={onLessonMove}
                            on_unscheduled_drop={onUnscheduledDrop}/>
        {/key}
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
          {#if actionLesson.locked}
            <div class="text-amber-700" data-testid="schedule-action-pinned">
              <strong>🔒 Bloccata</strong> in questo slot (sopravvive a una
              rigenerazione)</div>
          {/if}
        </div>
        <div class="grid grid-cols-2 gap-2">
          <button class="btn"
                  on:click={startEdit}
                  data-testid="schedule-action-edit">Modifica</button>
          <button class="btn"
                  on:click={startMove}
                  data-testid="schedule-action-move">Sposta</button>
          <button class="btn"
                  class:!bg-amber-50={actionLesson.locked}
                  class:!border-amber-200={actionLesson.locked}
                  class:!text-amber-800={actionLesson.locked}
                  on:click={togglePin}
                  title="Fissa la lezione in questo slot: una rigenerazione la mantiene qui (diverso dal blocco della cattedra, che fissa CHI insegna ma lascia muovere le ore)"
                  data-testid="schedule-action-pin">
            {actionLesson.locked ? '🔓 Sblocca slot' : '🔒 Blocca slot'}</button>
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

  {#if $dropConflictStore}
  <ScheduleConflictModal open={true}
                         title="Slot di destinazione occupato"
                         subject={$dropConflictStore.subject || ''}
                         details={$dropConflictStore.details
                                  || { teacher_busy: [],
                                       class_busy: [],
                                       room_busy: [] }}
                         showUnbind={false}
                         showSwap={!!$dropConflictStore.swapWith
                                   && $dropConflictStore.kind === 'move'}
                         deleteLabel="Sostituisci"
                         onCancel={cancelDropConflict}
                         onResolve={resolveDropConflict}/>
  {/if}
</div>

<style>
  /* Tighten the gap between the calendar card and the surrounding
     spacing so the calendar can use the full width. */
  :global(.weekly-calendar) { padding: 4px; }
</style>
