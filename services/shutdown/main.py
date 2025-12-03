"""
Shutdown Service für Proxmox VMs und Container.

Dieser Service überwacht VMs/Container und führt kontrollierte Shutdowns durch:
- Zeitbasierte Shutdowns (z.B. nachts Energie sparen)
- Shutdown basierend auf Inaktivität
- Kaskadierender Shutdown mit Abhängigkeiten (z.B. erst Clients, dann Server)
- Graceful shutdown mit konfigurierbaren Timeouts
"""

import asyncio
import structlog
from datetime import datetime, time
from typing import Optional
from pathlib import Path
import yaml

from shared.proxmox import ProxmoxClient


logger = structlog.get_logger()


class ShutdownConfig:
    """Konfiguration für Shutdown-Service."""
    
    def __init__(self, config_path: str = "services/shutdown/config.yml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Shutdown config nicht gefunden: {self.config_path}")
        
        with open(self.config_path) as f:
            return yaml.safe_load(f)
    
    @property
    def enabled(self) -> bool:
        return self.config.get('enabled', False)
    
    @property
    def check_interval(self) -> int:
        """Prüfintervall in Sekunden."""
        return self.config.get('check_interval', 300)  # Default: 5 Minuten
    
    @property
    def shutdown_time(self) -> Optional[time]:
        """Zeitpunkt für automatischen Shutdown (z.B. 22:00)."""
        if 'shutdown_time' in self.config:
            t = self.config['shutdown_time']
            return time(hour=t['hour'], minute=t.get('minute', 0))
        return None
    
    @property
    def grace_period(self) -> int:
        """Grace Period in Sekunden vor Shutdown."""
        return self.config.get('grace_period', 60)
    
    @property
    def excluded_vms(self) -> list[int]:
        """VMIDs die vom Shutdown ausgenommen sind."""
        return self.config.get('excluded_vms', [])
    
    @property
    def shutdown_order(self) -> list[dict]:
        """Reihenfolge für kaskadierten Shutdown."""
        return self.config.get('shutdown_order', [])
    
    @property
    def safe_shutdown_tag(self) -> str:
        """Tag für VMs die sicher heruntergefahren werden können."""
        return self.config.get('safe_shutdown_tag', 'safe-shutdown')


class ShutdownService:
    """Hauptservice für VM/Container Shutdown-Management."""
    
    def __init__(self):
        self.config = ShutdownConfig()
        self.proxmox = ProxmoxClient.get_instance()
        self.running = False
    
    async def check_and_shutdown(self):
        """Prüft Bedingungen und führt Shutdowns durch."""
        logger.info("Checking shutdown conditions")
        
        if not self.config.enabled:
            logger.info("Shutdown service disabled")
            return
        
        # Zeitbasierter Shutdown
        if self.config.shutdown_time:
            now = datetime.now().time()
            shutdown_time = self.config.shutdown_time
            
            # Prüfe ob wir im Shutdown-Zeitfenster sind (±5 Minuten)
            if self._is_within_window(now, shutdown_time, minutes=5):
                logger.info("Shutdown time reached, starting shutdown sequence")
                await self.shutdown_all()
    
    def _is_within_window(self, current: time, target: time, minutes: int) -> bool:
        """Prüft ob aktuelle Zeit im Zeitfenster liegt."""
        current_minutes = current.hour * 60 + current.minute
        target_minutes = target.hour * 60 + target.minute
        diff = abs(current_minutes - target_minutes)
        return diff <= minutes
    
    async def shutdown_all(self):
        """Führt kaskadierten Shutdown aller VMs/Container durch."""
        logger.info("Starting cascading shutdown", grace_period=self.config.grace_period)
        
        # Wenn Shutdown-Order definiert, verwende diese
        if self.config.shutdown_order:
            await self._ordered_shutdown()
        else:
            await self._simple_shutdown()
    
    async def _ordered_shutdown(self):
        """Shutdown gemäß definierter Reihenfolge."""
        for stage in self.config.shutdown_order:
            stage_name = stage.get('name', 'unknown')
            vmids = stage.get('vmids', [])
            wait_after = stage.get('wait_after', 30)
            
            logger.info(f"Shutdown stage: {stage_name}", vmids=vmids)
            
            # Shutdown aller VMs in dieser Stage parallel
            tasks = []
            for vmid in vmids:
                if vmid not in self.config.excluded_vms:
                    tasks.append(self._shutdown_vm_or_container(vmid))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            # Warte vor nächster Stage
            logger.info(f"Waiting {wait_after}s before next stage")
            await asyncio.sleep(wait_after)
    
    async def _simple_shutdown(self):
        """Einfacher Shutdown aller VMs/Container parallel."""
        nodes = self.proxmox.get_nodes()
        
        tasks = []
        for node in nodes:
            node_name = node['node']
            
            # VMs
            vms = self.proxmox.get_vms(node_name)
            for vm in vms:
                if self._should_shutdown(vm, node_name, 'vm'):
                    tasks.append(self._shutdown_vm_or_container(vm['vmid'], node_name, 'vm'))
            
            # Container
            containers = self.proxmox.get_containers(node_name)
            for ct in containers:
                if self._should_shutdown(ct, node_name, 'container'):
                    tasks.append(self._shutdown_vm_or_container(ct['vmid'], node_name, 'container'))
        
        if tasks:
            logger.info(f"Shutting down {len(tasks)} VMs/Containers")
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def _should_shutdown(self, vm: dict, node: str, vm_type: str) -> bool:
        """Prüft ob VM/Container heruntergefahren werden soll."""
        vmid = vm['vmid']
        
        # Nicht laufende VMs überspringen
        if vm['status'] != 'running':
            return False
        
        # Excluded VMs überspringen
        if vmid in self.config.excluded_vms:
            logger.debug(f"Skipping excluded {vm_type}", vmid=vmid)
            return False
        
        # Prüfe ob VM das safe-shutdown Tag hat
        has_safe_tag = self.proxmox.has_tag(node, vmid, self.config.safe_shutdown_tag, vm_type)
        
        if has_safe_tag:
            logger.info(f"{vm_type.upper()} {vmid} hat '{self.config.safe_shutdown_tag}' Tag", vmid=vmid, node=node)
            return True
        
        logger.debug(f"Skipping {vm_type} without safe-shutdown tag", vmid=vmid)
        return False
    
    async def _shutdown_vm_or_container(self, vmid: int, node: Optional[str] = None, vm_type: Optional[str] = None):
        """Shutdown einer einzelnen VM oder eines Containers."""
        try:
            # Node ermitteln falls nicht angegeben
            if node is None:
                node, vm_type = self._find_vm_node(vmid)
            
            logger.info(f"Shutting down {vm_type} {vmid} on {node}")
            
            if vm_type == 'vm':
                self.proxmox.shutdown_vm(node, vmid, timeout=self.config.grace_period)
            else:
                self.proxmox.shutdown_container(node, vmid, timeout=self.config.grace_period)
            
            logger.info(f"Shutdown initiated for {vm_type} {vmid}")
        except Exception as e:
            logger.error(f"Failed to shutdown {vmid}", error=str(e))
    
    def _find_vm_node(self, vmid: int) -> tuple[str, str]:
        """Findet Node und Typ einer VM/Container."""
        for node in self.proxmox.get_nodes():
            node_name = node['node']
            
            # Prüfe VMs
            vms = self.proxmox.get_vms(node_name)
            if any(vm['vmid'] == vmid for vm in vms):
                return node_name, 'vm'
            
            # Prüfe Container
            containers = self.proxmox.get_containers(node_name)
            if any(ct['vmid'] == vmid for ct in containers):
                return node_name, 'container'
        
        raise ValueError(f"VM/Container {vmid} not found")
    
    async def run(self):
        """Hauptloop des Services."""
        self.running = True
        logger.info("Shutdown service started", check_interval=self.config.check_interval)
        
        while self.running:
            try:
                await self.check_and_shutdown()
            except Exception as e:
                logger.error("Error in shutdown check", error=str(e))
            
            await asyncio.sleep(self.config.check_interval)
    
    def stop(self):
        """Stoppt den Service."""
        logger.info("Stopping shutdown service")
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
    
    service = ShutdownService()
    
    try:
        await service.run()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
        service.stop()


if __name__ == "__main__":
    asyncio.run(main())
