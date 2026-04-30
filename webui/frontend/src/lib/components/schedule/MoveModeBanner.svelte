<!--
  Banner shown above the matrix when the user has clicked "sposta" on a
  lesson and the page is in move-mode. The schedule page renders this
  three times (one per matrix view); extracting it keeps the parent
  small and the wording centralised.
-->
<script>
  import { DAY_NAMES_IT } from '$lib/constants';

  export let moveSrc;            // {subject, cls, teacher, day, hour}
  export let movePreviewBusy = false;
  export let showLegend = false; // class matrix shows a green/yellow/red legend
  export let onCancel;

  function cancel() { onCancel && onCancel(); }
</script>

{#if moveSrc}
  <div class="card p-3 bg-accent-500/5 border-accent-500/40 flex items-center gap-3 flex-wrap">
    <strong>Modalita sposta:</strong>
    <span class="text-sm">
      {moveSrc.subject} ({moveSrc.cls} con {moveSrc.teacher}) da
      <code>{DAY_NAMES_IT[moveSrc.day]} {moveSrc.hour}:00</code>
    </span>
    {#if showLegend}
      <span class="text-xs text-ink-500">
        verde = mossa OK / migliora SOFT,
        giallo = peggiora SOFT (con delta),
        rosso = HARD violato.
        {movePreviewBusy ? ' (calcolo preview...)' : ''}
      </span>
    {/if}
    <button class="btn !text-xs ml-auto" on:click={cancel}>Esc</button>
  </div>
{/if}
