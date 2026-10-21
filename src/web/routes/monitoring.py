"""Monitoring: watcher state, detected errors and fixes, health reports, liveness, Claude health."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from src.core.config import get_config
from src.web.auth import get_current_user, require_admin, UserInfo

router = APIRouter()


@router.get("/monitoring/status")
async def get_monitoring_status(user: UserInfo = Depends(get_current_user)):
    from src.monitoring.log_watcher import get_log_watcher
    from src.monitoring.health_checker import get_health_checker
    from src.monitoring.error_detector import get_error_detector

    watcher = get_log_watcher()
    checker = get_health_checker()
    detector = get_error_detector()

    result = {
        "log_watcher": {
            "running": watcher.is_running,
            "watched_files": watcher.watched_files
        },
        "health_checker": {
            "running": checker.is_running
        },
        "error_detector": {
            "stats": detector.get_error_stats()
        }
    }

    try:
        from src.monitoring.onu_monitor import get_onu_monitor
        onu_monitor = get_onu_monitor()
        result["onu_monitor"] = {
            "running": onu_monitor.is_running,
            "stats": onu_monitor.get_stats()
        }
    except Exception as e:
        logger.debug(f"ONU monitor status unavailable: {e}")

    return result


@router.get("/monitoring/errors")
async def get_recent_errors(
    minutes: int = 60,
    user: UserInfo = Depends(get_current_user)
):
    from src.monitoring.error_detector import get_error_detector

    detector = get_error_detector()
    errors = detector.get_recent_errors(minutes)

    return {
        "mode": get_config().load_settings().auto_remediation.mode,
        "count": len(errors),
        "errors": [
            {
                "server_id": e.event.server_id,
                "service_type": e.event.service_type,
                "log_file": e.event.log_file,
                "line": e.event.line[:200],
                "event_type": e.event.event_type.value,
                "error_hash": e.error_hash,
                "first_seen": e.first_seen.isoformat(),
                "last_seen": e.last_seen.isoformat(),
                "count": e.count,
                "resolved": e.resolved,
                "resolution": e.resolution,
                "pattern": {
                    "diagnosis": e.pattern.diagnosis,
                    "severity": e.pattern.severity,
                    "auto_fix": e.pattern.auto_fix,
                    "suggestions": e.pattern.suggestions,
                } if e.pattern else None,
                "remediation": e.remediation,
                "analysis": e.analysis,
            }
            for e in errors
        ]
    }


@router.post("/monitoring/errors/{error_hash}/fix")
async def apply_error_fix(
    error_hash: str,
    http_request: Request,
    user: UserInfo = Depends(require_admin)
):
    """Run the fix commands of a known error, after the operator confirmed them in the UI."""
    from src.actions.remediation import get_remediator
    from src.monitoring.error_detector import get_error_detector

    detector = get_error_detector()
    detected = detector.get_error(error_hash)
    if detected is None:
        raise HTTPException(status_code=404, detail="Error not found (it may have aged out)")
    if detected.pattern is None or not detected.pattern.commands:
        raise HTTPException(status_code=400, detail="This error has no fix commands")

    ip = http_request.client.host if http_request.client else None
    return await get_remediator().apply(detected, detector, user.username, user.role, ip)


@router.get("/monitoring/health")
async def get_health_reports(user: UserInfo = Depends(get_current_user)):
    from src.monitoring.health_checker import get_health_checker

    checker = get_health_checker()
    reports = checker.get_all_reports()

    return {
        "count": len(reports),
        "reports": [
            {
                "server_id": r.server_id,
                "host": r.host,
                "reachable": r.reachable,
                "check_result": r.check_result.value,
                "services": r.services,
                "system_info": r.system_info,
                "checked_at": r.checked_at.isoformat(),
                "error": r.error
            }
            for r in reports
        ]
    }


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/claude/health")
async def claude_health(user: UserInfo = Depends(get_current_user)):
    """Make a minimal Claude API call to verify the key and model are alive."""
    from src.core.claude_client import get_claude_client
    model = None
    try:
        secrets = get_config().load_secrets()
        model = secrets.claude.model
        if not secrets.claude.api_key:
            return {"ok": False, "model": model, "error": "No API key configured"}
        # Looking the model up checks the key and the model id without generating tokens
        await get_claude_client().client.models.retrieve(model)
        return {"ok": True, "model": model}
    except Exception as e:
        return {"ok": False, "model": model, "error": str(e)}
