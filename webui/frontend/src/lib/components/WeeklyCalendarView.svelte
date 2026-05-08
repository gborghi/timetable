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
  import * as api from '$lib/api';
  import {
    heldKey,
    startKeyboardConstraintMode,
    shortcutToMatrixState,
  } from '../keyboardConstraintMode';
  import KeyboardConstraintLegend from './KeyboardConstraintLegend.svelte';
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
   * a change. */
  export let mode = 'view';
  /** Edit-mode callback. Called with a SHALLOW COPY of ``config``
   * whose ``days[*].slots`` reflect the user's edits. The parent is
   * expected to persist the new slots via the working-hours API.
   * Defaults to a no-op so the view-mode call sites don't have to
   * pass anything. */
  export let onConfigEdit = (_newConfig) => {};

  let _config = config;
  let loadingConfig = false;
  $: _config = config || _config;

  let kbCleanup;
  let hovering = false;
  onMount(async () => {
    kbCleanup = startKeyboardConstraintMode();
    if (!_config) {
      try {
        loadingConfig = true;
        _config = await api.get('/api/working-hours/config');
      } catch {
        // Fall back to a synthetic default config so the component
        // still renders even if the API isn't reachable (e.g. unit
        // tests). This matches the engine's legacy fallback.
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
  });
  onDestroy(() => kbCleanup?.());

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
    }
  }

  function _editMouseUp() {
    if (!editDrag) return;
    const drag = editDrag;
    editDrag = null;
    editDragPreview = null;
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
    if (ev.key === 'Delete' || ev.key === 'Backspace') {
      ev.preventDefault();
      _editApplyDelete(selectedSel.dayId, selectedSel.idx);
    } else if (ev.key === 'Escape') {
      selectedSel = null;
    }
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

<svelte:window on:mouseup={onMouseUp}/>

<div class="select-none weekly-calendar"
     on:mouseenter={() => (hovering = true)}
     on:mouseleave={() => (hovering = false)}>
  <div class="flex items-baseline justify-between mb-2 flex-wrap gap-2">
    <h3 class="!text-base">{title}</h3>
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
  </div>
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

  {#if loadingConfig}
    <div class="text-sm text-ink-500">Caricamento configurazione...</div>
  {:else if displayActiveDays.length === 0}
    <div class="text-sm text-ink-500">
      Nessun giorno lavorativo configurato. Vai al tab
      <a href="/ore" class="link">Ore</a> per definirli.
    </div>
  {:else}
    <div class="overflow-x-auto" tabindex="0"
         on:keydown={onEditKeyDown}>
      <div class="cal-grid"
           class:cal-grid--edit={mode === 'edit'}
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
                  <div class="cal-event cal-event--edit"
                       class:cal-event--selected={isSelected}
                       style="top: {_pxFromTime(slot.start_time, displayBgRange)}px;
                              height: {_pxDuration(slot)}px"
                       data-day={dnum}
                       data-slot-idx={sIdx}
                       on:mousedown={(e) =>
                         onEditSlotMouseDown(e, dayId, sIdx,
                                              d._colEl, 'move')}
                       title={`${slot.start_time}-${slot.end_time} -- trascina i bordi per ridimensionare, il corpo per spostare, Canc per eliminare`}>
                    <div class="cal-edit-handle cal-edit-handle--top"
                         on:mousedown|stopPropagation={(e) =>
                           onEditSlotMouseDown(e, dayId, sIdx,
                                                d._colEl, 'resize-top')}>
                    </div>
                    <div class="cal-event-time">
                      {slot.start_time}-{slot.end_time}
                    </div>
                    <div class="cal-event-label">{slot.label || ''}</div>
                    <div class="cal-edit-handle cal-edit-handle--bot"
                         on:mousedown|stopPropagation={(e) =>
                           onEditSlotMouseDown(e, dayId, sIdx,
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
  {/if}

  <KeyboardConstraintLegend visible={hovering} variant="matrix"/>
</div>

<style>
  /* Calendar-grid layout: time column on the left + N day columns,
     with configured Tab Ore slots rendered as absolutely-positioned
     event blocks ON TOP of the always-visible hour gridlines. The
     hour gridlines are non-interactive (cursor: not-allowed) so the
     user cannot accidentally set a constraint at an unconfigured
     hour. */
  .cal-grid {
    display: flex;
    flex-direction: column;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    overflow: hidden;
    user-select: none;
  }
  .cal-header {
    display: grid;
    grid-template-columns: 60px repeat(var(--n-days, 6), 1fr);
    background: #f9fafb;
    border-bottom: 1px solid #e5e7eb;
  }
  .cal-day-header {
    padding: 6px 4px;
    text-align: center;
    font-size: 12px;
    font-weight: 600;
    color: #374151;
    border-left: 1px solid #e5e7eb;
  }
  .cal-body {
    display: grid;
    grid-template-columns: 60px repeat(var(--n-days, 6), 1fr);
    position: relative;
  }
  .cal-time-col {
    position: relative;
    background: #f9fafb;
    border-right: 1px solid #e5e7eb;
  }
  .cal-hour-label {
    position: absolute;
    left: 0;
    right: 4px;
    transform: translateY(-50%);
    text-align: right;
    font-size: 10px;
    color: #6b7280;
    pointer-events: none;
  }
  .cal-day-col {
    position: relative;
    border-left: 1px solid #f3f4f6;
  }
  .cal-day-col:first-of-type { border-left: none; }
  /* Background hour gridlines: visible but inert. */
  .cal-hour-bg {
    position: absolute;
    left: 0;
    right: 0;
    height: var(--hour-px, 40px);
    border-top: 1px dashed #f3f4f6;
    background: #fafafa;
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
    cursor: move;
    z-index: 2;
  }
  .cal-event--edit:hover { filter: brightness(0.94); }
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
  /* Hide click outline on the wrapping scroll container that catches
     keyboard Delete events (it must be focusable, but the visual
     focus ring is distracting on the calendar itself). */
  .weekly-calendar > .overflow-x-auto:focus { outline: none; }
</style>
