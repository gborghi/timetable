<script>
  /**
   * Reusable pipeline stage selector.
   *
   * Props:
   *   value:    string[]   currently enabled stage keys (bind:value)
   *   stages:   Array<{key, label, default?, kind?: 'meta'|'phase'|'diag'}>
   *
   * Renders a vertical list of checkboxes. The component is purely
   * presentational; the parent decides what to do with the selected
   * stage list (kick off /api/optimize/full-pipeline, run them in
   * sequence, etc.).
   *
   * Used by: Workflow page card 9, Monitor "Piazza evento" modal,
   * any future "Sostituisci docente" / re-optimize modals.
   */
  export let value = [];
  export let stages = [];

  function toggle(key) {
    if (value.includes(key)) {
      value = value.filter((k) => k !== key);
    } else {
      value = [...value, key];
    }
  }
</script>

<div class="space-y-1.5">
  {#each stages as s (s.key)}
    <label class="flex items-start gap-2 text-sm cursor-pointer
                  hover:bg-ink-50 rounded px-1 py-0.5">
      <input type="checkbox"
             class="mt-1"
             checked={value.includes(s.key)}
             on:change={() => toggle(s.key)}/>
      <span class="flex-1">
        <span class="font-medium">{s.label}</span>
        {#if s.kind === 'diag'}
          <span class="ml-1 pill pill-amber !text-[10px]">diag</span>
        {:else if s.kind === 'phase'}
          <span class="ml-1 pill pill-blue !text-[10px]">phase</span>
        {:else if s.kind === 'meta'}
          <span class="ml-1 pill !text-[10px]">meta</span>
        {/if}
        {#if s.hint}
          <div class="text-[11px] text-ink-500">{s.hint}</div>
        {/if}
      </span>
    </label>
  {/each}
</div>
