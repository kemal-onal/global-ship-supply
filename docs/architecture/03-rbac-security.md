# RBAC & network security

> Two layers of protection:
> 1. **Authentication + authorization** at the application layer (JWT + RBAC scopes)
> 2. **Network security simulation** at the request layer (rate limit, port scan
>    detection, injection filter, brute-force counter)
>
> In production these would map to a WAF + VPN; in the MVP they live in
> middleware that logs the same kinds of events.

---

## 1. Identity & session

### 1.1 JWT (RS256)

- 15-minute access token, 14-day refresh token
- RS256 (asymmetric) lets the API verify without holding the signing key
- Claims: `sub`, `iss`, `aud`, `iat`, `exp`, `scope`
- Refresh: `POST /auth/refresh` returns a new pair; old refresh is revoked
- The key pair is generated on first boot in dev; in production it's mounted
  from a secrets manager

### 1.2 Password hashing

- `passlib[argon2]` with `argon2-cffi` as backend
- Argon2id is the OWASP-recommended choice (memory-hard, GPU-resistant)
- Salt is per-user, encoded in the hash

### 1.3 Why not sessions?

A ship going through port-state changes IP frequently. JWTs are stateless and
survive NAT / IP rotation; the refresh token handles the long-lived
relationship with the auth server.

---

## 2. Permission model

Permissions are stored as `resource:action:scope` strings. Scopes follow a
hierarchy:

```
own < vessel < fleet < global
```

When the user has a permission with scope `fleet`, the auth dependency
also accepts narrower scopes (`vessel`, `own`).

### 2.1 Permission catalog

| Resource | Actions              | Example                                        |
| -------- | -------------------- | ---------------------------------------------- |
| order    | read, create, update, delete, approve | `order:read:fleet`              |
| rfq      | read, create, award  | `rfq:award:vessel`                            |
| catalog  | read, edit, price    | `catalog:read:global`                         |
| vessel   | read, edit           | `vessel:edit:fleet`                           |
| port     | read                 | `port:read:global`                            |
| catering | read, plan, edit     | `catering:plan:vessel`                        |
| customs  | read, evaluate       | `customs:evaluate:fleet`                      |
| user     | read, create, edit   | `user:create:global`                          |
| audit    | read                 | `audit:read:global`                           |

### 2.2 System roles

| Role        | Default grants                                          |
| ----------- | ------------------------------------------------------- |
| admin       | `*:*:global`                                            |
| port_agent  | `port:read:global`, `customs:read:global`, `order:read:fleet` |
| captain     | `order:read:own`, `order:create:own`, `order:approve:vessel` |
| purchaser   | `order:create:fleet`, `order:update:fleet`, `rfq:*:fleet`, `catalog:read:global`, `supplier:*:fleet` |
| steward     | `catering:plan:vessel`, `order:create:vessel`, `order:read:vessel` |
| supplier    | `rfq:read:own`, `quote:create:own`                      |

Roles are stored in `roles` and joined to `users` via `user_roles`. The
permission catalog is rebuilt idempotently at seed time.

### 2.3 Enforcement

```python
@router.post("/orders", dependencies=[Depends(require_permission("order", "create"))])
async def create_order(...): ...
```

`require_permission` returns 403 with a stable error code so the UI can
surface "you need purchaser role" rather than a generic error.

---

## 3. Network security simulation (IDS/IPS)

Lives in `app/core/ids.py` and is registered as a FastAPI middleware.

### 3.1 Sliding windows (in-memory; Redis in prod)

| Counter                          | Window       | Threshold | Action                  |
| -------------------------------- | ------------ | --------- | ----------------------- |
| `login_failures[ip]`             | 5 min        | 5         | 429 for 15 min          |
| `login_failures[user_id]`        | 15 min       | 10        | lock account            |
| `rate_window[ip]`                | 60 sec       | 120 req   | 429                     |
| `paths_seen[ip]`                 | 60 sec       | 60 paths  | flag as port scan       |
| `payload_size[ip]`               | 60 sec       | 10 MB     | 413                     |

In production these would be backed by Redis (`INCR`, `EXPIRE`, sorted
sets for sliding windows) so they're shared across workers and pods.

### 3.2 Injection pattern filter

```python
SQLI_PATTERNS = [
  re.compile(r"(\bunion\b.*\bselect\b)", re.I),
  re.compile(r"(;|\-\-)\s*(drop|delete|insert|update)", re.I),
  re.compile(r"(\bor\b\s+1\s*=\s*1)", re.I),
  re.compile(r"(waitfor\s+delay)", re.I),
]
XSS_PATTERNS = [
  re.compile(r"<\s*script", re.I),
  re.compile(r"javascript\s*:", re.I),
  re.compile(r"on(error|load|click)\s*=", re.I),
]
```

- Scans URL path, query string, JSON body
- On match: 400 response, `security_events` row with severity=blocking
- The middleware *adds* a defense layer; we still use parameterized
  queries via SQLAlchemy so the database itself is safe.

### 3.3 Port scan detection

If a single IP requests 60+ *distinct* paths within 60s (with most
returning 404), we log `security_events` with type=`port_scan` and
rate-limit that IP to 1 req/sec for the next hour.

### 3.4 Security event log

```sql
CREATE TABLE security_events (
  id BIGSERIAL PRIMARY KEY,
  type TEXT NOT NULL,           -- brute_force, injection, port_scan, rate_limit
  severity TEXT NOT NULL,       -- info, warning, blocking
  source_ip INET,
  user_id UUID,
  path TEXT,
  method TEXT,
  payload_excerpt TEXT,         -- first 200 chars of offending content
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ix_security_events_severity_created_at
  ON security_events (severity, created_at DESC);
```

---

## 4. Mapping to real network devices

| MVP defense             | Production equivalent                          |
| ----------------------- | ---------------------------------------------- |
| JWT RS256               | OAuth2 + IdP (Okta / Azure AD)                 |
| Rate limit middleware   | NGINX `limit_req` + WAF (Cloudflare, AWS WAF)  |
| Port scan detection     | Fail2Ban / CrowdSec                            |
| Brute-force counter     | Account lockout in IdP + adaptive MFA          |
| Injection filter        | WAF rule set + parameterized queries           |
| `security_events` table | SIEM (Splunk, Datadog, Elastic) ingestion      |

The MVP doesn't ship a VPN but the API is *shaped* to sit behind one:
every request carries `X-Forwarded-For` (trusted proxy), the
`source_ip` is recorded for every audit row, and the session model
would slot straight into an mTLS-enforced perimeter.
