# static/branding/

Asset serviti staticamente dal frontend SvelteKit.

Ogni file qui dentro e' raggiungibile come URL nel browser:

- `webui/frontend/static/branding/logo/logo_light.png`
  -> `http://127.0.0.1:5173/branding/logo/logo_light.png`

Vedere [`branding/`](../../../../branding/README.md) nella radice del
repo per la brand identity (palette, font, tagline, licenza degli
asset).

## Sottocartelle

```
static/branding/
+-- logo/         (`logo_light.png`, `logo_dark.png`, ecc.)
+-- banner/       (`og_image.png`, ecc.)
+-- icons/        (`favicon.png`, `apple-touch-icon.png`, ecc.)
+-- social/       (twitter / linkedin)
+-- screenshots/  (uso interno docs)
```

## Workflow

Il frontend si aspetta i file alle path standard (vedere
[`branding/logo/README.md`](../../../../branding/logo/README.md) e
[`branding/icons/README.md`](../../../../branding/icons/README.md)).
Finche' i file non sono qui, la UI degrada elegantemente al wordmark
testuale "piTantum".

I file in questa cartella **non sono master**: vivono in
`branding/<sottocartella>/` (archivio tracciato in git, con anche
versioni alternative). Qui ci sono solo le versioni "shipped".

I placeholder SVG (logo_light.svg, favicon.svg, banner_placeholder.svg)
ship-ano gia' in `branding/<sottocartella>/`. Quando vengono usati nel
frontend tramite path `/branding/...`, Vite serve dalla cartella
`webui/frontend/static/branding/`. Per renderli effettivamente raggiun-
gibili dal frontend, copia (o crea symlink) i file dalla cartella
master `branding/` a questa.
