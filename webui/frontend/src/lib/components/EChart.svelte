<script>
  /**
   * Thin Apache ECharts wrapper for Svelte. Lazy-loads echarts on
   * mount so the dashboard pages don't pay the bundle cost.
   *
   * Props:
   *   option:      ECharts option object (reactive; the component
   *                re-renders on prop change).
   *   height:      pixel height (default 320)
   *   theme:       optional theme name (we register 'pitantum' below)
   *   showActions: when true, shows "Export PNG" + "Clear" buttons in
   *                a small toolbar above the canvas. Default true so
   *                every diagnostic chart gets them for free.
   *   exportName:  filename (without extension) used by Export PNG.
   */
  import { onMount, onDestroy } from 'svelte';

  export let option = {};
  export let height = 320;
  export let theme = 'pitantum';
  export let showActions = true;
  export let exportName = 'chart';

  let el;
  let chart = null;
  let resizeObserver;
  let cleared = false;       // when true the chart is blanked

  // Brand palette: indaco / oro / avorio / terra di siena
  const PITANTUM_THEME = {
    color: ['#3f3d8e', '#c9a45c', '#e7dccc', '#a04425',
             '#5b8db8', '#5d8a4a', '#a83a5b', '#3d8a8a'],
    backgroundColor: 'transparent',
    textStyle: { color: '#1f2937' },
    title: { textStyle: { color: '#1f2937' } },
    grid: { left: '8%', right: '5%', bottom: '14%', top: '12%' },
    legend: { textStyle: { color: '#1f2937' } },
    tooltip: { backgroundColor: '#fafaf9', borderColor: '#d6d3d1' },
    xAxis: { axisLine: { lineStyle: { color: '#9ca3af' } } },
    yAxis: { axisLine: { lineStyle: { color: '#9ca3af' } } },
  };

  onMount(async () => {
    const echarts = await import('echarts');
    try {
      echarts.registerTheme(theme, PITANTUM_THEME);
    } catch { /* already registered */ }
    chart = echarts.init(el, theme);
    chart.setOption(option || {});
    resizeObserver = new ResizeObserver(() => {
      if (chart) chart.resize();
    });
    resizeObserver.observe(el);
  });

  onDestroy(() => {
    if (resizeObserver) resizeObserver.disconnect();
    if (chart) chart.dispose();
  });

  // Reactive option update -- skipped while the user has cleared the
  // chart manually (so a re-render doesn't undo their click).
  $: if (chart && !cleared) chart.setOption(option || {}, true);

  /** Export the current canvas as a PNG download. */
  function exportPng() {
    if (!chart) return;
    const url = chart.getDataURL({
      type: 'png',
      pixelRatio: 2,
      backgroundColor: '#ffffff',
    });
    const a = document.createElement('a');
    a.href = url;
    const ts = new Date().toISOString().replace(/[:.]/g, '-')
                  .slice(0, 19);
    a.download = `${exportName || 'chart'}_${ts}.png`;
    a.click();
  }

  /** Wipe the chart (the user can re-render it by re-running the
   *  diagnostic; we keep `option` intact in the parent). */
  function clearChart() {
    if (!chart) return;
    chart.clear();
    cleared = true;
  }

  /** Re-apply the current `option` (manual restore after Clear). */
  function restoreChart() {
    if (!chart) return;
    cleared = false;
    chart.setOption(option || {}, true);
  }
</script>

<div class="flex flex-col">
  {#if showActions}
    <div class="flex justify-end gap-1 text-[10px] mb-1">
      {#if cleared}
        <button class="btn !text-[10px] !px-2 !py-0.5"
                on:click={restoreChart}
                title="Ripristina il grafico cancellato">
          Ripristina
        </button>
      {/if}
      <button class="btn !text-[10px] !px-2 !py-0.5"
              on:click={exportPng}
              title="Scarica il grafico come PNG">
        Export PNG
      </button>
      <button class="btn !text-[10px] !px-2 !py-0.5"
              on:click={clearChart}
              disabled={cleared}
              title="Svuota il grafico (puoi ripristinarlo o lanciare di nuovo)">
        Clear
      </button>
    </div>
  {/if}
  <div bind:this={el} style="width: 100%; height: {height}px"></div>
</div>
