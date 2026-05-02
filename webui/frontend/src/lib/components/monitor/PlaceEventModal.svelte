<script>
  /**
   * "Piazza" modal for one or more selected events.
   *
   * Lets the user pick the lock_mode (which other lessons are
   * movable) and triggers POST /api/optimize/place-event. Streams
   * the run log via the existing RunLogPanel so the user sees
   * placement warnings if any hours can't fit.
   */
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import RunLogPanel from '$lib/components/RunLogPanel.svelte';

  export let open = false;
  export let eventIds = [];           // list of Assignment ids
  export let summaries = [];          // [{teacher_display, class_name, subject}]
  export let onClose = () => { open = false; };
  export let onCompleted = () => {};

  let lockMode = 'all_others_locked';
  let preferPref = false;
  let runId = null;
  let busy = false;

  $: if (open) {
    runId = null;
    busy = false;
    lockMode = 'all_others_locked';
    preferPref = false;
  }

  async function startPlace() {
    if (eventIds.length === 0) {
      flash('Nessun evento selezionato.', 'error');
      return;
    }
    busy = true;
    try {
      const r = await api.post('/api/optimize/place-event', {
        event_ids: eventIds,
        lock_mode: lockMode,
        prefer_pref: preferPref,
      });
      runId = r.run_id;
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }

  function onRunEnd() {
    onCompleted();
    flash('Piazzamento completato.', 'success');
    // Auto-close after the user has a moment to read the log
    setTimeout(() => { runId = null; onClose(); }, 1500);
  }
</script>

<Modal {open} title={`Piazza ${eventIds.length} eventi`} {onClose}>
  <div class="space-y-3 text-sm">
    {#if summaries.length}
      <div class="card !shadow-none p-2 bg-ink-50">
        <div class="text-xs text-ink-500 mb-1">Eventi selezionati:</div>
        <ul class="text-xs list-disc pl-5 max-h-32 overflow-y-auto">
          {#each summaries as s}
            <li><strong>{s.teacher_display}</strong>
                - {s.class_name} / {s.subject}</li>
          {/each}
        </ul>
      </div>
    {/if}

    <div class="card p-3 space-y-2 bg-ink-50/40">
      <div class="text-sm font-medium">Vincolo sugli altri eventi</div>
      <label class="flex items-start gap-2 text-xs">
        <input type="radio" bind:group={lockMode} value="all_others_locked"
               class="mt-0.5"/>
        <span>
          <strong>Tutti gli altri eventi sono lockati</strong> (default,
          quasi-fixed-point): solo le lezioni di questi eventi vengono
          piazzate, il resto resta com'e'. Veloce ma puo' fallire se
          gli slot disponibili sono pochi.
        </span>
      </label>
      <label class="flex items-start gap-2 text-xs">
        <input type="radio" bind:group={lockMode}
               value="same_class_or_teacher_movable" class="mt-0.5"/>
        <span>
          <strong>Solo eventi della stessa classe o docente possono
          essere spostati</strong>: si toccano le lezioni della classe
          o del docente coinvolto, il resto della scuola resta fermo.
          Compromesso utile per tweak locali.
        </span>
      </label>
      <label class="flex items-start gap-2 text-xs">
        <input type="radio" bind:group={lockMode} value="all_others_movable"
               class="mt-0.5"/>
        <span>
          <strong>Tutti gli altri eventi possono essere spostati</strong>:
          il placer ha la massima liberta' (puo' evictare qualsiasi
          lezione), ma rischia di rimescolare l'orario.
        </span>
      </label>
    </div>

    {#if runId}
      <RunLogPanel {runId}
                   title={`Piazza run #${runId}`}
                   onEnd={onRunEnd}/>
    {/if}

    <div class="flex justify-end gap-2 pt-3 border-t border-ink-100">
      <button class="btn" on:click={onClose} disabled={busy}>
        {runId ? 'Chiudi' : 'Annulla'}
      </button>
      {#if !runId}
        <button class="btn-primary" on:click={startPlace}
                disabled={busy || eventIds.length === 0}>
          {busy ? '...' : 'Avvia piazzamento'}
        </button>
      {/if}
    </div>
  </div>
</Modal>
