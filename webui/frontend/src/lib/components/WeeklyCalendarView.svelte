<script>
  /**
   * Reusable calendar-grid view for slot-level constraints.
   *
   * Layout: a Google-Calendar-style weekly grid. The BACKGROUND is a
   * full hour grid (auto-fitted around the configured slot range,
   * default 07:00-19:00) drawn as faint dashed gridlines. Each cell
   * of the background is non-interactive (cursor: not-allowed) so
   * the user cannot accidentally set a constraint on an unconfigured
   * hour. The Tab Ore slots are rendered ON TOP of the background as
   * absolutely-positioned event blocks, with `top` and `height`
   * computed from the slot's start_time / end_time so a 90-minute
   * lab block is twice as tall as a 45-minute slot. Only the events
   * are clickable + colorable (free / soft / hard / preferred /
   * enforced). Days with fewer or shorter slots than others render
   * fewer / smaller events; the background grid is shared.
   *
   * Data shape:
   *   value = Array<{ day, hour, state, soft_penalty?, reason? }>
   * where `day` is the legacy_day_number (1..7) and `hour` is the
   * slot's legacy_hour_number (0..23) -- same convention as the
   * existing TeacherUnavailability / ClassUnavailability rows.
   *
   * Props:
   *   value     -- array of cell records (see above)
   *   onChange  -- callback(newValue)
   *   title     -- header text
   *   readonly  -- disable editing if true
   *   config    -- optional pre-fetched WorkingHoursConfigOut. If not
   *                supplied, the component fetches it on mount.
   *
   * Keybindings:
   *   H/P/E/D/A/N + click immediately sets the cell to the
   *   corresponding state, bypassing the click-cycle.
   *
   * Click-cycle (no key held):
   *   free -> soft -> hard -> preferred -> enforced -> free
   */
  import { onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import {
    workingHoursConfig,
    loadWorkingHoursConfig,
  } from '$lib/stores';
  import {
    heldKey,
    startKeyboardConstraintMode,
    shortcutToMatrixState,
  } from '../keyboardConstraintMode';
  import KeyboardConstraintLegend from './KeyboardConstraintLegend.svelte';
  import UnscheduledPool from './UnscheduledPool.svelte';
  import {
    PX_PER_HOUR,
    bgRangeFor,
    pxFromTime as _pxFromTime,
    pxDuration as _pxDuration,
    gridHeight as _gridHeight,
    pxToTime as _pxToTime,
    makeSlot as _makeSlot,
    reindexSlots as _reindexSlots,
    clampToOpenWindow as _clampOpen,
  } from '$lib/calendar_layout.mjs';
  import { offGridLessons } from '$lib/off_grid';

  export let value = [];
  export let onChange = (_v) => {};
  export let title = 'Disponibilita oraria';
  export let readonly = false;
  export let config = null;
  /** "view" (default): slots are clickable for setting a constraint
   * level on each (day, hour) cell -- the existing teachers / classes /
   * classrooms availability matrices.
   * "edit": slots are draggable rectangles the user creates,
   * resizes, moves and deletes to define the working-hours layout
   * itself (Tab Ore). The component manages its own slot list in
   * edit mode and emits ``onConfigEdit`` whenever the user commits
   * a change.
   * "schedule": each Lesson is rendered as a positioned event on its
   * (day, hour) slot. Events are draggable + clickable; configured
   * slots accept drops, non-configured slots reject them. An
   * unscheduled-pool sidebar lets the user re-place pool entries via
   * drag onto the calendar. */
  export let mode = 'view';
  /** Edit-mode callback. Called with a SHALLOW COPY of ``config``
   * whose ``days[*].slots`` reflect the user's edits. The parent is
   * expected to persist the new slots via the working-hours API.
   * Defaults to a no-op so the view-mode call sites don't have to
   * pass anything. */
  export let onConfigEdit = (_newConfig) => {};

  // ---- mode='schedule' props -----------------------------------
  /** Lesson rows for mode='schedule'. Shape:
   *   { id, day, hour, class_name, teacher_name, subject,
   *     classroom_name, ... } */
  export let lessons = [];
  /** Unscheduled-pool entries for the sidebar. Shape:
   *   { id, class_name, teacher_name, subject, classroom_name,
   *     original_day?, original_hour? } */
  export let unscheduled_lessons = [];
  /** Filter the displayed events. type: 'class'|'teacher'|'room'|null;
   *  id: the name to match against the corresponding field, or null. */
  export let filter_by = { type: null, id: null };
  /** Click handler for a lesson event. Receives the lesson dict. */
  export let on_lesson_click = (_l) => {};
  /** Click handler for an empty CONFIGURED slot. Receives (day,hour). */
  export let on_slot_click = (_d, _h) => {};
  /** Drag-drop handler: moves a lesson_id to (new_day, new_hour). */
  export let on_lesson_move = (_id, _d, _h) => {};
  /** Drag-drop handler: places a pool entry at (day, hour). */
  export let on_unscheduled_drop = (_unsched_id, _d, _h) => {};

  let _config = config;
  let loadingConfig = false;
  $: _config = config || _config;

  let kbCleanup;
  let hovering = false;
  // Reactively pick up the shared working-hours config when the
  // caller didn't pass an explicit `config` prop. Whenever /ore
  // saves changes it calls reloadWorkingHoursConfig() on the same
  // store, which propagates to every mounted WeeklyCalendarView
  // without a navigation reload.
  let _storeUnsub = null;
  onMount(async () => {
    kbCleanup = startKeyboardConstraintMode();
    if (!config) {
      _storeUnsub = workingHoursConfig.subscribe((v) => {
        if (v) _config = v;
      });
      if (!get(workingHoursConfig)) {
        try {
          loadingConfig = true;
          await loadWorkingHoursConfig();
        } catch {
          // Synthetic fallback so the component still renders if the
          // API is unreachable (offline / unit tests). Matches the
          // engine's legacy hardcoded layout.
          _config = {
            days: [
              { id: 1, code: 'MON', label: 'Lun', position: 0,
                legacy_day_number: 1, is_active: true,
                slots: _defaultSlots() },
              { id: 2, code: 'TUE', label: 'Mar', position: 1,
                legacy_day_number: 2, is_active: true,
                slots: _defaultSlots() },
              { id: 3, code: 'WED', label: 'Mer', position: 2,
                legacy_day_number: 3, is_active: true,
                slots: _defaultSlots() },
              { id: 4, code: 'THU', label: 'Gio', position: 3,
                legacy_day_number: 4, is_active: true,
                slots: _defaultSlots() },
              { id: 5, code: 'FRI', label: 'Ven', position: 4,
                legacy_day_number: 5, is_active: true,
                slots: _defaultSlots() },
              { id: 6, code: 'SAT', label: 'Sab', position: 5,
                legacy_day_number: 6, is_active: true,
                slots: _defaultSlots() },
            ],
            max_slots_per_day: 6, uniform_slot_count: true,
          };
        } finally {
          loadingConfig = false;
        }
      }
    }
  });
  onDestroy(() => {
    kbCleanup?.();
    _storeUnsub?.();
  });

  function _defaultSlots() {
    return Array.from({ length: 6 }, (_, i) => ({
      slot_index: i,
      start_time: `${String(8 + i).padStart(2, '0')}:00`,
      end_time:   `${String(9 + i).padStart(2, '0')}:00`,
      label: `${i + 1}ª ora`,
      legacy_hour_number: 8 + i,
    }));
  }

  let cells = Array.isArray(value) ? value.slice() : [];
  $: if (Array.isArray(value)) cells = value.slice();
  let drafts = {};

  $: activeDays = (_config?.days || []).filter((d) => d.is_active);
  $: maxSlots = _config?.max_slots_per_day || 0;

  // Calendar background range: a Google-Calendar-style grid that
  // shows ALL hours of a typical school day (07:00-19:00) as faint,
  // non-clickable gridlines. The configured Tab Ore slots are then
  // rendered ON TOP of this background as positioned, clickable
  // event blocks. Background auto-expands beyond 7-19 to cover any
  // slot that starts earlier or ends later (e.g. evening adult-
  // school slots). Pure layout helpers live in $lib/calendar_layout
  // so they can be unit-tested.
  $: bgRange = bgRangeFor(activeDays);
  $: bgHours = (() => {
    const out = [];
    for (let h = bgRange.lo; h <= bgRange.hi; h += 1) out.push(h);
    return out;
  })();
  $: gridHeightPx = _gridHeight(bgRange);

  function _key(d, h) { return d + '-' + h; }

  function _commit(newCells) {
    cells = newCells;
    onChange(newCells);
  }

  function _defaultPenaltyFor(state) {
    if (state === 'soft') return 100;
    if (state === 'preferred') return -100;
    return 0;
  }

  function _slotForCell(day, slot_index) {
    const d = activeDays.find((x) => x.legacy_day_number === day);
    if (!d) return null;
    return d.slots[slot_index] || null;
  }

  function setCell(day, hour, state, penalty) {
    const list = cells.filter((c) => !(c.day === day && c.hour === hour));
    if (state !== 'free') {
      let pen;
      if (state === 'soft' || state === 'preferred') {
        pen = (penalty === undefined || penalty === null
                  ? _defaultPenaltyFor(state) : Number(penalty));
        if (state === 'soft' && pen < 0) pen = Math.abs(pen);
        if (state === 'preferred' && pen > 0) pen = -pen;
      } else {
        pen = 0;
      }
      list.push({
        day, hour, state, soft_penalty: pen, reason: null,
      });
    }
    _commit(list);
    if (state !== 'soft' && state !== 'preferred') {
      delete drafts[_key(day, hour)];
    }
  }

  function nextState(cur) {
    if (cur === null) return 'soft';
    if (cur === 'soft') return 'hard';
    if (cur === 'hard') return 'preferred';
    if (cur === 'preferred') return 'enforced';
    return 'free';
  }

  function _targetState(d, h) {
    const shortcutState = shortcutToMatrixState(get(heldKey));
    if (shortcutState !== null) return shortcutState;
    const cur = cells.find((c) => c.day === d && c.hour === h) || null;
    return nextState(cur ? cur.state : null);
  }

  // Drag-paint state.
  let dragOriginKey = null;
  let dragMoved = false;
  let dragMode = null;
  let dragApplied = new Set();

  function onMouseDown(ev, d, h) {
    if (readonly || ev.button !== 0 || ev.shiftKey) return;
    dragOriginKey = _key(d, h);
    dragMoved = false;
    dragApplied = new Set();
  }

  function onMouseEnter(d, h) {
    if (readonly || dragOriginKey === null) return;
    const k = _key(d, h);
    if (k === dragOriginKey) return;
    if (!dragMoved) {
      dragMoved = true;
      const [d0, h0] = dragOriginKey.split('-').map(Number);
      dragMode = _targetState(d0, h0);
      setCell(d0, h0, dragMode);
      dragApplied.add(dragOriginKey);
    }
    if (!dragApplied.has(k)) {
      dragApplied.add(k);
      setCell(d, h, dragMode);
    }
  }

  function onMouseUp() {
    dragOriginKey = null;
    dragMode = null;
    // Edit-mode commit happens here too (handled below).
    _editMouseUp();
  }

  // ---------------------------------------------------------------
  // EDIT MODE: the user creates / resizes / moves / deletes slots
  // directly on the calendar. The component manages its own
  // ``editingDays`` state in edit mode (a deep copy of
  // ``_config.days``) and emits ``onConfigEdit(newConfig)`` whenever
  // a change commits. The parent is expected to persist via the
  // working-hours API.
  // ---------------------------------------------------------------
  const EDGE_PX = 6;          // resize handle thickness
  const SNAP_MIN = 15;        // snap drag positions to 15-min steps
  const MIN_DURATION_MIN = 15;

  let editingDays = null;     // null in view mode, [{ ...day }] in edit
  let selectedSel = null;     // { dayId, idx } currently selected slot
  let editDrag = null;        // active drag operation
  let editDragPreview = null; // {dayId, top, height, label} for hover
  let editPopover = null;     // {dayId, idx, start_time, end_time, label}
  // when set, an inline form replaces the slot body for that slot.

  $: if (mode === 'edit' && _config?.days && editingDays === null) {
    editingDays = _config.days.map(
      (d) => ({ ...d, slots: (d.slots || []).map((s) => ({ ...s })) }));
  }
  $: if (mode === 'view' && editingDays !== null) {
    editingDays = null;
    selectedSel = null;
    editDrag = null;
    editDragPreview = null;
  }
  $: editActiveDays = (editingDays || []).filter((d) => d.is_active);
  $: editBgRange = bgRangeFor(
    mode === 'edit' ? editActiveDays : activeDays);
  $: displayActiveDays = mode === 'edit' ? editActiveDays : activeDays;
  $: displayBgRange = mode === 'edit' ? editBgRange : bgRange;
  $: displayBgHours = (() => {
    const out = [];
    for (let h = displayBgRange.lo; h <= displayBgRange.hi; h += 1)
      out.push(h);
    return out;
  })();
  $: displayGridHeightPx = _gridHeight(displayBgRange);

  function _commitEditingDays(nextDays) {
    editingDays = nextDays;
    const newConfig = {
      ..._config,
      days: nextDays,
      max_slots_per_day: nextDays.reduce(
        (m, d) => d.is_active ? Math.max(m, d.slots.length) : m, 0),
      uniform_slot_count: (() => {
        const counts = nextDays.filter((d) => d.is_active)
                                .map((d) => d.slots.length);
        return counts.every((c) => c === counts[0]);
      })(),
    };
    onConfigEdit(newConfig);
  }

  function _yFromEvent(ev, dayColEl) {
    const rect = dayColEl.getBoundingClientRect();
    return Math.max(0, Math.min(displayGridHeightPx,
                                ev.clientY - rect.top));
  }

  function _setDragCursor(kind) {
    if (typeof document === 'undefined') return;
    document.body.classList.remove(
      'cal-edit-dragging-move', 'cal-edit-dragging-resize');
    if (kind === 'move' || kind === 'create') {
      document.body.classList.add('cal-edit-dragging-move');
    } else if (kind === 'resize-top' || kind === 'resize-bottom') {
      document.body.classList.add('cal-edit-dragging-resize');
    }
  }
  function _clearDragCursor() {
    if (typeof document === 'undefined') return;
    document.body.classList.remove(
      'cal-edit-dragging-move', 'cal-edit-dragging-resize');
  }

  function onEditDayMouseDown(ev, dayId, dayColEl) {
    if (mode !== 'edit' || readonly || ev.button !== 0) return;
    // Did we click on an existing slot? The slot's own mousedown
    // handler runs first (z-index higher) and sets editDrag, so
    // here we only handle clicks on the BACKGROUND.
    if (editDrag) return;
    const y = _yFromEvent(ev, dayColEl);
    const t = _pxToTime(y, displayBgRange, PX_PER_HOUR, SNAP_MIN);
    editDrag = {
      kind: 'create', dayId, dayColEl,
      anchorY: y, currentY: y, startTime: t,
    };
    selectedSel = null;
    _setDragCursor('create');
    ev.preventDefault();
  }

  function onEditSlotMouseDown(ev, dayId, idx, dayColEl, edge) {
    if (mode !== 'edit' || readonly || ev.button !== 0) return;
    ev.stopPropagation();
    selectedSel = { dayId, idx };
    const day = editingDays.find((d) => d.id === dayId);
    const slot = day?.slots[idx];
    if (!slot) return;
    const y = _yFromEvent(ev, dayColEl);
    editDrag = {
      kind: edge || 'move',
      dayId, idx, dayColEl,
      anchorY: y, currentY: y,
      original: { ...slot },
    };
    _setDragCursor(edge || 'move');
  }

  function onEditMouseMove(ev) {
    if (!editDrag) return;
    const y = _yFromEvent(ev, editDrag.dayColEl);
    editDrag = { ...editDrag, currentY: y };
    if (editDrag.kind === 'create') {
      const a = editDrag.anchorY;
      const top = Math.min(a, y);
      const height = Math.max(8, Math.abs(y - a));
      editDragPreview = {
        dayId: editDrag.dayId, top, height,
        label: `${_pxToTime(top, displayBgRange, PX_PER_HOUR, SNAP_MIN)}` +
               `-${_pxToTime(top + height, displayBgRange, PX_PER_HOUR, SNAP_MIN)}`,
      };
    } else if (editDrag.kind === 'move') {
      const dy = editDrag.currentY - editDrag.anchorY;
      const origTop = _pxFromTime(editDrag.original.start_time,
                                  displayBgRange);
      const origBot = _pxFromTime(editDrag.original.end_time,
                                  displayBgRange);
      const top = origTop + dy;
      const height = Math.max(8, origBot - origTop);
      editDragPreview = {
        dayId: editDrag.dayId, top, height,
        label: `${_pxToTime(top, displayBgRange, PX_PER_HOUR, SNAP_MIN)}` +
               `-${_pxToTime(top + height, displayBgRange, PX_PER_HOUR, SNAP_MIN)}`,
      };
    } else if (editDrag.kind === 'resize-top') {
      const dy = editDrag.currentY - editDrag.anchorY;
      const origTop = _pxFromTime(editDrag.original.start_time,
                                  displayBgRange);
      const origBot = _pxFromTime(editDrag.original.end_time,
                                  displayBgRange);
      const newTop = Math.min(origBot - 8, origTop + dy);
      const top = newTop;
      const height = Math.max(8, origBot - newTop);
      editDragPreview = {
        dayId: editDrag.dayId, top, height,
        label: `${_pxToTime(top, displayBgRange, PX_PER_HOUR, SNAP_MIN)}` +
               `-${_pxToTime(top + height, displayBgRange, PX_PER_HOUR, SNAP_MIN)}`,
      };
    } else if (editDrag.kind === 'resize-bottom') {
      const dy = editDrag.currentY - editDrag.anchorY;
      const origTop = _pxFromTime(editDrag.original.start_time,
                                  displayBgRange);
      const origBot = _pxFromTime(editDrag.original.end_time,
                                  displayBgRange);
      const newBot = Math.max(origTop + 8, origBot + dy);
      const top = origTop;
      const height = newBot - origTop;
      editDragPreview = {
        dayId: editDrag.dayId, top, height,
        label: `${_pxToTime(top, displayBgRange, PX_PER_HOUR, SNAP_MIN)}` +
               `-${_pxToTime(top + height, displayBgRange, PX_PER_HOUR, SNAP_MIN)}`,
      };
    }
  }

  function _editMouseUp() {
    if (!editDrag) return;
    const drag = editDrag;
    editDrag = null;
    editDragPreview = null;
    _clearDragCursor();
    if (mode !== 'edit') return;
    if (drag.kind === 'create') {
      const a = drag.anchorY;
      const b = drag.currentY;
      if (Math.abs(b - a) < 6) return;        // accidental click
      const top = Math.min(a, b);
      const bottom = Math.max(a, b);
      const start = _pxToTime(top, displayBgRange, PX_PER_HOUR, SNAP_MIN);
      const end = _pxToTime(bottom, displayBgRange, PX_PER_HOUR, SNAP_MIN);
      _editApplyCreate(drag.dayId, start, end);
    } else if (drag.kind === 'move') {
      const dy = drag.currentY - drag.anchorY;
      const origTop = _pxFromTime(drag.original.start_time,
                                    displayBgRange);
      const origBot = _pxFromTime(drag.original.end_time,
                                    displayBgRange);
      const newTop = origTop + dy;
      const newBot = origBot + dy;
      const start = _pxToTime(newTop, displayBgRange, PX_PER_HOUR,
                              SNAP_MIN);
      const end = _pxToTime(newBot, displayBgRange, PX_PER_HOUR,
                            SNAP_MIN);
      _editApplyResize(drag.dayId, drag.idx, start, end);
    } else if (drag.kind === 'resize-top') {
      const newTop = _pxFromTime(drag.original.start_time,
                                   displayBgRange) +
                     (drag.currentY - drag.anchorY);
      const start = _pxToTime(newTop, displayBgRange, PX_PER_HOUR,
                              SNAP_MIN);
      _editApplyResize(drag.dayId, drag.idx, start,
                       drag.original.end_time);
    } else if (drag.kind === 'resize-bottom') {
      const newBot = _pxFromTime(drag.original.end_time,
                                   displayBgRange) +
                     (drag.currentY - drag.anchorY);
      const end = _pxToTime(newBot, displayBgRange, PX_PER_HOUR,
                            SNAP_MIN);
      _editApplyResize(drag.dayId, drag.idx, drag.original.start_time,
                       end);
    }
  }

  function _editApplyCreate(dayId, start, end) {
    const days = editingDays.map((d) => ({
      ...d, slots: d.slots.map((s) => ({ ...s })),
    }));
    const day = days.find((dd) => dd.id === dayId);
    if (!day) return;
    const clamped = _clampOpen(start, end, day.slots);
    if (!clamped) return;
    day.slots.push(_makeSlot(clamped.start_time, clamped.end_time,
                              day.slots.length));
    day.slots = _reindexSlots(day.slots);
    _commitEditingDays(days);
  }

  function _editApplyResize(dayId, idx, start, end) {
    const days = editingDays.map((d) => ({
      ...d, slots: d.slots.map((s) => ({ ...s })),
    }));
    const day = days.find((dd) => dd.id === dayId);
    if (!day) return;
    const others = day.slots.filter((_, i) => i !== idx);
    const clamped = _clampOpen(start, end, others);
    if (!clamped) {
      // Drop the slot if its new dimensions collapsed to zero.
      day.slots = _reindexSlots(others);
    } else {
      day.slots[idx] = {
        ..._makeSlot(clamped.start_time, clamped.end_time, idx),
        // preserve user-edited label if present
        label: day.slots[idx].label,
      };
      day.slots = _reindexSlots(day.slots);
    }
    _commitEditingDays(days);
    // Re-derive selection: the slot may have a different idx after
    // re-indexing.
    const newIdx = day.slots.findIndex(
      (s) => s.start_time === (clamped?.start_time));
    selectedSel = newIdx >= 0 ? { dayId, idx: newIdx } : null;
  }

  function _editApplyDelete(dayId, idx) {
    const days = editingDays.map((d) => ({
      ...d, slots: d.slots.map((s) => ({ ...s })),
    }));
    const day = days.find((dd) => dd.id === dayId);
    if (!day) return;
    day.slots = _reindexSlots(day.slots.filter((_, i) => i !== idx));
    _commitEditingDays(days);
    selectedSel = null;
  }

  function onEditKeyDown(ev) {
    if (mode !== 'edit' || !selectedSel) return;
    if (ev.key === 'Escape') {
      selectedSel = null;
      editPopover = null;
    }
  }

  function _openEditPopover(dayId, idx) {
    const day = editingDays.find((d) => d.id === dayId);
    const slot = day?.slots[idx];
    if (!slot) return;
    selectedSel = { dayId, idx };
    editPopover = {
      dayId, idx,
      start_time: slot.start_time,
      end_time: slot.end_time,
      label: slot.label || '',
    };
  }

  function _applyEditPopover() {
    if (!editPopover) return;
    const { dayId, idx, start_time, end_time, label } = editPopover;
    if (!start_time || !end_time || start_time >= end_time) {
      editPopover = null;
      return;
    }
    const days = editingDays.map((d) => ({
      ...d, slots: d.slots.map((s) => ({ ...s })),
    }));
    const day = days.find((dd) => dd.id === dayId);
    if (!day || !day.slots[idx]) { editPopover = null; return; }
    const [h, m] = start_time.split(':').map(Number);
    day.slots[idx] = {
      ...day.slots[idx],
      start_time, end_time, label,
      legacy_hour_number: Number.isFinite(h) ? h : day.slots[idx].legacy_hour_number,
    };
    day.slots = _reindexSlots(
      [...day.slots].sort((a, b) =>
        a.start_time < b.start_time ? -1 : a.start_time > b.start_time ? 1 : 0));
    _commitEditingDays(days);
    editPopover = null;
  }

  // ---------------------------------------------------------------
  // SCHEDULE MODE: lessons rendered as positioned events on the
  // calendar; HTML5 drag-drop moves them across slots; an unscheduled
  // pool sidebar lets the user re-place pool rows. Soft-conflict
  // preview during drag highlights existing events that share the
  // teacher / class / room of the dragged one.
  // ---------------------------------------------------------------

  // Filter lessons according to filter_by (when set).
  $: filteredLessons = (() => {
    if (mode !== 'schedule' || !Array.isArray(lessons)) return [];
    const t = filter_by?.type, id = filter_by?.id;
    if (!t || !id) return lessons;
    return lessons.filter((l) => {
      if (t === 'class')   return l.class_name === id;
      if (t === 'teacher') return l.teacher_name === id;
      if (t === 'room')    return l.classroom_name === id;
      return true;
    });
  })();

  // Group filtered lessons by "day-hour" key so we can stack
  // co-teachings or class-merges in a single configured slot.
  $: lessonsBySlot = (() => {
    const out = new Map();
    for (const l of filteredLessons) {
      if (l.day == null || l.hour == null) continue;
      const k = l.day + '-' + l.hour;
      if (!out.has(k)) out.set(k, []);
      out.get(k).push(l);
    }
    return out;
  })();

  // Configured-slot lookup: which (day, hour) pairs have a slot
  // configured in Tab Ore? Used to gate drop targets.
  $: configuredSlots = (() => {
    const set = new Set();
    for (const d of activeDays) {
      for (const s of (d.slots || [])) {
        set.add(d.legacy_day_number + '-' + s.legacy_hour_number);
      }
    }
    return set;
  })();

  // Lessons placed on a (day, hour) that no longer maps to a configured
  // slot (e.g. Tab Ore dropped an hour that still had lessons). They have
  // no cell to render into, so surface them in a banner instead of
  // silently dropping them from the view.
  $: offGrid = mode === 'schedule'
    ? offGridLessons(filteredLessons, configuredSlots)
    : [];

  // Drag state.
  let dragSource = null;     // {kind:'lesson',lesson} or {kind:'unscheduled',entry}
  let dragHoverKey = null;   // "day-hour" being hovered while dragging

  // Compresenza popup: when a filtered-view slot holds >1 lesson (sostegno /
  // codocenza / shared gym) we render the MAIN lesson as one full cell and
  // the co-present ones behind a small button that opens this popup, instead
  // of splitting the cell into unreadable halves. Fixed-positioned so it is
  // never clipped by the calendar's horizontal overflow.
  let compresenzaPopup = null;   // { lst, title, x, y } | null

  // Conflict set: which "day-hour" keys would HARD-conflict if the
  // dragged lesson dropped there? Same teacher OR same class busy at
  // that slot (excluding the dragged lesson itself). We use the FULL
  // lessons array (not filteredLessons) because conflicts cross views.
  $: conflictKeys = (() => {
    if (mode !== 'schedule' || !dragSource) return new Set();
    const drag = dragSource.kind === 'lesson'
      ? dragSource.lesson
      : dragSource.entry;
    if (!drag) return new Set();
    const out = new Set();
    for (const l of (lessons || [])) {
      if (l.day == null || l.hour == null) continue;
      if (dragSource.kind === 'lesson' && l.id === drag.id) continue;
      if ((drag.teacher_name && l.teacher_name === drag.teacher_name) ||
          (drag.class_name && l.class_name === drag.class_name) ||
          (drag.classroom_name && drag.classroom_name === l.classroom_name)) {
        out.add(l.day + '-' + l.hour);
      }
    }
    return out;
  })();

  // Deterministic palette: colour by (teacher_name | subject | class)
  // so siblings of the same cattedra share a hue across views.
  const _PALETTE = [
    { bg: '#dbeafe', bd: '#2563eb', fg: '#1e3a8a' }, // blue
    { bg: '#dcfce7', bd: '#16a34a', fg: '#14532d' }, // green
    { bg: '#fee2e2', bd: '#dc2626', fg: '#7f1d1d' }, // red
    { bg: '#fef3c7', bd: '#d97706', fg: '#78350f' }, // amber
    { bg: '#f3e8ff', bd: '#9333ea', fg: '#581c87' }, // violet
    { bg: '#ccfbf1', bd: '#0d9488', fg: '#134e4a' }, // teal
    { bg: '#ffe4e6', bd: '#e11d48', fg: '#881337' }, // rose
    { bg: '#e0e7ff', bd: '#4f46e5', fg: '#3730a3' }, // indigo
    { bg: '#fef9c3', bd: '#ca8a04', fg: '#713f12' }, // yellow
    { bg: '#cffafe', bd: '#0891b2', fg: '#155e75' }, // cyan
  ];
  function _hashStr(s) {
    let h = 2166136261;
    for (let i = 0; i < s.length; i += 1) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h;
  }
  function _colourFor(lesson) {
    const t = filter_by?.type;
    let key;
    if (t === 'teacher') key = lesson.subject || lesson.class_name || '';
    else if (t === 'class') key = lesson.subject || lesson.teacher_name || '';
    else if (t === 'room')  key = lesson.class_name || lesson.subject || '';
    else key = (lesson.teacher_name || '') + '|' + (lesson.subject || '');
    return _PALETTE[_hashStr(key) % _PALETTE.length];
  }

  function _onLessonDragStart(ev, lesson) {
    dragSource = { kind: 'lesson', lesson };
    try {
      ev.dataTransfer.effectAllowed = 'move';
      ev.dataTransfer.setData('text/plain', 'lesson:' + lesson.id);
    } catch { /* JSDOM */ }
  }
  function _onUnschedDragStart(ev, entry) {
    dragSource = { kind: 'unscheduled', entry };
    try {
      ev.dataTransfer.effectAllowed = 'move';
      ev.dataTransfer.setData('text/plain', 'unscheduled:' + entry.id);
    } catch { /* JSDOM */ }
  }
  function _onDragEnd() {
    dragSource = null;
    dragHoverKey = null;
  }
  function _onSlotDragOver(ev, day, hour) {
    if (!dragSource) return;
    const k = day + '-' + hour;
    if (configuredSlots.has(k)) {
      ev.preventDefault();
      try { ev.dataTransfer.dropEffect = 'move'; } catch { /* JSDOM */ }
    }
    // dragover fires continuously on the SAME cell; only write (and thus
    // trigger a re-render) when the hovered slot actually changes.
    if (dragHoverKey !== k) dragHoverKey = k;
  }
  function _onSlotDragLeave(ev, day, hour) {
    if (dragHoverKey === day + '-' + hour) dragHoverKey = null;
  }
  function _onSlotDrop(ev, day, hour) {
    ev.preventDefault();
    const k = day + '-' + hour;
    const ds = dragSource;
    dragSource = null;
    dragHoverKey = null;
    if (!ds) return;
    if (!configuredSlots.has(k)) return;
    if (ds.kind === 'lesson') {
      if (ds.lesson.day === day && ds.lesson.hour === hour) return;
      on_lesson_move(ds.lesson.id, day, hour);
    } else if (ds.kind === 'unscheduled') {
      on_unscheduled_drop(ds.entry.id, day, hour);
    }
  }
  function _onLessonClick(ev, lesson) {
    ev.stopPropagation();
    on_lesson_click(lesson);
  }
  function _onConfiguredSlotClick(ev, day, hour, hasLessons) {
    if (hasLessons) return;          // events handle their own click
    if (dragSource) return;          // ignore during drag
    on_slot_click(day, hour);
  }
  function _lessonLabel(l) {
    const t = filter_by?.type;
    if (t === 'class')   return (l.subject || '') + ' - ' + (l.teacher_name || '');
    if (t === 'teacher') return (l.class_name || '') + ' - ' + (l.subject || '');
    if (t === 'room')    return (l.class_name || '') + ' / ' + (l.subject || '');
    return (l.class_name || '') + ' - ' + (l.subject || '');
  }

  // Two-part label so the SUBJECT is always written and prominent (the
  // teacher orario used to read only as "class - subject" on one cramped
  // line). `primary` is bold, `secondary` muted below it, per view.
  function _lessonParts(l) {
    const t = filter_by?.type;
    const subj = l.subject || '';
    const cls = l.class_name || l.group_name || '';
    const tea = l.teacher_name || '';
    if (t === 'teacher') return { primary: subj, secondary: cls };
    if (t === 'room')    return { primary: cls, secondary: subj };
    if (t === 'class')   return { primary: subj, secondary: tea };
    return { primary: cls, secondary: subj };
  }
  const _isSupportLesson = (l) => (l.subject || '').toLowerCase() === 'sostegno';
  // The "main" lesson of a shared slot: the ordinary (non-sostegno) subject.
  function _primaryLesson(lst) {
    return lst.find((l) => !_isSupportLesson(l)) || lst[0];
  }
  function _openCompresenza(ev, key, lst, timeLabel) {
    ev.stopPropagation();
    // Toggle: pressing the button while ITS popup is open closes it.
    if (compresenzaPopup && compresenzaPopup.key === key) {
      compresenzaPopup = null;
      return;
    }
    const r = ev.currentTarget.getBoundingClientRect();
    compresenzaPopup = {
      key,
      lst,
      title: timeLabel,
      x: Math.min(r.left, window.innerWidth - 240),
      y: r.bottom + 4,
    };
  }
  function _compresenzaRow(l) {
    // "subject — teacher · class @ room", dropping empty parts.
    const bits = [];
    if (l.subject) bits.push(l.subject);
    const who = [l.teacher_name, (l.class_name || l.group_name)]
      .filter(Boolean).join(' · ');
    return { head: bits.join(''), who, room: l.classroom_name || '' };
  }

  function onCellClick(ev, d, h) {
    if (readonly) return;
    if (dragMoved) {
      dragMoved = false;
      return;
    }
    setCell(d, h, _targetState(d, h));
  }

  function onPenaltyInput(ev, d, h) {
    drafts[_key(d, h)] = ev.target.value;
    drafts = drafts;
  }
  function onPenaltyChange(ev, d, h) {
    if (readonly) return;
    const cell = cells.find((c) => c.day === d && c.hour === h) || null;
    if (cell === null) return;
    const v = Number(ev.target.value);
    if (!Number.isFinite(v)) {
      ev.target.value = cell.soft_penalty;
      return;
    }
    setCell(d, h, cell.state, v);
  }
  function onPenaltyKeydown(ev, d, h) {
    if (ev.key === 'Enter') ev.target.blur();
    else if (ev.key === 'Escape') {
      const cell = cells.find((c) => c.day === d && c.hour === h) || null;
      ev.target.value = cell ? cell.soft_penalty : 100;
      ev.target.blur();
    }
  }
</script>

<svelte:window on:mouseup={onMouseUp}
  on:click={() => { if (compresenzaPopup) compresenzaPopup = null; }}
  on:keydown={(e) => { if (e.key === 'Escape') compresenzaPopup = null; }}/>

<div class="select-none weekly-calendar"
     class:weekly-calendar--schedule={mode === 'schedule'}
     data-testid={mode === 'schedule' ? 'weekly-schedule' : undefined}
     on:mouseenter={() => (hovering = true)}
     on:mouseleave={() => (hovering = false)}>
  <div class="flex items-baseline justify-between mb-2 flex-wrap gap-2">
    <h3 class="!text-base">{title}</h3>
    {#if mode !== 'schedule'}
    <div class="flex gap-3 text-xs flex-wrap">
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-emerald-400
                     bg-emerald-100"></span> libero
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-amber-400
                     bg-amber-200"></span> SOFT (penalita +)
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-red-400
                     bg-red-300"></span> HARD non disp.
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-sky-400
                     bg-sky-200"></span> PREFERRED (penalita -)
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-emerald-700
                     bg-emerald-700"></span> ENFORCED
      </span>
    </div>
    {/if}
  </div>
  {#if mode !== 'schedule'}
  <p class="text-xs text-ink-500 mb-2">
    Click ciclico: libero -&gt; giallo -&gt; rosso -&gt; blu -&gt;
    verde scuro -&gt; libero. Trascina per applicare in blocco.
    <span class="text-ink-700">
      Tieni <kbd class="px-1 border border-ink-300 rounded text-[10px]">H</kbd>/<kbd
      class="px-1 border border-ink-300 rounded text-[10px]">P</kbd>/<kbd
      class="px-1 border border-ink-300 rounded text-[10px]">E</kbd>/<kbd
      class="px-1 border border-ink-300 rounded text-[10px]">D</kbd>/<kbd
      class="px-1 border border-ink-300 rounded text-[10px]">A</kbd>/<kbd
      class="px-1 border border-ink-300 rounded text-[10px]">N</kbd>
      + click per impostare direttamente.
    </span>
  </p>
  {/if}

  {#if loadingConfig}
    <div class="text-sm text-ink-500">Caricamento configurazione...</div>
  {:else if displayActiveDays.length === 0}
    <div class="text-sm text-ink-500">
      Nessun giorno lavorativo configurato. Vai al tab
      <a href="/ore" class="link">Ore</a> per definirli.
    </div>
  {:else}
    {#if offGrid.length}
      <div class="off-grid-warning" role="status">
        <strong>{offGrid.length}</strong>
        {offGrid.length === 1 ? 'lezione' : 'lezioni'} fuori dalla griglia
        configurata (ora non più presente in <a href="/ore" class="link">Ore</a>):
        non compaiono nel calendario. Sposta o rimuovi queste lezioni, oppure
        riabilita l'ora corrispondente.
        <span class="off-grid-warning__list">
          {offGrid.slice(0, 6).map((l) =>
            `${l.class_name ?? l.group_name ?? '?'} · ${l.subject ?? '?'}`
          ).join('  ·  ')}{offGrid.length > 6 ? ' …' : ''}
        </span>
      </div>
    {/if}
    <div class="cal-layout"
         class:cal-layout--with-pool={mode === 'schedule'}>
    <div class="overflow-x-auto cal-layout__calendar" tabindex="0" role="grid" aria-label="Orario settimanale"
         on:keydown={onEditKeyDown}>
      <div class="cal-grid"
           class:cal-grid--edit={mode === 'edit'}
           class:cal-grid--schedule={mode === 'schedule'}
           style="--n-days: {displayActiveDays.length};
                  --hour-px: {PX_PER_HOUR}px;
                  --grid-h: {displayGridHeightPx}px;">
        <!-- header row: time-col placeholder + day labels -->
        <div class="cal-header">
          <div class="cal-time-col"></div>
          {#each displayActiveDays as d}
            <div class="cal-day-header" title={d.label}>
              {d.label.slice(0, 3)}
            </div>
          {/each}
        </div>
        <!-- body row: time-col on the left + day-cols with events -->
        <div class="cal-body"
             style="height: {displayGridHeightPx}px"
             on:mousemove={onEditMouseMove}>
          <!-- time column with hour labels aligned with gridlines -->
          <div class="cal-time-col">
            {#each displayBgHours as h}
              <div class="cal-hour-label"
                   style="top: {(h - displayBgRange.lo) * PX_PER_HOUR}px">
                {String(h).padStart(2, '0')}:00
              </div>
            {/each}
          </div>
          <!-- one column per active day -->
          {#each displayActiveDays as d}
            {@const dnum = d.legacy_day_number}
            {@const dayId = d.id}
            <div class="cal-day-col" data-day={dnum}
                 bind:this={d._colEl}
                 on:mousedown={(e) => onEditDayMouseDown(e, dayId, d._colEl)}>
              <!-- background hour gridlines (non-clickable in view
                   mode; serves as drag-to-create surface in edit) -->
              {#each displayBgHours as h}
                <div class="cal-hour-bg"
                     class:cal-hour-bg--editable={mode === 'edit'}
                     class:cal-hour-bg--schedule-reject={mode === 'schedule' && dragSource && !configuredSlots.has(dnum + '-' + h)}
                     style="top: {(h - displayBgRange.lo) * PX_PER_HOUR}px"
                     aria-disabled={mode !== 'edit'}
                     title={mode === 'edit'
                       ? `Trascina per creare uno slot a partire da ${String(h).padStart(2, '0')}:00`
                       : `Ora ${String(h).padStart(2, '0')}:00 -- nessuno slot configurato qui`}></div>
              {/each}
              {#if mode === 'edit'}
                <!-- EDIT MODE: events are draggable rectangles the
                     user manipulates to define the working-hours
                     layout itself. -->
                {#each (d.slots || []) as slot, sIdx}
                  {@const isSelected = selectedSel
                      && selectedSel.dayId === dayId
                      && selectedSel.idx === sIdx}
                  {@const isEditing = editPopover
                      && editPopover.dayId === dayId
                      && editPopover.idx === sIdx}
                  {@const isGhosting = editDrag
                      && editDrag.dayId === dayId
                      && editDrag.idx === sIdx
                      && (editDrag.kind === 'move'
                          || editDrag.kind === 'resize-top'
                          || editDrag.kind === 'resize-bottom')}
                  <div class="cal-event cal-event--edit"
                       class:cal-event--selected={isSelected}
                       class:cal-event--editing={isEditing}
                       class:cal-event--ghosting={isGhosting}
                       style="top: {_pxFromTime(slot.start_time, displayBgRange)}px;
                              height: {_pxDuration(slot)}px"
                       data-day={dnum}
                       data-slot-idx={sIdx}
                       on:mousedown={(e) =>
                         (!isEditing) && onEditSlotMouseDown(e, dayId, sIdx,
                                              d._colEl, 'move')}
                       title={`${slot.start_time}-${slot.end_time} -- trascina i bordi per ridimensionare, il corpo per spostare`}>
                    <div class="cal-edit-handle cal-edit-handle--top"
                         on:mousedown|stopPropagation={(e) =>
                           (!isEditing) && onEditSlotMouseDown(e, dayId, sIdx,
                                                d._colEl, 'resize-top')}>
                    </div>
                    {#if isEditing}
                      <div class="cal-edit-popover"
                           on:mousedown|stopPropagation={() => {}}>
                        <div class="cal-edit-popover-row">
                          <label>Inizio
                            <input type="time" bind:value={editPopover.start_time}/>
                          </label>
                          <label>Fine
                            <input type="time" bind:value={editPopover.end_time}/>
                          </label>
                        </div>
                        <label class="cal-edit-popover-row">Etichetta
                          <input type="text" bind:value={editPopover.label}
                                 placeholder="es. 1ª ora"/>
                        </label>
                        <div class="cal-edit-popover-actions">
                          <button type="button" class="cal-edit-btn"
                                  on:click|stopPropagation={() => (editPopover = null)}>
                            Annulla
                          </button>
                          <button type="button" class="cal-edit-btn cal-edit-btn--primary"
                                  on:click|stopPropagation={_applyEditPopover}>
                            Applica
                          </button>
                        </div>
                      </div>
                    {:else}
                      <div class="cal-event-actions"
                           on:mousedown|stopPropagation={() => {}}>
                        <button type="button" class="cal-event-btn"
                                title="Modifica orari/etichetta"
                                aria-label="Modifica slot"
                                on:click|stopPropagation={() => _openEditPopover(dayId, sIdx)}>
                          Modifica
                        </button>
                        <button type="button" class="cal-event-btn cal-event-btn--danger"
                                title="Cancella slot"
                                aria-label="Cancella slot"
                                on:click|stopPropagation={() => _editApplyDelete(dayId, sIdx)}>
                          Cancella
                        </button>
                      </div>
                      <div class="cal-event-time">
                        {slot.start_time}-{slot.end_time}
                      </div>
                      <div class="cal-event-label">{slot.label || ''}</div>
                    {/if}
                    <div class="cal-edit-handle cal-edit-handle--bot"
                         on:mousedown|stopPropagation={(e) =>
                           (!isEditing) && onEditSlotMouseDown(e, dayId, sIdx,
                                                d._colEl, 'resize-bottom')}>
                    </div>
                  </div>
                {/each}
                <!-- drag-to-create live preview -->
                {#if editDragPreview && editDragPreview.dayId === dayId}
                  <div class="cal-event cal-event--preview"
                       style="top: {editDragPreview.top}px;
                              height: {editDragPreview.height}px;">
                    <div class="cal-event-time">
                      {editDragPreview.label}
                    </div>
                  </div>
                {/if}
              {:else if mode === 'schedule'}
                <!-- SCHEDULE MODE: configured slots are drop targets;
                     each lesson on (day, hour) is rendered as a
                     positioned, draggable, clickable event. -->
                {#each (d.slots || []) as slot}
                  {@const hnum = slot.legacy_hour_number}
                  {@const slotKey = dnum + '-' + hnum}
                  {@const lst = lessonsBySlot.get(slotKey) || []}
                  {@const isHover = dragHoverKey === slotKey}
                  {@const isConflict = conflictKeys.has(slotKey)}
                  <div class="cal-slot cal-slot--schedule"
                       class:cal-slot--drop-ok={isHover && dragSource}
                       class:cal-slot--drop-conflict={isConflict && dragSource}
                       style="top: {_pxFromTime(slot.start_time, displayBgRange)}px;
                              height: {_pxDuration(slot)}px"
                       data-day={dnum}
                       data-hour={hnum}
                       data-testid={'sched-slot-' + dnum + '-' + hnum}
                       on:dragover={(e) => _onSlotDragOver(e, dnum, hnum)}
                       on:dragleave={(e) => _onSlotDragLeave(e, dnum, hnum)}
                       on:drop={(e) => _onSlotDrop(e, dnum, hnum)}
                       on:click={(e) => _onConfiguredSlotClick(e, dnum, hnum, lst.length > 0)}
                       title={`${slot.start_time}-${slot.end_time}` +
                         (lst.length === 0 ? ' -- vuoto, click per nuova lezione'
                          : ` -- ${lst.length} lezion${lst.length === 1 ? 'e' : 'i'}`)}>
                    {#if lst.length === 0}
                      <div class="cal-slot-time">
                        {slot.start_time}-{slot.end_time}
                      </div>
                    {:else}
                      {@const isCompresenza = !!filter_by?.type && lst.length > 1}
                      {@const renderList = isCompresenza ? [_primaryLesson(lst)] : lst}
                      {#each renderList as l, lIdx}
                        {@const col = _colourFor(l)}
                        {@const parts = _lessonParts(l)}
                        <div class="cal-event cal-event--schedule"
                             class:cal-event--conflict={isConflict && dragSource}
                             style={`background:${col.bg};border-color:${col.bd};color:${col.fg};` +
                                    (!isCompresenza && lst.length > 1 ? `width:${100 / lst.length}%;left:${(100 / lst.length) * lIdx}%;` : '')}
                             draggable="true"
                             role="button"
                             tabindex="0"
                             data-lesson-id={l.id}
                             data-testid={'sched-lesson-' + l.id}
                             on:dragstart={(e) => _onLessonDragStart(e, l)}
                             on:dragend={_onDragEnd}
                             on:click={(e) => _onLessonClick(e, l)}
                             on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _onLessonClick(e, l); } }}
                             title={_lessonLabel(l) +
                               (l.classroom_name ? ' @ ' + l.classroom_name : '') +
                               (isCompresenza ? ` -- compresenza (${lst.length} lezioni, vedi bottone)` : '') +
                               (isConflict && dragSource ? ' -- conflitto con la lezione che stai trascinando' : '')}>
                          <div class="cal-event-time cal-event-time--row">
                            <span>{slot.start_time}-{slot.end_time}</span>
                            {#if isCompresenza}
                              <button type="button" class="cal-compresenza-btn"
                                      class:cal-compresenza-btn--on={compresenzaPopup
                                        && compresenzaPopup.key === (dnum + '-' + hnum)}
                                      title={`Compresenza: ${lst.length} lezioni -- apri/chiudi`}
                                      data-testid={'sched-compresenza-' + dnum + '-' + hnum}
                                      on:click={(e) => _openCompresenza(e, dnum + '-' + hnum,
                                        lst, `${slot.start_time}-${slot.end_time}`)}
                                      on:keydown|stopPropagation>
                                +{lst.length - 1}&nbsp;<span aria-hidden="true">👥</span>
                              </button>
                            {/if}
                          </div>
                          <div class="cal-event-label">
                            {#if l.locked}<span aria-hidden="true"
                              title="Bloccata in questo slot">🔒</span> {/if}<span
                              class="cal-event-primary">{parts.primary}</span>{#if parts.secondary}<span
                              class="cal-event-secondary">{parts.secondary}</span>{/if}
                          </div>
                          {#if l.classroom_name}
                            <div class="cal-event-room">
                              {l.classroom_name}
                            </div>
                          {/if}
                          {#if isConflict && dragSource}
                            <span class="cal-event-conflict-badge"
                                  data-testid="sched-conflict-badge">!</span>
                          {/if}
                        </div>
                      {/each}
                    {/if}
                  </div>
                {/each}
              {:else}
                <!-- VIEW MODE: events drive the constraint-level
                     painter (free / soft / hard / preferred /
                     enforced) for teachers / classes / classrooms
                     unavailability tabs. -->
                {#each (d.slots || []) as slot}
                  {@const hnum = slot.legacy_hour_number}
                  {@const cell = cells.find((c) =>
                      c.day === dnum && c.hour === hnum) || null}
                  {@const isFree = !cell}
                  {@const isSoft = cell && cell.state === 'soft'}
                  {@const isHard = cell && cell.state === 'hard'}
                  {@const isPref = cell && cell.state === 'preferred'}
                  {@const isEnf  = cell && cell.state === 'enforced'}
                  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                  <div class="cal-event"
                       class:cal-event--free={isFree}
                       class:cal-event--soft={isSoft}
                       class:cal-event--hard={isHard}
                       class:cal-event--preferred={isPref}
                       class:cal-event--enforced={isEnf}
                       class:cal-event--readonly={readonly}
                       style="top: {_pxFromTime(slot.start_time, displayBgRange)}px;
                              height: {_pxDuration(slot)}px"
                       data-day={dnum}
                       data-hour={hnum}
                       data-state={cell ? cell.state : 'free'}
                       role="gridcell"
                       tabindex="-1"
                       aria-label="{slot.start_time}-{slot.end_time}"
                       on:click={(e) => onCellClick(e, dnum, hnum)}
                       on:mousedown={(e) => onMouseDown(e, dnum, hnum)}
                       on:mouseenter={() => onMouseEnter(dnum, hnum)}
                       title={`${slot.start_time}-${slot.end_time}` +
                         (isSoft
                           ? ` -- SOFT, penalita ${cell.soft_penalty}`
                           : isPref
                           ? ` -- PREFERRED, bonus ${cell.soft_penalty}`
                           : isEnf
                           ? ' -- ENFORCED'
                           : isHard
                           ? ' -- HARD non disponibile'
                           : ' -- libero')}>
                    <div class="cal-event-time">
                      {slot.start_time}-{slot.end_time}
                    </div>
                    {#if isEnf}
                      <span class="cal-event-marker cal-event-marker--enf">!</span>
                    {:else if isHard}
                      <span class="cal-event-marker cal-event-marker--hard">X</span>
                    {:else if isSoft}
                      <input type="number" min="0" max="9999" step="10"
                        class="cal-event-input cal-event-input--soft"
                        value={drafts[_key(dnum, hnum)] ?? cell.soft_penalty}
                        on:click|stopPropagation
                        on:mousedown|stopPropagation
                        on:dblclick|stopPropagation
                        on:input={(e) => onPenaltyInput(e, dnum, hnum)}
                        on:change={(e) => onPenaltyChange(e, dnum, hnum)}
                        on:keydown={(e) => onPenaltyKeydown(e, dnum, hnum)}/>
                    {:else if isPref}
                      <input type="number" max="0" min="-9999" step="10"
                        class="cal-event-input cal-event-input--pref"
                        value={drafts[_key(dnum, hnum)] ?? cell.soft_penalty}
                        on:click|stopPropagation
                        on:mousedown|stopPropagation
                        on:dblclick|stopPropagation
                        on:input={(e) => onPenaltyInput(e, dnum, hnum)}
                        on:change={(e) => onPenaltyChange(e, dnum, hnum)}
                        on:keydown={(e) => onPenaltyKeydown(e, dnum, hnum)}/>
                    {/if}
                  </div>
                {/each}
              {/if}
            </div>
          {/each}
        </div>
      </div>
    </div>
    {#if mode === 'schedule'}
      <UnscheduledPool
        lessons={unscheduled_lessons || []}
        _colourFor={_colourFor}
        _onUnschedDragStart={_onUnschedDragStart}
        _onDragEnd={_onDragEnd}
      />
    {/if}
    </div>
  {/if}

  {#if mode !== 'schedule' && mode !== 'edit'}
  <KeyboardConstraintLegend visible={hovering} variant="matrix"/>
  {/if}
</div>

{#if compresenzaPopup}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="cal-compresenza-pop"
       data-testid="compresenza-popup"
       style={`left:${compresenzaPopup.x}px; top:${compresenzaPopup.y}px;`}
       on:click|stopPropagation
       on:keydown|stopPropagation>
    <div class="cal-compresenza-pop__title">
      Compresenza · {compresenzaPopup.title}
    </div>
    {#each compresenzaPopup.lst as cl2}
      {@const row = _compresenzaRow(cl2)}
      <div class="cal-compresenza-pop__row">
        <span class="cal-compresenza-pop__subj">{row.head || '?'}</span>
        {#if row.who}<span class="cal-compresenza-pop__who">{row.who}</span>{/if}
        {#if row.room}<span class="cal-compresenza-pop__room">@ {row.room}</span>{/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  /* Off-grid lessons banner: warns that some placed lessons fall on an
     hour no longer configured in Tab Ore, so they can't be rendered. */
  .off-grid-warning {
    margin: 0 0 0.5rem;
    padding: 0.5rem 0.75rem;
    border: 1px solid rgb(217 119 6 / 0.4);
    border-radius: 0.5rem;
    background: rgb(251 191 36 / 0.12);
    color: rgb(146 64 14);
    font-size: 0.8125rem;
    line-height: 1.4;
  }
  .off-grid-warning__list {
    display: block;
    margin-top: 0.25rem;
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
    opacity: 0.85;
  }

  /* Calendar-grid layout: time column on the left + N day columns,
     with configured Tab Ore slots rendered as absolutely-positioned
     event blocks ON TOP of the always-visible hour gridlines. The
     hour gridlines are non-interactive (cursor: not-allowed) so the
     user cannot accidentally set a constraint at an unconfigured
     hour. */
  .cal-grid {
    display: flex;
    flex-direction: column;
    border: 1px solid var(--line);
    border-radius: 6px;
    overflow: hidden;
    user-select: none;
  }
  .cal-header {
    display: grid;
    grid-template-columns: 60px repeat(var(--n-days, 6), 1fr);
    background: var(--band);
    border-bottom: 1px solid var(--line);
  }
  .cal-day-header {
    padding: 6px 4px;
    text-align: center;
    font-size: 12px;
    font-weight: 600;
    color: var(--ink2);
    border-left: 1px solid var(--line);
  }
  .cal-body {
    display: grid;
    grid-template-columns: 60px repeat(var(--n-days, 6), 1fr);
    position: relative;
  }
  .cal-time-col {
    position: relative;
    background: var(--band);
    border-right: 1px solid var(--line);
  }
  .cal-hour-label {
    position: absolute;
    left: 0;
    right: 4px;
    transform: translateY(-50%);
    text-align: right;
    font-size: 10px;
    color: var(--ink2);
    pointer-events: none;
  }
  .cal-day-col {
    position: relative;
    border-left: 1px solid var(--line2);
  }
  .cal-day-col:first-of-type { border-left: none; }
  /* Background hour gridlines: visible but inert. */
  .cal-hour-bg {
    position: absolute;
    left: 0;
    right: 0;
    height: var(--hour-px, 40px);
    border-top: 1px dashed var(--line2);
    background: var(--band);
    cursor: not-allowed;
    pointer-events: none;
  }
  /* Foreground events: clickable + colorable. */
  .cal-event {
    position: absolute;
    left: 2px;
    right: 2px;
    border: 1px solid;
    border-radius: 4px;
    padding: 2px 4px;
    font-size: 10px;
    overflow: hidden;
    cursor: pointer;
    transition: filter 0.15s, box-shadow 0.15s;
    display: flex;
    flex-direction: column;
    gap: 2px;
    z-index: 1;
  }
  .cal-event:hover { filter: brightness(0.96); box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .cal-event--readonly { cursor: default; }
  .cal-event-time {
    font-size: 9px;
    font-weight: 600;
    line-height: 1.1;
    opacity: 0.8;
  }
  .cal-event--free      { background: #ecfdf5; border-color: #6ee7b7; color: #065f46; }
  .cal-event--soft      { background: #fde68a; border-color: #f59e0b; color: #78350f; }
  .cal-event--hard      { background: #fca5a5; border-color: #ef4444; color: #7f1d1d; }
  .cal-event--preferred { background: #bae6fd; border-color: #38bdf8; color: #075985; }
  .cal-event--enforced  { background: #047857; border-color: #064e3b; color: white; }
  .cal-event-marker {
    align-self: center;
    font-weight: 700;
    font-size: 12px;
    line-height: 1;
  }
  .cal-event-marker--enf  { color: white; }
  .cal-event-marker--hard { color: #7f1d1d; }
  .cal-event-input {
    align-self: stretch;
    text-align: center;
    border: 1px solid;
    border-radius: 3px;
    padding: 1px 2px;
    font-size: 11px;
    font-weight: 600;
    appearance: textfield;
    -moz-appearance: textfield;
  }
  .cal-event-input::-webkit-outer-spin-button,
  .cal-event-input::-webkit-inner-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }
  .cal-event-input--soft { background: #fef3c7; border-color: #d97706; color: #78350f; }
  .cal-event-input--pref { background: #e0f2fe; border-color: #0ea5e9; color: #075985; }
  .cal-event-input:focus { outline: none; box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.3); }
  .cal-event-input--pref:focus { box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.3); }

  /* ----- EDIT MODE additions (Tab Ore slot editor) ----- */
  /* Edit-mode background gridlines accept drag-to-create. */
  .cal-grid--edit .cal-hour-bg.cal-hour-bg--editable {
    cursor: crosshair;
    pointer-events: auto;
    background: #ffffff;
  }
  .cal-grid--edit .cal-day-col {
    cursor: crosshair;
  }
  /* Edit-mode events: dashed border so users see they are mutable. */
  .cal-event--edit {
    background: #dbeafe;
    border: 1px dashed #2563eb;
    color: #1e3a8a;
    cursor: grab;
    z-index: 2;
  }
  .cal-event--edit:active { cursor: grabbing; }
  .cal-event--edit:hover { filter: brightness(0.94); }
  /* While a drag is in flight the cursor must stick to grabbing /
     ns-resize regardless of where the mouse moves -- the container
     class is toggled from JS based on editDrag.kind. */
  :global(body.cal-edit-dragging-move),
  :global(body.cal-edit-dragging-move *) { cursor: grabbing !important; }
  :global(body.cal-edit-dragging-resize),
  :global(body.cal-edit-dragging-resize *) { cursor: ns-resize !important; }
  .cal-event--selected {
    outline: 2px solid #1d4ed8;
    outline-offset: 1px;
    background: #bfdbfe;
  }
  .cal-event--preview {
    background: rgba(37, 99, 235, 0.18);
    border: 1px dashed #1d4ed8;
    color: #1e3a8a;
    pointer-events: none;
    z-index: 3;
  }
  /* During an active move/resize drag the source slot dims to make
     the live preview ("ghost") at the projected position read as
     the authoritative target. Commits to full opacity on mouse-up. */
  .cal-event--ghosting {
    opacity: 0.35;
    filter: grayscale(0.4);
    transition: opacity 60ms ease;
  }
  .cal-event-label {
    font-size: 9px;
    line-height: 1.1;
    opacity: 0.7;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* Top / bottom resize handles (6px grab strips at the slot edges). */
  .cal-edit-handle {
    position: absolute;
    left: 0;
    right: 0;
    height: 6px;
    cursor: ns-resize;
    background: rgba(29, 78, 216, 0.2);
  }
  .cal-edit-handle--top { top: 0; }
  .cal-edit-handle--bot { bottom: 0; }
  .cal-edit-handle:hover { background: rgba(29, 78, 216, 0.45); }

  /* Per-slot Modifica/Cancella action labels (edit mode). Plain text
     links, no border / background, so they don't overlap visually
     with the time + label rendered in the slot body. */
  .cal-event-actions {
    position: absolute;
    top: 2px;
    right: 4px;
    display: flex;
    gap: 6px;
    z-index: 5;
  }
  .cal-event-btn {
    font-size: 9px;
    line-height: 1;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--ink);
    text-decoration: underline;
    cursor: pointer;
  }
  .cal-event-btn:hover { color: var(--ink); }
  .cal-event-btn--danger { color: #b91c1c; }
  .cal-event-btn--danger:hover { color: #7f1d1d; }

  /* Inline edit popover replacing the slot's body while ``editPopover``
     targets it. Sized to fit inside the slot rectangle. The slot
     itself bumps z-index so the popover overlaps neighbouring slots
     in adjacent days; the popover content shows above any other
     calendar element. */
  .cal-event--editing {
    cursor: default;
    overflow: visible;
    z-index: 50;
  }
  .cal-edit-popover {
    position: absolute;
    /* Free the popover from the slot's height -- when the slot is
       short (e.g. 60 min = 60 px) the form would be clipped. Anchor
       to the top-left and let it grow downward over the neighbouring
       slots, which we explicitly outrank via z-index. */
    top: 0;
    left: 4px;
    width: max(220px, calc(100% - 8px));
    min-height: 110px;
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 6px;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18);
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    z-index: 100;
    font-size: 11px;
    color: var(--ink);
  }
  .cal-edit-popover-row {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .cal-edit-popover-row label {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 10px;
    color: var(--ink2);
    flex: 1 1 0;
  }
  .cal-edit-popover input[type='time'],
  .cal-edit-popover input[type='text'] {
    border: 1px solid var(--line);
    border-radius: 3px;
    padding: 2px 4px;
    font-size: 11px;
    width: 100%;
  }
  .cal-edit-popover-actions {
    display: flex;
    gap: 6px;
    justify-content: flex-end;
    margin-top: auto;
  }
  .cal-edit-btn {
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid var(--line);
    background: var(--band);
    cursor: pointer;
  }
  .cal-edit-btn:hover { background: var(--line); }
  .cal-edit-btn--primary {
    background: #2563eb;
    border-color: #2563eb;
    color: #fff;
  }
  .cal-edit-btn--primary:hover { background: #1d4ed8; }
  /* Hide click outline on the wrapping scroll container that catches
     keyboard Delete events (it must be focusable, but the visual
     focus ring is distracting on the calendar itself). */
  .weekly-calendar :global(.overflow-x-auto):focus { outline: none; }

  /* ----- SCHEDULE MODE additions ----- */
  .cal-layout {
    display: block;
  }
  .cal-layout--with-pool {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 236px;
    gap: 12px;
    align-items: start;
  }
  .cal-layout__calendar { min-width: 0; }

  /* Configured slot wrapper in schedule mode: receives drops + click. */
  .cal-slot--schedule {
    position: absolute;
    left: 2px;
    right: 2px;
    border: 1px dashed var(--line-dash, #d8d0be);
    border-radius: 4px;
    background: #ffffff;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    z-index: 1;
  }
  .cal-slot-time {
    font-size: 9px;
    color: var(--ink3);
    padding: 2px 4px;
    line-height: 1.1;
    pointer-events: none;
  }
  .cal-slot--schedule:hover {
    background: var(--band);
    border-color: var(--ink3);
  }
  .cal-slot--drop-ok {
    background: #d1fae5 !important;
    border: 2px solid #10b981 !important;
    border-style: solid !important;
  }
  .cal-slot--drop-conflict {
    background: #fef3c7 !important;
    border: 2px solid #f59e0b !important;
    border-style: solid !important;
  }
  /* Background grid cells light up red while a drag is in progress
     and the cursor is over an unconfigured hour. */
  .cal-grid--schedule .cal-hour-bg.cal-hour-bg--schedule-reject,
  .cal-hour-bg--schedule-reject {
    background: #fee2e2 !important;
    cursor: not-allowed;
  }

  /* Schedule events: positioned inside their slot via flex; coloured
     by deterministic palette via inline style. */
  .cal-event--schedule {
    position: relative;
    flex: 1 1 auto;
    border-style: solid;
    border-width: 1px;
    border-radius: 3px;
    padding: 2px 4px;
    margin: 1px;
    cursor: grab;
    overflow: hidden;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .cal-event--schedule:active { cursor: grabbing; }
  .cal-event--schedule.cal-event--conflict {
    outline: 2px solid #f59e0b;
    outline-offset: -2px;
  }
  .cal-event-room {
    font-size: 9px;
    line-height: 1.1;
    opacity: 0.75;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* Two-part label: subject (bold) always written, secondary muted below.
     Kept small so hour + subject + prof + room all pack into one cell. */
  .cal-event-primary {
    font-weight: 700;
    line-height: 1.1;
  }
  .cal-event-secondary {
    display: block;
    font-weight: 400;
    font-size: 9px;
    opacity: 0.8;
    line-height: 1.05;
  }
  /* The time row carries the compresenza button so the button is visible
     WITH everything else and never pushes the subject/prof/room out of the
     fixed-height cell. */
  .cal-event-time--row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 4px;
  }
  .cal-compresenza-btn {
    flex: none;
    padding: 0 5px;
    font-size: 8.5px;
    font-weight: 700;
    line-height: 1.4;
    border: 1px solid currentColor;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.6);
    color: inherit;
    cursor: pointer;
    white-space: nowrap;
  }
  .cal-compresenza-btn:hover,
  .cal-compresenza-btn--on {
    background: rgba(255, 255, 255, 0.96);
    box-shadow: inset 0 0 0 1px currentColor;
  }
  .cal-compresenza-pop {
    position: fixed;
    z-index: 1000;
    min-width: 180px;
    max-width: 240px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18);
    padding: 6px 8px;
    font-size: 11px;
    color: #1e293b;
  }
  .cal-compresenza-pop__title {
    font-weight: 700;
    font-size: 11px;
    margin-bottom: 4px;
    color: #0f172a;
  }
  .cal-compresenza-pop__row {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 6px;
    padding: 3px 0;
    border-top: 1px solid #f1f5f9;
  }
  .cal-compresenza-pop__subj { font-weight: 600; }
  .cal-compresenza-pop__who { opacity: 0.85; }
  .cal-compresenza-pop__room { opacity: 0.7; }
  .cal-event-conflict-badge {
    position: absolute;
    top: 1px;
    right: 2px;
    background: #f59e0b;
    color: white;
    border-radius: 50%;
    font-size: 9px;
    font-weight: 700;
    width: 12px;
    height: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
  }

</style>
