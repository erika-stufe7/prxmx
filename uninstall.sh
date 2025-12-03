#!/usr/bin/env bash
set -e

# =============================================================================
# Proxmox Management Services - Deinstallationsskript
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# =============================================================================

INSTALL_DIR="/opt/prxmx-services"
SERVICE_USER="prxmx-services"

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNUNG]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}[FEHLER]${NC} Dieses Script muss als root ausgeführt werden"
        exit 1
    fi
}

main() {
    check_root
    
    echo "=========================================================================="
    echo "  Proxmox Management Services - Deinstallation"
    echo "=========================================================================="
    echo
    
    read -p "Wirklich deinstallieren? Configs werden GELÖSCHT! (j/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Jj]$ ]]; then
        log_info "Abgebrochen"
        exit 0
    fi
    
    log_info "Stoppe Services..."
    systemctl stop prxmx-node-idle-shutdown 2>/dev/null || true
    systemctl stop prxmx-scheduled-shutdown 2>/dev/null || true
    
    log_info "Deaktiviere Services..."
    systemctl disable prxmx-node-idle-shutdown 2>/dev/null || true
    systemctl disable prxmx-scheduled-shutdown 2>/dev/null || true
    
    log_info "Entferne systemd Services..."
    rm -f /etc/systemd/system/prxmx-node-idle-shutdown.service
    rm -f /etc/systemd/system/prxmx-scheduled-shutdown.service
    systemctl daemon-reload
    
    # Sichere Config vor Löschung
    CONFIG_BACKUP="/root/prxmx-config-backup"
    if [[ -f "$INSTALL_DIR/config/proxmox.yml" ]]; then
        log_info "Sichere Proxmox-Config nach $CONFIG_BACKUP/"
        mkdir -p "$CONFIG_BACKUP"
        cp "$INSTALL_DIR/config/proxmox.yml" "$CONFIG_BACKUP/proxmox.yml"
        chmod 600 "$CONFIG_BACKUP/proxmox.yml"
        log_warning "Config gesichert in: $CONFIG_BACKUP/proxmox.yml"
    fi
    
    log_info "Entferne Installation..."
    rm -rf "$INSTALL_DIR"
    
    log_info "Entferne User..."
    userdel "$SERVICE_USER" 2>/dev/null || true
    
    echo
    echo -e "${GREEN}Deinstallation abgeschlossen${NC}"
    if [[ -f "$CONFIG_BACKUP/proxmox.yml" ]]; then
        echo
        echo -e "${YELLOW}💡 Proxmox-Config wurde gesichert:${NC}"
        echo "   $CONFIG_BACKUP/proxmox.yml"
        echo
        echo "Bei Neuinstallation wird gefragt, ob diese Config wiederverwendet werden soll."
    fi
    echo
}

main "$@"
