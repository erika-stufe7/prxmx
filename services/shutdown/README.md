# VM Scheduled Shutdown Service

Zeitbasierter Shutdown-Service für Proxmox VMs und Container.

**Hinweis:** Für automatischen Node-Shutdown bei Idle-Zustand siehe `services/node_idle_shutdown/`

## Features

- **Zeitbasierter Shutdown**: Automatisches Herunterfahren zu definierter Uhrzeit
- **Kaskadierter Shutdown**: Definierte Reihenfolge mit Abhängigkeiten
- **Graceful Shutdown**: Konfigurierbare Timeouts für sauberes Herunterfahren
- **Tag-Filterung**: Optional nur VMs mit bestimmten Tags herunterfahren
- **Exclusion List**: VMs/Container die vom Shutdown ausgenommen sind

## Konfiguration

### 1. VMs in Proxmox taggen

Setze das Tag `safe-shutdown` für VMs die automatisch heruntergefahren werden dürfen:

**Via Proxmox Web UI:**
1. VM auswählen → Options → Tags → Edit
2. Tag `safe-shutdown` hinzufügen
3. OK klicken

**Via CLI:**
```bash
# Für VM
qm set 200 --tags safe-shutdown

# Für Container
pct set 200 --tags safe-shutdown

# Mehrere Tags (semikolon-getrennt)
qm set 200 --tags "safe-shutdown;production;web"
```

**Wichtig**: Nur VMs **mit** diesem Tag werden vom Service heruntergefahren!

### 2. Service-Config

Kopiere `config.yml` und passe an:

```yaml
enabled: true
shutdown_time:
  hour: 22
  minute: 0
grace_period: 60
safe_shutdown_tag: "safe-shutdown"  # Anpassbar
excluded_vms: [100, 101]  # Zusätzliche Ausnahmen
```

## Ausführung

```bash
# Service starten
python -m services.shutdown.main

# Als Hintergrunddienst (mit nohup)
nohup python -m services.shutdown.main > /var/log/proxmox-shutdown.log 2>&1 &
```

## Systemd Integration

Erstelle `/etc/systemd/system/proxmox-shutdown.service`:

```ini
[Unit]
Description=Proxmox VM Shutdown Service
After=network.target

[Service]
Type=simple
User=proxmox
WorkingDirectory=/home/kewlio/DEV/proxmox
ExecStart=/home/kewlio/DEV/proxmox/venv/bin/python -m services.shutdown.main
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Aktivieren:
```bash
sudo systemctl enable proxmox-shutdown
sudo systemctl start proxmox-shutdown
sudo systemctl status proxmox-shutdown
```

## Use Cases

### Nächtlicher Shutdown
Fahre alle VMs nachts automatisch herunter:
```yaml
shutdown_time: {hour: 22, minute: 0}
safe_shutdown_tag: "safe-shutdown"
```

Tagge alle Desktop-VMs mit `safe-shutdown`, kritische Services nicht.

### Wartungsfenster
Koordinierter Shutdown für Updates mit Abhängigkeiten:
```yaml
shutdown_order:
  - name: "Frontends"
    vmids: [110, 111]
    wait_after: 30
  - name: "App Servers"
    vmids: [105, 106]
    wait_after: 60
  - name: "Databases"
    vmids: [100, 101]
```

## Logging

Service loggt nach stdout (umleiten für Persistenz):
- Info: Normale Operationen
- Error: Fehlgeschlagene Shutdowns (VM läuft weiter)
