# Proxmox Management Services

Ein modulares System für Proxmox VE Cluster-Management, bestehend aus:
- **Services**: Hintergrunddienste für Monitoring, Wartung und Automatisierung
  - `node_idle_shutdown`: Fährt Nodes automatisch herunter wenn nur noch unkritische VMs laufen
  - `shutdown`: Zeitbasierter VM-Shutdown für Wartungsfenster
- **REST APIs**: Backend-Services für externe Integrationen
- **Web Frontend**: Dashboard für Cluster-Übersicht und -Verwaltung

## Projektstruktur

```
.
├── services/                  # Hintergrunddienste (Python)
│   ├── node_idle_shutdown/   # Automatischer Node-Shutdown bei Idle
│   └── shutdown/             # Zeitbasierter VM-Shutdown
├── api/                      # REST API Backends (Python/FastAPI)
├── web/                      # Web Frontends (HTML/JS/React)
├── scripts/                  # Utility-Scripts
└── shared/                   # Gemeinsame Bibliotheken und Utilities
    ├── proxmox/              # Proxmox API Client mit Tag-Support
    └── config/               # Konfigurationsverwaltung
```

## Technologie-Stack

- **Services**: Python 3.11+ mit proxmoxer für Proxmox API
- **API**: FastAPI für REST Endpoints
- **Web**: Moderne JavaScript/TypeScript (React/Vue)
- **Config**: YAML/TOML für Konfigurationsdateien

## Installation

### Automatische Installation (empfohlen)

```bash
# Als root ausführen
sudo ./install.sh
```

Das Script:
- ✅ Prüft Debian-Version (13+)
- ✅ Installiert fehlende Dependencies
- ✅ Erstellt Service-User
- ✅ Richtet Virtual Environment ein
- ✅ Installiert systemd Services
- ✅ Konfiguriert Berechtigungen

**Unterstützt:** Debian 13 (Trixie) und neuere Versionen

### Nach Installation

1. **Proxmox API konfigurieren:**
   ```bash
   sudo nano /opt/proxmox-services/config/proxmox.yml
   ```

2. **Services aktivieren:**
   ```bash
   # Node Idle Shutdown
   sudo systemctl enable --now proxmox-node-idle-shutdown
   
   # Scheduled Shutdown
   sudo systemctl enable --now proxmox-scheduled-shutdown
   ```

3. **Logs überwachen:**
   ```bash
   sudo journalctl -u proxmox-node-idle-shutdown -f
   ```

### Deinstallation
```bash
sudo ./uninstall.sh
```

## Entwicklung

### Lokales Setup (ohne Installation)
```bash
# Virtual Environment erstellen
python3 -m venv venv
source venv/bin/activate

# Dependencies installieren
pip install -r requirements.txt

# Config kopieren
cp config/proxmox.example.yml config/proxmox.yml
# Config bearbeiten mit echten Credentials

# Services testen
python -m services.node_idle_shutdown.main
python -m services.shutdown.main
```

## Konfiguration

### 1. Proxmox API Token erstellen (Proxmox VE 9.x)

**Via Web UI:**
1. Datacenter → Permissions → API Tokens
2. Add → Token erstellen:
   - User: `root@pam` (oder eigener User)
   - Token ID: `automation` (beliebiger Name)
   - ✅ **Privilege Separation deaktivieren** (für volle User-Rechte)
3. Token Secret kopieren (wird nur einmal angezeigt!)

**Via CLI (auf Proxmox Node):**
```bash
# Token erstellen (ohne Privilege Separation)
pveum user token add root@pam automation --privsep 0

# Ausgabe: Token Secret (sicher aufbewahren!)
# ┌──────────────┬──────────────────────────────────────┐
# │ key          │ value                                │
# ├──────────────┼──────────────────────────────────────┤
# │ full-tokenid │ root@pam!automation                  │
# │ info         │ {"privsep":0}                        │
# │ value        │ xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx │
# └──────────────┴──────────────────────────────────────┘

# Token-Liste anzeigen
pveum user token list root@pam
```

### 2. Proxmox API Config
Erstelle `config/proxmox.yml` mit den Token-Daten:
```bash
cp config/proxmox.example.yml config/proxmox.yml
```

Fülle die Datei aus:
```yaml
proxmox:
  host: "192.168.1.10"          # Proxmox Host IP/Hostname
  user: "root@pam"               # User@Realm
  token_name: "automation"       # Token ID (ohne User-Prefix)
  token_value: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # Secret
  verify_ssl: false              # true bei gültigem SSL-Zertifikat
```

**Format-Hinweis:** Der `token_name` ist nur die Token-ID **ohne** User-Prefix:
- Full Token ID: `root@pam!automation`
- In Config verwenden: `token_name: "automation"`

### 3. VM/Container Tags
Das System nutzt Proxmox Tags für intelligente Filterung:

**`safe-shutdown` Tag**: VMs/Container mit diesem Tag sind "unkritisch"
- Node Idle Shutdown: Node wird heruntergefahren wenn **nur noch** VMs mit diesem Tag laufen
- Logik: VMs **OHNE** Tag = kritisch, blockieren Node-Shutdown

**Tags setzen:**
```bash
# Unkritische VMs taggen (dürfen automatisch gestoppt werden)
python scripts/tag_vms.py --tag safe-shutdown --vmids 200 201 202
qm set 200 --tags safe-shutdown

# Kritische VMs NICHT taggen (halten Node am Laufen)
# Beispiel: Datenbank, Monitoring, Router-VMs

# Alle VMs anzeigen
python scripts/tag_vms.py --list
```
