# branding/banner/

Banner promozionali del progetto Carpe Diem.

## File attesi

| File                       | Tipo  | Dimensioni       | Uso |
| -------------------------- | ----- | ---------------- | --- |
| `banner_dashboard.png`     | PNG   | 1500x300         | banner della Dashboard / hero image della UI (futuro) |
| `banner_github.png`        | PNG   | 1280x640         | "social preview" del repo su GitHub (Settings / Social preview) |
| `banner_readme.png`        | PNG   | 1200x400         | hero image del README principale (in alto, sopra il titolo) |
| `og_image.png`             | PNG   | 1200x630         | Open Graph image per quando il sito e' linkato su Telegram / WhatsApp / Discord |

## Note sul design

- L'OG image per GitHub deve essere **leggibile in piccolo** e contenere
  il nome "Carpe Diem", il sottotitolo / tagline e magari la grid 6x6.
- I banner sono opzionali: il progetto funziona benissimo senza, e si
  possono aggiungere in qualunque momento.

## Wire

- `banner_github.png` va caricato dalla pagina del repo
  (Settings -> General -> Social preview -> Edit), non viene letto in
  automatico dal codice.
- `og_image.png` puo' essere referenziato in
  `webui/frontend/src/app.html` con un meta tag
  `<meta property="og:image" content="/branding/banner/og_image.png" />`
  (da aggiungere quando esiste).
- `banner_readme.png`, una volta caricato, va incluso nel
  `README.md` principale come prima riga (img markdown).
