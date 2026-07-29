<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { QueryClientProvider } from '@tanstack/svelte-query';
  import { datasetState, refreshDataset, networkOnline,
           startNetworkMonitor } from '$lib/stores';
  import { queryClient } from '$lib/queries/client';
  import Toast from '$lib/components/Toast.svelte';
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

  // Top-level nav: 8 entries. Anagrafica, Pianificazione, Gestione e
  // Esecuzione sono dropdown che raggruppano sotto-pagine; le altre
  // sono link diretti. Vincoli sta sotto Pianificazione (e' un'azione
  // della fase di pianificazione, non un capitolo a parte). Orario
  // sale a tab standalone perche' e' la pagina che si visita di gran
  // lunga piu' spesso. Eventi (ex Monitor) e' standalone perche' e'
  // il pannello di run real-time, indipendente dalla pipeline di
  // ottimizzazione. Gestione raggruppa tutto cio' che riguarda la
  // gestione operativa post-orario (assenze, supplenze, ...).
  const navGroups = [
    { kind: 'link', href: '/', label: 'Dashboard', exact: true,
      hint: 'Panoramica: carica/genera la scuola, stato dei dati e dei run in corso.' },
    { kind: 'menu', label: 'Anagrafica',
      hint: 'I dati di base della scuola: chi insegna, quali classi, materie, aule.', children: [
      { href: '/teachers',   label: 'Docenti',
        hint: 'Docenti: ore, disponibilita oraria, giorni liberi, preferenze e materie insegnabili.' },
      { href: '/classes',    label: 'Classi',
        hint: 'Classi: monte ore per materia, indirizzo, n. studenti e vincoli di classe.' },
      { href: '/curricula',  label: 'Indirizzi',
        hint: 'Indirizzi (curricula): il piano orario per anno di corso, riusabile fra classi.' },
      { href: '/students',   label: 'Studenti',
        hint: 'Studenti: anagrafica, tag e appartenenza a gruppi.' },
      { href: '/groups',     label: 'Gruppi',
        hint: 'Gruppi studio: sottogruppi inter/intra-classe (potenziamento, splitting).' },
      { href: '/subjects',   label: 'Materie',
        hint: 'Materie: nomi, pesi di distribuzione e preferenze d\'aula.' },
      { href: '/classrooms', label: 'Aule',
        hint: 'Aule e laboratori: capienza, tipo, disponibilita e preferenze per materia.' },
      { href: '/plessi',     label: 'Plessi',
        hint: 'Plessi (sedi): regole di spostamento fra edifici e politiche per giorno.' },
      { href: '/ore',        label: 'Ore',
        hint: 'Tab Ore: definisce la settimana scolastica (giorni attivi e fasce orarie).' },
    ] },
    { kind: 'menu', label: 'Pianificazione',
      hint: 'Le decisioni a monte del solver: compresenze, cattedre e vincoli.', children: [
      { href: '/coteaching',  label: 'Compresenze',
        hint: 'Compresenze: due o piu docenti nella stessa ora/classe (es. laboratorio).' },
      { href: '/assignments', label: 'Cattedre',
        hint: 'Cattedre (Fase A): assegna ogni (classe, materia) a un docente.' },
      { href: '/constraints', label: 'Vincoli',
        hint: 'Vincoli: regole hard/soft sull\'orario, anche in linguaggio DSL generale.' },
    ] },
    { kind: 'link', href: '/schedule', label: 'Orario',
      hint: 'Orario: editor settimanale drag-and-drop con anteprima dei conflitti.' },
    { kind: 'menu', label: 'Gestione',
      hint: 'Gestione operativa dopo l\'orario: assenze e supplenze.', children: [
      { href: '/assenze-supplenze', label: 'Assenze e supplenze',
        hint: 'Assenze e supplenze: copertura settimanale e riassegnazione docenti.' },
    ] },
    { kind: 'menu', label: 'Esecuzione',
      hint: 'Far girare il solver e analizzare i risultati.', children: [
      { href: '/optimize',    label: 'Workflow',
        hint: 'Workflow: pipeline del solver (Fase A, Fase B, metaeuristiche, aule).' },
      { href: '/runs',        label: 'Runs',
        hint: 'Runs: storico delle esecuzioni con stato, log e metriche.' },
      { href: '/diagnostics', label: 'Statistiche',
        hint: 'Statistiche: pre-check Hall, Monte Carlo, matching e distribuzioni.' },
    ] },
    { kind: 'link', href: '/monitor', label: 'Eventi',
      hint: 'Eventi: editor delle cattedre/lezioni grezze con filtri e azioni di massa.' },
    { kind: 'link', href: '/import',  label: 'Import bulk',
      hint: 'Import bulk: carica docenti, classi, aule e altro da file xlsx/csv.' },
  ];

  onMount(() => {
    refreshDataset();
    startNetworkMonitor(30000);
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
</script>

<QueryClientProvider client={queryClient}>
<div class="min-h-screen flex flex-col">
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
    <div class="max-w-[1500px] mx-auto px-6 py-3 flex items-center gap-4">
      <a href="/" class="flex items-center gap-3 leading-tight"
         title={SENECA_LATIN}>
        <img src={LOGO_LIGHT} alt="piTantum"
             class="h-10 w-auto"
             class:hidden={!logoOk}
             on:load={onLogoOk} on:error={onLogoErr}/>
        <span class="flex flex-col">
          <span class="text-xl font-semibold tracking-tight"
                style="color: var(--brand-primary);">
            <span class="font-serif italic" style="color: var(--brand-secondary);">π</span>Tantum
          </span>
          <span class="text-[10px] italic text-ink-400 -mt-0.5 max-w-md">
            {SENECA_LATIN}
          </span>
        </span>
      </a>
      <nav class="flex flex-wrap gap-1 ml-4 relative"
           aria-label="Navigazione principale"
           data-testid="navbar">
        {#each navGroups as g}
          {#if g.kind === 'link'}
            {@const active = isLinkActive(g.href, g.exact)}
            <a href={g.href}
               class="px-3 py-1.5 text-sm rounded-md hover:bg-ink-100 focus-ring"
               class:bg-ink-100={active}
               class:font-medium={active}
               aria-current={active ? 'page' : undefined}
               use:tooltip={g.hint}
               data-testid="nav-link"
               data-nav-label={g.label}>{g.label}</a>
          {:else}
            {@const active = isMenuActive(g)}
            {@const open = openMenu === g.label}
            <div class="relative">
              <button type="button"
                      class="px-3 py-1.5 text-sm rounded-md hover:bg-ink-100
                             focus-ring inline-flex items-center gap-1"
                      class:bg-ink-100={active || open}
                      class:font-medium={active}
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
                            min-w-[10rem] bg-white border border-ink-200
                            rounded-md shadow-lg py-1"
                     role="menu"
                     tabindex="-1"
                     data-testid="nav-dropdown"
                     data-nav-parent={g.label}
                     on:mouseleave={closeMenu}>
                  {#each g.children as c}
                    {@const childActive = isLinkActive(c.href, false)}
                    <a href={c.href}
                       class="block px-3 py-1.5 text-sm hover:bg-ink-100
                              focus-ring"
                       class:bg-ink-100={childActive}
                       class:font-medium={childActive}
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
      <div class="ml-auto flex items-center gap-2 text-xs text-ink-500">
        <span class="pill">classi: {$datasetState.classes}</span>
        <span class="pill">docenti: {$datasetState.teachers}</span>
        <span class="pill">aule: {$datasetState.classrooms}</span>
        {#if $datasetState.active_solution}
          <span class="pill pill-green">obj {$datasetState.active_solution.obj_value}</span>
        {:else}
          <span class="pill pill-amber">no soluzione attiva</span>
        {/if}
      </div>
    </div>
  </header>

  <main id="main-content" tabindex="-1"
        class="flex-1 max-w-[1500px] w-full mx-auto px-6 py-6 focus:outline-none">
    <slot />
  </main>

  <footer class="border-t border-ink-200 bg-white">
    <div class="max-w-[1500px] mx-auto px-6 py-3 text-xs text-ink-500 flex flex-wrap gap-3 items-baseline">
      <span class="font-semibold" style="color: var(--brand-primary);">
        <span class="font-serif italic" style="color: var(--brand-secondary);">π</span>Tantum
      </span>
      <span class="italic">Tempus tantum nostrum est</span>
      <span>v{APP_VERSION}</span>
      <span class="ml-auto">Engine: ortools</span>
    </div>
  </footer>
</div>

<Toast />
</QueryClientProvider>
