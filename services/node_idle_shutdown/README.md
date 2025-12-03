# Node Idle Shutdown Service

Automatischer Node-Shutdown Service der Proxmox Nodes herunterfährt wenn nur noch VMs/Container mit `safe-shutdown` Tag laufen.

## Konzept

Der Service überwacht kontinuierlich den Node und prüft:
1. **Laufen kritische VMs?** → VMs/Container **OHNE** `safe-shutdown` Tag
2. **Falls NEIN** → Node ist "idle" und kann heruntergefahren werden
3. **Grace Period** → Wartezeit bevor Shutdown (verhindert Flapping)
4. **Shutdown-Sequenz** → Erst tagged VMs stoppen, dann Node herunterfahren

## Use Case

**Energie sparen bei hybrider Workload:**
- Permanente Services (Datenbank, Monitoring) → **KEIN** Tag
- On-Demand Services (Dev-VMs, Test-Container) → **MIT** `safe-shutdown` Tag
- Wenn nur noch On-Demand Services laufen → Node automatisch herunterfahren

## Konfiguration

```yaml
enabled: true
check_interval: 300       # Alle 5 Minuten prüfen
safe_shutdown_tag: "safe-shutdown"
grace_period: 60          # 60s warten nach Idle-Erkennung
dry_run: false            # true = nur loggen, false = wirklich herunterfahren
min_uptime: 600           # Node muss mind. 10 Min laufen
```

## VM-Setup

### Kritische VMs (blockieren Shutdown)
```bash
# KEIN Tag setzen - diese VMs halten den Node am Laufen
# Beispiele: Datenbank, Monitoring, Router-VMs
```

### Unkritische VMs (erlauben Shutdown)
```bash
# Tag setzen - diese VMs dürfen gestoppt werden
qm set 200 --tags safe-shutdown    # Desktop VM
qm set 201 --tags safe-shutdown    # Dev Server
pct set 150 --tags safe-shutdown   # Test Container
```

## Beispiel-Workflow

### Ausgangssituation (Node läuft)
```
Node: pve01
├─ VM 100 (MariaDB)          → KEIN Tag → KRITISCH
├─ VM 105 (Monitoring)       → KEIN Tag → KRITISCH  
├─ VM 200 (Desktop)          → safe-shutdown → unkritisch
└─ CT 150 (Dev Environment)  → safe-shutdown → unkritisch
```
**Status: Node aktiv** (kritische VMs laufen)

### Nach Shutdown kritischer VMs
```
Node: pve01
├─ VM 100 (MariaDB)          → gestoppt
├─ VM 105 (Monitoring)       → gestoppt
├─ VM 200 (Desktop)          → läuft (safe-shutdown)
└─ CT 150 (Dev Environment)  → läuft (safe-shutdown)
```
**Status: Node wird IDLE** → Service erkennt: nur noch VMs mit Tag laufen

### Nach Grace Period (60s)
```
1. Service stoppt VM 200 und CT 150
2. Service fährt Node pve01 herunter
3. Node ist aus → Energie gespart ⚡
```

## Systemd Integration

`/etc/systemd/system/proxmox-node-idle-shutdown.service`:
```ini
[Unit]
Description=Proxmox Node Idle Shutdown Service
After=network.target pve-cluster.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/proxmox-services
ExecStart=/opt/proxmox-services/venv/bin/python -m services.node_idle_shutdown.main
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Aktivieren:
```bash
sudo systemctl enable proxmox-node-idle-shutdown
sudo systemctl start proxmox-node-idle-shutdown
sudo systemctl status proxmox-node-idle-shutdown
```

## Logging

Der Service loggt **nur State-Änderungen** (kein Spam bei Checks):

### Log-Levels
- ✨ **INFO**: State-Änderungen (idle → active, Grace Period Start)
- ⚠️ **WARNING**: Shutdown-Initiation, wichtige Events
- ❌ **ERROR**: API-Fehler, Connection-Probleme
- 🚨 **CRITICAL**: Service-Stopp wegen zu vielen Fehlern

### Wichtige Log-Events
```
✨ Node ist IDLE (keine kritischen VMs laufen)          # Idle-Start
⏳ Node in Grace Period (remaining_seconds: 45)        # Grace Period
⚠️ Node Idle Grace Period abgelaufen - starte Shutdown # Shutdown-Start
🔌 Starte Node-Shutdown-Sequenz                        # Shutdown aktiv
🔄 Node nicht mehr idle - kritische VMs aktiv          # Zurück zu active
```

### Logs ansehen
```bash
# Live-Logs (systemd)
journalctl -u proxmox-node-idle-shutdown -f

# Nur Errors
journalctl -u proxmox-node-idle-shutdown -p err -f

# Letzte 50 Zeilen
journalctl -u proxmox-node-idle-shutdown -n 50

# Mit Timestamps
journalctl -u proxmox-node-idle-shutdown --since "1 hour ago"
```

### Log-Konfiguration
```yaml
# Reduzierte Logs (nur State-Änderungen)
log_state_changes_only: true   # Standard

# Verbose Logging (jede Check-Iteration)
log_state_changes_only: false  # Mehr Output
```

## Sicherheit & Fehlerbehandlung

### Config-Validierung
Service validiert Config beim Start:
- `check_interval` >= 30s
- `grace_period` >= 10s
- Proxmox-Verbindung erreichbar
- Bei ungültiger Config: Service startet nicht

### Dry-Run Modus
Testen ohne echten Shutdown:
```yaml
dry_run: true  # Nur loggen, NICHT herunterfahren
```

### Minimum Uptime
Node muss erst eine Weile laufen (verhindert Boot-Loop):
```yaml
min_uptime: 600  # 10 Minuten
```

### Grace Period
Wartezeit nach Idle-Erkennung (verhindert Flapping):
```yaml
grace_period: 300  # 5 Minuten warten
```

### Error-Handling
Service stoppt automatisch bei zu vielen Fehlern:
```yaml
max_consecutive_errors: 10  # Service stoppt nach 10 Fehlern
```

**Verhalten bei Fehlern:**
- API-Fehler → geloggt, Service läuft weiter
- 10 aufeinanderfolgende Fehler → Service stoppt (verhindert Endlos-Loop)
- Fehler bei Shutdown → geloggt, VMs bleiben laufen (sicher)
- Timeout bei Shutdown → 5 Min, dann Abbruch

## Monitoring

Der Service kann mit Prometheus/Telegraf integriert werden:
- Metrik: `proxmox_node_idle_duration_seconds`
- Metrik: `proxmox_node_critical_vms_count`
- Alert: Wenn Node > 1h idle aber nicht heruntergefahren

## Troubleshooting

**Node fährt nicht herunter:**
```bash
# Prüfe welche VMs als kritisch erkannt werden
python scripts/tag_vms.py --list | grep -v safe-shutdown

# Prüfe Service-Logs
journalctl -u proxmox-node-idle-shutdown --since "10 minutes ago"
```

**Node fährt zu früh herunter:**
```yaml
# Grace Period erhöhen
grace_period: 1800  # 30 Minuten
```

**Kritische VM hat fälschlicherweise Tag:**
```bash
# Tag entfernen
qm set 100 --tags ""  # Alle Tags entfernen
# Oder nur bestimmtes Tag:
qm set 100 --tags "production;database"  # safe-shutdown weglassen
```
