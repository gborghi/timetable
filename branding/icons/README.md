# branding/icons/

Icone applicative del progetto piTantum.

## File

| File                     | Tipo | Dimensioni | Stato       | Wire |
| ------------------------ | ---- | ---------- | ----------- | ---- |
| `favicon.svg`            | SVG  | -          | placeholder | wirato in `app.html`, ship-pa col repo |
| `favicon.png`            | PNG  | 32x32      | da generare | fallback per browser senza supporto SVG-favicon |
| `apple-touch-icon.png`   | PNG  | 180x180    | da generare | wirato in `app.html` |
| `icon-192.png`           | PNG  | 192x192    | da generare | PWA (futuro) |
| `icon-512.png`           | PNG  | 512x512    | da generare | PWA (futuro) |
| `favicon.ico`            | ICO  | multi      | opzionale   | per IE / vecchi browser |

## Wire frontend

In `webui/frontend/src/app.html`:

```html
<link rel="icon" type="image/svg+xml" href="/branding/icons/favicon.svg" />
<link rel="icon" type="image/png" href="/branding/icons/favicon.png" />
<link rel="apple-touch-icon" href="/branding/icons/apple-touch-icon.png" />
```

Il browser sceglie il piu' specifico: SVG sui browser moderni, PNG
come fallback. L'apple-touch-icon viene usato dagli iOS/Android home
screen.

## Generare le versioni definitive

Vedere [`grok_prompts.md`](grok_prompts.md) per i 4 prompt
copia-incolla pronti.

## Note di scala

A 16x16 (favicon piccolo) sono leggibili solo i tratti grossi:
$\pi$ + clessidra schematica. **L'alloro** introdotto nei loghi grandi
NON entra nel favicon -- diventa rumore.
