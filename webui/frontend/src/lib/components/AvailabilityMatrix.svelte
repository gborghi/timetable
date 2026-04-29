<script>
  // Reusable 3-state availability matrix.
  //
  // Props:
  //   value:    Array<{day, hour, state:'hard'|'soft', soft_penalty:int, reason?}>
  //   onChange: callback(newValue) -> void   (parent MUST reassign root state
  //                                            for Svelte 4 reactivity)
  //   title:    optional header
  //   readonly: if true, disables clicks
  //
  // Interactions:
  //   - single click on the cell BACKGROUND
  //                                -> cycle  free -> soft (yellow) -> hard (red) -> free
  //   - inline numeric input visible inside every yellow cell, with
  //     stopPropagation so editing the number does not change the colour;
  //     the value is committed on `change` (blur or Enter) — typing does NOT
  //     trigger re-renders, so the caret never jumps.
  //   - drag (mousedown + mouseenter) applies the cycle target to a block
  //
  import { DAYS, HOURS, DAY_NAMES_IT } from '../constants.js';

  export let value = [];
  export let onChange = (_v) => {};
  export let title = 'Disponibilita oraria';
  export let readonly = false;

  let dragOriginKey = null;
  let dragMoved = false;
  let dragMode = null;
  let dragApplied = new Set();

  // local mirror of value (so visual updates land in 1 frame even before the
  // parent has propagated the new prop back down).
  let cells = Array.isArray(value) ? value.slice() : [];
  $: if (Array.isArray(value)) cells = value.slice();

  // Per-cell local penalty drafts. The input writes here on every
  // keystroke; we only push to setCell() on `change` (blur or Enter).
  let drafts = {};

  function _key(d, h) { return d + '-' + h; }
  function _findIdx(arr, d, h) { return arr.findIndex((c) => c.day === d && c.hour === h); }

  function _commit(newCells) {
    cells = newCells;
    onChange(newCells);
  }

  function setCell(d, h, state, penalty) {
    const list = cells.filter((c) => !(c.day === d && c.hour === h));
    if (state !== 'free') {
      list.push({
        day: d, hour: h, state,
        soft_penalty: state === 'soft' ? Number(penalty ?? 100) : 0,
        reason: null
      });
    }
    _commit(list);
    // Reset draft for this cell if state is no longer soft
    if (state !== 'soft') delete drafts[_key(d, h)];
  }

  function nextState(cur) {
    if (cur === null) return 'soft';
    if (cur === 'soft') return 'hard';
    return 'free';
  }

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
      const cur = cells.find((c) => c.day === d0 && c.hour === h0) || null;
      dragMode = nextState(cur ? cur.state : null);
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
    const cur = cells.find((c) => c.day === d && c.hour === h) || null;
    setCell(d, h, nextState(cur ? cur.state : null));
  }

  // Input handlers (live edit; commit on change)
  function onPenaltyInput(ev, d, h) {
    drafts[_key(d, h)] = ev.target.value;
    drafts = drafts;  // svelte reactivity
  }

  function onPenaltyChange(ev, d, h) {
    if (readonly) return;
    const v = Number(ev.target.value);
    if (!Number.isFinite(v) || v < 0) {
      // restore from cell
      const cell = cells.find((c) => c.day === d && c.hour === h) || null;
      ev.target.value = cell ? cell.soft_penalty : 100;
      return;
    }
    setCell(d, h, 'soft', v);
  }

  function onPenaltyKeydown(ev, d, h) {
    if (ev.key === 'Enter') {
      ev.target.blur();
    } else if (ev.key === 'Escape') {
      const cell = cells.find((c) => c.day === d && c.hour === h) || null;
      ev.target.value = cell ? cell.soft_penalty : 100;
      ev.target.blur();
    }
  }
</script>

<svelte:window on:mouseup={onMouseUp}/>

<div class="select-none">
  <div class="flex items-baseline justify-between mb-2">
    <h3 class="!text-base">{title}</h3>
    <div class="flex gap-3 text-xs">
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-emerald-400 bg-emerald-100"></span> libero
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-amber-400 bg-amber-200"></span> SOFT (penalita)
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-red-400 bg-red-300"></span> HARD non disp.
      </span>
    </div>
  </div>
  <p class="text-xs text-ink-500 mb-2">
    Click sulla cella: libero -&gt; giallo -&gt; rosso -&gt; libero.
    Quando una cella e\` gialla, modifica la penalita direttamente nel
    campo numerico (cliccare nel campo non cambia il colore).
    Trascina per applicare lo stesso stato a un blocco.
  </p>
  <div class="overflow-x-auto">
    <table class="tbl">
      <thead>
        <tr>
          <th></th>
          {#each DAYS as d}<th class="text-center">{DAY_NAMES_IT[d]}</th>{/each}
        </tr>
      </thead>
      <tbody>
        {#each HOURS as h}
          <tr>
            <td class="text-xs text-ink-500 w-14">{h}:00</td>
            {#each DAYS as d}
              {@const cell = cells.find((c) => c.day === d && c.hour === h) || null}
              {@const isFree = !cell}
              {@const isSoft = cell && cell.state === 'soft'}
              {@const isHard = cell && cell.state === 'hard'}
              <td class="p-1 align-middle">
                <div class="relative h-9 rounded border cursor-pointer transition-colors flex items-center justify-center"
                  class:bg-emerald-50={isFree}
                  class:border-emerald-300={isFree}
                  class:hover:bg-emerald-100={isFree}
                  class:bg-amber-200={isSoft}
                  class:border-amber-400={isSoft}
                  class:bg-red-300={isHard}
                  class:border-red-500={isHard}
                  on:click={(e) => onCellClick(e, d, h)}
                  on:mousedown={(e) => onMouseDown(e, d, h)}
                  on:mouseenter={() => onMouseEnter(d, h)}
                  title={isSoft
                    ? 'SOFT - penalita ' + cell.soft_penalty + '. Click sui bordi per cambiare colore; modifica il numero per cambiare la penalita.'
                    : (isHard
                       ? 'HARD non disponibile' + (cell.reason ? ' - ' + cell.reason : '')
                       : 'Libero - click per cambiare')}>
                  {#if isFree}
                    <span class="text-emerald-700 font-semibold text-xs">-</span>
                  {:else if isHard}
                    <span class="text-red-900 font-semibold text-xs">X</span>
                  {:else}
                    <input type="number" min="0" max="9999" step="10"
                      class="block w-12 h-7 text-center text-xs font-semibold
                             text-amber-900 bg-amber-100 border border-amber-500 rounded
                             [appearance:textfield]
                             [&::-webkit-outer-spin-button]:appearance-none
                             [&::-webkit-inner-spin-button]:appearance-none
                             focus:outline-none focus:ring-2 focus:ring-amber-600/40"
                      value={drafts[_key(d, h)] ?? cell.soft_penalty}
                      on:click|stopPropagation
                      on:mousedown|stopPropagation
                      on:dblclick|stopPropagation
                      on:input={(e) => onPenaltyInput(e, d, h)}
                      on:change={(e) => onPenaltyChange(e, d, h)}
                      on:keydown={(e) => onPenaltyKeydown(e, d, h)}/>
                  {/if}
                </div>
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>
