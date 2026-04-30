<script>
  import { onDestroy } from 'svelte';
  import { streamRun, api } from '../api';
  export let runId = null;
  export let title = 'Log';
  export let onEnd = () => {};

  let lines = [];
  let status = null;
  let unsub = null;
  let logEl;

  $: if (runId) reset(runId);

  function reset(rid) {
    if (unsub) unsub();
    lines = [];
    status = null;
    unsub = streamRun(rid, {
      onLog: (l) => {
        lines = [...lines, l].slice(-2000);
        queueMicrotask(() => { if (logEl) logEl.scrollTop = logEl.scrollHeight; });
      },
      onStatus: (s) => { status = s; },
      onEnd: (s) => { onEnd(s); }
    });
  }

  onDestroy(() => { if (unsub) unsub(); });
</script>

<div class="card">
  <div class="flex items-center justify-between border-b border-ink-100 px-4 py-2">
    <div class="font-medium">{title}</div>
    {#if status}
      <div class="flex items-center gap-2 text-xs">
        <span class="pill" class:pill-green={status.status === 'done'} class:pill-red={status.status === 'failed'} class:pill-blue={status.status === 'running'}>
          {status.status}
        </span>
        {#if status.progress != null}
          <span class="text-ink-500">{Math.round(status.progress * 100)}%</span>
        {/if}
        {#if status.obj_value != null}
          <span class="text-ink-500">obj={status.obj_value}</span>
        {/if}
      </div>
    {/if}
  </div>
  <pre bind:this={logEl}
       class="overflow-auto text-xs text-ink-700 leading-snug font-mono whitespace-pre-wrap p-3 max-h-[460px] min-h-[200px]">{lines.join('\n')}</pre>
  {#if status?.metrics && Object.keys(status.metrics).length}
    <div class="border-t border-ink-100 px-4 py-2 text-xs text-ink-500">
      Metriche: {Object.entries(status.metrics).map(([k, v]) => `${k}=${v}`).join(' · ')}
    </div>
  {/if}
</div>
