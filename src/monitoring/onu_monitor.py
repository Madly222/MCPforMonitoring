"""
ONU SNMP Monitor for ZTE C320.

Monitors GPON ONU devices via SNMP on ZTE C320 OLT.
Uses CLI snmpwalk for reliability.
Uses SSH for MAC address retrieval.
Path: ~/ServersMonitoringMCP/src/monitoring/onu_monitor.py
"""

import asyncio
import re
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from loguru import logger

from src.core.config import get_config, OLTConfig


class ONUStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    LOW_SIGNAL = "low_signal"
    UNKNOWN = "unknown"


@dataclass
class ONUInfo:
    olt_id: str
    onu_id: str
    port: str
    status: ONUStatus
    rx_power: Optional[float] = None
    tx_power: Optional[float] = None
    rx_power_avg: Optional[float] = None  # Average over last 5 minutes
    tx_power_avg: Optional[float] = None  # Average over last 5 minutes
    description: str = ""
    onu_type: str = ""
    serial_number: str = ""  # ONU Serial Number (e.g. ZTEGC98D8E1A)
    mac_address: str = ""    # ONU MAC address (e.g. EC:23:7B:E6:1A:5E)
    offline_reason: Optional[str] = None  # String like "LOS (Loss of Signal)"
    last_offline: Optional[str] = None
    updated_at: datetime = field(default_factory=datetime.now)


# ZTE C320 OID definitions (tested on V1.2.5P3)
ZTE_C320_OIDS = {
    "onu_type": "1.3.6.1.4.1.3902.1012.3.28.1.1.1",           # STRING: "ZTE-F660"
    "onu_name": "1.3.6.1.4.1.3902.1012.3.28.1.1.2",           # STRING: "ONU-4:1"
    "onu_description": "1.3.6.1.4.1.3902.1012.3.28.1.1.3",    # STRING: "$$$$Client Name"
    "onu_sn": "1.3.6.1.4.1.3902.1012.3.28.1.1.5",             # Hex-STRING: Serial Number
    "onu_status": "1.3.6.1.4.1.3902.1012.3.28.2.1.1",         # INTEGER: 1=online, 2=offline
    "onu_phase_state": "1.3.6.1.4.1.3902.1012.3.28.2.1.4",    # INTEGER: 1=LOS, 3=DyingGasp, 6=Working
    "onu_last_offline": "1.3.6.1.4.1.3902.1012.3.28.2.1.5",   # STRING: datetime
}

# ВНИМАНИЕ: OID 3.11.4.1.1 и 3.11.4.1.2 РАНЬШЕ использовались как Rx/Tx power.
# Проверка на живом ZTE-C320-SW30-N показала, что это неверно:
#   - 3.11.4.1.2 содержит ДИСТАНЦИЮ до ONU в метрах (10317 = "ONU Distance: 10317m"),
#     а не мощность передатчика;
#   - 3.11.4.1.1 не коррелирует с реальной мощностью вообще (корреляция Пирсона 0.19
#     на 22 замерах): почти одинаковые сырые значения 119454 и 119830 соответствуют
#     -19.13 и -24.43 dBm. Формулы для него не существует.
# Реальных значений мощности в приватной ветке 3902.1012 нет ни в одном OID.
# Поэтому оптика теперь читается из CLI командой "show pon power onu-rx".


# ZTE C320 offline reason codes (from phase_state OID ...2.1.4)
ZTE_OFFLINE_REASONS = {
    1: "LOS (Loss of Signal)",      # Обрыв оптики
    2: "LOF (Loss of Frame)",       # Потеря кадра
    3: "Dying Gasp (Power Off)",    # Отключили питание ONU
    4: "LOA (Loss of Ack)",         # Нет подтверждения
    5: "Deregistered",              # Удалён с OLT
    6: None,                        # Working/Online
    0: None,                        # Unknown/Never offline
}


def decode_port_index(port_index: int, onu_id: str) -> str:
    """
    Decode ZTE port index to human-readable format.
    
    268501248 = 0x10010100 -> port 1
    268501760 = 0x10010300 -> port 3  
    268502016 = 0x10010400 -> port 4
    
    Returns format: "1/1/3:5" (slot/frame/port:onu)
    """
    try:
        # ZTE format: the port number is in bits 8-15
        port = (port_index >> 8) & 0xFF
        
        # Return readable format: 1/1/port:onu_id
        return f"1/1/{port}:{onu_id}"
        
    except:
        return f"?:{onu_id}"


def clean_description(desc: str) -> str:
    """Remove $$$$ prefix and clean up description."""
    if not desc:
        return ""
    
    # Remove $$$$ prefix
    if desc.startswith("$$$$"):
        desc = desc[4:]
    
    # Remove quotes
    desc = desc.strip('"').strip()
    
    # If it's just "ONU-X:Y", return empty (not useful)
    if desc.startswith("ONU-") and ":" in desc:
        return ""
    
    return desc


def parse_onu_serial_number(hex_string: str) -> str:
    """
    Parse ONU Serial Number from Hex-STRING.
    
    Input: "5A 54 45 47 C9 8D 8E 1A" or "Hex-STRING: 5A 54 45 47 C9 8D 8E 1A"
    Output: "ZTEGC98D8E1A"
    
    First 4 bytes are vendor ID (ASCII), remaining 4 bytes are serial (hex).
    """
    if not hex_string:
        return ""
    
    # Remove "Hex-STRING: " prefix if present
    if "Hex-STRING:" in hex_string:
        hex_string = hex_string.split("Hex-STRING:")[-1].strip()
    
    # Split by spaces
    hex_bytes = hex_string.strip().split()
    
    if len(hex_bytes) < 4:
        return hex_string  # Return as-is if format unknown
    
    try:
        # First 4 bytes: vendor ID as ASCII (e.g., "ZTEG")
        vendor = ""
        for i in range(4):
            byte_val = int(hex_bytes[i], 16)
            if 32 <= byte_val <= 126:  # Printable ASCII
                vendor += chr(byte_val)
            else:
                vendor += hex_bytes[i]
        
        # Remaining bytes: serial number as hex (uppercase, no separators)
        serial = "".join(hex_bytes[4:]).upper()
        
        return vendor + serial
        
    except (ValueError, IndexError):
        # If parsing fails, return cleaned hex string
        return "".join(hex_bytes).upper()


def format_mac_address(mac_str: str) -> str:
    """
    Format MAC address from raw string to standard format.
    
    Input: "284294001088" or "28:42:94:00:10:88"
    Output: "28:42:94:00:10:88"
    """
    if not mac_str:
        return ""
    
    # Remove quotes and whitespace
    mac_str = mac_str.strip().strip('"')
    
    # If already formatted with colons
    if ":" in mac_str:
        return mac_str.upper()
    
    # If 12 hex chars without separators
    if len(mac_str) == 12 and mac_str.isalnum():
        return ":".join(mac_str[i:i+2] for i in range(0, 12, 2)).upper()
    
    return mac_str


async def snmpwalk_cli(host: str, community: str, oid: str, timeout: int = 30) -> dict[str, str]:
    """
    Run snmpwalk via CLI and parse results.
    Returns dict[index, value].
    """
    cmd = [
        "snmpwalk", "-v2c",
        "-c", community,
        "-t", str(timeout),
        host, oid
    ]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
        
        if proc.returncode != 0:
            logger.debug(f"snmpwalk error: {stderr.decode()}")
            return {}
        
        results = {}
        base_parts = oid.split(".")
        
        for line in stdout.decode().strip().split("\n"):
            if not line or "=" not in line:
                continue
            
            try:
                # Format: iso.3.6.1.4.1.3902...268502016.1 = STRING: "ONU-4:1"
                oid_part, value_part = line.split(" = ", 1)
                
                # Convert iso -> 1
                oid_nums = oid_part.replace("iso", "1").split(".")
                
                # Extract index (everything after base OID)
                if len(oid_nums) > len(base_parts):
                    index = ".".join(oid_nums[len(base_parts):])
                else:
                    continue
                
                # Parse value
                if ": " in value_part:
                    value_type, value = value_part.split(": ", 1)
                    value = value.strip('"')
                else:
                    value = value_part.strip('"')
                
                results[index] = value
                
            except Exception as e:
                logger.debug(f"Parse error for line '{line}': {e}")
                continue
        
        return results
        
    except asyncio.TimeoutError:
        logger.error(f"snmpwalk timeout for {host} OID {oid}")
        return {}
    except Exception as e:
        logger.error(f"snmpwalk failed: {e}")
        return {}


async def ssh_get_olt_data(
    host: str,
    username: str,
    password: str,
    port: int = 22,
    timeout: int = 30,
    with_power: bool = True,
    ports: Optional[list[int]] = None,
) -> tuple[dict[str, str], dict[str, float], dict[str, float]]:
    """
    Собрать данные с ZTE C320 за ОДНУ интерактивную SSH-сессию.

    Возвращает (mac_table, rx_table, tx_table). Ключ везде "port:onu_id",
    например "6:1". Мощность в dBm, как её отдаёт сама железка.

    Одна сессия на цикл опроса: команды добавляются в тот же expect-скрипт,
    что и раньше собирал MAC, поэтому число подключений к OLT не растёт.

    ports — какие GPON-порты опрашивать. Вызывающий передаёт только те, где
    реально есть ONU (это видно из SNMP до захода по SSH). На OLT с ONU на
    половине портов это вдвое сокращает число команд и время сессии.
    По умолчанию все восемь.

    timeout — на ОДНУ команду expect. Общий лимит на сессию считается от
    количества команд, иначе большой OLT не успевает ответить и вся сессия
    падает по таймауту, теряя и MAC, и оптику.
    """
    mac_table: dict[str, str] = {}
    rx_table: dict[str, float] = {}
    tx_table: dict[str, float] = {}
    
    # Build expect script for interactive SSH
    expect_script = f'''
set timeout {timeout}
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o KexAlgorithms=+diffie-hellman-group1-sha1 -o HostKeyAlgorithms=+ssh-dss -o Ciphers=+aes128-cbc -p {port} {username}@{host}

expect {{
    -re "-+ *[Mm]ore *-+" {{ send " "; exp_continue }}
    "password:" {{
        send "{password}\\r"
        exp_continue
    }}
    "#" {{
        # Ready for commands
    }}
    ">" {{
        # Ready for commands
    }}
    timeout {{
        exit 1
    }}
}}

# Get MAC for ports 1-8
'''
    
    scan_ports = sorted(ports) if ports else list(range(1, 9))

    for gpon_port in scan_ports:
        expect_script += f'''
send "show mac gpon olt gpon-olt_1/1/{gpon_port}\\r"
expect {{
    -re "-+ *[Mm]ore *-+" {{ send " "; exp_continue }}
    "#" {{ }}
    ">" {{ }}
    timeout {{ }}
}}
'''

    if with_power:
        for gpon_port in scan_ports:
            # onu-rx поддерживается всеми прошивками C320.
            # onu-tx есть не везде; если команды нет, OLT ответит ошибкой,
            # разбор просто ничего не найдёт и tx останется пустым.
            expect_script += f'''
send "show pon power onu-rx gpon-olt_1/1/{gpon_port}\\r"
expect {{
    -re "-+ *[Mm]ore *-+" {{ send " "; exp_continue }}
    "#" {{ }}
    ">" {{ }}
    timeout {{ }}
}}
send "show pon power onu-tx gpon-olt_1/1/{gpon_port}\\r"
expect {{
    -re "-+ *[Mm]ore *-+" {{ send " "; exp_continue }}
    "#" {{ }}
    ">" {{ }}
    timeout {{ }}
}}
'''
    
    expect_script += '''
send "exit\\r"
expect eof
'''
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "expect", "-c", expect_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Команд в сессии: по одной на порт для MAC + по две на порт для оптики.
        num_commands = len(scan_ports) * (3 if with_power else 1)
        total_timeout = timeout + 10 * num_commands
        logger.debug(
            f"{host}: {num_commands} команд по портам {scan_ports}, "
            f"лимит сессии {total_timeout}s"
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=total_timeout)
        
        if proc.returncode != 0:
            logger.debug(f"SSH expect failed: {stderr.decode()}")
            return {}, {}, {}
        
        output = stdout.decode()
        
        # Parse output - look for MAC entries with vport 1
        # Format: ec23.7b1d.d2a8   800    Dynamic   gpon-onu_1/1/3:2          vport 1
        for line in output.split("\n"):
            line = line.strip()
            if not line or "vport 1" not in line:
                continue
            
            match = re.match(r'^([0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4})\s+.*gpon-onu_1/1/(\d+):(\d+)\s+vport 1', line, re.IGNORECASE)
            if match:
                mac_raw = match.group(1)
                port_num = match.group(2)
                onu_id = match.group(3)
                
                # Convert MAC: ec23.7b1d.d2a8 -> EC:23:7B:1D:D2:A8
                mac_clean = mac_raw.replace(".", "").upper()
                mac_formatted = ":".join(mac_clean[i:i+2] for i in range(0, 12, 2))
                
                key = f"{port_num}:{onu_id}"
                mac_table[key] = mac_formatted
                logger.debug(f"Found MAC {mac_formatted} for ONU {key}")
        
        # Разбор мощности.
        # Формат строк ZTE C320:
        #   gpon-onu_1/1/4:1    -24.432(dbm)
        #   gpon-onu_1/1/4:10 N/A
        # N/A означает "нет сигнала" и пропускается — значение останется None.
        if with_power:
            power_re = re.compile(
                r'gpon-onu_1/1/(\d+):(\d+)\s+(-?\d+(?:\.\d+)?)\s*\(dbm\)',
                re.IGNORECASE,
            )
            current = None
            for line in output.split("\n"):
                low = line.lower()
                if "onu-rx" in low:
                    current = rx_table
                    continue
                if "onu-tx" in low:
                    current = tx_table
                    continue
                if current is None:
                    continue
                m = power_re.search(line)
                if m:
                    key = f"{m.group(1)}:{m.group(2)}"
                    try:
                        current[key] = round(float(m.group(3)), 2)
                    except ValueError:
                        pass

        logger.info(
            f"SSH from {host}: {len(mac_table)} MAC, "
            f"{len(rx_table)} Rx, {len(tx_table)} Tx"
        )
        return mac_table, rx_table, tx_table
        
    except asyncio.TimeoutError:
        logger.warning(
            f"SSH timeout for {host} — сессия не уложилась в лимит. "
            f"Проверь, не выросло ли число портов с ONU"
        )
        return {}, {}, {}
    except Exception as e:
        logger.warning(f"SSH error for {host}: {e}")
        return {}, {}, {}


async def ssh_get_mac_table(
    host: str, username: str, password: str, port: int = 22, timeout: int = 30
) -> dict[str, str]:
    """
    Только MAC-таблица, без команд мощности.

    Оставлено для mac_port_sync, который вызывает это отдельно от цикла ONU
    и в оптике не нуждается — лишние команды к OLT ему не нужны.
    """
    mac_table, _, _ = await ssh_get_olt_data(
        host, username, password, port, timeout, with_power=False
    )
    return mac_table


class ONUMonitor:
    """SNMP-based ONU monitoring for ZTE C320 GPON OLT."""
    
    # How long to keep history for averaging (seconds)
    HISTORY_DURATION = 300  # 5 minutes
    
    def __init__(self):
        self.config = get_config()
        self._onu_cache: dict[str, list[ONUInfo]] = {}
        self._last_poll: dict[str, datetime] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # History for averaging: {olt_id:port_index.onu_id: [(timestamp, rx, tx), ...]}
        self._power_history: dict[str, list[tuple[datetime, Optional[float], Optional[float]]]] = {}
    
    def _get_onu_key(self, olt_id: str, index: str) -> str:
        """Generate unique key for ONU."""
        return f"{olt_id}:{index}"
    
    def _add_to_history(self, key: str, rx_power: Optional[float], tx_power: Optional[float]):
        """Add power reading to history."""
        now = datetime.now()
        
        if key not in self._power_history:
            self._power_history[key] = []
        
        self._power_history[key].append((now, rx_power, tx_power))
        
        # Remove old entries (older than HISTORY_DURATION)
        cutoff = now - timedelta(seconds=self.HISTORY_DURATION)
        self._power_history[key] = [
            (ts, rx, tx) for ts, rx, tx in self._power_history[key]
            if ts > cutoff
        ]
    
    def _get_averages(self, key: str) -> tuple[Optional[float], Optional[float]]:
        """Get average Rx and Tx power from history."""
        if key not in self._power_history or not self._power_history[key]:
            return None, None
        
        rx_values = [rx for _, rx, _ in self._power_history[key] if rx is not None]
        tx_values = [tx for _, _, tx in self._power_history[key] if tx is not None]
        
        rx_avg = round(sum(rx_values) / len(rx_values), 2) if rx_values else None
        tx_avg = round(sum(tx_values) / len(tx_values), 2) if tx_values else None
        
        return rx_avg, tx_avg
    
    async def poll_olt(self, olt: OLTConfig) -> list[ONUInfo]:
        """Poll single OLT for all ONU information."""
        logger.debug(f"Polling OLT: {olt.id} ({olt.host})")
        
        oids = ZTE_C320_OIDS
        onus: list[ONUInfo] = []
        community = olt.community or "public"
        
        try:
            # Get ONU names first (this gives us the list of all ONUs)
            name_results = await snmpwalk_cli(olt.host, community, oids["onu_name"])
            
            if not name_results:
                logger.warning(f"No ONU data from {olt.id}")
                self._onu_cache[olt.id] = []
                self._last_poll[olt.id] = datetime.now()
                return []
            
            logger.debug(f"Got {len(name_results)} ONU names")
            
            # Get other data
            type_results = await snmpwalk_cli(olt.host, community, oids["onu_type"])
            desc_results = await snmpwalk_cli(olt.host, community, oids["onu_description"])
            sn_results = await snmpwalk_cli(olt.host, community, oids["onu_sn"])
            status_results = await snmpwalk_cli(olt.host, community, oids["onu_status"])
            phase_state_results = await snmpwalk_cli(olt.host, community, oids["onu_phase_state"])
            last_offline_results = await snmpwalk_cli(olt.host, community, oids["onu_last_offline"])
            
            # Get MAC addresses via SSH if credentials are configured
            # MAC и оптика забираются одной SSH-сессией.
            # Мощность больше не берётся из SNMP: см. комментарий у ZTE_C320_OIDS.
            mac_table = {}
            rx_table = {}
            tx_table = {}
            # Порты, на которых SNMP уже показал ONU — только их и опрашиваем.
            active_ports = sorted({
                (int(idx.split(".")[0]) >> 8) & 0xFF
                for idx in name_results
                if "." in idx and idx.split(".")[0].isdigit()
            })

            if olt.ssh_username and olt.ssh_password:
                try:
                    mac_table, rx_table, tx_table = await ssh_get_olt_data(
                        olt.host,
                        olt.ssh_username,
                        olt.ssh_password,
                        olt.ssh_port if hasattr(olt, 'ssh_port') else 22,
                        ports=active_ports or None,
                    )
                except Exception as e:
                    logger.warning(f"SSH data retrieval failed for {olt.id}: {e}")
            else:
                logger.warning(
                    f"OLT {olt.id}: не заданы ssh_username/ssh_password — "
                    f"MAC и мощность будут пустыми"
                )
            
            # Get thresholds
            onu_config = self.config.get_onu_monitoring_config()
            thresholds = onu_config.thresholds if onu_config else None
            warning_threshold = thresholds.warning if thresholds else -25
            
            # Process each ONU
            for index, onu_name in name_results.items():
                try:
                    # Parse index: "port_index.onu_id"
                    parts = index.split(".")
                    if len(parts) < 2:
                        continue
                    
                    port_index = int(parts[0])
                    onu_id = parts[1]
                    
                    # Get values
                    onu_type = type_results.get(index, "")
                    description = clean_description(desc_results.get(index, ""))
                    serial_number = parse_onu_serial_number(sn_results.get(index, ""))
                    
                    # Get MAC address from SSH table
                    # Key format: "port:onu_id" e.g. "3:2"
                    port_num = (port_index >> 8) & 0xFF
                    mac_key = f"{port_num}:{onu_id}"
                    mac_address = mac_table.get(mac_key, "")
                    
                    # Get status from SNMP (1=online, 2=offline)
                    status_raw = status_results.get(index, "1")
                    try:
                        snmp_status = int(status_raw)
                    except:
                        snmp_status = 1
                    
                    # Мощность из CLI OLT (ключ тот же "port:onu_id", что у MAC).
                    # Отсутствие ключа = OLT ответил N/A либо сессия не удалась.
                    rx_power = rx_table.get(mac_key)
                    tx_power = tx_table.get(mac_key)
                    
                    # Check last offline time
                    last_offline = last_offline_results.get(index, "")
                    if last_offline and "0000" in last_offline:
                        last_offline = None  # Never was offline
                    
                    # Get offline reason from phase_state (OID ...2.1.4)
                    # 1=LOS, 3=Dying Gasp, 6=Working
                    # Only set offline_reason if device is actually offline
                    offline_reason = None
                    if snmp_status == 2:  # Only for offline devices
                        phase_state_raw = phase_state_results.get(index, "6")
                        try:
                            phase_code = int(phase_state_raw)
                            offline_reason = ZTE_OFFLINE_REASONS.get(phase_code)
                        except:
                            pass
                    
                    # Determine status (SNMP status is primary)
                    if snmp_status == 2:
                        status = ONUStatus.OFFLINE
                    elif rx_power is not None and rx_power < warning_threshold:
                        status = ONUStatus.LOW_SIGNAL
                    elif snmp_status == 1:
                        status = ONUStatus.ONLINE
                    else:
                        status = ONUStatus.UNKNOWN
                    
                    # Decode port to readable format: 1/1/3:5
                    port_str = decode_port_index(port_index, onu_id)
                    
                    # Add to history and get averages
                    onu_key = self._get_onu_key(olt.id, index)
                    self._add_to_history(onu_key, rx_power, tx_power)
                    rx_power_avg, tx_power_avg = self._get_averages(onu_key)
                    
                    onu = ONUInfo(
                        olt_id=olt.id,
                        onu_id=onu_id,
                        port=port_str,
                        status=status,
                        rx_power=rx_power,
                        tx_power=tx_power,
                        rx_power_avg=rx_power_avg,
                        tx_power_avg=tx_power_avg,
                        description=description,
                        onu_type=onu_type,
                        serial_number=serial_number,
                        mac_address=mac_address,
                        offline_reason=offline_reason,
                        last_offline=last_offline,
                    )
                    onus.append(onu)
                    
                except Exception as e:
                    logger.debug(f"Error processing ONU {index}: {e}")
                    continue
            
            # Sort by port number then ONU ID
            def sort_key(onu):
                try:
                    # Parse "1/1/3:5" -> (3, 5)
                    port_part = onu.port.split("/")[-1]  # "3:5"
                    port_num, onu_num = port_part.split(":")
                    return (int(port_num), int(onu_num))
                except:
                    return (999, 999)
            
            onus.sort(key=sort_key)
            
            logger.info(f"OLT {olt.id}: found {len(onus)} ONUs")
            
        except Exception as e:
            logger.error(f"Failed to poll OLT {olt.id}: {e}")
        
        self._onu_cache[olt.id] = onus
        self._last_poll[olt.id] = datetime.now()
        
        return onus
    
    async def poll_all(self) -> dict[str, list[ONUInfo]]:
        """Poll all enabled OLTs."""
        results = {}
        olts = self.config.get_enabled_olts()
        
        for olt in olts:
            onus = await self.poll_olt(olt)
            results[olt.id] = onus
        
        return results
    
    async def _poll_loop(self):
        """Main polling loop."""
        onu_config = self.config.get_onu_monitoring_config()
        interval = onu_config.poll_interval if onu_config else 60
        
        logger.info(f"ONU monitor loop started (interval: {interval}s)")
        
        while self._running:
            try:
                await self.poll_all()
            except Exception as e:
                logger.error(f"ONU poll loop error: {e}")
            
            await asyncio.sleep(interval)
        
        logger.info("ONU monitor loop stopped")
    
    async def start(self):
        """Start ONU monitoring."""
        if self._running:
            return
        
        olts = self.config.get_enabled_olts()
        if not olts:
            logger.info("No OLTs configured, ONU monitoring disabled")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"ONU monitor started for {len(olts)} OLT(s)")
    
    async def stop(self):
        """Stop ONU monitoring."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("ONU monitor stopped")
    
    def get_cached_onus(self, olt_id: Optional[str] = None) -> list[ONUInfo]:
        """Get cached ONU data."""
        if olt_id:
            return self._onu_cache.get(olt_id, [])
        
        all_onus = []
        for onus in self._onu_cache.values():
            all_onus.extend(onus)
        return all_onus
    
    def get_last_poll_time(self, olt_id: str) -> Optional[datetime]:
        """Get last poll time for OLT."""
        return self._last_poll.get(olt_id)
    
    def get_stats(self) -> dict:
        """Get monitoring statistics."""
        all_onus = self.get_cached_onus()
        
        return {
            "total_onus": len(all_onus),
            "online": len([o for o in all_onus if o.status == ONUStatus.ONLINE]),
            "offline": len([o for o in all_onus if o.status == ONUStatus.OFFLINE]),
            "low_signal": len([o for o in all_onus if o.status == ONUStatus.LOW_SIGNAL]),
            "olts_polled": len(self._onu_cache),
        }
    
    @property
    def is_running(self) -> bool:
        return self._running


_onu_monitor: Optional[ONUMonitor] = None


def get_onu_monitor() -> ONUMonitor:
    global _onu_monitor
    if _onu_monitor is None:
        _onu_monitor = ONUMonitor()
    return _onu_monitor