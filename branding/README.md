# piTantum - branding kit

Asset visivi del progetto. Le immagini definitive vengono generate da
**Giovanni Borghi** con **Grok**; ogni sottocartella contiene un
`grok_prompts.md` con prompt copia-incolla pronti, e dei placeholder
SVG funzionanti che ship-ano col repo per il primo avvio. Le immagini
finali sostituiscono in-place i placeholder.

## Brand identity

- **Nome canonico**: **piTantum** (Unicode: `&pi;Tantum`, glifo: $\pi$Tantum).
- **Variante esplicita ASCII**: **Tempus Tantum** (per URL,
  package name npm, voci di menu, contesti dove $\pi$ non e' garantito).
- **Tagline / epigrafe**:
  > *Omnia, Lucili, aliena sunt, tempus tantum nostrum est.*
  > -- Seneca, *Epistulae morales ad Lucilium*, I, 1
- **Traduzione**: "Tutto, Lucilio, ci viene da altri; soltanto
  il tempo e' nostro."
- **Senso**: del tempo non si dispone, se non organizzandolo. Una
  app per costruire l'orario settimanale di una scuola e' lo
  strumento concreto di questa idea.
- **Gioco grafico**: la lettera greca $\pi$ minuscola ha due tratti
  verticali, che ricordano le due **T** di **T**empus **T**antum.
  Il logo deve sfruttare visivamente questa coincidenza.

## Elementi visivi del logo

Tre componenti da combinare:

1. **Lettera $\pi$** (greca minuscola), elemento centrale.
2. **Clessidra** (sabbia, vetro), simbolo di tempo.
3. **Alloro** (foglie, ramo, corona), richiamo classico romano +
   Seneca.

Coerenza visiva: classico-moderno, palette ridotta, leggibile a
piccola scala (favicon 32x32). I tratti verticali della $\pi$ possono
ospitare una clessidra stilizzata (sabbia che scende).

## Palette colori

| Ruolo                | Hex        | Note |
| -------------------- | ---------- | ---- |
| Brand primary        | `#1e3a5f`  | indaco profondo (testo wordmark, tratti grafici) |
| Brand secondary      | `#c9a23a`  | oro caldo (lettera $\pi$, dettagli alloro) |
| Brand accent         | `#9c4a1c`  | terra di Siena (highlight rari, hover stati) |
| Brand bg             | `#f7f1de`  | avorio (sfondo carta) |
| Brand fg             | `#1a1612`  | nero caldo (testo su avorio) |
| Brand primary (dark) | `#88a5d8`  | indaco chiaro per dark mode |
| Brand secondary (dark)| `#f0c869` | oro chiaro per dark mode |

I colori sono esposti come CSS variables in
`webui/frontend/src/app.css` (`--brand-primary` ecc.) con override
automatico via `@media (prefers-color-scheme: dark)`. Sono anche
disponibili come Tailwind tokens (`bg-brand-primary`,
`text-brand-secondary`, ...).

## Colori di sistema (5 stati vincoli)

Indipendenti dalla palette di brand: HARD/SOFT/PREFERRED/ENFORCED/
ALLOWED hanno la loro palette in `tailwind.config.js::colors.c.*`.
Vedere `docs/constraints.md`.

## Font suggeriti

- **Wordmark**: serif classico (Cormorant Garamond, Cardo, EB
  Garamond) per coerenza con l'epigrafe latina.
- **Tagline**: serif italic dello stesso font.
- **UI / corpo**: Inter (gia' caricato dal frontend via rsms.me).

## Cosa caricare e come

```
branding/
+-- README.md          (questo file)
+-- logo/              loghi principali e variant
|   +-- README.md
|   +-- grok_prompts.md   <- prompt pronti copia-incolla
|   +-- logo_light.svg    <- placeholder SVG, sostituibile
|   +-- logo_dark.svg
+-- banner/            banner per la dashboard / OG / social
|   +-- README.md
|   +-- grok_prompts.md
|   +-- banner_placeholder.svg
+-- icons/             favicon, app icons
|   +-- README.md
|   +-- grok_prompts.md
|   +-- favicon.svg       <- placeholder SVG, gia' wirato in app.html
+-- social/            preview Twitter, LinkedIn, ecc.
|   +-- README.md
|   +-- grok_prompts.md
+-- screenshots/       screenshot della UI per docs/README
    +-- README.md
```

## Workflow

1. Apri `branding/<sottocartella>/grok_prompts.md`.
2. Copia uno dei prompt, incollalo in Grok, scarica il PNG.
3. Salva la versione master in `branding/<sottocartella>/<nome>.png`.
4. Copia la stessa nella served folder per la UI:
   `webui/frontend/static/branding/<sottocartella>/<nome>.png`.
5. Sostituisci eventualmente il placeholder SVG (oppure tienilo come
   secondo fallback rinominando in `<nome>_placeholder.svg`).
6. Commit + push.

## Licenza degli asset

Le immagini definitive sono generate da Giovanni Borghi via Grok e
licenziate per uso interno del progetto piTantum. I placeholder
SVG presenti nel repo sono originali del progetto e seguono la stessa
licenza interna.

Nessuna distribuzione pubblica, nessun riutilizzo esterno senza
esplicito consenso dell'autore.
