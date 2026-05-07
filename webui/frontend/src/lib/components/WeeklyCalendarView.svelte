<script>
  /**
   * Reusable calendar-grid view for slot-level constraints.
   *
   * Layout: columns = active working days (in Tab Ore position order),
   * rows = slot indices 0..max_slots_per_day-1. Each cell shows the
   * slot's (start_time-end_time) label and is colored by the cell's
   * level (free / soft / hard / preferred / enforced).
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

  export let value = [];
  export let onChange = (_v) => {};
  export let title = 'Disponibilita oraria';
  export let readonly = false;
  export let config = null;

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
  {:else if activeDays.length === 0}
    <div class="text-sm text-ink-500">
      Nessun giorno lavorativo configurato. Vai al tab
      <a href="/ore" class="link">Ore</a> per definirli.
    </div>
  {:else}
    <div class="overflow-x-auto">
      <table class="tbl">
        <thead>
          <tr>
            <th class="w-20"></th>
            {#each activeDays as d}
              <th class="text-center" title={d.label}>
                {d.label.slice(0, 3)}
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each Array(maxSlots) as _, slotIdx}
            <tr>
              <td class="text-xs text-ink-500 align-middle px-1">
                {#each activeDays.slice(0, 1) as d0}
                  {@const s = d0.slots[slotIdx]}
                  {#if s}
                    {s.start_time}
                  {:else}
                    --
                  {/if}
                {/each}
              </td>
              {#each activeDays as d}
                {@const slot = d.slots[slotIdx]}
                {#if !slot}
                  <td class="p-1 align-middle">
                    <div class="h-9 rounded border border-dashed
                                border-ink-200 bg-ink-50/50
                                flex items-center justify-center
                                text-[10px] text-ink-400">--</div>
                  </td>
                {:else}
                  {@const dnum = d.legacy_day_number}
                  {@const hnum = slot.legacy_hour_number}
                  {@const cell = cells.find((c) =>
                      c.day === dnum && c.hour === hnum) || null}
                  {@const isFree = !cell}
                  {@const isSoft = cell && cell.state === 'soft'}
                  {@const isHard = cell && cell.state === 'hard'}
                  {@const isPref = cell && cell.state === 'preferred'}
                  {@const isEnf  = cell && cell.state === 'enforced'}
                  <td class="p-1 align-middle">
                    <div class="relative h-9 rounded border
                                cursor-pointer transition-colors
                                flex items-center justify-center"
                      class:bg-emerald-50={isFree}
                      class:border-emerald-300={isFree}
                      class:hover:bg-emerald-100={isFree}
                      class:bg-amber-200={isSoft}
                      class:border-amber-400={isSoft}
                      class:bg-red-300={isHard}
                      class:border-red-500={isHard}
                      class:bg-sky-200={isPref}
                      class:border-sky-400={isPref}
                      class:bg-emerald-700={isEnf}
                      class:border-emerald-900={isEnf}
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
                      {#if isFree}
                        <span class="text-emerald-700 font-semibold
                                     text-xs">-</span>
                      {:else if isEnf}
                        <span class="text-white font-semibold text-xs">!</span>
                      {:else if isHard}
                        <span class="text-red-900 font-semibold text-xs">X</span>
                      {:else if isSoft}
                        <input type="number" min="0" max="9999" step="10"
                          class="block w-12 h-7 text-center text-xs
                                 font-semibold text-amber-900
                                 bg-amber-100 border border-amber-500
                                 rounded [appearance:textfield]
                                 [&::-webkit-outer-spin-button]:appearance-none
                                 [&::-webkit-inner-spin-button]:appearance-none
                                 focus:outline-none focus:ring-2
                                 focus:ring-amber-600/40"
                          value={drafts[_key(dnum, hnum)] ?? cell.soft_penalty}
                          on:click|stopPropagation
                          on:mousedown|stopPropagation
                          on:dblclick|stopPropagation
                          on:input={(e) => onPenaltyInput(e, dnum, hnum)}
                          on:change={(e) => onPenaltyChange(e, dnum, hnum)}
                          on:keydown={(e) => onPenaltyKeydown(e, dnum, hnum)}/>
                      {:else if isPref}
                        <input type="number" max="0" min="-9999" step="10"
                          class="block w-12 h-7 text-center text-xs
                                 font-semibold text-sky-900
                                 bg-sky-100 border border-sky-500
                                 rounded [appearance:textfield]
                                 [&::-webkit-outer-spin-button]:appearance-none
                                 [&::-webkit-inner-spin-button]:appearance-none
                                 focus:outline-none focus:ring-2
                                 focus:ring-sky-600/40"
                          value={drafts[_key(dnum, hnum)] ?? cell.soft_penalty}
                          on:click|stopPropagation
                          on:mousedown|stopPropagation
                          on:dblclick|stopPropagation
                          on:input={(e) => onPenaltyInput(e, dnum, hnum)}
                          on:change={(e) => onPenaltyChange(e, dnum, hnum)}
                          on:keydown={(e) => onPenaltyKeydown(e, dnum, hnum)}/>
                      {/if}
                    </div>
                  </td>
                {/if}
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}

  <KeyboardConstraintLegend visible={hovering} variant="matrix"/>
</div>

<style>
  .weekly-calendar :global(table.tbl) { border-collapse: separate; }
</style>
