"""
FastAPI Web Application.
Main web application for NetOps Control Plane.
Provides REST API and serves static files.
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from src.core.config import get_config, DEMO_MODE, PROJECT_ROOT
from src.core.ssh_manager import get_ssh_manager
from src.monitoring.log_watcher import get_log_watcher, LogEvent
from src.monitoring.error_detector import get_error_detector
from src.monitoring.health_checker import get_health_checker
from src.actions.remediation import get_remediator, spawn
from src.web.api import router as api_router
from src.web.auth import router as auth_router
from src.web.api_netbox import router as netbox_router
from src.web.admin import router as admin_router

async def handle_log_event(event: LogEvent):
    detector = get_error_detector()
    detected = detector.process_event(event)

    if not detected:
        return

    remediator = get_remediator()
    if detected.pattern:
        logger.info(f"Known error on {event.server_id}: {detected.pattern.diagnosis[:50]}...")
        # Restarts can take a while; keep the log stream moving
        spawn(remediator.handle(detected, detector))
    else:
        logger.warning(f"Unknown error on {event.server_id}: {event.line[:50]}...")
        spawn(remediator.analyze_unknown(detected))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting NetOps Control Plane...")

    config = get_config()
    secrets = config.load_secrets()
    settings = config.load_settings()

    logger.info(f"Web server starting on {secrets.mcp_server.web_host}:{secrets.mcp_server.web_port}")

    enabled_servers = config.get_enabled_servers()
    logger.info(f"Enabled servers: {len(enabled_servers)}")
    for server in enabled_servers:
        logger.info(f"  - {server.id} ({server.host})")

    enabled_olts = config.get_enabled_olts()
    if enabled_olts:
        logger.info(f"Enabled OLTs: {len(enabled_olts)}")
        for olt in enabled_olts:
            logger.info(f"  - {olt.id} ({olt.host})")

    log_watcher = get_log_watcher()
    health_checker = get_health_checker()

    log_watcher.add_handler(handle_log_event)

    if settings.monitoring.realtime.enabled:
        try:
            await log_watcher.start()
            logger.info(f"Log watcher started: {len(log_watcher.watched_files)} files")
        except Exception as e:
            logger.error(f"Failed to start log watcher: {e}")

    try:
        await health_checker.start()
        logger.info("Health checker started")
    except Exception as e:
        logger.error(f"Failed to start health checker: {e}")

    onu_monitor = None
    if enabled_olts:
        try:
            from src.monitoring.onu_monitor import get_onu_monitor
            onu_monitor = get_onu_monitor()
            await onu_monitor.start()
            logger.info("ONU monitor started")
        except Exception as e:
            logger.error(f"Failed to start ONU monitor: {e}")

    # Start the in-app outage scheduler (electricity + water, time set in panel)
    from src.monitoring.outage_scheduler import scheduler_loop
    outage_task = asyncio.create_task(scheduler_loop())

    yield

    # Shutdown
    logger.info("Shutting down NetOps Control Plane...")

    outage_task.cancel()
    try:
        await outage_task
    except asyncio.CancelledError:
        pass

    await log_watcher.stop()
    await health_checker.stop()

    if onu_monitor:
        try:
            await onu_monitor.stop()
        except Exception as e:
            logger.warning(f"Failed to stop ONU monitor: {e}")

    ssh = get_ssh_manager()
    await ssh.close()

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    if DEMO_MODE:
        # Must run before anything creates the SSH manager or the monitors
        from src.demo import install
        install()

    server_cfg = get_config().load_secrets().mcp_server

    app = FastAPI(
        title="NetOps Control Plane",
        description="Intelligent server monitoring and auto-remediation system",
        version="1.1.2",
        lifespan=lifespan
    )

    # The dashboard is served by this app, so CORS is off unless origins are listed.
    if server_cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=server_cfg.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
    app.include_router(api_router, prefix="/api", tags=["API"])
    app.include_router(netbox_router, prefix="/api/netbox", tags=["NetBox Auto-Fill"])
    app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])

    static_dir = PROJECT_ROOT / "web"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
