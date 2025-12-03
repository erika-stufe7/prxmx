# prxmx - Proxmox Service Collection

A growing collection of automation services for Proxmox VE clusters.

## 🎯 Available Services

### `node_idle_shutdown` - Smart Node Shutdown ⚡
Automatically shuts down Proxmox nodes when only non-critical VMs are running.
- **Use Case:** Energy saving with hybrid workloads
- **Logic:** VMs without `safe-shutdown` tag keep the node running
- **Status:** ✅ Production-ready

### `shutdown` - Scheduled VM Shutdown 🕒
Time-based shutdown of VMs at defined times.
- **Use Cases:**
  - **Solar Energy Optimization:** Shutdown nodes at night when solar surplus ends, save battery/grid costs
  - **Crypto Mining:** Run mining operations during free solar hours, auto-shutdown when electricity costs exceed profits
  - **Peak Energy Savings:** Run workloads during cheap daytime solar hours, shutdown expensive night operations
  - **Maintenance Windows:** Scheduled shutdowns for updates and maintenance
- **Features:** Cascading shutdown, tag-based filtering
- **Status:** ✅ Production-ready

## 🔮 Planned Services

### Cluster Management
- `backup_scheduler` - Intelligent backup orchestration
- `health_monitor` - Cluster health monitoring and alerting
- `resource_optimizer` - Automatic VM migration based on load
- `snapshot_manager` - Snapshot lifecycle management

### VM Provisioning
- `win11_gaming_provisioner` - Automated Windows 11 Gaming VM creation
  - NVIDIA GPU passthrough (vGPU or PCIe)
  - Game streaming setup (Parsec, Moonlight, Steam Remote Play)
  - Optimized gaming performance (CPU pinning, huge pages)
  - Template-based deployment
  - *AI-assisted configuration already developed - integration coming soon*

## 🏗️ Architecture

Modular system with shared libraries:
- **Services**: Independent background services (Python, asyncio)
- **Shared Client**: Unified Proxmox API access with tag support
- **Systemd Integration**: Native Linux service management
- **Future**: REST APIs and web dashboard planned

## Project Structure

```
.
├── services/                  # Background services (Python)
│   ├── node_idle_shutdown/   # Automatic node shutdown when idle
│   └── shutdown/             # Scheduled VM shutdown
├── api/                      # REST API backends (Python/FastAPI)
├── web/                      # Web frontends (HTML/JS/React)
├── scripts/                  # Utility scripts
└── shared/                   # Shared libraries and utilities
    ├── proxmox/              # Proxmox API client with tag support
    └── config/               # Configuration management
```

## 🛠️ Tech Stack

- **Services**: Python 3.11+ with asyncio
- **Proxmox API**: proxmoxer library
- **Config**: YAML configuration
- **Logging**: structlog (structured JSON logging)
- **Deployment**: systemd services
- **Future**: FastAPI REST APIs, React dashboard

## Installation

### Automatic Installation (recommended)

```bash
# Clone repository (use permanent location, not /tmp!)
cd /opt
git clone https://github.com/erika-stufe7/prxmx.git
cd prxmx

# Run installation
sudo bash install.sh
```

The script will:
- ✅ Check Debian version and Python 3.10+
- ✅ Install missing dependencies (python3-venv, pip, git, rsync)
- ✅ Create service user (`proxmox-services`)
- ✅ Copy files to `/opt/proxmox-services`
- ✅ Set up virtual environment
- ✅ Install Python dependencies
- ✅ Create systemd services
- ✅ Install uninstall command: `proxmox-services-uninstall`

**Supported:** Debian 13 (Trixie), Proxmox VE 9, and newer versions

### Post-Installation

1. **Configure Proxmox API:**
   ```bash
   sudo nano /opt/proxmox-services/config/proxmox.yml
   ```

2. **Enable services:**
   ```bash
   # Node Idle Shutdown
   sudo systemctl enable --now proxmox-node-idle-shutdown
   
   # Scheduled Shutdown
   sudo systemctl enable --now proxmox-scheduled-shutdown
   ```

3. **Monitor logs:**
   ```bash
   sudo journalctl -u proxmox-node-idle-shutdown -f
   ```

### Uninstallation
```bash
# Uninstall command is available globally after installation
sudo proxmox-services-uninstall

# Alternative: Run from installation directory
sudo /opt/proxmox-services/uninstall.sh
```

## Development

### Local Setup (without installation)
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy config
cp config/proxmox.example.yml config/proxmox.yml
# Edit config with real credentials

# Test services
python -m services.node_idle_shutdown.main
python -m services.shutdown.main
```

## Configuration

### 1. Create Proxmox API Token (Proxmox VE 9.x)

**Via Web UI:**
1. Datacenter → Permissions → API Tokens
2. Add → Create token:
   - User: `root@pam` (or custom user)
   - Token ID: `automation` (any name)
   - ✅ **Disable Privilege Separation** (for full user rights)
3. Copy token secret (shown only once!)

**Via CLI (on Proxmox node):**
```bash
# Create token (without privilege separation)
pveum user token add root@pam automation --privsep 0

# Output: Token secret (keep secure!)
# ┌──────────────┬──────────────────────────────────────┐
# │ key          │ value                                │
# ├──────────────┼──────────────────────────────────────┤
# │ full-tokenid │ root@pam!automation                  │
# │ info         │ {"privsep":0}                        │
# │ value        │ xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx │
# └──────────────┴──────────────────────────────────────┘

# List tokens
pveum user token list root@pam
```

### 2. Proxmox API Config
Create `config/proxmox.yml` with token data:
```bash
cp config/proxmox.example.yml config/proxmox.yml
```

Fill in the file:
```yaml
proxmox:
  host: "192.168.1.10"          # Proxmox host IP/hostname
  user: "root@pam"               # User@Realm
  token_name: "automation"       # Token ID (without user prefix)
  token_value: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # Secret
  verify_ssl: false              # true for valid SSL certificate
```

**Format note:** The `token_name` is only the token ID **without** user prefix:
- Full Token ID: `root@pam!automation`
- Use in config: `token_name: "automation"`

### 3. VM/Container Tags
The system uses Proxmox tags for intelligent filtering:

**`safe-shutdown` tag**: VMs/containers with this tag are "non-critical"
- Node Idle Shutdown: Node shuts down when **only** VMs with this tag are running
- Logic: VMs **WITHOUT** tag = critical, block node shutdown

**Set tags:**
```bash
# Tag non-critical VMs (can be automatically stopped)
python scripts/tag_vms.py --tag safe-shutdown --vmids 200 201 202
qm set 200 --tags safe-shutdown

# Do NOT tag critical VMs (keep node running)
# Examples: Database, monitoring, router VMs

# Show all VMs
python scripts/tag_vms.py --list
```
