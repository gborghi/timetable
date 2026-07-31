<script>
  /**
   * Accordion del redesign: una riga-titolo cliccabile e il contenuto
   * che compare sotto. Serve a togliere dalla vista gli strumenti che
   * si usano di rado (backup, travaso vincoli, modalita' avanzata del
   * solver) senza rimuoverli.
   *
   *   <Panel id="backup-db" title="Backup del database"
   *          subtitle="esporta o ripristina .zip" meta="83 vincoli">
   *     …contenuto…
   *   </Panel>
   *
   * Lo stato aperto/chiuso e' ricordato in localStorage per `id`, cosi'
   * chi apre sempre lo stesso pannello non deve rifarlo a ogni visita.
   * `open` e' bindabile se la pagina vuole controllarlo da fuori.
   *
   * Per i test E2E: data-testid="panel" + data-panel-id sull'elemento,
   * aria-expanded sul bottone. Vedi cypress/support/panels.ts.
   */
  export let id;
  export let title;
  export let subtitle = '';
  /** Testo allineato a destra nell'intestazione (conteggi, timestamp). */
  export let meta = '';
  /** Stato iniziale, usato solo se non c'e' nulla in localStorage. */
  export let open = false;
  /** 'default' | 'danger' — 'danger' e' la "Zona pericolosa". */
  export let tone = 'default';

  const KEY = `pt_panel_${id}`;
  let hydrated = false;

  // Ripristina lo stato salvato al primo mount. Non usiamo onMount per
  // non far lampeggiare il pannello: il valore arriva prima del paint
  // successivo e comunque il contenuto e' sotto la piega.
  import { onMount } from 'svelte';
  onMount(() => {
    try {
      const saved = localStorage.getItem(KEY);
      if (saved !== null) open = saved === '1';
    } catch (_e) { /* private mode: si resta sul default */ }
    hydrated = true;
  });

  function toggle() {
    open = !open;
    if (!hydrated) return;
    try { localStorage.setItem(KEY, open ? '1' : '0'); } catch (_e) { /**/ }
  }

  $: danger = tone === 'danger';
</script>

<section class="card overflow-hidden"
         class:border-[#f0d6d0]={danger}
         data-testid="panel"
         data-panel-id={id}>
  <button type="button"
          class="w-full flex items-center gap-[11px] px-[18px] py-[13px]
                 text-left hover:bg-paper-band focus-ring"
          aria-expanded={open}
          on:click={toggle}>
    <span class="text-[10px] text-ink-300 w-2 shrink-0" aria-hidden="true">
      {open ? '▾' : '▸'}
    </span>
    <h2 class="!text-[16px] !m-0" class:text-siena={danger}>{title}</h2>
    {#if subtitle}
      <span class="text-[11.5px] text-ink-300">{subtitle}</span>
    {/if}
    {#if meta}
      <span class="ml-auto font-mono text-[10.5px] text-ink-300">{meta}</span>
    {/if}
  </button>

  {#if open}
    <div class="border-t border-ink-200 px-[18px] py-4"
         class:border-[#f0d6d0]={danger}>
      <slot />
    </div>
  {/if}
</section>
