<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { QueryClientProvider } from '@tanstack/svelte-query';
  import { datasetState, refreshDataset, networkOnline,
           startNetworkMonitor } from '$lib/stores';
  import { navGroups, tappaFor, siblingsFor } from '$lib/nav';
  import { queryClient } from '$lib/queries/client';
  import Toast from '$lib/components/Toast.svelte';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import { tooltip } from '$lib/actions/tooltip';

  // Brand assets: paths into webui/frontend/static/branding/. The
  // SVG placeholder ships with the repo (logo_light.svg); when Giovanni
  // generates the final art via Grok he replaces the file in-place.
  // The img falls back to text-only when the file is missing entirely.
  const LOGO_LIGHT = '/branding/logo/logo_light.svg';
  let logoOk = false;
  function onLogoOk() { logoOk = true; }
  function onLogoErr() { logoOk = false; }

  const APP_VERSION = '0.1';
  // Brand: piTantum / Tempus Tantum, after Seneca, Ep. I, 1.
  const SENECA_LATIN = 'Omnia, Lucili, aliena sunt, tempus tantum nostrum est.';
  const SENECA_IT = 'Tutto, Lucilio, ci viene da altri; soltanto il tempo e\' nostro.';

  // Densita' della UI. 'compatta' e' il default (piu' righe a schermo,
  // e' un applicativo da scrivania); 'comfort' allarga padding e righe
  // via le variabili --pad-* in app.css. Sta su <html> perche' deve
  // valere anche per i portali (tooltip, dialog) montati fuori da qui.
  let density = 'compatta';
  function applyDensity(d) {
    density = d;
    if (typeof document !== 'undefined') document.documentElement.dataset.density = d;
    try { localStorage.setItem('pt_density', d); } catch (_e) { /**/ }
  }

  onMount(() => {
    refreshDataset();
    startNetworkMonitor(30000);
    let saved = null;
    try { saved = localStorage.getItem('pt_density'); } catch (_e) { /**/ }
    applyDensity(saved === 'comfort' ? 'comfort' : 'compatta');
  });

  $: cur = $page.url.pathname;

  // Track which menu is open (only one at a time, click-driven).
  let openMenu = null;
  function toggleMenu(name) {
    openMenu = openMenu === name ? null : name;
  }
  function closeMenu() { openMenu = null; }
  // Close any open dropdown when the route changes.
  $: if (cur !== undefined) openMenu = null;
  function isLinkActive(href, exact) {
    if (exact) return cur === href;
    return cur === href || cur.startsWith(href + '/');
  }
  function isMenuActive(menu) {
    return menu.children.some((c) => isLinkActive(c.href, false));
  }
  function onMenuKeydown(ev, name) {
    if (ev.key === 'Escape') closeMenu();
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggleMenu(name); }
  }

  // Striscia della tappa: sotto l'header, mostra a che punto del
  // percorso siamo e le pagine sorelle. Compare solo dove ha senso
  // (non su Dashboard e Import bulk, che non appartengono a una tappa).
  $: tappa = tappaFor(cur);
  $: siblings = siblingsFor(cur);

  // Classi delle voci di navigazione. Stanno qui e non nel markup
  // perche' attivo/inattivo cambiano colore, sfondo e peso insieme:
  // con le direttive class: servirebbero cinque righe per voce.
  const NAV_BASE = 'px-3 py-1.5 text-[13px] rounded-[7px] focus-ring whitespace-nowrap';
  const NAV_ON = 'bg-paper-sunk text-ink-900 font-medium';
  const NAV_OFF = 'text-ink-500 hover:bg-ink-100 hover:text-ink-900';
  const navClass = (on) => `${NAV_BASE} ${on ? NAV_ON : NAV_OFF}`;

  const STRIP_BASE = 'px-[11px] py-1 rounded-full text-[12px] focus-ring';
  const stripClass = (on) => `${STRIP_BASE} ${on
    ? 'bg-accent-500 text-white font-medium'
    : 'bg-white border border-ink-200 text-ink-500 hover:text-ink-900'}`;
</script>

<QueryClientProvider client={queryClient}>
<div class="min-h-screen flex flex-col bg-paper">
  <a href="#main-content" class="skip-link">Vai al contenuto principale</a>
  {#if !$networkOnline}
    <div class="bg-red-600 text-white text-sm px-4 py-2 text-center"
         role="alert" aria-live="assertive">
      <strong>Backend non raggiungibile.</strong>
      Verifica che il server FastAPI sia attivo
      (<code>start.bat</code> / <code>./start.sh</code>).
      Le modifiche fatte ora non saranno salvate.
    </div>
  {/if}

  <header class="bg-white border-b border-ink-200">
    <div class="max-w-[1500px] mx-auto px-6 min-h-[60px] flex items-center gap-4">
      <a href="/" class="flex items-center gap-2.5 shrink-0"
         title={SENECA_LATIN}>
        <img src={LOGO_LIGHT} alt="piTantum"
             class="h-[34px] w-[34px]"
             class:hidden={!logoOk}
             on:load={onLogoOk} on:error={onLogoErr}/>
        <span class="font-serif text-xl font-semibold"
              style="color: var(--brand-primary);">
          <span class="italic" style="color: var(--brand-secondary);">π</span>Tantum
        </span>
      </a>
      <span class="hidden sm:inline text-[10px] font-semibold uppercase
                   tracking-wide text-ink-400 shrink-0 -ml-1"
            title="Sviluppato con l'aiuto dell'intelligenza artificiale (Claude)"
            data-testid="built-with-ai">built with AI</span>
      <div class="w-px h-6 bg-ink-200 shrink-0" aria-hidden="true"></div>

      <nav class="flex flex-wrap gap-[3px] relative min-w-0"
           aria-label="Navigazione principale"
           data-testid="navbar">
        {#each navGroups as g}
          {#if g.kind === 'link'}
            {@const active = isLinkActive(g.href, g.exact)}
            <a href={g.href}
               class={navClass(active)}
               aria-current={active ? 'page' : undefined}
               use:tooltip={g.hint}
               data-testid="nav-link"
               data-nav-label={g.label}>{g.label}</a>
          {:else}
            {@const active = isMenuActive(g)}
            {@const open = openMenu === g.label}
            <div class="relative">
              <button type="button"
                      class="{navClass(active || open)} inline-flex items-center gap-1"
                      aria-haspopup="true"
                      aria-expanded={open}
                      use:tooltip={g.hint}
                      data-testid="nav-menu"
                      data-nav-label={g.label}
                      on:click={() => toggleMenu(g.label)}
                      on:keydown={(e) => onMenuKeydown(e, g.label)}>
                {g.label}
                <svg class="w-3 h-3 opacity-60" viewBox="0 0 12 12"
                     fill="none" stroke="currentColor" stroke-width="1.5"
                     aria-hidden="true">
                  <path d="M3 4.5 L6 7.5 L9 4.5"/>
                </svg>
              </button>
              {#if open}
                <div class="absolute left-0 top-full mt-1 z-30
                            min-w-[11rem] bg-white border border-ink-200
                            rounded-[9px] shadow-lg py-1"
                     role="menu"
                     tabindex="-1"
                     data-testid="nav-dropdown"
                     data-nav-parent={g.label}
                     on:mouseleave={closeMenu}>
                  {#each g.children as c}
                    {@const childActive = isLinkActive(c.href, false)}
                    <a href={c.href}
                       class="block {navClass(childActive)} !rounded-none"
                       role="menuitem"
                       aria-current={childActive ? 'page' : undefined}
                       use:tooltip={c.hint}
                       data-testid="nav-child-link"
                       data-nav-label={c.label}
                       on:click={closeMenu}>{c.label}</a>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        {/each}
      </nav>
      <!-- Click-outside catcher for open dropdowns -->
      {#if openMenu}
        <button type="button" tabindex="-1"
                class="fixed inset-0 z-20 cursor-default"
                aria-hidden="true"
                on:click={closeMenu}></button>
      {/if}

      <div class="ml-auto flex items-center gap-3 shrink-0">
        <span class="hidden lg:inline font-mono text-[11px] text-ink-300 tabular-nums">
          {$datasetState.classes} classi · {$datasetState.teachers} docenti ·
          {$datasetState.classrooms} aule
        </span>
        {#if $datasetState.active_solution}
          <span class="pill-green">obj {$datasetState.active_solution.obj_value}</span>
        {:else}
          <span class="pill-amber">no soluzione attiva</span>
        {/if}
        <div class="flex border border-ink-200 rounded-[7px] overflow-hidden text-[11px]"
             role="group" aria-label="Densita' dell'interfaccia">
          {#each ['compatta', 'comfort'] as d}
            <button type="button"
                    class="px-[9px] py-1 focus-ring {density === d
                             ? 'bg-accent-500 text-white'
                             : 'text-ink-500 hover:bg-ink-50'}
                           {d === 'comfort' ? 'border-l border-ink-200' : ''}"
                    aria-pressed={density === d}
                    data-testid="density-{d}"
                    on:click={() => applyDensity(d)}>{d}</button>
          {/each}
        </div>
      </div>
    </div>
  </header>

  {#if tappa && siblings}
    <!-- Striscia della tappa: dove sono nel percorso, e cos'altro c'e'
         in questo capitolo. -->
    <div class="bg-paper-band border-b border-ink-200">
      <div class="max-w-[1500px] mx-auto px-6 py-[9px]
                  flex flex-wrap items-center gap-1.5">
        <span class="eyebrow mr-2">Tappa {tappa.n} · {tappa.label}</span>
        {#each siblings as c}
          {@const childActive = isLinkActive(c.href, false)}
          <a href={c.href}
             class={stripClass(childActive)}
             aria-current={childActive ? 'page' : undefined}
             use:tooltip={c.hint}>{c.label}</a>
        {/each}
      </div>
    </div>
  {/if}

  <main id="main-content" tabindex="-1"
        class="flex-1 max-w-[1500px] w-full mx-auto px-6 py-6 focus:outline-none">
    <slot />
  </main>

  <footer class="border-t border-ink-200 bg-white">
    <div class="max-w-[1500px] mx-auto px-6 py-3 text-[11.5px] text-ink-300
                flex flex-wrap gap-3 items-baseline">
      <span class="font-serif font-semibold text-[15px]"
            style="color: var(--brand-primary);">
        <span class="italic" style="color: var(--brand-secondary);">π</span>Tantum
      </span>
      <span class="font-serif italic text-ink-500" title={SENECA_IT}>
        {SENECA_LATIN}
      </span>
      <span class="font-mono">v{APP_VERSION}</span>
      <span class="ml-auto font-mono">Engine: ortools</span>
    </div>
  </footer>
</div>

<Toast />
<ConfirmDialog />
</QueryClientProvider>
