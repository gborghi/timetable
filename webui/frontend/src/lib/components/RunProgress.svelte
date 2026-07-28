<script>
  // Slim progress bar for an async run, shown while it is pending/running.
  // `progress` is a fraction in [0, 1] (the /api/optimize/runs payload).
  export let status = null;
  export let progress = null;

  $: active = status === 'pending' || status === 'running';
  // `pending` has no real fraction yet -> show an indeterminate pulse.
  $: indeterminate = status === 'pending' || progress == null;
  $: pct = Math.max(0, Math.min(100, Math.round((progress ?? 0) * 100)));
</script>

{#if active}
  <span class="run-progress" title={indeterminate ? 'in coda / avvio…' : pct + '%'}
        role="progressbar" aria-valuemin="0" aria-valuemax="100"
        aria-valuenow={indeterminate ? undefined : pct}>
    <span class="run-progress__track">
      <span class="run-progress__bar"
            class:run-progress__bar--indet={indeterminate}
            style={indeterminate ? '' : `width:${pct}%`}></span>
    </span>
    {#if !indeterminate}
      <span class="run-progress__pct">{pct}%</span>
    {/if}
  </span>
{/if}

<style>
  .run-progress {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    vertical-align: middle;
  }
  .run-progress__track {
    display: inline-block;
    width: 72px;
    height: 6px;
    border-radius: 9999px;
    background: rgb(0 0 0 / 0.09);
    overflow: hidden;
  }
  .run-progress__bar {
    display: block;
    height: 100%;
    border-radius: 9999px;
    background: var(--color-accent-500, #3b82f6);
    transition: width 0.3s ease;
  }
  .run-progress__bar--indet {
    width: 40%;
    animation: run-progress-indet 1.1s ease-in-out infinite;
  }
  @keyframes run-progress-indet {
    0%   { margin-left: -40%; }
    100% { margin-left: 100%; }
  }
  .run-progress__pct {
    font-size: 10px;
    font-variant-numeric: tabular-nums;
    color: rgb(100 116 139);
  }
</style>
