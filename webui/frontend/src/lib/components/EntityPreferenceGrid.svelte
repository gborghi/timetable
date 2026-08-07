<!--
  Generic 5-state preference grid for "teacher likes/dislikes <entity>".
  Reused by Teacher modal for classes and curricula.

  Props:
    items:    Array<{key: string, label: string, hint?: string}>
              the entities to render (one card each).
    value:    Array<{key: string, state: string, soft_penalty: number}>
              current preferences. The component edits a copy and
              emits via onChange.
    onChange: callback(newValue) -> void
    title:    optional header
    subtitle: small italic helper line
    legendKey: 'matrix' | 'room' for the keyboard shortcut legend.

  States: allowed | soft | preferred | forbidden | enforced (the same
  taxonomy used in ClassroomGrid). Click cycles
    allowed -> soft -> preferred -> forbidden -> enforced -> allowed.
  Holding H/P/E/D/A/N + click sets the state directly (uses the
  global keyboardConstraintMode shortcuts).
-->
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { get } from "svelte/store";
  import {
    heldKey,
    startKeyboardConstraintMode,
    shortcutToRoomState,
  } from "$lib/keyboardConstraintMode";
  import KeyboardConstraintLegend from "./KeyboardConstraintLegend.svelte";

  type Item = { key: string; label: string; hint?: string };
  type Pref = { key: string; state: string; soft_penalty: number };

  export let items: Item[] = [];
  export let value: Pref[] = [];
  export let onChange: (v: Pref[]) => void = () => {};
  export let title = "";
  export let subtitle = "";
  export let collapsedByDefault = true;

  let collapsed = collapsedByDefault;
  let hovering = false;
  let kbCleanup: (() => void) | undefined;
  onMount(() => {
    kbCleanup = startKeyboardConstraintMode();
  });
  onDestroy(() => kbCleanup?.());

  $: byKey = new Map((value || []).map((p) => [p.key, p]));
  $: nSet = (value || []).filter((p) => p.state !== "allowed").length;

  function defaultPenalty(state: string): number {
    if (state === "soft") return 100;
    if (state === "preferred") return -100;
    return 0;
  }

  function nextState(cur: string): string {
    if (cur === "allowed") return "soft";
    if (cur === "soft") return "preferred";
    if (cur === "preferred") return "forbidden";
    if (cur === "forbidden") return "enforced";
    return "allowed";
  }

  function setItem(key: string, state: string, penalty?: number): void {
    const w = penalty == null ? defaultPenalty(state) : Number(penalty);
    let list = (value || []).filter((p) => p.key !== key);
    if (state !== "allowed") {
      list = [...list, { key, state, soft_penalty: w }];
    }
    onChange(list);
  }

  function onClick(ev: MouseEvent | KeyboardEvent, item: Item): void {
    const t = ev.target as HTMLElement | null;
    if (t && t.tagName === "INPUT") return;
    const shortcutState = shortcutToRoomState(get(heldKey));
    if (shortcutState !== null) {
      setItem(item.key, shortcutState);
      return;
    }
    const cur = byKey.get(item.key);
    setItem(item.key, nextState(cur ? cur.state : "allowed"));
  }

  function onPenaltyInput(ev: Event, item: Item): void {
    const cur = byKey.get(item.key);
    if (!cur) return;
    let v = Number((ev.target as HTMLInputElement).value);
    if (!Number.isFinite(v)) return;
    if (cur.state === "soft" && v < 0) v = Math.abs(v);
    if (cur.state === "preferred" && v > 0) v = -Math.abs(v);
    setItem(item.key, cur.state, v);
  }

  function colorClasses(state: string): string {
    if (state === "soft") return "bg-amber-200 border-amber-400 text-amber-900";
    if (state === "preferred") return "bg-sky-200 border-sky-400 text-sky-900";
    if (state === "forbidden") return "bg-red-200 border-red-400 text-red-900";
    if (state === "enforced") return "bg-emerald-700 border-emerald-900 text-white";
    return "bg-emerald-50 border-emerald-300 text-emerald-800";
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="select-none space-y-2"
     on:mouseenter={() => (hovering = true)}
     on:mouseleave={() => (hovering = false)}>
  <div class="flex items-baseline gap-2 flex-wrap">
    <button class="btn !text-xs !px-2 !py-1"
            on:click={() => (collapsed = !collapsed)}>
      {collapsed ? "+" : "-"} {title} ({nSet} settate / {items.length})
    </button>
    {#if subtitle}
      <span class="text-xs italic text-ink-500">{subtitle}</span>
    {/if}
  </div>
  {#if !collapsed}
    {#if items.length === 0}
      <p class="text-xs text-ink-400 italic">Nessun elemento.</p>
    {:else}
      <div class="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
        {#each items as it (it.key)}
          {@const pref = byKey.get(it.key)}
          {@const state = pref ? pref.state : "allowed"}
          <div class="rounded border-2 p-2 cursor-pointer transition-colors {colorClasses(state)}"
               role="button" tabindex="0"
               on:click={(e) => onClick(e, it)}
               on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e, it); } }}
               title={(state === "allowed" ? "Default (consentito)" :
                       state === "soft" ? "SOFT - penalita " + (pref?.soft_penalty ?? "") :
                       state === "preferred" ? "PREFERITA - bonus " + (pref?.soft_penalty ?? "") :
                       state === "forbidden" ? "VIETATO (HARD)" :
                       "OBBLIGATORIO (HARD)")
                       + (it.hint ? " - " + it.hint : "")
                       + " \nTieni H/P/E/D/A/N + click per impostare direttamente."}>
            <div class="font-semibold text-sm truncate">{it.label}</div>
            {#if it.hint}
              <div class="text-[10px] opacity-75 truncate">{it.hint}</div>
            {/if}
            {#if state === "soft" || state === "preferred"}
              <div class="mt-1">
                <input type="number" step="10"
                       class="w-full text-xs px-1 py-0.5 rounded border bg-white text-ink-900"
                       value={pref?.soft_penalty ?? defaultPenalty(state)}
                       on:click|stopPropagation
                       on:input={(e) => onPenaltyInput(e, it)}/>
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
    <KeyboardConstraintLegend visible={hovering} variant="room"/>
  {/if}
</div>
