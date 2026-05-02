<script>
  /**
   * Thin Apache ECharts wrapper for Svelte. Lazy-loads echarts on
   * mount so the dashboard pages don't pay the bundle cost.
   *
   * Props:
   *   option:  ECharts option object (reactive; the component
   *            re-renders on prop change).
   *   height:  pixel height (default 320)
   *   theme:   optional theme name (we register 'pitantum' below)
   */
  import { onMount, onDestroy } from 'svelte';

  export let option = {};
  export let height = 320;
  export let theme = 'pitantum';

  let el;
  let chart = null;
  let resizeObserver;

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

  // Reactive option update
  $: if (chart) chart.setOption(option || {}, true);
</script>

<div bind:this={el} style="width: 100%; height: {height}px"></div>
