"""
MCP Server Monitor - Main Entry Point.

Usage:
    python -m src.main
    or
    uvicorn src.web.app:app --host 0.0.0.0 --port 4455
"""

import sys
from pathlib import Path

import uvicorn
from loguru import logger

from src.core.config import get_config, LOGS_DIR, SECRETS_FILE


def setup_logging():
    """Configure application logging."""
    config = get_config()
    settings = config.load_settings()
    
    log_level = settings.logging.level
    log_format = settings.logging.format
    
    logger.remove()
    
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level=log_level,
        colorize=True
    )
    
    log_file = LOGS_DIR / "app.log"
    logger.add(
        str(log_file),
        format=log_format,
        level=log_level,
        rotation=f"{settings.logging.rotation.max_size_mb} MB",
        retention=settings.logging.rotation.backup_count,
        compression="zip"
    )
    
    logger.info(f"Logging configured: level={log_level}, file={log_file}")


def check_configuration():
    """Verify configuration before starting."""
    if not SECRETS_FILE.exists():
        logger.error(f"Secrets file not found: {SECRETS_FILE}")
        logger.info("Please copy secrets.example.yaml to secrets.yaml and configure it:")
        logger.info(f"  cp secrets.example.yaml secrets.yaml")
        sys.exit(1)
    
    config = get_config()
    
    try:
        secrets = config.load_secrets()
        logger.info("Configuration loaded successfully")
        
        enabled_servers = config.get_enabled_servers()
        logger.info(f"Enabled servers: {len(enabled_servers)}")
        
        if not enabled_servers:
            logger.warning("No servers are enabled. Enable servers in secrets.yaml")
        
        if not secrets.web_users:
            logger.error("No web users configured. Add users to secrets.yaml")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    setup_logging()
    
    logger.info("=" * 60)
    logger.info("MCP Server Monitor v1.0.0")
    logger.info("=" * 60)
    
    check_configuration()
    
    config = get_config()
    secrets = config.load_secrets()
    
    host = secrets.mcp_server.web_host
    port = secrets.mcp_server.web_port
    
    logger.info(f"Starting web server on http://{host}:{port}")
    
    uvicorn.run(
        "src.web.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True
    )


if __name__ == "__main__":
    main()
