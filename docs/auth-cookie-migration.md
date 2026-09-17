---
name: cookie-auth-steps
description: Move JWT from localStorage to cookies (supervisor instruction 2026-09-17)
metadata:
  type: reference
---

Steps to relocate avs-auth from localStorage (localhost) to cookies:

1. `frontend/src/store/auth.js` — replace `persist` middleware (localStorage) with cookie-based storage (or remove persistence since cookie handles session).
2. `frontend/src/api/client.js` — add `credentials: 'include'` to `fetch` so cookies travel with `/api` requests.
3. `backend/app/deps/auth.py` — update `get_current_token` to read token from `request.cookies.get('access_token')` (fallback to `Authorization` header for backward compat).
4. `backend/app/api/v1/auth.py` — set `HttpOnly` / `Secure` cookies on `/login` and `/refresh` responses.
5. `backend/.env` / `.env.example` — add `COOKIE_DOMAIN=localhost` and `COOKIE_SECURE=false` for dev.
6. `frontend/src/store/auth.js` — change `name: 'avs-auth'` reference; update comment from "localStorage" to "cookie".

**Why:** supervisor requires cookie-based auth so multi-account demo (admin + purchaser + supplier) works without cookie collision; browsers isolate cookies per profile/incognito but share localStorage within the same origin/profile.

**How to apply:** implement steps 1-6 in sequence; restart backend (`python -m uvicorn`) and frontend (`vite`); verify `/auth/login` sets cookie and `/orders/{id}/proposal` receives it via `request.cookies`.
