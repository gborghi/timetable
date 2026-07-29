<script>
  import DecorIcon from '$lib/components/DecorIcon.svelte';
  import { confirmDialog } from '$lib/confirm';
  /**
   * Tab Ore -- working days + per-day timetable slots.
   *
   * Two views, switchable via a top-bar toggle:
   *
   *   - "Calendario" (default): the working-hours layout is edited
   *     directly on the same WeeklyCalendarView calendar grid that
   *     drives the unavailability matrices. The user drags on the
   *     background to create slots, drags edges to resize, drags
   *     bodies to move, clicks + Delete to remove. Changes are
   *     buffered in ``draftConfig`` and persisted with one POST per
   *     dirty day on "Salva tutto".
   *
   *   - "Lista" (legacy form): the old start/end input table per
   *     day. Kept as a fallback for keyboard-only editing and for
   *     fields the calendar editor does not surface (label,
   *     legacy_hour_number).
   *
   * Default config (matches the engine's legacy hardcoded
   * DAYS=[1..6] / HOURS=[8..13]): lun-sab, 6 slots/day, 8:00-14:00.
   * The "Reset default" button restores it via POST
   * /api/working-hours/reset.
   */
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, reloadWorkingHoursConfig } from '$lib/stores';
  import WeeklyCalendarView from '$lib/components/WeeklyCalendarView.svelte';

  let config = null;
  let loading = false;
  let error = '';

  // Per-day editing state used by the legacy "Lista" view. Keys are
  // the day id; values are arrays of slots.
  let drafts = {};
  let dirty = {};

  // Calendar-mode editing state: one buffered config, with a
  // per-day dirty flag derived from the diff against ``config``.
  let draftConfig = null;
  let calDirtyDayIds = new Set();
  let view = 'calendar';   // 'calendar' | 'list'

  async function refresh() {
    loading = true;
    error = '';
    try {
      // Always go through the shared store so every other open
      // WeeklyCalendarView (schedule / classes / teachers /
      // classrooms) sees the same canonical config.
      config = await reloadWorkingHoursConfig();
      drafts = {};
      dirty = {};
      for (const d of config.days) {
        drafts[d.id] = d.slots.map((s) => ({ ...s }));
        dirty[d.id] = false;
      }
      draftConfig = JSON.parse(JSON.stringify(config));
      calDirtyDayIds = new Set();
    } catch (e) {
      error = e?.message || String(e);
    } finally {
      loading = false;
    }
  }

  onMount(refresh);

  function markDirty(dayId) { dirty = { ...dirty, [dayId]: true }; }

  async function toggleActive(day) {
    try {
      await api.put(`/api/working-hours/days/${day.id}`, {
        is_active: !day.is_active,
      });
      flash(day.is_active ? 'Giorno disattivato' : 'Giorno attivato',
            'success');
      await refresh();
    } catch (e) {
      flash(`Errore: ${e?.message || e}`, 'error');
    }
  }

  // Calendar-mode handlers ------------------------------------------------

  function _slotsEqual(a, b) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i += 1) {
      if (a[i].start_time !== b[i].start_time
          || a[i].end_time !== b[i].end_time) return false;
    }
    return true;
  }

  function onCalendarEdit(newConfig) {
    draftConfig = newConfig;
    // Diff against the persisted config to mark dirty days.
    const dirtySet = new Set();
    const original = new Map(
      (config?.days || []).map((d) => [d.id, d.slots]));
    for (const d of newConfig.days) {
      const orig = original.get(d.id) || [];
      if (!_slotsEqual(orig, d.slots)) dirtySet.add(d.id);
    }
    calDirtyDayIds = dirtySet;
  }

  async function saveCalendarChanges() {
    const ids = [...calDirtyDayIds];
    if (ids.length === 0) return;
    try {
      for (const dayId of ids) {
        const day = draftConfig.days.find((d) => d.id === dayId);
        if (!day) continue;
        const slots = day.slots.map((s, i) => ({ ...s, slot_index: i }));
        await api.put(`/api/working-hours/days/${dayId}/slots`,
                      { slots });
      }
      flash(`Slot aggiornati per ${ids.length} giorno/i`, 'success');
      await refresh();
    } catch (e) {
      flash(`Errore: ${e?.message || e}`, 'error');
    }
  }

  function discardCalendarChanges() {
    draftConfig = JSON.parse(JSON.stringify(config));
    calDirtyDayIds = new Set();
  }

  function addSlot(dayId) {
    const list = drafts[dayId] || [];
    let nextStart = '08:00';
    let nextEnd = '09:00';
    let legacyHour = 8;
    if (list.length > 0) {
      const last = list[list.length - 1];
      nextStart = last.end_time;
      const [h, m] = nextStart.split(':').map(Number);
      const eh = (h + 1) % 24;
      nextEnd = `${String(eh).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
      legacyHour = h;
    }
    drafts = {
      ...drafts,
      [dayId]: [...list, {
        slot_index: list.length,
        start_time: nextStart,
        end_time: nextEnd,
        label: `${list.length + 1}ª ora`,
        legacy_hour_number: legacyHour,
      }],
    };
    markDirty(dayId);
  }

  function removeSlot(dayId, idx) {
    const list = (drafts[dayId] || []).filter((_, i) => i !== idx);
    drafts = { ...drafts, [dayId]: list };
    markDirty(dayId);
  }

  function updateSlot(dayId, idx, field, value) {
    const list = (drafts[dayId] || []).map((s, i) =>
      i === idx ? { ...s, [field]: value } : s
    );
    if (field === 'start_time') {
      const [h] = String(value).split(':').map(Number);
      if (Number.isFinite(h)) list[idx].legacy_hour_number = h;
    }
    drafts = { ...drafts, [dayId]: list };
    markDirty(dayId);
  }

  async function saveDay(dayId) {
    try {
      const slots = (drafts[dayId] || []).map((s, i) => ({
        ...s,
        slot_index: i,
      }));
      await api.put(`/api/working-hours/days/${dayId}/slots`, { slots });
      flash('Slot aggiornati', 'success');
      await refresh();
    } catch (e) {
      flash(`Errore: ${e?.message || e}`, 'error');
    }
  }

  async function resetAll() {
    if (!await confirmDialog(
      'Ripristinare la configurazione di default ' +
      '(lun-sab, 8:00-14:00)? Le modifiche correnti saranno perse.'
    )) {
      return;
    }
    try {
      await api.post('/api/working-hours/reset');
      flash('Configurazione ripristinata', 'success');
      await refresh();
    } catch (e) {
      flash(`Errore: ${e?.message || e}`, 'error');
    }
  }

  $: anyDirty = Object.values(dirty).some(Boolean);
  $: anyCalDirty = calDirtyDayIds.size > 0;
</script>

<svelte:head><title>Ore -- piTantum</title></svelte:head>

<div class="max-w-[1300px] mx-auto p-6 space-y-6">
  <header class="flex items-center justify-between gap-4">
    <div>
      <h1 class="text-2xl font-semibold flex items-center gap-2"><DecorIcon name="clock" size={28} class="shrink-0" /> Ore di lavoro</h1>
      <p class="text-sm text-ink-600 max-w-2xl">
        Definisci i giorni della settimana lavorativa e, per ciascun
        giorno, le ore di lezione (con orario di inizio e fine). È il
        primo passo: l'orario verrà costruito su questa griglia.
      </p>
      <details class="text-xs text-ink-500 max-w-2xl mt-1">
        <summary class="cursor-pointer select-none">Dettagli tecnici</summary>
        Gli slot sono indicizzati 0..N-1 (nel motore: <code>hour_idx</code>);
        il motore usa <code>max_slots_per_day</code> come lunghezza comune
        di <code>HOURS</code> e i giorni con meno slot lasciano gli indici
        eccedenti inutilizzati.
      </details>
    </div>
    <div class="flex items-center gap-3">
      <div class="inline-flex border border-ink-300 rounded
                  overflow-hidden text-sm" role="tablist"
           aria-label="Vista">
        <button type="button" role="tab"
                aria-selected={view === 'calendar'}
                class="px-3 py-1.5"
                class:bg-sky-100={view === 'calendar'}
                class:text-sky-900={view === 'calendar'}
                on:click={() => (view = 'calendar')}>
          Calendario
        </button>
        <button type="button" role="tab"
                aria-selected={view === 'list'}
                class="px-3 py-1.5 border-l border-ink-300"
                class:bg-sky-100={view === 'list'}
                class:text-sky-900={view === 'list'}
                on:click={() => (view = 'list')}>
          Lista
        </button>
      </div>
      <button class="btn btn-ghost" on:click={refresh}
              disabled={loading}>Ricarica</button>
      <button class="btn btn-danger" on:click={resetAll}>
        Reimposta default (lun-sab, 8-14)
      </button>
    </div>
  </header>

  {#if error}
    <div class="bg-rose-50 border border-rose-200 text-rose-800
                rounded p-3" role="alert">
      Errore: {error}
    </div>
  {/if}

  {#if config}
    <section class="space-y-3">
      <div class="bg-amber-50 border border-amber-200 text-amber-900
                  rounded p-3 text-sm leading-relaxed">
        <strong>Riepilogo:</strong>
        {config.days.filter((d) => d.is_active).length} giorni
        attivi, max {config.max_slots_per_day} ore/giorno,
        {config.uniform_slot_count
          ? 'numero di ore uguale in tutti i giorni.'
          : 'numero di ore variabile per giorno.'}
      </div>

      <div class="bg-white border border-ink-200 rounded p-4"
           class:hidden={view !== 'calendar'}>
        <header class="flex items-baseline justify-between mb-3 gap-3">
          <div>
            <h2 class="text-lg font-medium">Editor calendario</h2>
            <p class="text-xs text-ink-600">
              Trascina su un'area vuota per creare uno slot.
              Trascina i bordi per ridimensionarlo, il corpo per
              spostarlo. Su ogni slot trovi i bottoni
              <strong>Modifica</strong> e <strong>Cancella</strong>.
              Snap a 15 min.
            </p>
          </div>
          <div class="flex items-center gap-2">
            <button class="btn btn-ghost" type="button"
                    disabled={!anyCalDirty}
                    on:click={discardCalendarChanges}>
              Annulla modifiche
            </button>
            <button class="btn btn-primary" type="button"
                    disabled={!anyCalDirty}
                    data-testid="save-calendar"
                    on:click={saveCalendarChanges}>
              Salva
              {#if anyCalDirty}
                ({calDirtyDayIds.size} giorno{calDirtyDayIds.size === 1 ? '' : 'i'})
              {/if}
            </button>
          </div>
        </header>
        {#if draftConfig}
          <WeeklyCalendarView config={draftConfig} mode="edit"
                              onConfigEdit={onCalendarEdit}
                              title="Configurazione ore lavorative"/>
        {/if}
      </div>
    </section>

    <section class="space-y-4" class:hidden={view !== 'list'}>
      <h2 class="text-lg font-medium">Giorni e slot</h2>
      {#each config.days as day (day.id)}
        <div class="bg-white border border-ink-200 rounded p-4
                    {day.is_active ? '' : 'opacity-60'}">
          <header class="flex items-center justify-between gap-3 mb-3">
            <div class="flex items-center gap-3">
              <span class="text-sm font-mono bg-ink-100 px-2 py-0.5
                           rounded">{day.code}</span>
              <strong>{day.label}</strong>
              <span class="text-xs text-ink-500">
                pos {day.position} -- legacy day #{day.legacy_day_number}
              </span>
            </div>
            <div class="flex items-center gap-2">
              <label class="text-sm flex items-center gap-1">
                <input type="checkbox" checked={day.is_active}
                       on:change={() => toggleActive(day)}/>
                Attivo
              </label>
              <button class="btn btn-primary" disabled={!dirty[day.id]}
                      on:click={() => saveDay(day.id)}>
                Salva slot
              </button>
            </div>
          </header>

          <table class="w-full text-sm">
            <thead class="text-left text-ink-500">
              <tr>
                <th class="w-10">#</th>
                <th>Inizio</th>
                <th>Fine</th>
                <th>Etichetta</th>
                <th class="w-32">Legacy hour #</th>
                <th class="w-16"></th>
              </tr>
            </thead>
            <tbody>
              {#each (drafts[day.id] || []) as slot, i}
                <tr class="border-t border-ink-100">
                  <td class="py-1.5">{i}</td>
                  <td>
                    <input type="time" value={slot.start_time}
                           on:input={(e) => updateSlot(day.id, i,
                              'start_time', e.target.value)}
                           class="bg-ink-50 px-2 py-1 rounded"/>
                  </td>
                  <td>
                    <input type="time" value={slot.end_time}
                           on:input={(e) => updateSlot(day.id, i,
                              'end_time', e.target.value)}
                           class="bg-ink-50 px-2 py-1 rounded"/>
                  </td>
                  <td>
                    <input type="text" value={slot.label || ''}
                           on:input={(e) => updateSlot(day.id, i,
                              'label', e.target.value)}
                           class="bg-ink-50 px-2 py-1 rounded w-full"
                           placeholder={`${i + 1}ª ora`}/>
                  </td>
                  <td>
                    <input type="number" min="0" max="23"
                           value={slot.legacy_hour_number}
                           on:input={(e) => updateSlot(day.id, i,
                              'legacy_hour_number',
                              Number(e.target.value))}
                           class="bg-ink-50 px-2 py-1 rounded w-20"/>
                  </td>
                  <td>
                    <button class="text-rose-600 hover:underline
                                   text-xs"
                            on:click={() => removeSlot(day.id, i)}>
                      Rimuovi
                    </button>
                  </td>
                </tr>
              {/each}
              <tr class="border-t border-ink-100">
                <td colspan="6" class="py-2">
                  <button class="text-sky-700 hover:underline text-sm"
                          on:click={() => addSlot(day.id)}>
                    + Aggiungi slot
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      {/each}
    </section>

    {#if (view === 'list' && anyDirty)
         || (view === 'calendar' && anyCalDirty)}
      <div class="fixed bottom-4 left-1/2 -translate-x-1/2 bg-amber-100
                  border border-amber-300 px-4 py-2 rounded shadow
                  text-sm">
        {#if view === 'list'}
          Modifiche non salvate. Premi <strong>Salva slot</strong> sui
          giorni interessati per applicarle.
        {:else}
          {calDirtyDayIds.size} giorno{calDirtyDayIds.size === 1 ? '' : 'i'} con
          modifiche non salvate. Premi <strong>Salva</strong>
          in alto a destra per applicarle.
        {/if}
      </div>
    {/if}
  {/if}
</div>
