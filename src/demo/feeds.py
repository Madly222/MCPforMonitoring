"""Demo replacements for the GPON poller and the utility outage scrapers."""

import random
from datetime import datetime, timedelta

from src.core.config import OLTConfig
from src.monitoring.onu_monitor import ONUInfo, ONUMonitor, ONURegistration, ONUStatus

CUSTOMERS = [
    "Office Block A", "Bakery on Main St", "Clinic North", "Library", "Warehouse 3", "School Annex",
    "Apartment 12", "Apartment 14", "Cafe Corner", "Pharmacy", "Gym", "Print Shop", "Dental Office",
    "Hostel", "Florist", "Car Service",
]


class DemoONUMonitor(ONUMonitor):
    """Two PON ports per OLT with a few low-signal and offline ONUs; levels drift a little per poll."""

    async def poll_olt(self, olt: OLTConfig) -> list[ONUInfo]:
        rng = random.Random(olt.id)
        onus = []
        for port in (1, 2):
            for n in range(1, 9):
                idx = (port - 1) * 8 + n
                base_rx = rng.uniform(-24.5, -17.0)
                status, registration, reason, last_offline = ONUStatus.ONLINE, ONURegistration.REGISTERED, None, None
                if idx in (5, 13):
                    base_rx = rng.uniform(-28.5, -26.0)
                    status = ONUStatus.LOW_SIGNAL
                rx = round(base_rx + random.uniform(-0.3, 0.3), 2)
                tx = round(rng.uniform(1.8, 2.6), 2)
                if idx in (7, 16):
                    status, registration, rx, tx = ONUStatus.OFFLINE, ONURegistration.NOT_REGISTERED, None, None
                    reason = "LOS (Loss of Signal)" if idx == 7 else "Dying Gasp"
                    last_offline = (datetime.now() - timedelta(hours=rng.randint(2, 30))).strftime("%Y-%m-%d %H:%M:%S")
                key = self._get_onu_key(olt.id, f"{port}.{n}")
                self._add_to_history(key, rx, tx)
                rx_avg, tx_avg = self._get_averages(key)
                onus.append(ONUInfo(
                    olt_id=olt.id,
                    onu_id=str(n),
                    port=f"1/1/{port}:{n}",
                    status=status,
                    registration=registration,
                    rx_power=rx,
                    tx_power=tx,
                    rx_power_avg=rx_avg,
                    tx_power_avg=tx_avg,
                    description=CUSTOMERS[idx - 1],
                    onu_type="ZTE-F660" if idx % 3 else "ZTE-F601",
                    serial_number=f"ZTEG{rng.getrandbits(32):08X}",
                    mac_address="02:00:5E:10:{:02X}:{:02X}".format(port, n),
                    offline_reason=reason,
                    last_offline=last_offline,
                ))
        self._onu_cache[olt.id] = onus
        self._last_poll[olt.id] = datetime.now()
        return onus


def _outage_status(module, matches: list[str]):
    status = module.ElectricStatus if hasattr(module, "ElectricStatus") else module.ACCStatus
    return status(ok=not matches, last_check=datetime.now(), matches=matches)


def make_electric_check():
    import src.monitoring.electric_monitor as em

    async def check_electric_status(force: bool = False):
        day = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        matches = [
            f"[{day}] ⚡ str. Example 12 (Chișinău, Centru) ⏰ 09:00-17:00\n"
            "   📍 ...planned maintenance of the 10 kV line: str. Example 2-24, str. Sample 1-9..."
        ]
        em._cached_status = _outage_status(em, matches)
        em._last_check_time = datetime.now()
        return em._cached_status

    return check_electric_status


def make_acc_check():
    import src.monitoring.acc_monitor as acc

    async def check_acc_status(force: bool = False):
        acc._cached_status = _outage_status(acc, [])
        acc._last_check_time = datetime.now()
        return acc._cached_status

    return check_acc_status
