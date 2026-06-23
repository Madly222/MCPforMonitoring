"""
NetBox Auto-Fill API Router.
Separate module to keep api.py clean.
"""
import os
import sys
from pathlib import Path
from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from loguru import logger
from dotenv import load_dotenv

from src.web.auth import get_current_user, UserInfo

# Load netbox .env
netbox_env = Path(__file__).parent.parent.parent / ".env"
load_dotenv(netbox_env)

# Add services path for imports
services_path = str(Path(__file__).parent.parent.parent / "services" / "netbox-autofill")
if services_path not in sys.path:
    sys.path.insert(0, services_path)

from ssh_connector import CiscoSSH
from netbox_client import NetBoxClient
from orchestrator import Orchestrator, ScanResult

router = APIRouter()

_scan_cache: dict[str, ScanResult] = {}


class ScanRequest(BaseModel):
    connection_type: str = "ssh"
    device_type: str = "switch"
    host: str
    username: str | None = None
    password: str | None = None


class ApplyRequest(BaseModel):
    host: str
    selected_ports: list[str]


@router.get("/health")
async def netbox_health(user: UserInfo = Depends(get_current_user)):
    try:
        nb = NetBoxClient()
        status = nb.nb.status()
        return {"status": "ok", "netbox": {"connected": True, "version": status.get("netbox-version", "unknown")}}
    except Exception as e:
        return {"status": "degraded", "netbox": {"connected": False, "error": str(e)}}

@router.post("/scan")
async def netbox_scan(req: ScanRequest, user: UserInfo = Depends(get_current_user)):
    if user.role == "operator":
        raise HTTPException(403, "Access denied for operator role")
    # Validate credentials - user must provide them
    if not req.username or not req.password:
        raise HTTPException(400, "Username and password are required")
    orch = Orchestrator(
        ssh_username=req.username,
        ssh_password=req.password,
    )
    logs = []
    result = orch.scan_device(req.host, progress_callback=lambda msg: logs.append(msg))
    _scan_cache[req.host] = result
    return {
        "host": result.host, "hostname": result.hostname, "device_id": result.device_id,
        "device_name": result.device_name, "errors": result.errors, "logs": logs,
        "ports": [asdict(p) for p in result.ports],
    }


@router.post("/apply")
async def netbox_apply(req: ApplyRequest, user: UserInfo = Depends(get_current_user)):
    if user.role == "operator":
        raise HTTPException(403, "Access denied for operator role")
    if req.host not in _scan_cache:
        raise HTTPException(404, "Device not scanned yet. Run scan first.")
    orch = Orchestrator()
    logs = []
    results = orch.apply_actions(_scan_cache[req.host], selected_ports=req.selected_ports, progress_callback=lambda msg: logs.append(msg))
    return {"logs": logs, "results": results}


@router.post("/auto")
async def netbox_auto(req: ScanRequest, user: UserInfo = Depends(get_current_user)):
    if user.role == "operator":
        raise HTTPException(403, "Access denied for operator role")
    if not req.username or not req.password:
        raise HTTPException(400, "Username and password are required")
    orch = Orchestrator(
        ssh_username=req.username,
        ssh_password=req.password,
    )
    scan_logs = []
    result = orch.scan_device(req.host, progress_callback=lambda msg: scan_logs.append(msg))
    _scan_cache[req.host] = result
    if result.errors and not result.ports:
        return {"scan_logs": scan_logs, "apply_logs": [], "errors": result.errors, "ports_updated": 0, "cables_created": 0}
    apply_logs = []
    all_ports = [p.port_name for p in result.ports]
    results = orch.apply_actions(result, selected_ports=all_ports, progress_callback=lambda msg: apply_logs.append(msg))
    ports_updated = sum(1 for r in results for s in r["steps"] if s.get("action") == "update_interface" and s.get("result", {}).get("success"))
    cables_created = sum(1 for r in results for s in r["steps"] if s.get("action") == "create_cable" and s.get("result", {}).get("success"))
    return {
        "host": result.host, "hostname": result.hostname, "device_name": result.device_name,
        "scan_logs": scan_logs, "apply_logs": apply_logs, "ports_updated": ports_updated,
        "cables_created": cables_created, "errors": result.errors, "details": results,
    }


# ==============================================================================
# ROUTER SCAN ENDPOINT
# ==============================================================================
@router.post("/scan-router")
async def netbox_scan_router(req: ScanRequest, user: UserInfo = Depends(get_current_user)):
    """Scan a Cisco router and return interfaces, routes, CDP neighbors."""
    if user.role == "operator":
        raise HTTPException(403, "Access denied for operator role")
    if not req.username or not req.password:
        raise HTTPException(400, "Username and password are required")
    
    from ssh_connector import CiscoRouterSSH
    
    logs = []
    try:
        logs.append(f"Connecting to router {req.host}...")
        ssh = CiscoRouterSSH(req.host, req.username, req.password)
        result = ssh.connect()
        
        if not result["success"]:
            logs.append(f"Connection failed: {result.get('error', 'Unknown error')}")
            return {"success": False, "logs": logs, "error": result.get("error")}
        
        logs.append(f"Connected to {result.get('hostname', req.host)}")
        logs.append("Scanning interfaces...")
        
        scan_result = ssh.scan_router()
        # Cache for apply - convert to dict format
        _scan_cache[req.host] = {
            "hostname": scan_result["hostname"],
            "model": scan_result["model"],
            "interfaces": [
                {"name": i.name, "ip_address": i.ip_address, "status": i.status, "protocol": i.protocol, "description": i.description, "mtu": getattr(i, "mtu", None)}
                for i in scan_result["interfaces"]
            ],
            "routes": [
                {"network": r.network, "interface": r.interface}
                for r in scan_result["routes"]
            ],
            "cdp_neighbors": [
                {"local_port": n.local_port, "remote_device": n.remote_device, "remote_port": n.remote_port, "platform": n.platform}
                for n in scan_result["cdp_neighbors"]
            ],
        }
        ssh.disconnect()
        
        logs.append(f"Found {len(scan_result['interfaces'])} interfaces")
        logs.append(f"Found {len(scan_result['routes'])} connected routes")
        logs.append(f"Found {len(scan_result['cdp_neighbors'])} CDP neighbors")
        
        return {
            "success": True,
            "host": req.host,
            "hostname": scan_result["hostname"],
            "model": scan_result["model"],
            "serial": scan_result["serial"],
            "ios_version": scan_result["ios_version"],
            "uptime": scan_result["uptime"],
            "interfaces": [
                {
                    "name": i.name,
                    "ip_address": i.ip_address,
                    "status": i.status,
                    "protocol": i.protocol,
                    "description": i.description,
                }
                for i in scan_result["interfaces"]
            ],
            "routes": [
                {"network": r.network, "interface": r.interface}
                for r in scan_result["routes"]
            ],
            "cdp_neighbors": [
                {
                    "local_port": n.local_port,
                    "remote_device": n.remote_device,
                    "remote_port": n.remote_port,
                    "platform": n.platform,
                }
                for n in scan_result["cdp_neighbors"]
            ],
            "logs": logs,
        }
    except Exception as e:
        logger.error(f"Router scan error: {e}")
        logs.append(f"Error: {str(e)}")
        return {"success": False, "logs": logs, "error": str(e)}


@router.post("/apply-router")
async def netbox_apply_router(req: ApplyRequest, user: UserInfo = Depends(get_current_user)):
    """Apply router interfaces to NetBox."""
    if user.role == "operator":
        raise HTTPException(403, "Access denied for operator role")
    
    logs = []
    results = {"interfaces_updated": 0, "ips_created": 0, "cables_created": 0}
    
    try:
        from netbox_client import NetBoxClient
        nb = NetBoxClient()
        
        # Get cached scan data first to get hostname
        if req.host not in _scan_cache:
            logs.append("❌ No scan data found. Please scan the router first.")
            return {"success": False, "logs": logs, "error": "Scan the router first"}
        
        scan_data = _scan_cache[req.host]
        hostname = scan_data.get("hostname", req.host)
        model = scan_data.get("model", "Unknown")
        
        logs.append(f"Looking for device '{hostname}' in NetBox...")
        
        # First try EXACT match by hostname
        device = nb.find_device_by_name_exact(hostname)
        
        if not device:
            logs.append(f"Device '{hostname}' not found by exact name, trying by management IP {req.host}...")
            device = nb.find_device_by_ip(req.host)
            if device:
                logs.append(f"✅ Found device by management IP: {device['name']} (ID: {device['id']})")
                # Update hostname to match actual router hostname
                if device['name'] != hostname:
                    logs.append(f"Updating hostname from '{device['name']}' to '{hostname}'...")
                    update_result = nb.update_device_name(device['id'], hostname)
                    if update_result.get('success'):
                        logs.append(f"✅ Hostname updated to '{hostname}'")
                        device['name'] = hostname
                    else:
                        logs.append(f"⚠️ Could not update hostname: {update_result.get('error')}")
                        # Continue anyway - device is correct, just hostname update failed
        
        if not device:
            logs.append(f"Device not found, creating {hostname}...")
            # Find or create device type
            dt_result = nb.find_or_create_device_type(model)
            if not dt_result.get("success"):
                logs.append(f"⚠️ Cannot create device type: {dt_result.get('error')}")
                device_type_id = None
            else:
                device_type_id = dt_result.get("device_type_id")
            
            # Create device
            create_result = nb.create_device(
                name=hostname,
                device_type_id=device_type_id,
                serial=scan_data.get("serial"),
            )
            if create_result.get("success"):
                device = create_result.get("device")
                logs.append(f"✅ Created device {hostname} (ID: {device['id']})")
            else:
                logs.append(f"❌ Failed to create device: {create_result.get('error')}")
                return {"success": False, "logs": logs, "error": create_result.get("error")}
        
        device_id = device["id"]
        device_name = device["name"]
        logs.append(f"✅ Found device: {device_name} (ID: {device_id})")
        

        
        # Process selected interfaces
        for port_name in req.selected_ports:
            # Find interface in scan data
            iface_data = None
            for iface in scan_data.get("interfaces", []):
                if iface.get("name") == port_name:
                    iface_data = iface
                    break
            
            if not iface_data:
                continue
            
            logs.append(f"Processing {port_name}...")
            
            # Find or create interface in NetBox
            nb_iface = nb.find_interface(device_id, port_name)
            if not nb_iface:
                # Try full name
                full_name = port_name.replace("Gi", "GigabitEthernet").replace("Fa", "FastEthernet")
                nb_iface = nb.find_interface(device_id, full_name)
            
            if not nb_iface:
                # Create interface if not found
                create_result = nb.create_interface(device_id, port_name, iface_data.get("description", ""), iface_data.get("mtu"))
                if create_result.get("success"):
                    nb_iface = {"id": create_result["interface_id"], "name": port_name}
                    logs.append(f"  ✅ Created interface {port_name}")
                else:
                    logs.append(f"  ⚠️ Could not create interface {port_name}: {create_result.get('error')}")
                    continue
            
            # Update description and MTU
            update_data = {}
            if iface_data.get("description"):
                update_data["description"] = iface_data["description"]
            if iface_data.get("mtu"):
                update_data["mtu"] = iface_data["mtu"]
            if update_data:
                nb.update_interface(nb_iface["id"], update_data)
                logs.append(f"  ✅ Updated {port_name}" + (f" (MTU: {iface_data.get('mtu')})" if iface_data.get('mtu') else ""))
            results["interfaces_updated"] += 1
            
            # Add IP address if exists
            ip_addr = iface_data.get("ip_address")
            if ip_addr and ip_addr != "unassigned":
                # Always reassign IP to correct interface
                result = nb.reassign_ip(f"{ip_addr}/24", nb_iface["id"])
                if result.get("success"):
                    logs.append(f"  ✅ IP {ip_addr}/24 assigned to {port_name}")
                    results["ips_created"] += 1
                else:
                    logs.append(f"  ⚠️ IP {ip_addr}: {result.get('error', 'failed')}")
        
        # Process CDP neighbors for cables
        for cdp in scan_data.get("cdp_neighbors", []):
            local_port = cdp.get("local_port")
            remote_device = cdp.get("remote_device")
            remote_port = cdp.get("remote_port")
            
            if local_port not in req.selected_ports:
                continue
            
            logs.append(f"Creating cable: {local_port} -> {remote_device}:{remote_port}")
            
            # Find local interface
            local_iface = nb.find_interface(device_id, local_port)
            if not local_iface:
                logs.append(f"  ⚠️ Local interface {local_port} not found")
                continue
            
            # Find remote device and interface
            remote_dev = nb.find_device_by_name(remote_device)
            if not remote_dev:
                logs.append(f"  ⚠️ Remote device {remote_device} not found")
                continue
            
            remote_iface = nb.find_interface(remote_dev["id"], remote_port)
            if not remote_iface:
                logs.append(f"  ⚠️ Remote interface {remote_port} not found")
                continue
            
            # Delete existing cables first
            if nb.check_cable_exists(local_iface["id"]):
                nb.delete_cable(local_iface["id"])
                logs.append(f"  🗑️ Deleted old cable on {local_port}")
            if nb.check_cable_exists(remote_iface["id"]):
                nb.delete_cable(remote_iface["id"])
                logs.append(f"  🗑️ Deleted old cable on {remote_port}")
            
            # Create cable
            cable_result = nb.create_cable(local_iface["id"], remote_iface["id"])
            if cable_result.get("success"):
                logs.append(f"  ✅ Cable created")
                results["cables_created"] += 1
            else:
                logs.append(f"  ⚠️ Cable: {cable_result.get('error', 'failed')}")
        
        logs.append(f"Done: {results['interfaces_updated']} interfaces, {results['ips_created']} IPs, {results['cables_created']} cables")
        return {"success": True, "logs": logs, "results": results}
        
    except Exception as e:
        logger.error(f"Router apply error: {e}")
        logs.append(f"❌ Error: {str(e)}")
        return {"success": False, "logs": logs, "error": str(e)}


# ==============================================================================
# DHCP MAC SYNC ENDPOINT
# ==============================================================================
@router.post("/sync-mac")
async def netbox_sync_mac(user: UserInfo = Depends(get_current_user)):
    """Sync MAC addresses from DHCP to NetBox."""
    if user.role == "operator":
        raise HTTPException(403, "Access denied for operator role")
    
    try:
        from src.monitoring.dhcp_mac_sync import sync_dhcp_to_netbox
        result = sync_dhcp_to_netbox()
        return result
    except Exception as e:
        logger.error(f"DHCP-MAC sync error: {e}")
        return {"success": False, "logs": [f"Error: {str(e)}"], "error": str(e)}
