# branding/icons/

Icone applicative.

## File attesi

| File                        | Tipo | Dimensioni | Uso |
| --------------------------- | ---- | ---------- | --- |
| `favicon.png`               | PNG  | 32x32      | favicon del browser (gia' wirata in `app.html`) |
| `favicon.svg`               | SVG  | -          | favicon vettoriale (browser moderni) |
| `apple-touch-icon.png`      | PNG  | 180x180    | iOS / Android home screen (gia' wirata in `app.html`) |
| `icon-192.png`              | PNG  | 192x192    | PWA / Android |
| `icon-512.png`              | PNG  | 512x512    | PWA / Android |
| `icon-mask.png`             | PNG  | 512x512    | maskable icon per PWA con safe-area centrale |

## Note

- Il favicon e' la prima cosa che vedi nella tab del browser; puntare
  a un'icona molto semplice e leggibile a 16x16 (la versione squashata
  di favicon.png).
- Le PWA icon servono se in futuro vogliamo trasformare la webapp in
  app installabile (vedere `docs/improvements.md` -> sezione "PWA",
  P3).

## Wire frontend

- `webui/frontend/src/app.html` ha gia':
  ```html
  <link rel="icon" type="image/png" href="/branding/icons/favicon.png" />
  <link rel="apple-touch-icon" href="/branding/icons/apple-touch-icon.png" />
  ```
  Quando i file vengono caricati in
  `webui/frontend/static/branding/icons/`, sono raggiungibili
  immediatamente.
