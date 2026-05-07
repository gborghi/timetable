<script>
  /**
   * Tab Ore -- working days + per-day timetable slots.
   *
   * The user picks which days of the week are "working" (active),
   * sets the order via a position field, and edits the list of
   * timetable slots for each day. Slots are ordered top-to-bottom
   * by their start_time and indexed 0..N-1 internally; the engine
   * uses those indices as `hour_idx`.
   *
   * Default config (matches the legacy hardcoded DAYS=[1..6] /
   * HOURS=[8..13]): lun-sab, 6 slots/day, 8:00-14:00.
   *
   * The "Reset" button re-creates the default config in one shot.
   */
  import { onMount } from 'svelte';
  import * as api from '$lib/api';
  import { flash } from '$lib/stores';
  import WeeklyCalendarView from '$lib/components/WeeklyCalendarView.svelte';

  let config = null;
  let loading = false;
  let error = '';

  // Per-day editing state. Keys are the day id; values are arrays
  // of {slot_index, start_time, end_time, label, legacy_hour_number}.
  let drafts = {};
  let dirty = {};

  async function refresh() {
    loading = true;
    error = '';
    try {
      config = await api.get('/api/working-hours/config');
      drafts = {};
      dirty = {};
      for (const d of config.days) {
        drafts[d.id] = d.slots.map((s) => ({ ...s }));
        dirty[d.id] = false;
      }
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
    if (!confirm(
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
</script>

<svelte:head><title>Ore -- piTantum</title></svelte:head>

<div class="max-w-[1300px] mx-auto p-6 space-y-6">
  <header class="flex items-center justify-between gap-4">
    <div>
      <h1 class="text-2xl font-semibold">Ore di lavoro</h1>
      <p class="text-sm text-ink-600 max-w-2xl">
        Definisci i giorni della settimana lavorativa e gli slot
        orari per ciascun giorno. Gli slot sono indicizzati 0..N-1 e
        usati internamente dal motore come <code>hour_idx</code>;
        gli orari (HH:MM) appaiono nelle viste calendarietto e nei
        report.
      </p>
    </div>
    <div class="flex items-center gap-3">
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
        attivi, max {config.max_slots_per_day} slot/giorno,
        {config.uniform_slot_count
          ? 'conteggio slot uniforme.'
          : 'conteggio slot variabile per giorno.'}
        Il motore usa <code>max_slots_per_day</code> come lunghezza
        comune di <code>HOURS</code>; i giorni con meno slot
        lasciano gli indici eccedenti inutilizzati.
      </div>

      <div class="bg-white border border-ink-200 rounded p-4">
        <h2 class="text-lg font-medium mb-3">Anteprima settimanale</h2>
        <WeeklyCalendarView {config} slots={[]}/>
      </div>
    </section>

    <section class="space-y-4">
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

    {#if anyDirty}
      <div class="fixed bottom-4 left-1/2 -translate-x-1/2 bg-amber-100
                  border border-amber-300 px-4 py-2 rounded shadow
                  text-sm">
        Modifiche non salvate. Premi <strong>Salva slot</strong> sui
        giorni interessati per applicarle.
      </div>
    {/if}
  {/if}
</div>
