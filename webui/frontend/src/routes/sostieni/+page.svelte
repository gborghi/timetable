<script>
  /**
   * /sostieni -- PayPal donate, same pattern as SubjectBrain Physics
   * (obsidian-vault/Sostieni.md) and English/quartz-eng-lit/content/sostieni.md.
   * Amounts land on Giovanni's PayPal business 4ZM48BHWAGTDL.
   */
  import PageHero from '$lib/components/PageHero.svelte';

  const BUSINESS = '4ZM48BHWAGTDL';
  const ITEM = 'piTantum';
  const AMOUNTS = [1, 2, 5, 10];

  function donateUrl(amount) {
    const q = new URLSearchParams({
      business: BUSINESS,
      currency_code: 'EUR',
      item_name: ITEM,
    });
    if (amount) q.set('amount', String(amount));
    return `https://www.paypal.com/donate/?${q.toString()}`;
  }
</script>

<svelte:head>
  <title>Sostieni il sito · πTantum</title>
</svelte:head>

<div data-testid="sostieni-page">
  <PageHero
    title="Sostieni il sito"
    description="πTantum è gratuito e senza pubblicità. Se ti è utile e vuoi contribuire alle spese (dominio, costi di sviluppo), puoi lasciare un piccolo contributo con PayPal. Grazie!"
    eyebrow={null}
  />

  <div class="flex flex-wrap gap-3 my-6" data-testid="sostieni-amounts">
    {#each AMOUNTS as n}
      <a class="sostieni-amt"
         href={donateUrl(n)}
         target="_blank"
         rel="noopener"
         data-testid="sostieni-amount-{n}">
        {n}&nbsp;€
      </a>
    {/each}
  </div>

  <p class="text-[13px] text-ink-500">
    <a class="underline hover:text-ink-900"
       href={donateUrl(null)}
       target="_blank"
       rel="noopener"
       data-testid="sostieni-other">↗ Dona un altro importo</a>
    · il pagamento avviene sui server sicuri di PayPal.
  </p>
</div>

<style>
  .sostieni-amt {
    flex: 1 1 100px;
    text-align: center;
    padding: 16px 12px;
    border-radius: 10px;
    background: #ffc439;
    color: #003087;
    font-weight: 800;
    font-size: 1.1rem;
    text-decoration: none;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
  }
  .sostieni-amt:hover { filter: brightness(0.97); }
</style>
