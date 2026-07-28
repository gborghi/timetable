<script>
  // First-run guided checklist: tells a non-technical user WHAT to do and
  // IN WHICH ORDER, with a live green tick per step driven by the actual
  // dataset state. Each row links to the page that completes it. It hides
  // itself once the school has a timetable (and can be re-shown), so it
  // never nags an established user.
  import { onMount } from 'svelte';
  import { datasetState, workingHoursConfig, loadWorkingHoursConfig } from '$lib/stores';

  let dismissed = false;

  onMount(() => {
    if ($workingHoursConfig == null) loadWorkingHoursConfig();
    try { dismissed = localStorage.getItem('pt_onboarding_dismissed') === '1'; }
    catch (_e) { /* private mode: just show it */ }
  });

  function dismiss() {
    dismissed = true;
    try { localStorage.setItem('pt_onboarding_dismissed', '1'); } catch (_e) { /**/ }
  }
  function reopen() {
    dismissed = false;
    try { localStorage.removeItem('pt_onboarding_dismissed'); } catch (_e) { /**/ }
  }

  // "Ore configurate" = at least one active day carrying at least one slot.
  $: oreConfigured = Array.isArray($workingHoursConfig?.days)
    && $workingHoursConfig.days.some((d) => d?.is_active && (d?.slots?.length ?? 0) > 0);

  $: s = $datasetState || {};
  $: hasSolution = !!s.active_solution || (s.solutions ?? 0) > 0;

  $: steps = [
    { label: 'Configura le Ore (la settimana scolastica)', href: '/ore', done: oreConfigured },
    { label: 'Inserisci le Materie',                        href: '/subjects',    done: (s.subjects ?? 0) > 0 },
    { label: 'Inserisci i Docenti',                         href: '/teachers',    done: (s.teachers ?? 0) > 0 },
    { label: 'Inserisci le Classi',                         href: '/classes',     done: (s.classes ?? 0) > 0 },
    { label: 'Inserisci le Aule',                           href: '/classrooms',  done: (s.classrooms ?? 0) > 0 },
    { label: 'Assegna le Cattedre (docente → classe → materia)', href: '/assignments', done: (s.assignments ?? 0) > 0 },
    { label: 'Imposta i Vincoli', href: '/constraints', optional: true, done: false },
    { label: "Genera l'orario", href: '/optimize', done: hasSolution },
    { label: "Visualizza e modifica l'orario", href: '/schedule', done: hasSolution },
  ];

  // Progress counts only the required steps.
  $: required = steps.filter((st) => !st.optional);
  $: doneCount = required.filter((st) => st.done).length;
  $: allDone = doneCount === required.length;
  // The next actionable step (first required step still to do).
  $: nextIdx = steps.findIndex((st) => !st.optional && !st.done);
</script>

{#if dismissed}
  <button type="button" class="text-xs text-accent-500 hover:underline" on:click={reopen}>
    Mostra la guida ai primi passi
  </button>
{:else}
  <div class="card p-4" data-testid="onboarding-checklist">
    <div class="flex items-center justify-between gap-2">
      <h2 class="!text-base !mb-0">Primi passi — {doneCount}/{required.length}</h2>
      <button type="button" class="text-xs text-ink-400 hover:text-ink-600" on:click={dismiss}>
        {allDone ? 'Nascondi' : 'Nascondi guida'}
      </button>
    </div>

    {#if allDone}
      <p class="text-sm text-ink-500 mt-1">
        Tutto pronto: la scuola ha un orario. Puoi rigenerarlo da
        <a href="/optimize" class="text-accent-500 hover:underline">Ottimizza</a>
        o modificarlo in <a href="/schedule" class="text-accent-500 hover:underline">Orario</a>.
      </p>
    {:else}
      <p class="text-sm text-ink-500 mt-1">
        Segui i passi nell'ordine. Il prossimo da fare è evidenziato.
      </p>
    {/if}

    <ol class="mt-3 space-y-1.5">
      {#each steps as st, i}
        <li class="flex items-center gap-2 text-sm"
            class:opacity-60={st.done}>
          <span class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-medium"
                class:bg-green-100={st.done}
                class:text-green-700={st.done}
                class:bg-accent-100={!st.done && i === nextIdx}
                class:text-accent-700={!st.done && i === nextIdx}
                class:bg-ink-100={!st.done && i !== nextIdx}
                class:text-ink-500={!st.done && i !== nextIdx}>
            {st.done ? '✓' : i + 1}
          </span>
          <a href={st.href}
             class="hover:underline"
             class:font-medium={!st.done && i === nextIdx}
             class:text-accent-600={!st.done && i === nextIdx}>
            {st.label}
          </a>
          {#if st.optional}
            <span class="text-xs text-ink-400">(facoltativo)</span>
          {/if}
        </li>
      {/each}
    </ol>
  </div>
{/if}
