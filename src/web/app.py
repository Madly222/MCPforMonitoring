"""
FastAPI Web Application.
Main web application for MCP Server Monitor.
Provides REST API and serves static files.
"""
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from src.core.config import get_config, PROJECT_ROOT
from src.core.ssh_manager import get_ssh_manager
from src.monitoring.log_watcher import get_log_watcher, LogEvent
from src.monitoring.error_detector import get_error_detector
from src.monitoring.health_checker import get_health_checker
from src.monitoring.updates_checker import get_updates_checker
from src.web.api import router as api_router
from src.web.auth import router as auth_router
from src.web.api_netbox import router as netbox_router
from src.web.admin import router as admin_router

async def handle_log_event(event: LogEvent):
    """Process log events from watcher."""
    detector = get_error_detector()
    detected = detector.process_event(event)
    
    if detected:
        if detected.pattern:
            logger.info(f"Known error on {event.server_id}: {detected.pattern.diagnosis[:50]}...")
            
            # Check if auto-fix is possible
            if detector.can_auto_fix(detected):
                logger.info(f"Auto-fix available for: {detected.error_hash}")
                # TODO: Execute auto-fix in Stage 5
        else:
            logger.warning(f"Unknown error on {event.server_id}: {event.line[:50]}...")
            # TODO: Send to Claude API for analysis in Stage 4


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting MCP Server Monitor...")
    
    config = get_config()
    secrets = config.load_secrets()
    settings = config.load_settings()
    
    logger.info(f"Web server starting on {secrets.mcp_server.web_host}:{secrets.mcp_server.web_port}")
    
    enabled_servers = config.get_enabled_servers()
    logger.info(f"Enabled servers: {len(enabled_servers)}")
    for server in enabled_servers:
        logger.info(f"  - {server.id} ({server.host})")
    
    # Log enabled OLTs
    enabled_olts = config.get_enabled_olts()
    if enabled_olts:
        logger.info(f"Enabled OLTs: {len(enabled_olts)}")
        for olt in enabled_olts:
            logger.info(f"  - {olt.id} ({olt.host})")
    
    # Start monitoring components
    log_watcher = get_log_watcher()
    health_checker = get_health_checker()
    updates_checker = get_updates_checker()
    
    # Add log event handler
    log_watcher.add_handler(handle_log_event)
    
    # Start log watcher if realtime monitoring enabled
    if settings.monitoring.realtime.enabled:
        try:
            await log_watcher.start()
            logger.info(f"Log watcher started: {len(log_watcher.watched_files)} files")
        except Exception as e:
            logger.error(f"Failed to start log watcher: {e}")
    
    # Start health checker
    try:
        await health_checker.start()
        logger.info("Health checker started")
    except Exception as e:
        logger.error(f"Failed to start health checker: {e}")
    
    # Start updates checker (checks once per day)
    try:
        await updates_checker.start()
        logger.info("Updates checker started (24h interval)")
    except Exception as e:
        logger.error(f"Failed to start updates checker: {e}")
    
    # Start ONU monitor if configured
    onu_monitor = None
    if enabled_olts:
        try:
            from src.monitoring.onu_monitor import get_onu_monitor
            onu_monitor = get_onu_monitor()
            await onu_monitor.start()
            logger.info("ONU monitor started")
        except Exception as e:
            logger.error(f"Failed to start ONU monitor: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down MCP Server Monitor...")
    
    await log_watcher.stop()
    await health_checker.stop()
    await updates_checker.stop()
    
    # Stop ONU monitor if it was started
    if onu_monitor:
        try:
            await onu_monitor.stop()
        except:
            pass
    
    ssh = get_ssh_manager()
    await ssh.close()
    
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    config = get_config()
    secrets = config.load_secrets()
    
    app = FastAPI(
        title="MCP Server Monitor",
        description="Intelligent server monitoring and auto-remediation system",
        version="1.0.0",
        lifespan=lifespan
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
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