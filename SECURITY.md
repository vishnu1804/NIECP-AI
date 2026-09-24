# NIECP-AI — Security Notes

## Authentication & sessions
- Passwords: bcrypt (cost 12), with a deterministic policy (length + classes + weak-word rejection).
- Access tokens: short-lived JWT (HS256, server-side secret). No secrets in the frontend bundle.
- Refresh tokens: opaque random strings; **only SHA-256 hashes stored**; rotation on every use (old token single-use); revocable per-session and globally; lockout after 5 failed logins (15 minutes) with security-event audit records.
- Password reset / email verification: single-use hashed tokens with expiry. Where SMTP is unconfigured, tokens are shown in the API response **and the response says so** — the UI labels this as a deployment limitation, never as an emailed link.

## Authorization
- Platform roles (8, spec §2) + organization membership roles (ADMIN / MANAGER / EMPLOYEE / VIEWER, spec §33).
- Every project-scoped endpoint passes through `project_access()`: owner, same-organization member, or platform admin — otherwise 403. Verified by tests (`test_project_isolation`).
- Admin endpoints (`/admin/*`) require elevated platform roles; demo-data purge is system-admin only.

## Input & file safety
- Pydantic validation on every write path; strict file extension allow-list; executable extensions rejected; upload size cap (25 MB default); random server-side storage names; download only through authorized, audit-logged endpoints.
- Rule expressions run through a hand-written recursive-descent parser with a fixed grammar and a **whitelisted function table validated at parse time** — no `eval`/`exec`, no attribute access, no imports. Injection attempts raise and are covered by tests.

## Transport & headers
- HSTS automatically in production; `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: microphone=(self)` (the app legitimately uses the mic for the voice assistant).
- CORS locked to configured origins (must not be `*` in production; validated by `validate_production_readiness()` surfaced in `/api/v1/health`).
- Fixed-window rate limiting per client IP (240/min default).

## Secrets
- All credentials (DB, LLM, government APIs, SMTP) are server-side environment variables only. The Integration API never returns secrets — only booleans (`credentials_configured`) and statuses.
- SQLite file lives under `backend/` (git-ignored in real deployments); snapshots exclude credential files.

## Audit
- Spec §38 events are recorded with user, action, category, project, resource, result, IP, user-agent, request-id, before/after, and an agent tag. Security events (failed logins, lockouts, voice confirmations, permission changes) are flagged and filterable in the admin panel.

## Known limitations (stated, not hidden)
- Rate limiting is in-process — use a shared store (e.g., Redis) when clustering.
- Email delivery requires SMTP configuration; without it, the platform is honest about it (no fake "email sent").
- Document OCR is not bundled: image-only PDFs/scans are flagged `NO_TEXT` rather than silently accepted.
- The optional external LLM only ever rephrases tool-composed answers; verdicts and sources remain deterministic.


## Integration upgrade additions (2026-09-22)

- **Demo endpoints are non-government by construction** and are hard-disabled when
  `environment=production` unless `NIECP_DEMO_ALLOW_IN_PRODUCTION` is explicitly set.
  They never perform outbound calls; the outbound-call kill-switch
  (`NIECP_ENABLE_OUTBOUND_GOV_CALLS=0`) continues to gate every real network probe.
- **Voice assistant**: microphone permission is requested only from a user gesture;
  tracks and the AudioContext are stopped on Stop/Close/unmount; no audio is recorded
  or uploaded — recognition uses the browser's own Web Speech pipeline and only the
  final transcript text is sent to NIECP's own API (same authorization as chat).
- **No new secrets**: API Setu/DigiLocker credentials remain server-side settings and
  are unconfigured by default; the frontend never sees credentials, and the demo
  environment uses none.
- **Correlated audit trail**: execution events (DEMO_SUBMITTED, OFFICIAL_REDIRECT_OPENED,
  QUERY_RECORDED, QUERY_RESPONSE_SUBMITTED, MANUAL_PACKET_GENERATED, demo decisions) are
  audit-logged with correlation_id, integration_mode and provider.

- **Government data services (2026-09-23)**: every external call is server-side through
  `gov_manager.dispatch` → provider adapters with timeout/retry/validation/error-mapping.
  Secrets are backend-only (data.gov.in key, MCA/NSWS/DigiLocker credentials); API payloads
  expose boolean "configured" flags, never values. Dataset results are labelled
  GOVERNMENT_DATASET_MATCH (never verification); DigiLocker retrieval requires a GRANTED
  consent row plus provisioned credentials and otherwise honestly returns
  PENDING_AUTHORIZATION with the official redirect. All provider calls and consent grants/
  denials/revocations are audit-logged with correlation ids; provider logs never store
  secrets or raw payloads.
- The dataset cache stores PUBLIC government dataset responses only (pincode/UDYAM/MCA/CPCB/ASI) under a short TTL; credentials, tokens and user-supplied/private payloads are never cached. API keys travel server→data.gov.in only and are never serialized into any API payload, log line, or cache entry.
- Public environmental/industrial datasets (CPCB air, surface water, ASI) are labelled ENVIRONMENTAL_CONTEXT / HISTORICAL_SUPPORTING_DATA / INDUSTRIAL_STATISTICAL_DATA in both API payloads and the UI, and can never by themselves create or remove an approval requirement.
