#!/usr/bin/env bash
set -e  # Exit bei Fehler

# =============================================================================
# Proxmox Management Services - Installationsskript
# Für Debian 13+ (Trixie und zukünftige Versionen)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/proxmox-services"
SERVICE_USER="proxmox-services"
VENV_DIR="$INSTALL_DIR/venv"
PYTHON_MIN_VERSION="3.10"
PYTHON_MAX_VERSION="3.11"

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Utility Functions
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNUNG]${NC} $1"
}

log_error() {
    echo -e "${RED}[FEHLER]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Dieses Script muss als root ausgeführt werden"
        log_info "Verwende: sudo $0"
        exit 1
    fi
}

check_debian() {
    if [[ ! -f /etc/debian_version ]]; then
        log_error "Dieses System ist kein Debian"
        log_info "Unterstützt: Debian 13+ (Trixie und neuer)"
        exit 1
    fi
    
    DEBIAN_VERSION=$(cat /etc/debian_version | cut -d'.' -f1)
    log_info "Debian Version erkannt: $(cat /etc/debian_version)"
    
    if [[ $DEBIAN_VERSION -lt 13 ]] && [[ ! "$DEBIAN_VERSION" =~ ^trixie ]]; then
        log_warning "Dieses Script ist für Debian 13+ optimiert"
        log_warning "Aktuelle Version: $(cat /etc/debian_version)"
        read -p "Trotzdem fortfahren? (j/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Jj]$ ]]; then
            exit 1
        fi
    fi
}

check_python() {
    log_info "Prüfe Python-Installation..."
    
    # Versuche Python-Versionen in absteigender Reihenfolge (max 3.11 wegen pydantic)
    for py_version in python3.11 python3.10 python3; do
        if command -v "$py_cmd" &> /dev/null; then
            PYTHON_CMD="$py_cmd"
            PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
            log_success "Python gefunden: $PYTHON_CMD ($PYTHON_VERSION)"
            
            # Version-Check (3.10-3.11 wegen pydantic-Kompatibilität)
            PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
            PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
            
            if [[ $PYTHON_MAJOR -eq 3 ]] && [[ $PYTHON_MINOR -ge 10 ]] && [[ $PYTHON_MINOR -le 11 ]]; then
                return 0
            elif [[ $PYTHON_MAJOR -eq 3 ]] && [[ $PYTHON_MINOR -gt 11 ]]; then
                log_error "Python $PYTHON_VERSION ist zu neu (maximal 3.11 unterstützt wegen pydantic)"
                log_info "Installiere Python 3.11: apt install python3.11 python3.11-venv"
                exit 1
            fi
        fi
    done
    
    log_error "Python 3.10 oder 3.11 nicht gefunden"
    log_info "Installation mit: apt install python3.11 python3.11-venv python3-pip"
    exit 1
}

check_dependencies() {
    log_info "Prüfe System-Abhängigkeiten..."
    
    local missing_deps=()
    
    # Core Dependencies
    local required_packages=(
        "python3-venv"
        "python3-pip"
        "git"
        "rsync"
    )
    
    for pkg in "${required_packages[@]}"; do
        if ! dpkg -l | grep -q "^ii  $pkg"; then
            missing_deps+=("$pkg")
        fi
    done
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_warning "Fehlende Pakete: ${missing_deps[*]}"
        log_info "Installiere fehlende Abhängigkeiten..."
        
        apt-get update -qq
        apt-get install -y "${missing_deps[@]}"
        
        log_success "Abhängigkeiten installiert"
    else
        log_success "Alle Abhängigkeiten vorhanden"
    fi
}

create_user() {
    log_info "Erstelle Service-User..."
    
    if id "$SERVICE_USER" &>/dev/null; then
        log_success "User '$SERVICE_USER' existiert bereits"
    else
        useradd --system --home-dir "$INSTALL_DIR" --shell /bin/bash "$SERVICE_USER"
        log_success "User '$SERVICE_USER' erstellt"
    fi
}

install_files() {
    log_info "Installiere Dateien nach $INSTALL_DIR..."
    
    # Erstelle Install-Verzeichnis
    mkdir -p "$INSTALL_DIR"
    
    # Kopiere Projektdateien
    if rsync -a --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
        "$SCRIPT_DIR/" "$INSTALL_DIR/"; then
        log_success "Dateien kopiert"
    else
        log_error "Fehler beim Kopieren der Dateien"
        exit 1
    fi
    
    # Setze Berechtigungen
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    
    log_success "Dateien installiert"
}

setup_venv() {
    log_info "Erstelle Python Virtual Environment..."
    
    # Entferne altes venv falls vorhanden
    if [[ -d "$VENV_DIR" ]]; then
        log_warning "Entferne altes Virtual Environment"
        rm -rf "$VENV_DIR"
    fi
    
    # Erstelle neues venv
    sudo -u "$SERVICE_USER" "$PYTHON_CMD" -m venv "$VENV_DIR"
    
    # Upgrade pip (für zukünftige Kompatibilität)
    sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
    
    log_success "Virtual Environment erstellt"
}

install_python_deps() {
    log_info "Installiere Python-Abhängigkeiten..."
    
    if [[ ! -f "$INSTALL_DIR/requirements.txt" ]]; then
        log_error "requirements.txt nicht gefunden"
        exit 1
    fi
    
    # Installiere mit pip (robust für zukünftige Versionen)
    if sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"; then
        log_success "Python-Pakete installiert"
    else
        log_error "Python-Paket-Installation fehlgeschlagen"
        log_info "Prüfe requirements.txt und Netzwerkverbindung"
        exit 1
    fi
}

setup_config() {
    log_info "Konfiguriere Services..."
    
    # Proxmox Config
    if [[ ! -f "$INSTALL_DIR/config/proxmox.yml" ]]; then
        if [[ -f "$INSTALL_DIR/config/proxmox.example.yml" ]]; then
            cp "$INSTALL_DIR/config/proxmox.example.yml" "$INSTALL_DIR/config/proxmox.yml"
            chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/config/proxmox.yml"
            chmod 600 "$INSTALL_DIR/config/proxmox.yml"
            
            log_warning "Proxmox Config erstellt: $INSTALL_DIR/config/proxmox.yml"
            log_warning "WICHTIG: Bearbeite die Datei und füge Proxmox API-Credentials ein!"
        else
            log_error "proxmox.example.yml nicht gefunden"
            exit 1
        fi
    else
        log_success "Proxmox Config existiert bereits"
    fi
    
    # Service Configs prüfen
    for service_dir in "$INSTALL_DIR/services"/*; do
        if [[ -d "$service_dir" ]] && [[ -f "$service_dir/config.yml" ]]; then
            service_name=$(basename "$service_dir")
            log_info "Service gefunden: $service_name"
        fi
    done
}

install_systemd_services() {
    log_info "Installiere systemd Services..."
    
    # Node Idle Shutdown Service
    cat > /etc/systemd/system/proxmox-node-idle-shutdown.service <<EOF
[Unit]
Description=Proxmox Node Idle Shutdown Service
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python -m services.node_idle_shutdown.main

# Restart strategy
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=5

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=proxmox-node-idle-shutdown

[Install]
WantedBy=multi-user.target
EOF
    
    # Scheduled Shutdown Service
    cat > /etc/systemd/system/proxmox-scheduled-shutdown.service <<EOF
[Unit]
Description=Proxmox Scheduled VM Shutdown Service
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python -m services.shutdown.main

# Restart strategy
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=5

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=proxmox-scheduled-shutdown

[Install]
WantedBy=multi-user.target
EOF
    
    # Reload systemd
    systemctl daemon-reload
    
    # Prüfe ob Services erstellt wurden
    if systemctl list-unit-files | grep -q "proxmox-node-idle-shutdown.service"; then
        log_success "Systemd Services installiert"
    else
        log_error "Fehler beim Erstellen der systemd Services"
        exit 1
    fi
}

print_summary() {
    echo
    echo "=========================================================================="
    echo -e "${GREEN}Installation erfolgreich abgeschlossen!${NC}"
    echo "=========================================================================="
    echo
    echo "📁 Installation: $INSTALL_DIR"
    echo "👤 User: $SERVICE_USER"
    echo "🐍 Python: $PYTHON_CMD ($PYTHON_VERSION)"
    echo
    echo "📋 Nächste Schritte:"
    echo
    echo "1. Proxmox API-Token konfigurieren:"
    echo "   sudo nano $INSTALL_DIR/config/proxmox.yml"
    echo
    echo "2. Services konfigurieren:"
    echo "   sudo nano $INSTALL_DIR/services/node_idle_shutdown/config.yml"
    echo "   sudo nano $INSTALL_DIR/services/shutdown/config.yml"
    echo
    echo "3. Services aktivieren und starten:"
    echo "   # Node Idle Shutdown"
    echo "   sudo systemctl enable proxmox-node-idle-shutdown"
    echo "   sudo systemctl start proxmox-node-idle-shutdown"
    echo
    echo "   # Scheduled Shutdown"
    echo "   sudo systemctl enable proxmox-scheduled-shutdown"
    echo "   sudo systemctl start proxmox-scheduled-shutdown"
    echo
    echo "4. Status prüfen:"
    echo "   sudo systemctl status proxmox-node-idle-shutdown"
    echo "   sudo journalctl -u proxmox-node-idle-shutdown -f"
    echo
    echo "=========================================================================="
    echo
}

# =============================================================================
# Main Installation
# =============================================================================

main() {
    echo "=========================================================================="
    echo "  Proxmox Management Services - Installation"
    echo "  Debian 13+ (Trixie und zukünftige Versionen)"
    echo "=========================================================================="
    echo
    
    check_root
    check_debian
    check_python
    check_dependencies
    create_user
    install_files
    setup_venv
    install_python_deps
    setup_config
    install_systemd_services
    print_summary
}

main "$@"
