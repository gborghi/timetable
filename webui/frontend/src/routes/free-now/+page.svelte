<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash } from '$lib/stores.js';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants.js';

  let day = 1, hour = 8;
  let data = null;
  let teacherFilter = '';
  let subjectFilter = '';

  onMount(load);

  async function load() {
    try { data = await api.get(`/api/schedule/free-now?day=${day}&hour=${hour}`); }
    catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  $: filteredFreeT = !data ? [] : data.free_teachers.filter((t) =>
    (!teacherFilter || t.name.toLowerCase().includes(teacherFilter.toLowerCase()))
    && (!subjectFilter || (t.subjects || []).some((s) => s.toLowerCase().includes(subjectFilter.toLowerCase()))));
</script>

<div class="space-y-4">
  <h1>Chi e libero?</h1>
  <p class="text-sm text-ink-500 max-w-3xl">
    Seleziona giorno + ora e ottieni docenti liberi, classi senza lezione, e chi
    e occupato (con classe, materia e aula). Utile per supplenze al volo o per
    pianificare un'ora aggiuntiva.
  </p>

  <div class="card p-3 flex gap-3 items-end flex-wrap">
    <div class="field">
      <label>Giorno</label>
      <select bind:value={day} on:change={load}>
        {#each DAYS as d}<option value={d}>{DAY_NAMES_IT[d]}</option>{/each}
      </select>
    </div>
    <div class="field">
      <label>Ora</label>
      <select bind:value={hour} on:change={load}>
        {#each HOURS as h}<option value={h}>{h}:00</option>{/each}
      </select>
    </div>
    <div class="field">
      <label>Filtra docente</label>
      <input bind:value={teacherFilter} placeholder="nome..."/>
    </div>
    <div class="field">
      <label>Filtra materia</label>
      <input bind:value={subjectFilter} placeholder="materia..."/>
    </div>
    <button class="btn" on:click={load}>Aggiorna</button>
  </div>

  {#if data}
    <div class="grid lg:grid-cols-2 gap-4">
      <div class="card p-4">
        <h2 class="mb-2">
          Docenti liberi <span class="pill-green ml-2">{filteredFreeT.length}</span>
        </h2>
        <table class="tbl">
          <thead><tr><th>Nome</th><th>Cl. concorso</th><th>Materie</th><th>Ore sett.</th></tr></thead>
          <tbody>
            {#each filteredFreeT as t}
              <tr>
                <td><strong>{t.name}</strong></td>
                <td>{t.group ?? ''}</td>
                <td class="text-xs">{(t.subjects || []).join(', ')}</td>
                <td class="text-xs">{t.scheduled_hours} / {t.max_hours}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <div class="card p-4">
        <h2 class="mb-2">
          Docenti occupati <span class="pill ml-2">{data.busy_teachers.length}</span>
        </h2>
        <table class="tbl">
          <thead><tr><th>Nome</th><th>Classe</th><th>Materia</th><th>Aula</th></tr></thead>
          <tbody>
            {#each data.busy_teachers as t}
              <tr>
                <td><strong>{t.name}</strong></td>
                <td>{t.class_name ?? ''}</td>
                <td>{t.subject ?? ''}</td>
                <td>{t.classroom ?? ''}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <div class="card p-4">
        <h2 class="mb-2">
          Classi libere (senza lezione) <span class="pill-green ml-2">{data.free_classes.length}</span>
        </h2>
        <ul class="text-sm grid grid-cols-2 gap-1">
          {#each data.free_classes as c}
            <li class="px-2 py-1 rounded bg-emerald-50">{c.name} <span class="text-xs text-ink-500">({c.curriculum})</span></li>
          {/each}
        </ul>
      </div>

      <div class="card p-4">
        <h2 class="mb-2">
          Classi occupate <span class="pill ml-2">{data.busy_classes.length}</span>
        </h2>
        <table class="tbl">
          <thead><tr><th>Classe</th><th>Materia</th><th>Docente</th><th>Aula</th></tr></thead>
          <tbody>
            {#each data.busy_classes as c}
              <tr>
                <td><strong>{c.name}</strong></td>
                <td>{c.subject ?? ''}</td>
                <td>{c.teacher ?? ''}</td>
                <td>{c.classroom ?? ''}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {:else}
    <p class="text-sm text-ink-500">Nessuna soluzione attiva.</p>
  {/if}
</div>
