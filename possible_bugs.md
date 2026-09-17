---
name: possible-bugs
metadata:
  type: reference
---

# Possible / Unsolved Bugs — Mock-up-Backup

Created: 2026-09-17
Status: 12 new unsolved (0 fixes applied to these); P2 verified design tensions (4) also documented.

---

## P-CRITICAL (break imports / tests)

1. `backend/app/models/supplier.py` — MISSING `AssignmentStatus` enum
   - Blocks: `test_preparation_timeout.py`, `test_purchaser_approval.py`, `test_sealed_identities.py`, `test_supplier_portal.py`

2. `backend/app/models/order.py` — MISSING `AWAITING_PURCHASER_APPROVAL` in `OrderStatus`
   - Blocks: `test_purchaser_approval.py`

---

## P-HIGH (functional risk / error-prone)

3. `backend/app/api/v1/auth.py:148` — `UUID(user_id)` used directly; may crash if `sub` is not UUID format
4. `backend/app/deps/auth.py` — cookie `token` read from cookie but no domain/path validation against cookie settings
5. `frontend/src/store/auth.js` — `readCookie()` split not defensive; partial cookie value could corrupt token

---

## P-MEDIUM (deprecated / design tension)

6. `backend/app/api/v1/marketplace_simple.py` — `PydanticDeprecatedSince20`: class-based `config` deprecated (ConfigDict required)
7. `backend/sim/scenarios.py:181` — `port_dwell_minutes` global (not per-vessel); `suez_blockage` sets 10_000_000 affecting Cape-route vessels too
8. `backend/sim/config.py:75-77` — `get_settings` `lru_cached`; env changes after first call ignored (workaround: `SimSettings()` directly)
9. `backend/sim/world.py:323` vs `407` — `VISUAL_SPEED_BOOST` (10x) applied to movement distance but not to ETA math; ETA recedes incorrectly
10. `backend/sim/events.py:61-81` — position reports (flat dict) and events (nested `payload`) share same `reports` list; future strict schema change breaks silently

---

## P-LOW / DOCUMENTED (intentional behavior — not hidden bugs)

11. `backend/sim/world.py:336` and `:394` — `_advance_through_passed_waypoints` called twice per tick; second call documented at lines 389-393 (needed for VISUAL_SPEED_BOOST > 1)
12. `backend/sim/types.py:513` — `Waypoint.eta` guard (`if new_route.waypoints[-1].eta else None`) working fine; no fix needed

---

## Verified Design Tensions (P2 — not hidden bugs, not fixed)

- `sim/routes.py`: duplicate destination waypoint removed (P1 fix #1)
- `sim/runner.py`: flush_interval uses total ticks instead of ticks-since-last-flush (P1 fix #2)
- `sim/world.py`: `PositionReport.ts` uses wall-clock instead of sim clock (P1 fix #3 — intentional per docstring)
- `sim/world.py`: arrival check strict `< 0.5` nm (P1 fix #4)
- `sim/world.py`: departure speed mismatch — pilot-out `* 0.5` vs full cruise ETA (P1 fix #5)
- `sim/routes.py`: short routes (`total <= step_nm`) always get duplicate destination (fixed by P1 #1 removal)

---

## Not Bugs (verified working)

- MMSI/IMO mirroring between `seed.py` and `vessels.py`: all 900000001-900000012 and IMO numbers match exactly
- `_assignments_by_mmsi` correctly populated in `World.__init__` (`line 211`)
- Multi-vessel port arrival test passes (`test_runner.py:234`)
- `test_runner.py:234` regression test confirms no `KeyError` on multi-vessel arrivals