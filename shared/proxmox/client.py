"""
Shared Proxmox API Client für alle Services und APIs.

Zentrale Verwaltung der Proxmox-Verbindung mit Token-basierter Authentifizierung.
"""

from proxmoxer import ProxmoxAPI
from typing import Optional
import yaml
from pathlib import Path


class ProxmoxClient:
    """Thread-safe Proxmox API Client mit Connection Pooling."""
    
    _instance: Optional['ProxmoxClient'] = None
    
    def __init__(self, config_path: str = "config/proxmox.yml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._client: Optional[ProxmoxAPI] = None
    
    def _load_config(self) -> dict:
        """Lädt Proxmox-Konfiguration aus YAML."""
        if not self.config_path.exists():
            # Fallback auf Example-Config
            example_path = self.config_path.parent / f"{self.config_path.stem}.example{self.config_path.suffix}"
            if example_path.exists():
                raise FileNotFoundError(
                    f"Config nicht gefunden: {self.config_path}\n"
                    f"Kopiere {example_path} nach {self.config_path} und fülle Credentials aus."
                )
            raise FileNotFoundError(f"Config nicht gefunden: {self.config_path}")
        
        with open(self.config_path) as f:
            return yaml.safe_load(f)
    
    @property
    def client(self) -> ProxmoxAPI:
        """Lazy-initialisierter Proxmox API Client."""
        if self._client is None:
            cfg = self.config['proxmox']
            self._client = ProxmoxAPI(
                cfg['host'],
                user=cfg['user'],
                token_name=cfg['token_name'],
                token_value=cfg['token_value'],
                verify_ssl=cfg.get('verify_ssl', True)
            )
        return self._client
    
    @classmethod
    def get_instance(cls, config_path: str = "config/proxmox.yml") -> 'ProxmoxClient':
        """Singleton-Pattern für shared Client."""
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance
    
    def get_nodes(self) -> list[dict]:
        """Gibt alle Cluster-Nodes zurück."""
        return self.client.nodes.get()
    
    def get_vms(self, node: str) -> list[dict]:
        """Gibt alle VMs eines Nodes zurück."""
        return self.client.nodes(node).qemu.get()
    
    def get_containers(self, node: str) -> list[dict]:
        """Gibt alle LXC-Container eines Nodes zurück."""
        return self.client.nodes(node).lxc.get()
    
    def shutdown_vm(self, node: str, vmid: int, timeout: int = 60) -> dict:
        """Shutdown einer VM mit Timeout."""
        return self.client.nodes(node).qemu(vmid).status.shutdown.post(timeout=timeout)
    
    def shutdown_container(self, node: str, vmid: int, timeout: int = 60) -> dict:
        """Shutdown eines LXC-Containers mit Timeout."""
        return self.client.nodes(node).lxc(vmid).status.shutdown.post(timeout=timeout)
    
    def get_vm_tags(self, node: str, vmid: int, vm_type: str = 'vm') -> list[str]:
        """Gibt Tags einer VM/Container zurück."""
        try:
            if vm_type == 'vm':
                config = self.client.nodes(node).qemu(vmid).config.get()
            else:
                config = self.client.nodes(node).lxc(vmid).config.get()
            
            tags = config.get('tags', '')
            return [tag.strip() for tag in tags.split(';') if tag.strip()] if tags else []
        except Exception:
            return []
    
    def has_tag(self, node: str, vmid: int, tag: str, vm_type: str = 'vm') -> bool:
        """Prüft ob VM/Container ein bestimmtes Tag hat."""
        tags = self.get_vm_tags(node, vmid, vm_type)
        return tag in tags
