<!--
  Tiny hint rendered inside an empty cell during move-mode: shows the
  delta_soft for OK/soft_worse moves, X for HARD violations, otherwise
  a placeholder dash. Three matrix views all need it.
-->
<script>
  export let preview;     // {status, delta_soft, reason} | null
  export let active;      // boolean: are we currently in move-mode?
</script>

<div class="text-ink-300 text-center">
  {#if active && preview}
    {#if preview.status === 'ok' && preview.delta_soft != null}
      <span class="text-emerald-700 font-semibold">{preview.delta_soft >= 0 ? '+' : ''}{preview.delta_soft}</span>
    {:else if preview.status === 'soft_worse'}
      <span class="text-amber-700 font-semibold">+{preview.delta_soft}</span>
    {:else if preview.status === 'hard_violation'}
      <span class="text-red-700">X</span>
    {/if}
  {:else}
    -
  {/if}
</div>
