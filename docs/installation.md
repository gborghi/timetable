# Guida all'installazione

Guida cross-platform per installare ed eseguire **piTantum** su
Windows, Linux e macOS. Il progetto è composto da un backend Python
(FastAPI + SQLAlchemy + ortools) e un frontend SvelteKit (Vite +
Tailwind), avviati insieme da uno script unico (`start.bat` su
Windows, `start.sh` su Linux / macOS).

> Quick start: installa Python ≥ 3.11, Node ≥ 20 LTS, Git → clona il
> repo → lancia `webui/start.bat` (Windows) o `./webui/start.sh`
> (Linux / macOS) → apri <http://localhost:5173>.

Indice:

- [Windows](#windows)
- [Linux (Ubuntu / Debian / Fedora / Arch)](#linux)
- [macOS (Intel + Apple Silicon)](#macos)
- [Verifica installazione](#verifica-installazione)
- [Aggiornamento](#aggiornamento)
- [Disinstallazione](#disinstallazione)

---

## Windows

### Prerequisiti

| Strumento | Versione | Installer ufficiale |
| --------- | -------- | ------------------- |
| Python    | ≥ 3.11   | <https://www.python.org/downloads/windows/> |
| Node.js   | ≥ 20 LTS | <https://nodejs.org/en/download> (scegli "LTS") |
| Git       | qualsiasi recente | <https://git-scm.com/download/win> |

**Note importanti durante l'installazione**:

- **Python**: spunta `Add python.exe to PATH` nella prima schermata
  dell'installer. Senza, lo script `start.bat` non troverà il
  comando `python` e fallirà al primo lancio.
- **Node**: l'installer aggiunge `npm` al PATH automaticamente.
  Conferma "Automatically install the necessary tools" nella
  schermata "Tools for Native Modules" — ti risparmia problemi se
  in futuro ti servirà compilare moduli C nativi.
- **Git**: lascia le opzioni di default ("Git from the command line
  and also from 3rd-party software" e "Use Windows' default console
  window") a meno che tu non abbia preferenze.

Dopo l'installazione **chiudi e riapri** ogni terminale `cmd` /
PowerShell aperto, altrimenti il PATH non è aggiornato.

### Clone del repo

```cmd
cd C:\Users\<utente>\code
git clone https://github.com/gborghi/timetable.git
cd timetable
```

(Il path è arbitrario; scegli dove preferisci. Evita percorsi con
spazi se possibile.)

### Primo lancio

Doppio-click su `webui\start.bat`. Lo script:

1. crea `webui\backend\.venv\` se manca (può richiedere 30-60s)
2. installa le dipendenze Python da `webui\backend\requirements.txt`
   (1-3 minuti la prima volta)
3. crea `webui\frontend\node_modules\` se manca
4. lancia `npm install` per le dipendenze frontend (1-3 minuti la
   prima volta)
5. apre due finestre `cmd`:
   - "**piTantum - backend**" con uvicorn su porta 8000
   - "**piTantum - frontend**" con Vite su porta 5173

Quando entrambe le finestre mostrano log stabili (`Application
startup complete` per il backend, `ready in 1234 ms` per Vite), apri
il browser su <http://localhost:5173>.

### Avvio quotidiano

Doppio-click su `webui\start.bat` (le dipendenze sono già
installate, parte in 5-10 secondi). In alternativa da PowerShell:

```powershell
.\webui\start.ps1
```

### Stop

Su Windows non c'è uno script `stop.bat` dedicato: chiudi le due
finestre `cmd` aperte da `start.bat`, oppure premi `Ctrl+C` in
ciascuna.

### Troubleshooting Windows

- **`python` non riconosciuto come comando**: hai dimenticato di
  spuntare "Add to PATH". Reinstalla Python o aggiungi manualmente
  `C:\Users\<tu>\AppData\Local\Programs\Python\Python311\` (e
  sottocartella `Scripts\`) al PATH di sistema.
- **`npm` non riconosciuto come comando**: chiudi e riapri il
  terminale; se persiste, reinstalla Node.js.
- **`Errno 98 / Address already in use` sul backend**: la porta 8000
  è già occupata. Esegui `netstat -ano | findstr :8000` per trovare
  il PID, poi `taskkill /PID <pid> /F`.
- **`Errno 98` sul frontend**: stessa cosa con porta 5173.
- **Antivirus blocca lo script**: aggiungi `webui\start.bat` alla
  whitelist (Windows Defender → Sicurezza → Esclusioni).
- **`SSL: CERTIFICATE_VERIFY_FAILED` su `pip install`**: rete azienda
  con proxy MITM. Soluzione: aggiungi il certificato della tua
  organizzazione al `cacert.pem` di Python, oppure imposta
  `PIP_TRUSTED_HOST=pypi.org`.

---

## Linux

Testato su Ubuntu 22.04 LTS, Debian 12, Fedora 40, Arch Linux,
Manjaro 24.

### Prerequisiti

Python ≥ 3.11, Node ≥ 20 LTS, Git, build-essential (per moduli C
opzionali). Comandi di installazione per famiglia di distribuzione:

#### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm git \
                    build-essential
```

> ⚠️ **Attenzione**: i repo apt di Ubuntu 22.04 hanno Node 12 (troppo
> vecchio) e Debian 12 ha Node 18. SvelteKit 2 richiede Node 20+.
> Soluzione consigliata: installa **nvm** e ottieni la LTS più
> recente:
>
> ```bash
> curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
> source ~/.bashrc
> nvm install --lts
> nvm use --lts
> ```

#### Fedora

```bash
sudo dnf install -y python3 python3-virtualenv nodejs npm git \
                    gcc make
```

Fedora 40+ ha già Node 20 nei repo ufficiali. In versioni più
vecchie usa `nvm` come sopra.

#### Arch / Manjaro

```bash
sudo pacman -S python python-pip nodejs npm git base-devel
```

Arch ha sempre la rolling release più recente, quindi Node è già
20+.

### Clone + lancio

```bash
cd ~/code            # o dove preferisci
git clone https://github.com/gborghi/timetable.git
cd timetable
chmod +x webui/start.sh webui/stop.sh
./webui/start.sh
```

Lo script:

1. crea `webui/backend/.venv/` se manca
2. installa requirements Python
3. crea `webui/frontend/node_modules/` se manca
4. installa dipendenze frontend
5. avvia backend + frontend **in background**, scrivendo i log in
   `webui/logs/{backend,frontend}.log`

### Avvio in foreground

Se preferisci vedere i log live in console (entrambi i processi
moriranno con `Ctrl+C`):

```bash
./webui/start.sh --foreground
```

### Stop

```bash
./webui/stop.sh
```

Lo script legge i PID da `webui/logs/pids` e termina entrambi i
processi (SIGTERM, fallback SIGKILL dopo 3s).

### Troubleshooting Linux

- **`Address already in use` su porta 8000 o 5173**:
  ```bash
  sudo lsof -i :8000     # mostra il PID che la occupa
  kill <pid>             # SIGTERM
  kill -9 <pid>          # forza
  ```
  Se `lsof` non è installato: `sudo apt install lsof` /
  `sudo dnf install lsof`.
- **`python3: command not found`**: alcune distro minimal hanno solo
  `python` (3.x); aggiungi un alias o riusa quello.
- **`npm install` molto lento**: usa un mirror; per esempio
  `npm config set registry https://registry.npmmirror.com/`.
- **`error: Microsoft Visual C++ ... required` quando installa
  ortools**: solo su Windows. Su Linux ortools spedisce wheel
  precompilati per glibc moderni; aggiorna pip:
  `python3 -m pip install --upgrade pip`.
- **WSL2**: `start.sh` funziona normalmente. Apri il browser dal lato
  Windows su `http://localhost:5173`; WSL2 inoltra le porte
  automaticamente.

---

## macOS

Testato su macOS 12 Monterey (Intel) e macOS 14 Sonoma (Apple
Silicon M1/M2).

### Prerequisiti

| Strumento | Versione | Comando |
| --------- | -------- | ------- |
| Xcode CLT | qualsiasi | `xcode-select --install` |
| Python    | ≥ 3.11    | `brew install python@3.12` |
| Node.js   | ≥ 20 LTS  | `brew install node` |
| Git       | qualsiasi | `brew install git` (o già nel CLT) |

### Installazione tramite Homebrew

```bash
# 1. Installa Homebrew se non l'hai
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Installa i prerequisiti
brew install python@3.12 node git

# 3. Verifica
python3 --version    # >= 3.11
node --version       # >= v20
git --version
```

### Note specifiche Apple Silicon

- **ortools**: dalla v9.7 spedisce wheel ARM64 nativi per macOS.
  Usa `requirements.txt` di piTantum (richiede `ortools>=9.7`).
- **Rosetta NON serve**: tutto il toolchain (Python ARM, Node ARM,
  ortools ARM) gira nativo.
- Se installi Python da python.org invece che da Homebrew, scegli
  l'installer "macOS 64-bit universal2" (combinato Intel + ARM).

### Note specifiche Intel

Nessuna nota particolare. macOS 11+ supportato.

### Clone + lancio

```bash
cd ~/code
git clone https://github.com/gborghi/timetable.git
cd timetable
chmod +x webui/start.sh webui/stop.sh
./webui/start.sh
```

Stesso flusso di Linux: backend in background, log in
`webui/logs/`, browser su <http://localhost:5173>.

### Stop

```bash
./webui/stop.sh
```

### Troubleshooting macOS

- **Gatekeeper blocca `start.sh`**: macOS può rifiutarsi di eseguire
  script scaricati. Soluzione:
  ```bash
  xattr -d com.apple.quarantine webui/start.sh webui/stop.sh
  ```
  o approva manualmente in Sistema → Privacy e Sicurezza.
- **`xcode-select: error: tool 'xcodebuild' requires Xcode`**: hai
  installato CLT ma Homebrew vuole Xcode completo. Lancia:
  ```bash
  sudo xcode-select --switch /Library/Developer/CommandLineTools
  ```
- **ortools mancano wheel ARM** (versioni vecchie macOS / ortools
  &lt; 9.7): aggiorna il pacchetto:
  ```bash
  source webui/backend/.venv/bin/activate
  pip install --upgrade ortools
  ```
- **`zsh: command not found: brew`**: `/opt/homebrew/bin` non è nel
  PATH. Aggiungi `eval "$(/opt/homebrew/bin/brew shellenv)"` al tuo
  `~/.zprofile`.
- **Porta 8000 / 5173 occupata**:
  ```bash
  lsof -i :8000
  kill <pid>
  ```

---

## Verifica installazione

Dopo il primo lancio andato a buon fine, verifica che tutto sia in
piedi:

```bash
# 1. Versioni dei toolchain (su tutti gli OS)
python --version       # deve dare >= 3.11   (su Linux/macOS forse python3)
node --version         # deve dare >= v20
npm --version          # deve dare >= 10
git --version

# 2. Backend health
curl http://127.0.0.1:8000/api/health
# Output atteso: {"status":"ok","name":"pitantum","version":"0.1.0"}

# 3. Async layer (sezione 2.5 P2)
curl http://127.0.0.1:8000/api/health/async
# Output atteso: {"status":"ok","async":true,"dialect":"sqlite"}

# 4. Frontend
curl -I http://127.0.0.1:5173
# Output atteso: HTTP/1.1 200 OK
```

Se tutti e quattro rispondono, l'installazione è completa. Apri il
browser su <http://localhost:5173> e fai un giro: clic su
"Visualizza grafo" sulla Dashboard, oppure importa il profilo
`small` per popolare il DB.

---

## Aggiornamento

Quando vuoi portarti a casa nuovi commit:

```bash
cd /path/to/timetable
git pull origin main

# Se il commit ha aggiunto / aggiornato dipendenze Python:
webui/backend/.venv/bin/pip install -r webui/backend/requirements.txt
# (Windows: webui\backend\.venv\Scripts\pip install ...)

# Se ha aggiornato dipendenze frontend:
cd webui/frontend && npm install && cd ../..

# Se ci sono migration DB:
cd webui/backend && ./.venv/bin/alembic upgrade head && cd ../..
# (Windows: webui\backend\.venv\Scripts\alembic upgrade head)
```

In pratica `start.sh` / `start.bat` rilanciato dopo `git pull`
gestisce automaticamente `pip install` e `npm install` quando
servono. Le migration DB sono coperte da
`_apply_lightweight_migrations()` allo startup come safety-net (vedi
[data_model.md](data_model.md) sezione "Migrazioni"); per la via
canonica usa `alembic upgrade head`.

Dopo un aggiornamento che cambia il backend è prudente fare un
**hard reload del browser** (Ctrl+Shift+R) per pulire eventuali chunk
JavaScript cached.

---

## Disinstallazione

```bash
cd /path/to/timetable
./webui/stop.sh                 # Linux/macOS
# (Windows: chiudi le finestre cmd di start.bat)

rm -rf webui/backend/.venv      # rimuove venv Python (~150 MB)
rm -rf webui/frontend/node_modules  # rimuove node_modules (~400 MB)
rm -rf webui/data/timetable.db  # rimuove il DB SQLite (DATI UTENTE!)
```

Per rimuovere completamente: cancella la cartella `timetable/`. Il
DB SQLite (`webui/data/timetable.db`) contiene i tuoi dati: salvalo
prima se li vuoi conservare.

Python, Node, Git restano installati nel sistema; rimuovili dal
gestore pacchetti (`brew uninstall ...`, `sudo apt remove ...`,
"App e funzionalità" su Windows) solo se non servono ad altri
progetti.
