#!/usr/bin/env python3
"""
phpDHCPAdmin (MySQL) -> NetBox MAC Sync
"""

import re
import os
import paramiko
import requests
from datetime import datetime
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ============================================================================
# SETTINGS FROM .ENV
# ============================================================================

NETBOX_URL = os.getenv("NETBOX_URL", "http://172.22.22.57")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN", "")

DHCP_SSH_HOST = os.getenv("DHCP_SSH_HOST", "")
DHCP_SSH_USER = os.getenv("DHCP_SSH_USER", "")
DHCP_SSH_PASS = os.getenv("DHCP_SSH_PASS", "")
DHCP_SSH_PORT = int(os.getenv("DHCP_SSH_PORT", "22"))

MYSQL_USER = os.getenv("DHCP_MYSQL_USER", "")
MYSQL_PASS = os.getenv("DHCP_MYSQL_PASS", "")
MYSQL_DB = os.getenv("DHCP_MYSQL_DB", "")

NETBOX_MAC_FIELD = "MAC"

# ============================================================================
# SSH + MySQL
# ============================================================================

def ssh_connect(host, username, password, port=22):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=username, password=password, timeout=30)
    return client

def mysql_query(ssh_client, query):
    query_escaped = query.replace('`', '\\`')
    cmd = f"mysql -u{MYSQL_USER} -p'{MYSQL_PASS}' -N -B {MYSQL_DB} -e \"{query_escaped}\""
    stdin, stdout, stderr = ssh_client.exec_command(cmd)
    return stdout.read().decode('utf-8')

def normalize_mac(mac):
    if not mac:
        return None
    mac_clean = re.sub(r'[.:-]', '', mac.lower())
    if len(mac_clean) != 12:
        return None
    return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)]).upper()

def get_dhcp_clients(ssh_client):
    query = "SELECT `ip-address`, `mac-address` FROM conf_hosts WHERE `ip-address` IS NOT NULL AND `ip-address` != '' AND `mac-address` IS NOT NULL AND `mac-address` != ''"
    output = mysql_query(ssh_client, query)
    clients = []
    for line in output.strip().split('\n'):
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) >= 2:
            ip = parts[0].strip()
            mac = normalize_mac(parts[1])
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip) and mac:
                clients.append({'ip': ip, 'mac': mac})
    return clients

# ============================================================================
# NETBOX
# ============================================================================

def netbox_find_ip(ip_address):
    headers = {'Authorization': f'Token {NETBOX_TOKEN}', 'Content-Type': 'application/json'}
    url = f"{NETBOX_URL}/api/ipam/ip-addresses/"
    try:
        response = requests.get(url, headers=headers, params={'address': ip_address}, verify=False, timeout=10)
        data = response.json()
        if data.get('count', 0) > 0:
            return data['results'][0]
        response = requests.get(url, headers=headers, params={'q': ip_address}, verify=False, timeout=10)
        data = response.json()
        if data.get('count', 0) > 0:
            for ip_obj in data['results']:
                if ip_obj['address'].split('/')[0] == ip_address:
                    return ip_obj
        return None
    except Exception as e:
        logger.error(f"NetBox search error for {ip_address}: {e}")
        return None

def netbox_update_mac(ip_id, ip_address, mac_address):
    headers = {'Authorization': f'Token {NETBOX_TOKEN}', 'Content-Type': 'application/json'}
    url = f"{NETBOX_URL}/api/ipam/ip-addresses/{ip_id}/"
    try:
        data = {'custom_fields': {NETBOX_MAC_FIELD: mac_address}}
        response = requests.patch(url, headers=headers, json=data, verify=False, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"NetBox update error for {ip_address}: {e}")
        return False

def netbox_get_current_mac(ip_obj):
    if not ip_obj.get('custom_fields'):
        return None
    return ip_obj['custom_fields'].get(NETBOX_MAC_FIELD)

# ============================================================================
# SYNC
# ============================================================================

def sync_dhcp_to_netbox(progress_callback=None):
    """Sync DHCP MACs to NetBox. Returns dict with stats and logs."""
    import urllib3
    urllib3.disable_warnings()
    
    logs = []
    stats = {'updated': 0, 'skipped': 0, 'not_found': 0, 'errors': 0, 'total': 0}
    
    def log(msg):
        logs.append(msg)
        logger.info(f"DHCP-MAC: {msg}")
        if progress_callback:
            progress_callback(msg)
    
    try:
        log(f"Connecting to DHCP server {DHCP_SSH_HOST}...")
        ssh = ssh_connect(DHCP_SSH_HOST, DHCP_SSH_USER, DHCP_SSH_PASS, DHCP_SSH_PORT)
        log("SSH connected")
        
        log("Getting clients from MySQL...")
        clients = get_dhcp_clients(ssh)
        stats['total'] = len(clients)
        log(f"Found {len(clients)} clients in DHCP")
        
        for i, client in enumerate(clients, 1):
            ip = client['ip']
            mac = client['mac']
            
            ip_obj = netbox_find_ip(ip)
            
            if not ip_obj:
                stats['not_found'] += 1
                continue
            
            current_mac = netbox_get_current_mac(ip_obj)
            
            if current_mac:
                current_normalized = normalize_mac(current_mac)
                if current_normalized == mac:
                    stats['skipped'] += 1
                    continue
            
            if netbox_update_mac(ip_obj['id'], ip, mac):
                stats['updated'] += 1
                log(f"Updated {ip} -> {mac}")
            else:
                stats['errors'] += 1
        
        ssh.close()
        
        log(f"Sync complete: {stats['updated']} updated, {stats['skipped']} skipped, {stats['not_found']} not found, {stats['errors']} errors")
        
        return {"success": True, "stats": stats, "logs": logs}
        
    except Exception as e:
        logger.error(f"DHCP-MAC sync error: {e}")
        logs.append(f"Error: {str(e)}")
        return {"success": False, "stats": stats, "logs": logs, "error": str(e)}
