"""GPON: OLTs and ONU status."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from src.core.config import get_config
from src.web.auth import get_current_user, require_admin, UserInfo

router = APIRouter()


@router.get("/onu/status")
async def get_onu_status(user: UserInfo = Depends(get_current_user)):
    """Get all ONU status from all OLTs."""
    from src.monitoring.onu_monitor import get_onu_monitor

    monitor = get_onu_monitor()
    onus = monitor.get_cached_onus()
    stats = monitor.get_stats()

    config = get_config()
    onu_config = config.get_onu_monitoring_config()
    thresholds = onu_config.thresholds if onu_config else None

    return {
        "timestamp": datetime.now().isoformat(),
        "stats": stats,
        "thresholds": {
            "good": thresholds.good if thresholds else -20,
            "warning": thresholds.warning if thresholds else -25
        },
        "onus": [
            {
                "olt_id": o.olt_id,
                "onu_id": o.onu_id,
                "port": o.port,
                "status": o.status.value,
                "registration": o.registration.value,
                "rx_power": o.rx_power,
                "tx_power": o.tx_power,
                "rx_power_avg": getattr(o, 'rx_power_avg', None),
                "tx_power_avg": getattr(o, 'tx_power_avg', None),
                "description": o.description,
                "onu_type": getattr(o, 'onu_type', ''),
                "serial_number": getattr(o, 'serial_number', ''),
                "mac_address": getattr(o, 'mac_address', ''),
                "last_offline": getattr(o, 'last_offline', None),
                "offline_reason": getattr(o, 'offline_reason', None),
                "updated_at": o.updated_at.isoformat()
            }
            for o in onus
        ]
    }


@router.get("/onu/olts")
async def get_olts(user: UserInfo = Depends(get_current_user)):
    """Get configured OLTs."""
    config = get_config()
    olts = config.get_enabled_olts()

    return {
        "olts": [
            {
                "id": olt.id,
                "host": olt.host,
                "vendor": olt.vendor,
                "enabled": olt.enabled
            }
            for olt in olts
        ]
    }


@router.get("/onu/olt/{olt_id}")
async def get_olt_onus(
    olt_id: str,
    user: UserInfo = Depends(get_current_user)
):
    """Get ONU status for specific OLT."""
    from src.monitoring.onu_monitor import get_onu_monitor

    config = get_config()
    olt = config.get_olt_by_id(olt_id)

    if not olt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OLT not found: {olt_id}"
        )

    monitor = get_onu_monitor()
    onus = monitor.get_cached_onus(olt_id)
    last_poll = monitor.get_last_poll_time(olt_id)

    return {
        "olt_id": olt_id,
        "host": olt.host,
        "vendor": olt.vendor,
        "last_poll": last_poll.isoformat() if last_poll else None,
        "onus": [
            {
                "onu_id": o.onu_id,
                "port": o.port,
                "status": o.status.value,
                "registration": o.registration.value,
                "rx_power": o.rx_power,
                "tx_power": o.tx_power,
                "description": o.description,
                "offline_reason": o.offline_reason.value if o.offline_reason else None,
            }
            for o in onus
        ]
    }


@router.post("/onu/olt/{olt_id}/poll")
async def poll_olt(
    olt_id: str,
    user: UserInfo = Depends(require_admin)
):
    """Force poll specific OLT."""
    from src.monitoring.onu_monitor import get_onu_monitor

    config = get_config()
    olt = config.get_olt_by_id(olt_id)

    if not olt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OLT not found: {olt_id}"
        )

    monitor = get_onu_monitor()
    onus = await monitor.poll_olt(olt)

    return {
        "success": True,
        "message": f"Polled {len(onus)} ONUs from {olt_id}",
        "count": len(onus)
    }
