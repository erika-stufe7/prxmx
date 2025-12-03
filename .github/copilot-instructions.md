# Proxmox Management Services - AI Coding Instructions

## Projekt-Architektur

Dieses Projekt ist ein **modulares Proxmox VE Management-System** mit drei Hauptkomponenten:

1. **Services** (`services/`): Hintergrunddienste für Automatisierung (Python, asyncio)
2. **REST APIs** (`api/`): Backend-Endpoints für externe Integration (FastAPI)
3. **Web Frontend** (`web/`): Dashboard für Cluster-Übersicht

**Zentrale Designentscheidung**: Shared Proxmox Client (`shared/proxmox/client.py`) als Singleton für konsistente API-Verbindungen über alle Komponenten.

## Proxmox API Patterns

### Client-Nutzung
```python
from shared.proxmox import ProxmoxClient

# Immer Singleton verwenden
proxmox = ProxmoxClient.get_instance()

# VM-Operationen
vms = proxmox.get_vms(node='pve01')
proxmox.shutdown_vm(node='pve01', vmid=100, timeout=60)
```

**Wichtig**: Verwende nie `ProxmoxClient()` direkt, sondern immer `.get_instance()` für Connection Pooling.

### Node/VMID Discovery
VMs/Container sind node-spezifisch. Nutze `_find_vm_node()` Pattern aus `services/shutdown/main.py`:
- Iteriere über alle Nodes
- Prüfe VMs mit `proxmox.get_vms(node)`
- Prüfe Container mit `proxmox.get_containers(node)`

### Tag-basierte Filterung
Proxmox Tags sind semikolon-getrennte Strings im Config. Nutze Client-Methoden:
```python
# Tag prüfen
if proxmox.has_tag(node, vmid, 'safe-shutdown', vm_type='vm'):
    await shutdown_vm()

# Alle Tags abrufen
tags = proxmox.get_vm_tags(node, vmid, vm_type='container')
```

**Tag-Konvention**: Verwende kebab-case (`safe-shutdown`, nicht `SafeShutdown`).

## Service Development Patterns

### Service-Struktur (siehe `services/node_idle_shutdown/` oder `services/shutdown/`)
```
services/<service-name>/
├── main.py         # Entry point mit async main() + Service class
├── config.yml      # YAML-Config für Service-spezifische Settings
└── README.md       # Service-Dokumentation
```

### Async Service Loop Pattern
```python
class MyService:
    async def run(self):
        self.running = True
        while self.running:
            try:
                await self.check_and_perform()
            except Exception as e:
                logger.error("Error", error=str(e))
            await asyncio.sleep(self.config.check_interval)
```

### Config-Management
Jeder Service hat eigene `config.yml` mit `enabled` Flag. Prüfe immer `if not self.config.enabled: return`.

## Konfiguration & Secrets

- **Proxmox Credentials**: `config/proxmox.yml` (gitignored, Vorlage: `proxmox.example.yml`)
- **Service Configs**: `services/<name>/config.yml` (nicht gitignored, enthält keine Secrets)
- **API Token**: Verwende Proxmox API Tokens, keine Passwörter

### Config-Laden Pattern
```python
def _load_config(self) -> dict:
    if not self.config_path.exists():
        example_path = self.config_path.parent / f"{self.config_path.stem}.example{self.config_path.suffix}"
        if example_path.exists():
            raise FileNotFoundError(f"Kopiere {example_path} nach {self.config_path}")
```

## Logging

Nutze **structlog** für strukturiertes Logging:
```python
logger.info("Shutting down VM", vmid=100, node="pve01", timeout=60)
logger.error("Shutdown failed", vmid=100, error=str(e))
```

Vorteile: Maschinell parsbar, bessere Filterung in Log-Aggregation.

## Entwicklungs-Workflows

### Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config/proxmox.example.yml config/proxmox.yml
# Fülle config/proxmox.yml mit echten Credentials
```

### Service lokal testen
```bash
# Einzelner Service
python -m services.shutdown.main

# Mit Debug-Output
PYTHONPATH=. python services/shutdown/main.py
```

### Code-Qualität
```bash
# Formatierung
black .

# Linting
ruff check .
```

## Wichtige Konventionen

1. **VMIDs sind Integers**: Immer `vmid: int`, nie Strings
2. **Node-Namen sind Strings**: `node: str` (z.B. 'pve01', 'pve02')
3. **Timeouts in Sekunden**: Alle Timeout-Parameter in Sekunden als `int`
4. **Async für I/O**: Services nutzen `asyncio` für Proxmox API Calls
5. **Error Handling**: Catch Exceptions, logge mit structlog, Service läuft weiter
6. **Tags in kebab-case**: Proxmox Tags immer lowercase mit Bindestrichen (`safe-shutdown`, `prod-web`)

## VM/Container Unterscheidung

Proxmox unterscheidet zwischen:
- **VMs** (QEMU): `proxmox.nodes(node).qemu.*`
- **Containers** (LXC): `proxmox.nodes(node).lxc.*`

Operationen sind identisch benannt aber auf unterschiedlichen Endpoints:
```python
proxmox.shutdown_vm(node, vmid, timeout)       # für VMs
proxmox.shutdown_container(node, vmid, timeout) # für LXC
```

## Typische Service-Aufgaben

### Node Idle Shutdown Pattern
Prüfe ob nur VMs mit bestimmtem Tag laufen → siehe `services/node_idle_shutdown/main.py`:
- Iteriere über alle VMs/Container
- Prüfe Tags mit `proxmox.has_tag()`
- VMs OHNE `safe-shutdown` Tag = kritisch, blockieren Shutdown
- Track Idle-Zustand mit Grace Period (verhindert Flapping)

### Monitoring Service
Prüfe Status, sammle Metriken → nutze `asyncio.gather()` für parallele Node-Abfragen

### Maintenance Service
Zeitgesteuerte Tasks → nutze `datetime.time` Vergleiche wie in `services/shutdown/main.py`

### Alert Service
Webhook/Email bei Problemen → integriere mit `structlog` Logger

## REST API (Future)

APIs in `api/` folgen FastAPI Patterns:
- Dependency Injection für ProxmoxClient
- Pydantic Models für Request/Response
- Async Endpoints für Proxmox Calls

## Testing

Nutze `pytest-asyncio` für async Service Tests:
```python
@pytest.mark.asyncio
async def test_shutdown_service():
    service = ShutdownService()
    # ...
```

Mock ProxmoxClient für Unit-Tests ohne echte Proxmox-Verbindung.
