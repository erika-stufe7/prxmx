#!/usr/bin/env python3
"""
Utility-Script zum Setzen von Tags auf Proxmox VMs/Container.

Verwendung:
    python scripts/tag_vms.py --tag safe-shutdown --vmids 200 201 202
    python scripts/tag_vms.py --tag safe-shutdown --node pve01 --all-vms
    python scripts/tag_vms.py --list  # Zeige alle VMs mit Tags
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.proxmox import ProxmoxClient
import structlog


logger = structlog.get_logger()


def list_vms_with_tags(proxmox: ProxmoxClient):
    """Zeigt alle VMs/Container mit ihren Tags."""
    print("\n🏷️  VMs und Container mit Tags:\n")
    print(f"{'Type':<10} {'VMID':<8} {'Node':<12} {'Name':<20} {'Tags':<30}")
    print("=" * 90)
    
    for node_info in proxmox.get_nodes():
        node = node_info['node']
        
        # VMs
        for vm in proxmox.get_vms(node):
            tags = proxmox.get_vm_tags(node, vm['vmid'], 'vm')
            if tags or True:  # Zeige alle, auch ohne Tags
                print(f"{'VM':<10} {vm['vmid']:<8} {node:<12} {vm.get('name', 'N/A'):<20} {', '.join(tags) if tags else '-':<30}")
        
        # Container
        for ct in proxmox.get_containers(node):
            tags = proxmox.get_vm_tags(node, ct['vmid'], 'container')
            if tags or True:
                print(f"{'Container':<10} {ct['vmid']:<8} {node:<12} {ct.get('name', 'N/A'):<20} {', '.join(tags) if tags else '-':<30}")


def tag_vms(proxmox: ProxmoxClient, vmids: list[int], tag: str, node: str = None):
    """Setzt Tag auf angegebene VMs."""
    for vmid in vmids:
        try:
            # Node ermitteln falls nicht angegeben
            if node is None:
                vm_node, vm_type = find_vm_node(proxmox, vmid)
            else:
                vm_node = node
                vm_type = detect_vm_type(proxmox, node, vmid)
            
            # Aktuelle Tags abrufen
            current_tags = proxmox.get_vm_tags(vm_node, vmid, vm_type)
            
            if tag in current_tags:
                logger.info(f"✓ {vm_type.upper()} {vmid} hat bereits Tag '{tag}'", vmid=vmid, node=vm_node)
                continue
            
            # Tag hinzufügen
            new_tags = current_tags + [tag]
            tags_string = ";".join(new_tags)
            
            if vm_type == 'vm':
                proxmox.client.nodes(vm_node).qemu(vmid).config.put(tags=tags_string)
            else:
                proxmox.client.nodes(vm_node).lxc(vmid).config.put(tags=tags_string)
            
            logger.info(f"✅ Tag '{tag}' gesetzt", vmid=vmid, node=vm_node, type=vm_type)
        
        except Exception as e:
            logger.error(f"❌ Fehler bei VMID {vmid}", error=str(e))


def find_vm_node(proxmox: ProxmoxClient, vmid: int) -> tuple[str, str]:
    """Findet Node und Typ einer VM/Container."""
    for node_info in proxmox.get_nodes():
        node = node_info['node']
        
        # Prüfe VMs
        if any(vm['vmid'] == vmid for vm in proxmox.get_vms(node)):
            return node, 'vm'
        
        # Prüfe Container
        if any(ct['vmid'] == vmid for ct in proxmox.get_containers(node)):
            return node, 'container'
    
    raise ValueError(f"VM/Container {vmid} nicht gefunden")


def detect_vm_type(proxmox: ProxmoxClient, node: str, vmid: int) -> str:
    """Erkennt ob VM oder Container."""
    if any(vm['vmid'] == vmid for vm in proxmox.get_vms(node)):
        return 'vm'
    if any(ct['vmid'] == vmid for ct in proxmox.get_containers(node)):
        return 'container'
    raise ValueError(f"VMID {vmid} nicht auf Node {node} gefunden")


def main():
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer()
        ]
    )
    
    parser = argparse.ArgumentParser(description='Proxmox VM/Container Tag Management')
    parser.add_argument('--list', action='store_true', help='Zeige alle VMs mit Tags')
    parser.add_argument('--tag', type=str, help='Tag das gesetzt werden soll')
    parser.add_argument('--vmids', type=int, nargs='+', help='VMIDs zum taggen')
    parser.add_argument('--node', type=str, help='Node-Name (optional, wird sonst automatisch ermittelt)')
    parser.add_argument('--all-vms', action='store_true', help='Tagge alle VMs auf dem Node')
    
    args = parser.parse_args()
    
    try:
        proxmox = ProxmoxClient.get_instance()
        
        if args.list:
            list_vms_with_tags(proxmox)
        elif args.tag:
            if args.all_vms and args.node:
                # Alle VMs auf einem Node taggen
                vmids = [vm['vmid'] for vm in proxmox.get_vms(args.node)]
                vmids += [ct['vmid'] for ct in proxmox.get_containers(args.node)]
                tag_vms(proxmox, vmids, args.tag, args.node)
            elif args.vmids:
                tag_vms(proxmox, args.vmids, args.tag, args.node)
            else:
                print("❌ Entweder --vmids oder --all-vms mit --node angeben")
                sys.exit(1)
        else:
            parser.print_help()
    
    except Exception as e:
        logger.error("Fehler", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
