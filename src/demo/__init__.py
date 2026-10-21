"""
Demo mode: the whole app against simulated infrastructure.

Enabled with DEMO_MODE=1. install() swaps the SSH layer, the GPON poller and
the outage scrapers for simulations before anything else creates them; the rest
of the app (API, resolver, risk policy, remediation, dashboard) runs as usual.
"""

from loguru import logger


def install() -> None:
    import src.core.ssh_manager as ssh_manager
    import src.monitoring.acc_monitor as acc_monitor
    import src.monitoring.electric_monitor as electric_monitor
    import src.monitoring.onu_monitor as onu_monitor
    from src.demo.feeds import DemoONUMonitor, make_acc_check, make_electric_check
    from src.demo.ssh import DemoSSHManager

    ssh_manager._ssh_manager = DemoSSHManager()
    onu_monitor._onu_monitor = DemoONUMonitor()
    electric_monitor.check_electric_status = make_electric_check()
    acc_monitor.check_acc_status = make_acc_check()
    logger.warning("DEMO MODE: servers, OLTs and outage feeds are simulated; nothing real is contacted")
