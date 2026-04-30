<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash } from '$lib/stores.js';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';

  let summary = null;
  let listRef = null;

  onMount(async () => {
    try { summary = await api.get('/api/monitor/summary'); } catch { /* */ }
  });

  const columns = [
    { key: 'docente', label: 'Docente' },
    { key: 'classe', label: 'Classe' },
    { key: 'materia', label: 'Materia' },
    { key: 'expected_hours', label: 'Ore attese' },
    { key: 'assigned_hours', label: 'Ore assegnate' },
    { key: 'missing_hours', label: 'Ore mancanti' },
    { key: 'missing_room', label: 'Aule mancanti' },
    { key: 'gruppo', label: 'Gruppo' },
    { key: 'stato', label: 'Stato' }
  ];
  const help = {
    fields: ['docente', 'teacher', 'classe', 'class_name', 'materia',
             'subject', 'expected_hours', 'ore_attese', 'assigned_hours',
             'ore_assegnate', 'missing_hours', 'ore_mancanti',
             'missing_room', 'aule_mancanti', 'missing_group', 'is_complete',
             'completo', 'group', 'gruppo', 'status', 'stato'],
    examples: [
      'completo = 0',
      'missing_hours > 0',
      'aule_mancanti > 0',
      'materia = Matematica',
      'classe startswith 1A',
      'docente contains Rossi'
    ]
  };

  function rowBg(row) {
    return row.is_complete ? '' : 'background-color: #fef9c3;';
  }
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Monitor</h1>
    {#if summary}
      <span class="text-sm text-ink-500">
        {summary.n_events} eventi totali
        - <span class="pill-amber">{summary.n_incomplete} incompleti</span>
        {#if summary.n_missing_hours}
          - <span class="pill-red">{summary.n_missing_hours} senza ore</span>
        {/if}
        {#if summary.n_missing_room}
          - <span class="pill-amber">{summary.n_missing_room} senza aula</span>
        {/if}
        {#if summary.n_missing_group}
          - <span class="pill">{summary.n_missing_group} senza gruppo</span>
        {/if}
      </span>
    {/if}
  </div>

  <p class="text-xs text-ink-500">
    Lista degli "eventi" (docente + classe + materia) generati dalle
    cattedre. Le righe con sfondo giallino non hanno ancora una
    scheduling completa: mancano ore, aule, oppure il gruppo articolato.
  </p>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/monitor/events"
    {columns}
    {help}
    rowKey={(r) => r.assignment_id}
    let:row let:columns>
    <tr style={rowBg(row)}>
      <td><strong>{row.teacher_display}</strong>
        <span class="text-[10px] text-ink-400">({row.teacher_name})</span>
      </td>
      <td>{row.class_name}</td>
      <td>{row.subject}</td>
      <td class="text-center">{row.expected_hours}</td>
      <td class="text-center">{row.assigned_hours}</td>
      <td class="text-center">
        {#if row.missing_hours > 0}
          <span class="pill-red">{row.missing_hours}</span>
        {:else}
          <span class="text-ink-300">-</span>
        {/if}
      </td>
      <td class="text-center">
        {#if row.missing_room > 0}
          <span class="pill-amber">{row.missing_room}</span>
        {:else}
          <span class="text-ink-300">-</span>
        {/if}
      </td>
      <td class="text-xs">
        {#if row.group_name}{row.group_name}
        {:else if row.missing_group}<span class="pill-amber">manca</span>
        {:else}<span class="text-ink-300">-</span>{/if}
      </td>
      <td class="text-xs">
        {#if row.is_complete}<span class="pill-green">ok</span>
        {:else}{row.status}{/if}
      </td>
    </tr>
  </SortableQueryableList>
</div>
