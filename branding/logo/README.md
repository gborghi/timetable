# branding/logo/

Loghi principali del progetto piTantum.

## File

| File                       | Tipo            | Stato          | Note |
| -------------------------- | --------------- | -------------- | ---- |
| `logo_light.svg`           | SVG vettoriale  | placeholder    | wirato in `webui/frontend/src/routes/+layout.svelte` come header logo, ship-pa con il repo |
| `logo_dark.svg`            | SVG vettoriale  | placeholder    | per dark mode (futuro) |
| `logo_light.png`           | PNG trasparente | da generare    | 512x512, sostituisce eventualmente l'SVG |
| `logo_dark.png`            | PNG trasparente | da generare    | 512x512 |
| `logo_horizontal.png`      | PNG trasparente | da generare    | 1200x300, wordmark + mark |
| `logo_mark.png`            | PNG             | da generare    | 512x512 con sfondo solido, per favicon-derivati |

## Stile

Tre componenti visivi:

1. **$\pi$** (greca minuscola) come elemento centrale
2. **Clessidra** (sabbia, vetro) embedded fra i due tratti verticali
   della $\pi$
3. **Alloro** stilizzato attorno (richiamo classico romano)

Palette: indaco profondo `#1e3a5f`, oro caldo `#c9a23a`, terra di Siena
`#9c4a1c`, avorio `#f7f1de`. Vedere `branding/README.md` per la tavola
completa.

## Wire frontend

Il file `logo_light.svg` (o, in alternativa, `logo_light.png` se
caricato) e' letto da `webui/frontend/src/routes/+layout.svelte`:

```html
<img src="/branding/logo/logo_light.svg" alt="piTantum" .../>
```

Se il file non esiste o non carica, l'UI mostra il wordmark
"$\pi$Tantum" in puro testo (CSS variables `--brand-primary` per il
testo, `--brand-secondary` per il glifo $\pi$ italic).

## Generare le versioni definitive

Vedere [`grok_prompts.md`](grok_prompts.md) per i 4 prompt
copia-incolla pronti.
