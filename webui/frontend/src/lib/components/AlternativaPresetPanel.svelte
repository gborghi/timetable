<script>
  /**
   * Monta AlternativaRoomPreset e lo collega al dato
   * data/preset_alternativa.json (GET/PUT /api/presets/alternativa-aula).
   */
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import AlternativaRoomPreset from './AlternativaRoomPreset.svelte';

  let value = null;
  let error = '';
  let saving = false;

  onMount(async () => {
    try {
      value = await api.get('/api/presets/alternativa-aula');
    } catch (e) {
      error = e.message || String(e);
    }
  });

  async function save(next) {
    saving = true;
    try {
      value = await api.put('/api/presets/alternativa-aula', next);
      flash('Aula di Alternativa salvata', 'success');
    } catch (e) {
      flash(`Aula di Alternativa non salvata: ${e.message || e}`, 'error');
    } finally {
      saving = false;
    }
  }
</script>

<section class="rounded border border-ink-200 bg-white p-4 mb-4" aria-labelledby="alternativa-preset-title"
         aria-busy={saving}>
  <h2 id="alternativa-preset-title" class="text-base font-semibold mb-2">
    Aula per l'attività alternativa
  </h2>
  {#if error}
    <p class="text-sm text-red-700" role="alert">Preset non disponibile: {error}</p>
  {:else if value}
    <AlternativaRoomPreset {value} onchange={save} />
  {:else}
    <p class="text-sm text-ink-500">Caricamento…</p>
  {/if}
</section>
