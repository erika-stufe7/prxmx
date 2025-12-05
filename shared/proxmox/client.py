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
    
    def shutdown_node(self, node: str) -> bool:
        """
        Shutdown a Proxmox node.
        
        Args:
            node: Node name to shutdown
            
        Returns:
            True if shutdown initiated successfully
            
        Raises:
            Exception: If shutdown command fails
        """
        import socket
        import subprocess
        
        try:
            hostname = socket.gethostname()
            
            if node == hostname:
                # Local node - use system shutdown command (service runs as root)
                cmd = ['shutdown', '-h', 'now']
                subprocess.run(cmd, check=True)
                return True
            else:
                # Remote node - use Proxmox API
                # Correct endpoint: POST /nodes/{node}/status with command=shutdown
                self.client.nodes(node).status.post(command='shutdown')
                return True
                
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to execute shutdown command: {str(e)}")
        except Exception as e:
            raise Exception(f"Failed to shutdown node {node}: {str(e)}")
    
    def check_permissions(self) -> dict:
        """
        Checks Proxmox API access and required permissions.
        
        Returns:
            dict with:
                - success: bool
                - errors: list of error messages
                - warnings: list of warnings
                - nodes_accessible: list of accessible node names
        """
        result = {
            'success': True,
            'errors': [],
            'warnings': [],
            'nodes_accessible': []
        }
        
        try:
            # Test 1: Can we connect and get cluster nodes?
            nodes = self.client.nodes.get()
            if not nodes:
                result['errors'].append("No nodes found - check cluster access")
                result['success'] = False
                return result
            
            result['nodes_accessible'] = [n['node'] for n in nodes]
            
            # Test 2: Check permissions on each node
            for node_info in nodes:
                node = node_info['node']
                
                # Test Sys.Audit - node status
                try:
                    self.client.nodes(node).status.get()
                except Exception as e:
                    if '403' in str(e) or 'Permission' in str(e):
                        result['errors'].append(f"Node {node}: Missing Sys.Audit permission - cannot read node status")
                        result['success'] = False
                    else:
                        result['warnings'].append(f"Node {node}: Could not check status - {str(e)}")
                
                # Test VM.Audit - list VMs
                try:
                    self.client.nodes(node).qemu.get()
                except Exception as e:
                    if '403' in str(e) or 'Permission' in str(e):
                        result['errors'].append(f"Node {node}: Missing VM.Audit permission - cannot list VMs")
                        result['success'] = False
                
                # Test VM.Audit - list containers
                try:
                    self.client.nodes(node).lxc.get()
                except Exception as e:
                    if '403' in str(e) or 'Permission' in str(e):
                        result['errors'].append(f"Node {node}: Missing VM.Audit permission - cannot list containers")
                        result['success'] = False
                
                # Note: VM.PowerMgmt and Sys.PowerMgmt can't be tested without actually shutting down
                # We just warn about them
                result['warnings'].append(f"Node {node}: VM.PowerMgmt and Sys.PowerMgmt not tested (would require shutdown)")
        
        except Exception as e:
            result['errors'].append(f"Connection failed: {str(e)}")
            result['success'] = False
        
        return result
