# Carpe Diem - branding kit

Asset visivi del progetto. Le immagini vengono generate da **Giovanni
Borghi** con **Grok** e licenziate per uso interno del progetto.

## Brand identity

- **Nome**: Carpe Diem
- **Tagline / verso**:
  > *Carpe diem, quam minimum credula postero.*
  > -- Orazio, *Odi*, I, 11
- **Traduzione**: "Cogli il giorno presente, fidandoti il meno possibile
  del domani."
- **Senso**: l'app organizza il tempo della scuola **adesso**, senza
  rimandare. Il verso oraziano riassume il programma: pianificare,
  attaccarsi al presente, non sperare nel domani per coprire i buchi.

## Palette colori suggerita

| Ruolo            | Hex      | Note |
| ---------------- | -------- | ---- |
| Accent / brand   | `#3b82f6` | blu Tailwind `accent-500` (gia' usato nel frontend) |
| Ink / testo      | `#0f172a` | nero-blu profondo |
| Background       | `#f8fafc` | grigio chiarissimo |
| Verde "ok"       | `#10b981` | per stato ALLOWED / verde della UI |
| Verde scuro      | `#065f46` | ENFORCED, anche per il latino |
| Giallo SOFT      | `#f59e0b` |
| Rosso HARD       | `#dc2626` |
| Blu PREFERITO    | `#2563eb` |

I 5 colori vincolo (HARD/SOFT/PREFERITO/ENFORCED/ALLOWED) sono gia'
codificati nel frontend; il logo dovrebbe stare bene contro qualunque
combinazione di questi.

## Font suggeriti

- **Logo wordmark**: serif classico (e.g., Cormorant Garamond, Cardo,
  EB Garamond) -- coerente con l'epigrafe latina.
- **Tagline**: serif italic dello stesso font.
- **UI / corpo**: Inter (gia' caricato dal frontend via rsms.me).

## Cosa caricare

Carica i file nelle sottocartelle, rispettando i nomi suggeriti nel
README di ciascuna. Il frontend ha gia' i wire pronti (vedere
`webui/frontend/static/branding/...`); appena le immagini sono in
posizione, l'UI le mostra senza modifiche al codice.

```
branding/
+-- README.md          (questo file)
+-- logo/              loghi principali e variant
|   +-- README.md
+-- banner/            banner per la dashboard / OG image / social
|   +-- README.md
+-- icons/             favicon, app icons, button icons
|   +-- README.md
+-- social/            preview Twitter, Facebook, LinkedIn
|   +-- README.md
+-- screenshots/       screenshot della UI per docs / README
|   +-- README.md
```

## Workflow di upload

Le immagini Grok generate vanno in due posti:

1. **`branding/<sottocartella>/<nome>.png`** -- copia "master" tracciata
   in git. Cartella di archivio: qui finiscono **anche** versioni
   intermedie, varianti scartate, esperimenti.
2. **`webui/frontend/static/branding/<sottocartella>/<nome>.png`** --
   copia "served" da Vite. Solo i file che usa la UI. Per come e'
   configurato SvelteKit, ogni file in `static/` e' raggiungibile
   come URL nel browser (es. `/branding/logo/logo_light.png`).

Quando aggiungi un asset:

```
# 1. salva la versione master nell'archivio
cp ~/Downloads/logo_v3.png branding/logo/logo_light.png

# 2. copia la stessa nella static folder per la UI
cp branding/logo/logo_light.png webui/frontend/static/branding/logo/

# 3. commit
git add branding webui/frontend/static/branding
git commit -m "branding: logo light v3"
git push
```

Il frontend ha fallback testuale: se l'immagine non esiste ancora, la
UI mostra il wordmark "Carpe Diem" in puro testo (vedere
`webui/frontend/src/routes/+layout.svelte`). Quindi puo' lavorare
senza asset finche' non li carichi.

## Licenza degli asset

> Le immagini sono generate da Giovanni Borghi via Grok e licenziate
> per uso interno del progetto Carpe Diem. Non sono distribuite con
> licenza pubblica e non possono essere riutilizzate al di fuori del
> progetto senza esplicito consenso dell'autore.

Eventuali screenshot della UI a supporto della documentazione
(README, manuale tecnico) sono autorizzati come parte del progetto
stesso.
