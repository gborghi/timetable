<script>
  // Reusable 4-state availability matrix.
  //
  // States:
  //   free       (green) : no entry, no constraint
  //   soft       (yellow): SOFT non-preferred, positive penalty (default 100)
  //                        -- objective is penalised when this slot is used
  //   hard       (red)   : HARD unavailable
  //   preferred  (blue)  : SOFT preferred, negative penalty (default -100)
  //                        -- objective is REWARDED (gets a bonus) when this
  //                        slot is used
  //
  // Props:
  //   value:    Array<{day, hour, state, soft_penalty:int, reason?}>
  //   onChange: callback(newValue) -> void  (parent must reassign root state)
  //   title, readonly: cosmetics
  //
  // Click cycle on a cell BACKGROUND: free -> yellow(soft, +100) -> red(hard)
  //                                         -> blue(preferred, -100)
  //                                         -> dark-green(enforced) -> free
  // Inline numeric input visible when yellow OR blue. The input is freely
  // editable; commit happens on `change` (blur or Enter). Sign: positive on
  // yellow, negative on blue (auto-flipped if you toggle).

  import { DAYS, HOURS, DAY_NAMES_IT } from '../constants';

  export let value = [];
  export let onChange = (_v) => {};
  export let title = 'Disponibilita oraria';
  export let readonly = false;

  let dragOriginKey = null;
  let dragMoved = false;
  let dragMode = null;
  let dragApplied = new Set();

  let cells = Array.isArray(value) ? value.slice() : [];
  $: if (Array.isArray(value)) cells = value.slice();

  let drafts = {};

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

  function setCell(d, h, state, penalty) {
    const list = cells.filter((c) => !(c.day === d && c.hour === h));
    if (state !== 'free') {
      let pen;
      if (state === 'soft' || state === 'preferred') {
        pen = (penalty === undefined || penalty === null
                  ? _defaultPenaltyFor(state) : Number(penalty));
        // sign-clamp: yellow has positive, blue has negative
        if (state === 'soft' && pen < 0) pen = Math.abs(pen);
        if (state === 'preferred' && pen > 0) pen = -pen;
      } else {
        pen = 0;
      }
      list.push({
        day: d, hour: h, state,
        soft_penalty: pen,
        reason: null
      });
    }
    _commit(list);
    if (state !== 'soft' && state !== 'preferred') delete drafts[_key(d, h)];
  }

  function nextState(cur) {
    if (cur === null) return 'soft';
    if (cur === 'soft') return 'hard';
    if (cur === 'hard') return 'preferred';
    if (cur === 'preferred') return 'enforced';
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
    // Re-anchor sign by current state
    setCell(d, h, cell.state, v);
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
  <div class="flex items-baseline justify-between mb-2 flex-wrap gap-2">
    <h3 class="!text-base">{title}</h3>
    <div class="flex gap-3 text-xs flex-wrap">
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-emerald-400 bg-emerald-100"></span> libero
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-amber-400 bg-amber-200"></span> SOFT (penalita +)
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-red-400 bg-red-300"></span> HARD non disp.
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-sky-400 bg-sky-200"></span> PREFERITO (penalita -)
      </span>
      <span class="flex items-center gap-1">
        <span class="w-3 h-3 rounded-sm border border-emerald-700 bg-emerald-700"></span> ENFORCED (deve esserci)
      </span>
    </div>
  </div>
  <p class="text-xs text-ink-500 mb-2">
    Click sulla cella: libero -&gt; giallo (soft, +100) -&gt; rosso (hard) -&gt;
    blu (preferito, -100) -&gt; libero.
    Quando la cella e\` gialla o blu, modifica la penalita nel campo numerico.
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
              {@const isPref = cell && cell.state === 'preferred'}
              {@const isEnf  = cell && cell.state === 'enforced'}
              <td class="p-1 align-middle">
                <div class="relative h-9 rounded border cursor-pointer transition-colors flex items-center justify-center"
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
                  on:click={(e) => onCellClick(e, d, h)}
                  on:mousedown={(e) => onMouseDown(e, d, h)}
                  on:mouseenter={() => onMouseEnter(d, h)}
                  title={isSoft
                    ? 'SOFT - penalita ' + cell.soft_penalty
                    : isPref
                    ? 'PREFERITO - bonus ' + cell.soft_penalty
                    : isEnf
                    ? 'ENFORCED - DEVE essere occupata' + (cell.reason ? ' - ' + cell.reason : '')
                    : isHard
                    ? 'HARD non disponibile' + (cell.reason ? ' - ' + cell.reason : '')
                    : 'Libero - click per cambiare'}>
                  {#if isFree}
                    <span class="text-emerald-700 font-semibold text-xs">-</span>
                  {:else if isEnf}
                    <span class="text-white font-semibold text-xs">!</span>
                  {:else if isHard}
                    <span class="text-red-900 font-semibold text-xs">X</span>
                  {:else if isSoft}
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
                  {:else if isPref}
                    <input type="number" max="0" min="-9999" step="10"
                      class="block w-12 h-7 text-center text-xs font-semibold
                             text-sky-900 bg-sky-100 border border-sky-500 rounded
                             [appearance:textfield]
                             [&::-webkit-outer-spin-button]:appearance-none
                             [&::-webkit-inner-spin-button]:appearance-none
                             focus:outline-none focus:ring-2 focus:ring-sky-600/40"
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
