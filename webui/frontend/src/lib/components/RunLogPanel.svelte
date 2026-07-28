<script>
  import { onDestroy } from 'svelte';
  import { streamRun, api } from '../api';
  import { appendCapped, MAX_LOG_LINES } from '../log_buffer';
  export let runId = null;
  export let title = 'Log';
  export let onEnd = () => {};

  let lines = [];
  let status = null;
  let unsub = null;
  let logEl;

  // Incoming SSE lines are batched and flushed at most once per animation
  // frame: a fast solver can stream thousands of lines/sec, and merging
  // + re-rendering per line is O(n^2). `pending` accumulates between
  // frames; `flush` caps and assigns once (see log_buffer.appendCapped).
  let pending = [];
  let rafId = null;

  $: if (runId) reset(runId);

  function scheduleFlush() {
    if (rafId != null) return;
    rafId = requestAnimationFrame(flush);
  }
  function cancelFlush() {
    if (rafId != null) { cancelAnimationFrame(rafId); rafId = null; }
  }
  function flush() {
    rafId = null;
    if (!pending.length) return;
    // Only auto-scroll to the tail if the user is already near the
    // bottom; if they scrolled up to read earlier lines, leave them be.
    const el = logEl;
    const atBottom = !el
      || (el.scrollHeight - el.scrollTop - el.clientHeight <= 40);
    lines = appendCapped(lines, pending, MAX_LOG_LINES);
    pending = [];
    if (atBottom) {
      queueMicrotask(() => {
        if (logEl) logEl.scrollTop = logEl.scrollHeight;
      });
    }
  }

  function reset(rid) {
    if (unsub) unsub();
    cancelFlush();
    lines = [];
    pending = [];
    status = null;
    unsub = streamRun(rid, {
      onLog: (l) => { pending.push(l); scheduleFlush(); },
      onStatus: (s) => { status = s; },
      onEnd: (s) => { flush(); onEnd(s); }
    });
  }

  onDestroy(() => { if (unsub) unsub(); cancelFlush(); });
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
