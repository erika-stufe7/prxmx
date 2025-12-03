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
    
    log_info "Entferne Installation..."
    rm -rf "$INSTALL_DIR"
    
    log_info "Entferne User..."
    userdel "$SERVICE_USER" 2>/dev/null || true
    
    echo
    echo -e "${GREEN}Deinstallation abgeschlossen${NC}"
    echo
}

main "$@"
