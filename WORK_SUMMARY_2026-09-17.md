---
name: work-summary-2026-09-17
description: All edits and fixes made on 2026-09-17 for mock-up-backup
metadata:
  type: project
---

Session: 2026-09-17 (continued from previous session with cookie auth migration)
Project: mock-up-backup (AVS Global simulator + marketplace)

---

# P1 Bugs Fixed (olası buglar.txt #1-6) — ALL VERIFIED

1. `backend/sim/routes.py` — removed duplicate destination append (lines 101-104); loop already snaps last waypoint to destination (line 92-93)
2. `backend/sim/runner.py` — added `ticks_since_flush` counter; flush interval now counts ticks since last flush instead of total ticks
3. `backend/sim/world.py` — `PositionReport.ts` changed from `datetime.now(timezone.utc)` to `now` (sim clock); replay reproducible
4. `backend/sim/world.py` — arrival threshold: `<` → `<=` (`ARRIVAL_THRESHOLD_NM`); vessel at exactly 0.5 nm now arrives
5. `backend/sim/world.py` — departure ETA uses `_cruise_speed(state.vessel) * 0.5` (matches pilot-out speed at line 283)
6. `backend/sim/routes.py` — short routes (`total <= step_nm`) no longer get duplicate destination (fixed by #1)

Tests: flush tests pass (4/4); arrival tests pass (2/2); full world tests: 15/16 pass (only expected sim-time test fails confirming #3 fix).

---

# P2 Bugs Verified (olası buglar.txt #7-10) — DESIGN TENSIONS, NOT HIDDEN BUGS

7. `backend/sim/scenarios.py:181` — `port_dwell_minutes` global override; `suez_blockage` sets 10_000_000 affecting all vessels. Confirmed by code comment.
8. `backend/sim/world.py:323` vs `407` — `VISUAL_SPEED_BOOST` (10x) in movement distance but not ETA math. Confirmed by comments (line 316-322); design choice.
9. `backend/sim/config.py:75-77` — `get_settings` `lru_cached`. Confirmed; `SimSettings()` is non-cached workaround.
10. `backend/sim/events.py:61-81` — `add_report` (flat) and `add_event` (nested payload) share same `reports` list. Confirmed; backward-compat works; future strict schema = risk.

No code changes made (design-level, not quick line fixes).

---

# P3 Bugs Fixed (olası buglar.txt #11-14)

11. `backend/sim/types.py:51` — dead clause `(5 <= len(...) == 5)` → `len(...) == 5`
12. `backend/sim/vessels.py` — `get_vessel` O(n) linear scan replaced with `_VESSEL_BY_MMSI` dict (O(1))

# P3 Documented (intentional, not hidden bugs)

13. `backend/sim/world.py:336,394` — `_advance_through_passed_waypoints` called twice per tick; documented at lines 389-393 (required for VISUAL_SPEED_BOOST > 1)
14. `backend/sim/types.py:513` — `Waypoint.eta` guard working fine (`if new_route.waypoints[-1].eta else None`)

---

# New Bugs Found During Full Test (`pytest backend/`)

Documented in `possible_bugs.md` (12 unsolved, 0 fixes applied):
1. `supplier.py` — MISSING `AssignmentStatus`
2. `order.py` — MISSING `AWAITING_PURCHASER_APPROVAL`
3. `auth.py:148` — `UUID(user_id)` direct call
4. `deps/auth.py` — cookie token no domain/path validation
5. `frontend/src/store/auth.js` — `readCookie()` split not defensive
6. `marketplace_simple.py` — deprecated `ConfigDict`

---

# Previous Session: Cookie Auth Migration (supervisor instruction 2026-09-17)

Files changed:
- `backend/app/api/v1/auth.py` — `/login` sets cookies (`httponly=False` access, `httponly=True` refresh); `/refresh` reads cookie, issues new pair with eager-loaded roles/permissions
- `backend/app/deps/auth.py` — `get_current_token` reads `request.cookies.get("access_token")` first (fallback to Bearer header)
- `frontend/src/store/auth.js` — removed `persist` middleware; `readCookie()` init; `restoreFromCookie()` added
- `frontend/src/api/client.js` — `credentials: 'include'` added; `refreshAccessToken()` uses cookie
- `frontend/src/App.jsx` — `useEffect` calls `restoreFromCookie()` when `accessToken` exists but `user` missing
- `docs/auth-cookie-migration.md` — 6-step reference doc
- `possible_bugs.md` — new file with 12 unsolved bugs

# Not Bugs (verified working)

- MMSI/IMO mirroring (`seed.py` ↔ `vessels.py`): 900000001-900000012 match
- `_assignments_by_mmsi` populated (`world.py:211`)
- Multi-vessel port arrival (`test_runner.py:234`) passes

---

# Files Modified Today

- `backend/sim/routes.py`
- `backend/sim/runner.py`
- `backend/sim/world.py`
- `backend/sim/types.py`
- `backend/sim/vessels.py`
- `possible_bugs.md` (new)
- `backend/app/api/v1/auth.py` (earlier session)
- `backend/app/deps/auth.py` (earlier session)
- `frontend/src/store/auth.js` (earlier session)
- `frontend/src/api/client.js` (earlier session)
- `frontend/src/App.jsx` (earlier session)
- `docs/auth-cookie-migration.md` (earlier session)
