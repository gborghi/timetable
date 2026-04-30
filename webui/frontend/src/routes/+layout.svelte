<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { datasetState, refreshDataset, networkOnline,
           startNetworkMonitor } from '$lib/stores.js';
  import Toast from '$lib/components/Toast.svelte';

  // Brand assets: paths into webui/frontend/static/branding/. The
  // images are not in the repo until Giovanni uploads them; the UI
  // gracefully degrades to text-only "Carpe Diem" if the file 404s.
  const LOGO_LIGHT = '/branding/logo/logo_light.png';
  let logoOk = false;
  function onLogoOk() { logoOk = true; }
  function onLogoErr() { logoOk = false; }

  const APP_VERSION = '0.1';
  const HORACE_LATIN = 'Carpe diem, quam minimum credula postero.';
  const HORACE_IT = 'Cogli il giorno presente, fidandoti il meno possibile del domani.';

  const links = [
    { href: '/',           label: 'Dashboard',   exact: true  },
    { href: '/teachers',   label: 'Docenti'                  },
    { href: '/classes',    label: 'Classi'                   },
    { href: '/curricula',  label: 'Indirizzi'                },
    { href: '/students',   label: 'Studenti'                 },
    { href: '/groups',     label: 'Gruppi'                   },
    { href: '/subjects',   label: 'Materie'                  },
    { href: '/classrooms', label: 'Aule'                     },
    { href: '/coteaching', label: 'Compresenze'              },
    { href: '/assignments',label: 'Cattedre'                 },
    { href: '/schedule',   label: 'Orario'                   },
    { href: '/assenze-supplenze', label: 'Assenze e supplenze' },
    { href: '/monitor',    label: 'Monitor'                  },
    { href: '/constraints',label: 'Vincoli'                  },
    { href: '/optimize',   label: 'Workflow'                 },
  ];

  onMount(() => {
    refreshDataset();
    startNetworkMonitor(30000);
  });

  $: cur = $page.url.pathname;
</script>

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
  <header class="bg-white border-b border-ink-200" role="banner">
    <div class="max-w-[1500px] mx-auto px-6 py-3 flex items-center gap-4">
      <a href="/" class="flex items-center gap-3 leading-tight"
         title={HORACE_LATIN}>
        <img src={LOGO_LIGHT} alt="Carpe Diem"
             class="h-9 w-auto"
             class:hidden={!logoOk}
             on:load={onLogoOk} on:error={onLogoErr}/>
        <span class="flex flex-col">
          <span class="text-xl font-semibold tracking-tight text-accent-500">Carpe Diem</span>
          <span class="text-[10px] italic text-ink-400 -mt-0.5">
            {HORACE_LATIN}
          </span>
        </span>
      </a>
      <nav class="flex flex-wrap gap-1 ml-4" aria-label="Navigazione principale">
        {#each links as l}
          {@const active = l.exact ? cur === l.href
                                    : cur.startsWith(l.href) && l.href !== '/'}
          <a href={l.href}
             class="px-3 py-1.5 text-sm rounded-md hover:bg-ink-100 focus-ring"
             class:bg-ink-100={active}
             class:font-medium={active}
             aria-current={active ? 'page' : undefined}>{l.label}</a>
        {/each}
      </nav>
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

  <footer class="border-t border-ink-200 bg-white" role="contentinfo">
    <div class="max-w-[1500px] mx-auto px-6 py-3 text-xs text-ink-500 flex flex-wrap gap-3 items-baseline">
      <span class="font-semibold text-ink-600">Carpe Diem</span>
      <span class="italic">Cogli il giorno</span>
      <span>v{APP_VERSION}</span>
      <span class="ml-auto">Backend: localhost:8000 &middot; Frontend: localhost:5173 &middot; Engine: ortools</span>
    </div>
  </footer>
</div>

<Toast />
