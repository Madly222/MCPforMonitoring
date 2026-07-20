"""
Offline tests for outage notification filtering and de-duplication.

No network: exercises the pure functions that decide when the ⚡/💧 indicator
clears and when an email is considered "new". Run:

    python scripts/test_outage_filters.py
"""

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.monitoring.electric_monitor as em  # noqa: E402
import src.monitoring.acc_monitor as acc       # noqa: E402

_TMP = Path(tempfile.mkdtemp())
em.NOTIFIED_FILE = _TMP / "electric_notified.json"
acc.NOTIFIED_FILE = _TMP / "acc_notified.json"

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_fail = 0


def check(name, cond):
    global _fail
    print(f"  [{PASS if cond else FAIL}] {name}")
    if not cond:
        _fail += 1


now = datetime.now()
today = now.strftime('%Y-%m-%d')
yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
tomorrow = (now + timedelta(days=1)).strftime('%Y-%m-%d')
past_end = (now - timedelta(hours=1)).strftime('%H:%M')
future_end = (now + timedelta(hours=2)).strftime('%H:%M')

print("\n== electric: time/date filtering ==")
m_expired = f"[{today}] ⚡ Asachi 71 (Chișinău, Centru) ⏰ 09:00-{past_end}\n   📍 ...str..."
m_active = f"[{today}] ⚡ Asachi 71 (Chișinău, Centru) ⏰ 09:00-{future_end}\n   📍 ...str..."
m_yesterday = f"[{yesterday}] ⚡ Asachi 71 ⏰ 09:00-23:00"
m_tomorrow = f"[{tomorrow}] ⚡ Asachi 71 ⏰ 09:00-12:00"
m_nodate = "⚡ Asachi 71 no date"

out = em.filter_current_matches([m_expired, m_active, m_yesterday, m_tomorrow, m_nodate])
check("today's expired outage dropped", m_expired not in out)
check("today's active outage kept", m_active in out)
check("yesterday dropped", m_yesterday not in out)
check("tomorrow kept", m_tomorrow in out)
check("undated kept", m_nodate in out)

print("\n== electric: content de-dup ==")
sig_a = em._match_signature(m_active)
sig_t = em._match_signature(m_tomorrow)
check("signature is first line", sig_a == m_active.split('\n')[0].strip())
em.mark_notified([m_active])
notified = em.get_notified_signatures()
check("active marked notified", sig_a in notified)
check("tomorrow NOT yet notified (new address scenario)", sig_t not in notified)
# Simulate: tomorrow's outage is new -> should be considered new even though today notified
all_m = [m_active, m_tomorrow]
new = [m for m in all_m if em._match_signature(m) not in em.get_notified_signatures()]
check("newly added outage still triggers email", m_tomorrow in new and m_active not in new)

print("\n== electric: past entries pruned ==")
em.mark_notified([m_yesterday])  # date in past
em.cleanup_old_notifications()
check("past-date signature pruned", em._match_signature(m_yesterday) not in em.get_notified_signatures())

print("\n== water (ACC): restoration-time filtering ==")
end_past = (now - timedelta(hours=1)).strftime('%d.%m.%Y %H:%M')
end_future = (now + timedelta(hours=3)).strftime('%d.%m.%Y %H:%M')
w_expired = f"[Работы] 📍 Centru: Asachi 71 [în lucru]\n   Откл: 01.01.2026 09:00, Восст: {end_past}"
w_active = f"[Работы] 📍 Centru: Asachi 71 [în lucru]\n   Откл: 01.01.2026 09:00, Восст: {end_future}"
w_notice = "[Уведомление] ⚠️ Плановое отключение!\n   📅 mâine\n   📍 Улицы: Asachi"

wout = acc.filter_current_matches([w_expired, w_active, w_notice])
check("restored (past Восст) dropped", w_expired not in wout)
check("ongoing (future Восст) kept", w_active in wout)
check("plain notice (no Восст) kept", w_notice in wout)

print("\n== water: content de-dup ==")
acc.mark_notified([w_active])
check("active disconnection marked", acc._match_signature(w_active) in acc.get_notified_signatures())
new_w = [m for m in [w_active, w_notice] if acc._match_signature(m) not in acc.get_notified_signatures()]
check("new notice still triggers", w_notice in new_w and w_active not in new_w)

print("\n== invalidate() resets cache ==")
em._cached_status = "x"; em._last_check_time = now
em.invalidate()
check("electric cache cleared", em._cached_status is None and em._last_check_time is None)
acc._cached_status = "x"; acc._last_check_time = now
acc.invalidate()
check("water cache cleared", acc._cached_status is None and acc._last_check_time is None)

print()
if _fail:
    print(f"\033[91m{_fail} check(s) failed\033[0m")
    sys.exit(1)
print("\033[92mAll checks passed\033[0m")
