<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { datasetState, refreshDataset } from '$lib/stores.js';
  import Toast from '$lib/components/Toast.svelte';

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
    { href: '/optimize',   label: 'Workflow'                 },
    { href: '/schedule',   label: 'Orario'                   },
    { href: '/assenze-supplenze', label: 'Assenze e supplenze' },
  ];

  onMount(refreshDataset);

  $: cur = $page.url.pathname;
</script>

<div class="min-h-screen flex flex-col">
  <header class="bg-white border-b border-ink-200">
    <div class="max-w-[1500px] mx-auto px-6 py-3 flex items-center gap-4">
      <a href="/" class="font-semibold tracking-tight">
        <span class="text-accent-500">Timetable</span> WebUI
      </a>
      <nav class="flex flex-wrap gap-1 ml-4">
        {#each links as l}
          <a href={l.href}
             class="px-3 py-1.5 text-sm rounded-md hover:bg-ink-100"
             class:bg-ink-100={l.exact ? cur === l.href : cur.startsWith(l.href) && l.href !== '/'}
             class:font-medium={l.exact ? cur === l.href : cur.startsWith(l.href) && l.href !== '/'}>{l.label}</a>
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

  <main class="flex-1 max-w-[1500px] w-full mx-auto px-6 py-6">
    <slot />
  </main>

  <footer class="border-t border-ink-200 bg-white">
    <div class="max-w-[1500px] mx-auto px-6 py-3 text-xs text-ink-500">
      Backend: localhost:8000 - Frontend: localhost:5173 - Engine: ortools (esperimenti in <code>experiments/</code>)
    </div>
  </footer>
</div>

<Toast />
