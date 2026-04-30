<!--
  Compact legend for the keyboard-shortcut color matrices.

  Usage:
    <KeyboardConstraintLegend visible={hovering} />

  Subscribes to the global `heldKey` store from
  $lib/keyboardConstraintMode and highlights the active shortcut
  while the user is holding it. Hidden until `visible` is true so
  the matrix UI doesn't carry permanent footer noise.
-->
<script lang="ts">
  import { heldKey, LEGEND_ITEMS } from "$lib/keyboardConstraintMode";

  export let visible = false;
  /** "matrix" -> labels for AvailabilityMatrix (free/soft/hard/...).
      "room"   -> labels for ClassroomGrid (allowed/forbidden/...). */
  export let variant: "matrix" | "room" = "matrix";

  const ROOM_LABELS: Record<string, string> = {
    H: "VIETATA (HARD)",
    P: "PREFERITA",
    E: "OBBLIGATORIA",
    D: "SOFT +",
    A: "CONSENTITA",
    N: "RESET",
  };
</script>

{#if visible}
  <div
    class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]
           text-ink-600 bg-ink-50 border border-ink-200 rounded
           px-2 py-1.5"
    aria-label="Scorciatoie tastiera: tieni premuto un tasto e clicca sulla cella per impostare lo stato"
  >
    <span class="font-medium text-ink-700">Tieni premuto + click:</span>
    {#each LEGEND_ITEMS as it}
      {@const active = $heldKey === it.shortcut}
      <span
        class="inline-flex items-center gap-1 px-1 py-0.5 rounded transition-colors"
        class:bg-accent-500={active}
        class:text-white={active}
      >
        <kbd
          class="inline-block min-w-[18px] text-center font-mono text-[10px]
                 leading-none px-1 py-0.5 rounded border {active
                  ? 'bg-white/20 border-white text-white'
                  : 'bg-white border-ink-300 text-ink-800'}"
          >{it.key}</kbd
        >
        <span
          class="inline-block w-3 h-3 rounded-sm border {it.swatch}"
          aria-hidden="true"
        ></span>
        <span>{variant === "room" ? ROOM_LABELS[it.key] : it.label}</span>
      </span>
    {/each}
    {#if $heldKey}
      <span class="ml-auto text-[10px] text-ink-500 italic">
        Tasto attivo: <strong class="text-ink-800">{$heldKey.toUpperCase()}</strong>
      </span>
    {/if}
  </div>
{/if}
