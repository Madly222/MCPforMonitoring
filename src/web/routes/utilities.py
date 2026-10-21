"""Utility outage monitors: water (acc.md) and electricity (Premier Energy)."""


from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from src.web.auth import get_current_user, UserInfo

router = APIRouter()


@router.get("/acc/status")
async def get_acc_status(user: UserInfo = Depends(get_current_user)):
    """Get ACC.md water disconnection status."""
    try:
        from src.monitoring.acc_monitor import get_status_dict, check_acc_status
        import asyncio
        asyncio.create_task(check_acc_status())
        return get_status_dict()
    except ImportError:
        return {"ok": True, "last_check": None, "matches_count": 0, "matches": [], "error": "ACC module not installed"}
    except Exception as e:
        logger.error(f"ACC status error: {e}")
        return {"ok": True, "last_check": None, "matches_count": 0, "matches": [], "error": str(e)}


@router.post("/acc/check")
async def check_acc_now(user: UserInfo = Depends(get_current_user)):
    """Force check ACC.md now."""
    try:
        from src.monitoring.acc_monitor import check_acc_status, get_status_dict
        await check_acc_status(force=True)
        return get_status_dict()
    except Exception as e:
        logger.error(f"ACC check error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/electric/status")
async def get_electric_status(user: UserInfo = Depends(get_current_user)):
    """Get Premier Energy disconnection status."""
    try:
        from src.monitoring.electric_monitor import get_status_dict, check_electric_status
        import asyncio
        asyncio.create_task(check_electric_status())
        return get_status_dict()
    except ImportError:
        return {"ok": True, "last_check": None, "matches_count": 0, "matches": [], "error": "Electric module not installed"}
    except Exception as e:
        logger.error(f"Electric status error: {e}")
        return {"ok": True, "last_check": None, "matches_count": 0, "matches": [], "error": str(e)}


@router.post("/electric/check")
async def check_electric_now(user: UserInfo = Depends(get_current_user)):
    """Force check Premier Energy now."""
    try:
        from src.monitoring.electric_monitor import check_electric_status, get_status_dict
        await check_electric_status(force=True)
        return get_status_dict()
    except Exception as e:
        logger.error(f"Electric check error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
