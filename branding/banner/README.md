# branding/banner/

Banner promozionali del progetto piTantum.

## File

| File                       | Dimensioni       | Stato          | Uso |
| -------------------------- | ---------------- | -------------- | --- |
| `banner_placeholder.svg`   | 1200x400         | placeholder    | banner editoriale, usabile direttamente nei .md |
| `banner_github.png`        | 1280x640         | da generare    | GitHub Settings -> Social preview |
| `og_image.png`             | 1200x630         | da generare    | Open Graph (Telegram/WhatsApp/Discord) |
| `banner_readme.png`        | 1200x300         | da generare    | hero del README principale |
| `banner_dashboard.png`     | 1500x300         | da generare    | hero della Dashboard (UI futura) |

## Wire

- `banner_github.png` va caricato dalla pagina GitHub del repo
  (Settings -> General -> Social preview), non viene letto dal codice.
- `og_image.png` -> aggiungere in `webui/frontend/src/app.html` un
  `<meta property="og:image" content="/branding/banner/og_image.png" />`.
- `banner_readme.png` -> referenziare in `README.md` con
  `![piTantum](branding/banner/banner_readme.png)`.
- `banner_dashboard.png` -> includere nella Dashboard
  (`webui/frontend/src/routes/+page.svelte`) come hero futuro.

## Generare le versioni definitive

Vedere [`grok_prompts.md`](grok_prompts.md) per i 4 prompt
copia-incolla pronti.
