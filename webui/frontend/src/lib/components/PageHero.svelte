<script>
  /**
   * Fascia introduttiva della pagina: l'elemento che nel redesign rende
   * riconoscibile ogni schermata. Occhiello con la tappa, titolo serif,
   * una riga che spiega a cosa serve la pagina, i dati di stato a
   * sinistra e le azioni principali a destra.
   *
   *   <PageHero title="Docenti"
   *             description="Ore, disponibilita', giorni liberi.">
   *     <svelte:fragment slot="chips">
   *       <span class="pill-num">64 docenti</span>
   *     </svelte:fragment>
   *     <svelte:fragment slot="actions">
   *       <button class="btn-primary">+ Nuovo docente</button>
   *     </svelte:fragment>
   *   </PageHero>
   *
   * L'occhiello si ricava da solo dalla route (vedi tappaFor in
   * $lib/nav); passare `eyebrow` lo forza, `eyebrow={null}` lo toglie.
   * Quando il layout mostra gia' la striscia della tappa (cioe' quando
   * la pagina ha delle sorelle) l'occhiello automatico si toglie da
   * solo, altrimenti la stessa dicitura comparirebbe due volte di fila.
   *
   * La fascia esce dai margini del contenitore principale (i margini
   * negativi) per attaccarsi ai bordi come nel design, ed e' pensata
   * per stare come primo elemento dentro <main>.
   */
  import { page } from '$app/stores';
  import { tappaFor, siblingsFor } from '$lib/nav';

  export let title;
  export let description = '';
  /** undefined = deducilo dalla route; null o '' = nessun occhiello. */
  export let eyebrow = undefined;

  $: tappa = tappaFor($page.url.pathname);
  // Stessa condizione con cui +layout.svelte decide di mostrare la
  // striscia: se c'e' lei, l'occhiello qui sarebbe un doppione.
  $: inStrip = !!(tappa && siblingsFor($page.url.pathname));
  $: label = eyebrow === undefined
    ? (tappa && !inStrip ? `Tappa ${tappa.n} · ${tappa.label}` : '')
    : (eyebrow || '');
</script>

<div class="hero-band -mx-6 -mt-6 mb-6 px-6 pt-[22px] pb-[18px]">
  <div class="flex flex-wrap items-end gap-6">
    <div class="min-w-0 flex-1">
      {#if label}
        <p class="eyebrow mb-1.5">{label}</p>
      {/if}
      <h1>{title}</h1>
      {#if $$slots.chips}
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <slot name="chips" />
        </div>
      {/if}
    </div>

    {#if $$slots.actions}
      <div class="flex flex-wrap items-center justify-end gap-2">
        <slot name="actions" />
      </div>
    {/if}
  </div>

  {#if description}
    <p class="mt-2 text-[13px] leading-[1.55] text-ink-500">
      {description}
    </p>
  {/if}

  <slot />
</div>
