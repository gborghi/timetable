<script>
  // Standalone demo page for the WeeklyCalendarView calendar-grid
  // layout. Used to take a manual screenshot without running the
  // backend. Lives under /_demo_calendar so it does not show up in
  // the regular nav. Renders the component with a synthetic
  // variable-slots-per-day config (lun..ven 6 slots 8-14, sab 4
  // slots 8-12) so the variable-slots behaviour is exercised
  // visually.
  import WeeklyCalendarView from '$lib/components/WeeklyCalendarView.svelte';

  function _slot(i, h0) {
    const h = h0 + i;
    return {
      slot_index: i,
      start_time: `${String(h).padStart(2, '0')}:00`,
      end_time:   `${String(h + 1).padStart(2, '0')}:00`,
      label: `${i + 1}ª ora`,
      legacy_hour_number: h,
    };
  }

  const config = {
    days: [
      { id: 1, code: 'MON', label: 'Lunedi',    position: 0,
        legacy_day_number: 1, is_active: true,
        slots: Array.from({ length: 6 }, (_, i) => _slot(i, 8)) },
      { id: 2, code: 'TUE', label: 'Martedi',   position: 1,
        legacy_day_number: 2, is_active: true,
        slots: Array.from({ length: 6 }, (_, i) => _slot(i, 8)) },
      { id: 3, code: 'WED', label: 'Mercoledi', position: 2,
        legacy_day_number: 3, is_active: true,
        slots: Array.from({ length: 6 }, (_, i) => _slot(i, 8)) },
      { id: 4, code: 'THU', label: 'Giovedi',   position: 3,
        legacy_day_number: 4, is_active: true,
        slots: Array.from({ length: 6 }, (_, i) => _slot(i, 8)) },
      { id: 5, code: 'FRI', label: 'Venerdi',   position: 4,
        legacy_day_number: 5, is_active: true,
        slots: Array.from({ length: 6 }, (_, i) => _slot(i, 8)) },
      { id: 6, code: 'SAT', label: 'Sabato',    position: 5,
        legacy_day_number: 6, is_active: true,
        slots: Array.from({ length: 4 }, (_, i) => _slot(i, 8)) },
    ],
    max_slots_per_day: 6,
    uniform_slot_count: false,
  };

  // Pre-paint a few cells so all 5 constraint states are visible.
  let cells = [
    { day: 1, hour:  8, state: 'soft',      soft_penalty: 100 },
    { day: 2, hour:  9, state: 'hard',      soft_penalty: 0   },
    { day: 3, hour: 10, state: 'preferred', soft_penalty: -100 },
    { day: 4, hour: 11, state: 'enforced',  soft_penalty: 0   },
    { day: 6, hour:  8, state: 'soft',      soft_penalty: 50  },
  ];
</script>

<div class="p-6 max-w-5xl mx-auto">
  <h1 class="text-xl font-bold mb-4">
    WeeklyCalendarView -- demo (variable slots per day)
  </h1>
  <p class="text-sm text-ink-600 mb-4">
    Lun-Ven aperti 8-14 (6 slot ciascuno), Sab aperto solo 8-12 (4
    slot). Le ore 7:00 e 14:00-19:00 sono background grigio
    non-cliccabile. Cliccabili solo i blocchi colorati = slot
    configurati nel Tab Ore.
  </p>
  <WeeklyCalendarView {config} value={cells} onChange={(v) => cells = v}
                      title="Disponibilita oraria (demo)"/>
</div>
