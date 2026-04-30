<script>
  // Reusable 4-state classroom-preference grid.
  //
  // States (per classroom):
  //   allowed   (verdino, default): the entity may use the room
  //   soft      (giallo)          : SOFT penalty when used (positive weight)
  //   preferred (blu)             : SOFT bonus when used (negative weight)
  //   forbidden (rosso)           : HARD: cannot be in this room (no weight)
  //   enforced  (verde scuro)     : HARD: MUST be in a room of this kind
  //
  // Props:
  //   classrooms: full list of {id, name, kind, capacity, ...}
  //   value:      Array<{classroom_name, state, weight}>
  //   onChange:   callback(newValue)
  //   title:      optional header
  //   readonly
  //
  // Click cycle on a card: allowed -> preferred -> forbidden -> enforced -> allowed.
  // Numeric weight input is shown for preferred (negative default) and forbidden
  // (irrelevant — kept for symmetry but inert when state=hard).
  //
  // The grid is filtered by an optional kind filter and a free-text name filter.

  import { onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import {
    heldKey,
    startKeyboardConstraintMode,
    shortcutToRoomState
  } from '../keyboardConstraintMode';
  import KeyboardConstraintLegend from './KeyboardConstraintLegend.svelte';

  export let classrooms = [];
  export let value = [];
  export let onChange = (_v) => {};
  export let title = 'Aule (preferenze)';
  export let readonly = false;
  export let collapsedByDefault = true;

  let collapsed = collapsedByDefault;
  let kindFilter = '';
  let nameFilter = '';
  let hovering = false;

  // Keyboard listener (ref-counted globally).
  let kbCleanup;
  onMount(() => { kbCleanup = startKeyboardConstraintMode(); });
  onDestroy(() => kbCleanup?.());

  $: byName = new Map((value || []).map((p) => [p.classroom_name, p]));
  $: kinds = [...new Set((classrooms || []).map((c) => c.kind))];

  $: filteredRooms = (classrooms || []).filter((r) => {
    if (kindFilter && r.kind !== kindFilter) return false;
    if (nameFilter && !r.name.toLowerCase().includes(nameFilter.toLowerCase())
        && !r.kind.toLowerCase().includes(nameFilter.toLowerCase()))
      return false;
    return true;
  });

  function defaultWeightFor(state) {
    if (state === 'soft') return 100;
    if (state === 'preferred') return -100;
    if (state === 'forbidden') return 0;   // HARD, weight unused
    if (state === 'enforced') return 0;
    return 0;
  }

  function nextState(cur) {
    if (cur === 'allowed') return 'soft';
    if (cur === 'soft') return 'preferred';
    if (cur === 'preferred') return 'forbidden';
    if (cur === 'forbidden') return 'enforced';
    return 'allowed';
  }

  function setRoom(name, state, weight) {
    const cur = byName.get(name) || { classroom_name: name,
                                      state: 'allowed', weight: 0 };
    const w = (weight === undefined || weight === null
                ? defaultWeightFor(state) : Number(weight));
    const next = { classroom_name: name, state, weight: w };
    let list = (value || []).filter((p) => p.classroom_name !== name);
    if (state !== 'allowed') list = [...list, next];
    onChange(list);
  }

  function onClick(ev, room) {
    if (readonly) return;
    const t = ev.target;
    if (t && (t.tagName === 'INPUT')) return;
    // If a shortcut key is held, set the state directly; otherwise
    // advance the click-cycle.
    const shortcutState = shortcutToRoomState(get(heldKey));
    if (shortcutState !== null) {
      setRoom(room.name, shortcutState);
      return;
    }
    const cur = byName.get(room.name);
    setRoom(room.name, nextState(cur ? cur.state : 'allowed'));
  }

  function onWeightInput(ev, room) {
    if (readonly) return;
    const cur = byName.get(room.name);
    if (!cur) return;
    let v = Number(ev.target.value);
    if (!Number.isFinite(v)) return;
    if (cur.state === 'soft' && v < 0) v = Math.abs(v);
    if (cur.state === 'preferred' && v > 0) v = -Math.abs(v);
    setRoom(room.name, cur.state, v);
  }

  function colorClasses(state) {
    if (state === 'soft')      return 'bg-amber-200 border-amber-400 text-amber-900';
    if (state === 'preferred') return 'bg-sky-200 border-sky-400 text-sky-900';
    if (state === 'forbidden') return 'bg-red-200 border-red-400 text-red-900';
    if (state === 'enforced')  return 'bg-emerald-700 border-emerald-900 text-white';
    return 'bg-emerald-50 border-emerald-300 text-emerald-800';
  }
</script>

<div class="select-none space-y-2"
     on:mouseenter={() => (hovering = true)}
     on:mouseleave={() => (hovering = false)}>
  <div class="flex items-baseline gap-2 flex-wrap">
    <button class="btn !text-xs !px-2 !py-1"
            on:click={() => (collapsed = !collapsed)}>
      {collapsed ? '+' : '-'} {title} ({(value || []).filter((p) => p.state !== 'allowed').length} settate / {(classrooms || []).length})
    </button>
    {#if !collapsed}
      <select bind:value={kindFilter}
              class="text-xs px-2 py-1 border border-ink-200 rounded">
        <option value="">tutti i tipi</option>
        {#each kinds as k}<option value={k}>{k}</option>{/each}
      </select>
      <input class="text-xs px-2 py-1 border border-ink-200 rounded"
             placeholder="filtra per nome/tipo..."
             bind:value={nameFilter}/>
      <span class="text-[11px] text-ink-500 ml-auto">
        click cicla:
        <span class="pill-c-allowed">verdino</span>
        ->
        <span class="pill-c-soft">giallo (+)</span>
        ->
        <span class="pill-c-preferred">blu (-)</span>
        ->
        <span class="pill-c-hard">rosso (HARD)</span>
        ->
        <span class="pill-c-enforced">verdone (must)</span>
      </span>
    {/if}
  </div>

  {#if !collapsed}
    {#if filteredRooms.length === 0}
      <p class="text-xs text-ink-400 italic">Nessuna aula trovata.</p>
    {:else}
      <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
        {#each filteredRooms as room (room.id)}
          {@const pref = byName.get(room.name)}
          {@const state = pref ? pref.state : 'allowed'}
          <div class="rounded border-2 p-2 cursor-pointer transition-colors {colorClasses(state)}"
               on:click={(e) => onClick(e, room)}
               title={(state === 'allowed' ? 'Aula consentita (default)' :
                      state === 'soft' ? 'SOFT - penalita ' + (pref?.weight ?? '') :
                      state === 'preferred' ? 'PREFERITA - bonus ' + (pref?.weight ?? '') :
                      state === 'forbidden' ? 'VIETATA (HARD, no penalty)' :
                      'OBBLIGATORIA (enforced)')
                      + ' \nTieni H/P/E/D/A/N + click per impostare direttamente.'}>
            <div class="flex items-baseline justify-between">
              <strong class="text-sm truncate">{room.name}</strong>
              <span class="text-[10px] opacity-75">{room.kind}</span>
            </div>
            <div class="text-[10px] opacity-75">cap. {room.capacity}</div>
            {#if state === 'soft' || state === 'preferred'}
              <div class="mt-1">
                <input type="number" step="10"
                       class="w-full text-xs px-1 py-0.5 rounded border bg-white text-ink-900"
                       value={pref?.weight ?? defaultWeightFor(state)}
                       on:click|stopPropagation
                       on:input={(e) => onWeightInput(e, room)}/>
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
    <KeyboardConstraintLegend visible={hovering} variant="room"/>
  {/if}
</div>
