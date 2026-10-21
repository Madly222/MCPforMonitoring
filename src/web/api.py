"""
REST API under /api.

The endpoints live in src/web/routes/, one module per area; this module
combines them into the router app.py mounts.
"""

from fastapi import APIRouter

from src.web.routes import commands, monitoring, onu, servers, utilities

router = APIRouter()
for module in (servers, utilities, onu, commands, monitoring):
    router.include_router(module.router)
