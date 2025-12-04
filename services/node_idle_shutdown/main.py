
"""
Node Idle Shutdown Service für Proxmox.

Überwacht Proxmox Nodes und fährt sie automatisch herunter wenn:
- Nur noch VMs/Container mit 'safe-shutdown' Tag laufen (oder gar keine)
- Minimum Uptime erreicht ist
- Grace Period abgelaufen ist

Use Case: Energie sparen wenn nur noch unkritische VMs laufen die 
         problemlos gestoppt werden können.
"""

import asyncio
import structlog
from datetime import datetime
from typing import Optional
from pathlib import Path
import yaml
import subprocess
import socket

from shared.proxmox import ProxmoxClient


logger = structlog.get_logger()


class IdleShutdownConfig:
    """Konfiguration für Node Idle Shutdown Service."""
    
    def __init__(self, config_path: str = "services/node_idle_shutdown/config.yml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config nicht gefunden: {self.config_path}")
        
        with open(self.config_path) as f:
            return yaml.safe_load(f)
    
    @property
    def enabled(self) -> bool:
        return self.config.get('enabled', False)
    
    @property
    def check_interval(self) -> int:
        return self.config.get('check_interval', 300)
    
    @property
    def monitored_nodes(self) -> list[str]:
        nodes = self.config.get('monitored_nodes', [])
        # Wenn leer, nur lokaler Node
        if not nodes:
            return [socket.gethostname()]
        return nodes
    
    @property
    def safe_shutdown_tag(self) -> str:
        return self.config.get('safe_shutdown_tag', 'safe-shutdown')
    
    @property
    def grace_period(self) -> int:
        return self.config.get('grace_period', 60)
    
    @property
    def dry_run(self) -> bool:
        return self.config.get('dry_run', True)
    
    @property
    def min_uptime(self) -> int:
        return self.config.get('min_uptime', 600)
    
    @property
    def max_consecutive_errors(self) -> int:
        return self.config.get('max_consecutive_errors', 10)
    
    @property
    def log_state_changes_only(self) -> bool:
        return self.config.get('log_state_changes_only', True)


class NodeIdleShutdownService:
    """Service für automatischen Node-Shutdown bei Idle-Zustand."""
    
    def __init__(self):
        self.config = IdleShutdownConfig()
        self.proxmox = ProxmoxClient.get_instance()
        self.running = False
        # Track idle state pro Node
        self.idle_since: dict[str, Optional[datetime]] = {}
        # Track letzten Status pro Node für Change-Detection
        self.last_state: dict[str, str] = {}  # 'active' | 'idle' | 'grace_period'
        # Error tracking
        self.consecutive_errors: int = 0
        self.last_error_time: Optional[datetime] = None
    
    def _validate_config(self) -> bool:
        """Validiert Konfiguration auf kritische Fehler."""
        try:
            if self.config.check_interval < 30:
                logger.error("check_interval zu kurz (minimum 30s)", value=self.config.check_interval)
                return False
            
            if self.config.grace_period < 10:
                logger.error("grace_period zu kurz (minimum 10s)", value=self.config.grace_period)
                return False
            
            if self.config.min_uptime < 60:
                logger.warning("min_uptime sehr kurz, empfohlen: >= 300s", value=self.config.min_uptime)
            
            # Test Proxmox-Verbindung und Berechtigungen
            logger.info("Prüfe Proxmox API-Zugriff und Berechtigungen...")
            perm_check = self.proxmox.check_permissions()
            
            if not perm_check['success']:
                logger.error("❌ Proxmox Berechtigungsprüfung fehlgeschlagen")
                for error in perm_check['errors']:
                    logger.error(f"  • {error}")
                logger.info("Lösung: Stelle sicher, dass der API-Token diese Berechtigungen hat:")
                logger.info("  • VM.Audit (VMs/Container auflisten)")
                logger.info("  • VM.PowerMgmt (VMs/Container herunterfahren)")
                logger.info("  • Sys.Audit (Node-Status lesen)")
                logger.info("  • Sys.PowerMgmt (Nodes herunterfahren)")
                logger.info("Oder deaktiviere 'Privilege Separation' für root@pam Token")
                return False
            
            # Log warnings
            for warning in perm_check['warnings']:
                logger.warning(warning)
            
            nodes_found = len(perm_check['nodes_accessible'])
            logger.info("✅ Proxmox API-Zugriff validiert", 
                       nodes_found=nodes_found,
                       nodes=perm_check['nodes_accessible'])
            return True
        
        except Exception as e:
            logger.error("Config-Validierung fehlgeschlagen", error=str(e))
            return False
    
    def _get_node_uptime(self, node: str) -> int:
        """Gibt Uptime des Nodes in Sekunden zurück."""
        try:
            node_status = self.proxmox.client.nodes(node).status.get()
            # Proxmox gibt uptime in Sekunden zurück
            return node_status.get('uptime', 0)
        except Exception as e:
            logger.error("Konnte Node-Uptime nicht abrufen", node=node, error=str(e))
            return 0
    
    def _is_vm_critical(self, vm: dict, node: str, vm_type: str) -> bool:
        """
        Prüft ob VM/Container kritisch ist (OHNE safe-shutdown Tag).
        Kritische VMs blockieren den Node-Shutdown.
        """
        vmid = vm['vmid']
        
        # Nur laufende VMs prüfen
        if vm['status'] != 'running':
            return False
        
        # Prüfe ob VM das safe-shutdown Tag hat
        has_safe_tag = self.proxmox.has_tag(node, vmid, self.config.safe_shutdown_tag, vm_type)
        
        # VM ist kritisch wenn sie KEIN safe-shutdown Tag hat
        return not has_safe_tag
    
    def _check_node_idle(self, node: str) -> tuple[bool, list[dict]]:
        """
        Prüft ob Node im Idle-Zustand ist (nur VMs mit safe-shutdown Tag oder keine VMs).
        
        Returns:
            (is_idle, critical_vms) - is_idle=True wenn Node heruntergefahren werden kann
        """
        critical_vms = []
        
        try:
            # VMs prüfen
            vms = self.proxmox.get_vms(node)
            for vm in vms:
                if self._is_vm_critical(vm, node, 'vm'):
                    critical_vms.append({
                        'type': 'vm',
                        'vmid': vm['vmid'],
                        'name': vm.get('name', 'unknown'),
                        'status': vm['status']
                    })
            
            # Container prüfen
            containers = self.proxmox.get_containers(node)
            for ct in containers:
                if self._is_vm_critical(ct, node, 'container'):
                    critical_vms.append({
                        'type': 'container',
                        'vmid': ct['vmid'],
                        'name': ct.get('name', 'unknown'),
                        'status': ct['status']
                    })
            
            is_idle = len(critical_vms) == 0
            
            return is_idle, critical_vms
        
        except Exception as e:
            logger.error("Fehler bei Node-Idle-Check", node=node, error=str(e), exc_info=False)
            # Bei Fehler als nicht-idle betrachten (sicherer)
            return False, []
    
    async def _shutdown_node(self, node: str):
        """Fährt Node herunter (stoppt erst alle VMs mit safe-shutdown Tag)."""
        logger.warning("🔌 Starte Node-Shutdown-Sequenz", node=node)
        
        try:
            # Timeout für gesamte Shutdown-Sequenz
            shutdown_timeout = 300  # 5 Minuten
            async with asyncio.timeout(shutdown_timeout):
                # 1. Alle VMs/Container mit safe-shutdown Tag herunterfahren
                vms_to_shutdown = []
                
                vms = self.proxmox.get_vms(node)
                for vm in vms:
                    if vm['status'] == 'running' and self.proxmox.has_tag(node, vm['vmid'], self.config.safe_shutdown_tag, 'vm'):
                        vms_to_shutdown.append((vm['vmid'], 'vm', vm.get('name', 'unknown')))
                
                containers = self.proxmox.get_containers(node)
                for ct in containers:
                    if ct['status'] == 'running' and self.proxmox.has_tag(node, ct['vmid'], self.config.safe_shutdown_tag, 'container'):
                        vms_to_shutdown.append((ct['vmid'], 'container', ct.get('name', 'unknown')))
                
                if vms_to_shutdown:
                    logger.info(f"Fahre {len(vms_to_shutdown)} VMs/Container herunter", node=node, count=len(vms_to_shutdown))
                    
                    # Parallel herunterfahren
                    tasks = []
                    for vmid, vm_type, name in vms_to_shutdown:
                        logger.info(f"Shutdown {vm_type} {vmid} ({name})", vmid=vmid, type=vm_type)
                        if vm_type == 'vm':
                            tasks.append(asyncio.to_thread(
                                self.proxmox.shutdown_vm, node, vmid, timeout=60
                            ))
                        else:
                            tasks.append(asyncio.to_thread(
                                self.proxmox.shutdown_container, node, vmid, timeout=60
                            ))
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Prüfe auf Fehler
                    failed = sum(1 for r in results if isinstance(r, Exception))
                    if failed > 0:
                        logger.warning(f"{failed} VMs konnten nicht heruntergefahren werden", failed=failed, total=len(results))
                    
                    # Warte bis VMs heruntergefahren sind
                    logger.info("Warte auf VM-Shutdowns...", wait_time=30)
                    await asyncio.sleep(30)
                
                # 2. Node herunterfahren
                if self.config.dry_run:
                    logger.warning("🧪 DRY-RUN: Node-Shutdown würde jetzt ausgeführt", node=node)
                else:
                    logger.warning("🔌 FAHRE NODE HERUNTER", node=node)
                    self.proxmox.client.nodes(node).status.shutdown.post()
                    logger.info("Node-Shutdown-Befehl gesendet", node=node)
        
        except asyncio.TimeoutError:
            logger.error("Timeout bei Node-Shutdown-Sequenz", node=node, timeout=300)
        except Exception as e:
            logger.error("Fehler beim Node-Shutdown", node=node, error=str(e), exc_info=False)
    
    async def _check_and_shutdown_nodes(self):
        """Prüft alle überwachten Nodes und fährt idle Nodes herunter."""
        # Nur bei aktiviertem Verbose-Logging
        if not self.config.log_state_changes_only:
            logger.debug("Prüfe Node-Status", nodes=self.config.monitored_nodes)
        
        for node in self.config.monitored_nodes:
            try:
                # Uptime prüfen
                uptime = self._get_node_uptime(node)
                if uptime < self.config.min_uptime:
                    # Nur loggen wenn State sich ändert
                    if self.last_state.get(node) != 'uptime_too_low':
                        logger.info(
                            "Node Uptime zu kurz",
                            node=node,
                            uptime=uptime,
                            min_uptime=self.config.min_uptime
                        )
                        self.last_state[node] = 'uptime_too_low'
                    
                    self.idle_since[node] = None
                    continue
                
                # Idle-Status prüfen
                is_idle, critical_vms = self._check_node_idle(node)
                
                if is_idle:
                    # Node ist idle
                    if node not in self.idle_since or self.idle_since[node] is None:
                        # Erste Idle-Erkennung - IMMER loggen
                        self.idle_since[node] = datetime.now()
                        logger.info(
                            "✨ Node ist IDLE (keine kritischen VMs laufen)",
                            node=node,
                            grace_period=self.config.grace_period
                        )
                        self.last_state[node] = 'idle_started'
                    else:
                        # Prüfe ob Grace Period abgelaufen
                        idle_duration = (datetime.now() - self.idle_since[node]).total_seconds()
                        
                        if idle_duration >= self.config.grace_period:
                            logger.warning(
                                "⚠️ Node Idle Grace Period abgelaufen - starte Shutdown",
                                node=node,
                                idle_duration=int(idle_duration)
                            )
                            await self._shutdown_node(node)
                            # Reset idle tracking
                            self.idle_since[node] = None
                            self.last_state[node] = 'shutdown_initiated'
                        else:
                            # Nur alle 60s während Grace Period loggen
                            if self.last_state.get(node) != 'grace_period' or not self.config.log_state_changes_only:
                                remaining = self.config.grace_period - idle_duration
                                logger.info(
                                    "⏳ Node in Grace Period",
                                    node=node,
                                    remaining_seconds=int(remaining)
                                )
                                self.last_state[node] = 'grace_period'
                else:
                    # Node ist NICHT idle - kritische VMs laufen
                    if self.last_state.get(node) in ['idle_started', 'grace_period']:
                        logger.info(
                            "🔄 Node nicht mehr idle - kritische VMs aktiv",
                            node=node,
                            critical_vms_count=len(critical_vms)
                        )
                        self.last_state[node] = 'active'
                    elif self.last_state.get(node) != 'active':
                        # Erste Erkennung als aktiv
                        logger.info("Node aktiv", node=node, critical_vms=len(critical_vms))
                        self.last_state[node] = 'active'
                    
                    self.idle_since[node] = None
                
                # Error-Counter zurücksetzen bei Erfolg
                self.consecutive_errors = 0
            
            except Exception as e:
                self.consecutive_errors += 1
                self.last_error_time = datetime.now()
                
                logger.error(
                    "Fehler bei Node-Check",
                    node=node,
                    error=str(e),
                    consecutive_errors=self.consecutive_errors,
                    exc_info=False
                )
                
                # Bei zu vielen Fehlern Service stoppen (verhindert Endlos-Loop)
                if self.consecutive_errors >= self.config.max_consecutive_errors:
                    logger.critical(
                        "Zu viele aufeinanderfolgende Fehler - stoppe Service",
                        consecutive_errors=self.consecutive_errors,
                        max_allowed=self.config.max_consecutive_errors
                    )
                    self.running = False
                    raise RuntimeError(f"Service gestoppt nach {self.consecutive_errors} Fehlern")
    
    async def run(self):
        """Hauptloop des Services."""
        # Config validieren vor Start
        if not self._validate_config():
            logger.critical("Service-Start abgebrochen - ungültige Konfiguration")
            return
        
        self.running = True
        logger.info(
            "🚀 Node Idle Shutdown Service gestartet",
            check_interval=self.config.check_interval,
            monitored_nodes=self.config.monitored_nodes,
            safe_shutdown_tag=self.config.safe_shutdown_tag,
            grace_period=self.config.grace_period,
            dry_run=self.config.dry_run,
            log_state_changes_only=self.config.log_state_changes_only
        )
        
        if self.config.dry_run:
            logger.warning("⚠️ DRY-RUN Modus aktiv - Node wird NICHT wirklich heruntergefahren")
        
        iteration = 0
        while self.running:
            try:
                iteration += 1
                await self._check_and_shutdown_nodes()
                
                # Status-Update alle 10 Iterationen (reduziert Log-Spam)
                if iteration % 10 == 0 and not self.config.log_state_changes_only:
                    logger.info(
                        "Service läuft",
                        iteration=iteration,
                        monitored_nodes=len(self.config.monitored_nodes),
                        errors=self.consecutive_errors
                    )
            
            except RuntimeError:
                # Service wurde wegen zu vielen Fehlern gestoppt
                break
            except Exception as e:
                self.consecutive_errors += 1
                logger.error(
                    "Unerwarteter Fehler im Service-Loop",
                    error=str(e),
                    consecutive_errors=self.consecutive_errors,
                    exc_info=True
                )
                
                if self.consecutive_errors >= self.config.max_consecutive_errors:
                    logger.critical("Service-Stopp wegen zu vielen Fehlern")
                    break
            
            await asyncio.sleep(self.config.check_interval)
        
        logger.warning("Service beendet", total_iterations=iteration)
    
    def stop(self):
        """Stoppt den Service."""
        logger.info("Stoppe Node Idle Shutdown Service")
        self.running = False


async def main():
    """Entry point für den Service."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer()
        ]
    )
    
    service = NodeIdleShutdownService()
    
    if not service.config.enabled:
        logger.warning("Service ist deaktiviert (enabled: false in config.yml)")
        return
    
    try:
        await service.run()
    except KeyboardInterrupt:
        logger.info("Shutdown-Signal empfangen")
        service.stop()


if __name__ == "__main__":
    asyncio.run(main())
