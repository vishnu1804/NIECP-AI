# NIECP-AI — National Industrial Ease & Compliance Platform

**AI-powered industrial approval & compliance navigator** for entrepreneurs, MSMEs, startups, consultants and compliance managers in India.

> NIECP-AI is a navigator, not an authority. It never grants, promises or simulates government approvals. Users always apply through official channels — NIECP-AI makes sure they walk in prepared.

---

## What it does

| Capability | How it stays honest |
|---|---|
| **Approval discovery** — 46 curated approval/registration types (business, land, environment, safety, labour, industry-specific) | A deterministic rule engine (no LLM) evaluates your project profile. Every verdict (`APPLIES` / `CONDITIONAL` / `NOT_APPLICABLE`) shows the matched facts, the rule, the legal basis and the authority. Unknown facts degrade to "needs information", never to a silent "not applicable". |
| **Application readiness score** | A preparation measure — explicitly *not* a probability of approval. Every component lists the checks that produced it. |
| **Document intelligence** | Classification, field extraction (PAN/GSTIN/CIN/Udyam/dates), profile cross-check, expiry detection, low-quality-scan flags. All findings labelled `AI_INTERPRETATION`. No OCR engine is bundled: unparseable scans are flagged, never waved through. |
| **Dependency graph & critical path** | Layered SVG graph (Business → Land → Building → Environment → Safety → Operations → Ongoing) derived from catalogue edges and live project state. |
| **Get Approval workflow** | DRAFT → READY_TO_APPLY → SUBMITTED → … with an explicit user-confirmation gate. NIECP-AI prepares; **you** submit on the official portal. Recording an application/reference number requires you to confirm it came from the authority. |
| **Compliance calendar & renewal engine** | Renewals, document expiries, inspections, queries and tasks with configurable 90/60/30/7-day reminders. |
| **Government queries** | Deterministic decomposition of a query into pointable asks + likely document mapping. Recording a response requires your confirmation that it was actually filed. |
| **Schemes & incentives** — 29 schemes with machine-evaluable criteria | Per-criterion verdicts: MET / NOT_MET / **INFO_REQUIRED**. Never claims eligibility. |
| **RAG assistant (text + voice)** | Hybrid sparse retrieval over a curated corpus of official-source summaries; answers carry source, publisher, date, verification status. No confident hit → *"I could not verify this from the available official sources."* |
| **Voice-first HUD** | Web Speech API STT, Web Audio waveform, speechSynthesis TTS. Sensitive commands ("submit this application") always raise a CONFIRM/CANCEL gate — never executed on speech alone. |
| **Integration manager** | API Setu / NSWS / DigiLocker / MyScheme / PARIVESH / XGNB. Without provisioned credentials everything is `MANUAL_MODE` with the official portal link. Health checks report skipped/failure honestly — failure is never converted into success. |

## Quick start

```bash
# backend (Python 3.11+)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8899
# → seeds reference data + a labelled demo project on first boot

# frontend (Node 18+)
cd frontend
npm install
npx vite build        # outputs to frontend/static, served by the API
```

Open `http://localhost:8899`.

**Accounts** (demonstration deployment — rotate in production):

| Account | Password | Purpose |
|---|---|---|
| `demo@niecp.local` | `Demo!Demo!123` | labelled demo project (electronics mfg., Tamil Nadu) |
| `admin@niecp.local` | `NIECP-Admin!2026` | admin panel (`must_change_password` flag set) |

## Production deployment

1. **PostgreSQL**: set `NIECP_DATABASE_URL=postgresql+psycopg://user:pass@host/db`, then `cd backend && alembic upgrade head`.
2. **Secrets**: `NIECP_SECRET_KEY` (required — boot refuses insecure defaults in production), `NIECP_CORS_ORIGINS` (must not be `*`).
3. **HTTPS** at the reverse proxy; HSTS is enabled automatically in production mode.
4. Run `alembic revision --autogenerate -m "..."` for future schema changes; `NIECP_ENVIRONMENT=production` turns on the production-readiness checks reported by `/api/v1/health`.
5. Government API credentials (API Setu, DigiLocker, …) are supplied **only** via server-side env — they are never exposed to the frontend and never simulated.

### Configuration (subset — see `.env.example`)

```
NIECP_DATABASE_URL=sqlite:///backend/niecp.db     # PostgreSQL in production
NIECP_SECRET_KEY=change-me                        # required in production
NIECP_CORS_ORIGINS=https://your-domain
NIECP_LLM_PROVIDER=none                           # openai | azure_openai | none
NIECP_LLM_API_KEY=                                # optional; verdicts stay rule-engine
NIECP_SMTP_HOST=                                  # empty ⇒ email honestly reported unconfigured
NIECP_ENABLE_OUTBOUND_GOV_CALLS=0                 # keep 0 until APIs are provisioned
```

## Architecture

```
USER ──► React SPA (frontend/static, served by FastAPI)
   │      · Vite + TypeScript + Tailwind · PWA (service worker, offline queue)
   │      · Voice HUD (Web Speech + Web Audio) · SVG approval graph
   ▼
FastAPI REST API  (/api/v1)  ── JWT + refresh rotation ── RBAC (platform + org roles)
   │
   ├─ Rule Engine (deterministic, sandboxed grammar — no eval)  ◄── the only authority on applicability
   ├─ Retrieval (BM25-lite + hash embeddings, curated corpus, citations)
   ├─ Assistant (intent router → tools: approvals/readiness/documents/schemes/calendar)
   ├─ Document AI (extraction → classification → profile cross-check → findings)
   ├─ Approval Engine (discovery, dependency graph, critical path, next-best-action)
   ├─ Renewal & notification engine (90/60/30/7 reminders; honest email status)
   ├─ Integration Manager (status machine; never fakes connectivity)
   └─ Audit Log (every security-relevant event)
   ▼
SQLAlchemy ORM ──► PostgreSQL (production) / SQLite (local, WAL)
```

Key backend layout:

```
backend/app/
├── ai/            rule_engine.py (sandboxed), retrieval.py, llm.py (optional), assistant.py (agents)
├── knowledge/data/  approval_data.py, scheme_data.py, portal_data.py, industries.py, knowledge_data.py, states.py
├── routers/       auth, projects, documents, applications, compliance, govdata, assistant, admin, pwa, system
├── services/      approval_engine, readiness, next_action, scheme_engine, questionnaire,
│                  documents_ai, gov_integrations, notifications, seed, portal_seed, audit, auth_service
└── models.py      40+ entities (spec §45) with provenance columns throughout
```

## Provenance labels used everywhere

`VERIFIED_GOV_SOURCE` · `OFFICIAL_API` · `USER_PROVIDED` · `AI_INTERPRETATION` · `REQUIRES_VERIFICATION` · `INFORMATION_UNAVAILABLE` · `DEMO`

Demo data is always flagged (`is_demo`, `[DEMO]` in names) and can be purged from the admin panel without touching real data.

## Tests

```bash
cd backend && python -m pytest tests/ -q
```

143 tests covering: rule-engine parser safety (injection attempts fail closed), three-valued honesty semantics, full API flows, document validation, application confirmation gates, assistant grounding/honesty, integration honesty, RBAC isolation, demo labelling, readiness, retrieval, localization — plus the integration-upgrade suite (`tests/test_upgrade.py`): Government registry, demo-government lifecycle with honesty invariants, execution channels, official redirect, manual packet, query translator and the `/ai/assistant` alias.

A second, live-server verification script exists at `backend/scripts/verify_upgrade_live.py` (41 checks, including the full demo journey end-to-end).

## Curriculum coverage (spec §57)

Phases 1–19 are implemented and working; phase 20 (hardening/deployment) is prepared via Alembic migrations, production validation gates, security headers, rate limiting, audit retention and the documented deployment steps. See `SECURITY.md` for the threat model, `AUDIT.md` for the upgrade audit, and `docs/` notes inline in each module.

## MSME Regulatory Intelligence (phase 3)

A deterministic MSMED Act, 2006 knowledge engine over the project profile — **not legal advice, not an official classification, not verification**. Every conclusion is labelled (OFFICIAL SOURCE / DATASET / REGULATORY DOCUMENT / USER-PROVIDED INFORMATION / AI INFERENCE / PENDING VERIFICATION) and carries an official source link.

- **Versioned law data (§10)** — §7 classification criteria carry amendment history: `v1-2006` (investment-only, SUPERSEDED), `v2-2020` (1/5 · 10/50 · 50/250 Cr, SUPERSEDED), `v3-2025` (micro 2.5/10 · small 25/100 · medium 125/500 Cr, PENDING_VERIFICATION). The engine applies the newest version and always surfaces a freshness warning: the knowledge base may not represent the latest applicable law.
- **Honest classification (§§1-2)** — class is *never* claimed without machinery investment + annual turnover + enterprise type + activity; output is `INFORMATION_REQUIRED` with the exact missing inputs. Declared class is a **potential classification** ("not an official government classification").
- **Conditional provisions (§§7,8,9,10,11,15,16,17,18,20,21,22,23,24,27)** — each shows applicability (APPLICABLE / CONDITIONAL / NOT_APPLICABLE / INFORMATIONAL), why it appears, required inputs & documents, recommended action, authority and official source. Nothing applies automatically. §22 (buyer-side disclosure) activates only with the *buys-from-MSME-suppliers* profile flag; §§15-18 (payment protection) activate for Micro/Small suppliers.
- **Payment Protection (§6)** — invoice/supply/payment dates, amount, terms → 45-day default period (flagged for verification), careful date math, compound monthly-rest interest estimate at 3× the RBI bank rate (placeholder rate, labelled AI INFERENCE), Samadhaan/MSEFC official routes. Framed as an **informational regulatory assessment — NOT LEGAL ADVICE**. Non-MSE suppliers are honestly told the MSEFC route may not apply.
- **MAITRI (§8, OFFICIAL_REDIRECT)** — Maharashtra projects get a 6-service facilitation catalogue (why it applies, required info, dependencies, official channel). "Apply on Official Portal" deep-links `maitri.maharashtra.gov.in`; **submission is never automated** (no authorized API). Non-MH projects are told it doesn't apply.
- **Document intelligence (§9)** — `GET /api/v1/msme/provisions/{section}/explain?project_id=` answers "what does this section mean for my project?" in plain language with condition, action, documents, source, confidence and a never-invent-provisions disclaimer.
- **MSME endpoints** — `GET /projects/{pid}/msme/intelligence` (full 10-block regulatory profile), `/msme/law-versions`, `/projects/{pid}/msme/classification`, `/alerts`, `/smart-action-guide`, `/maitri-services`, `POST /projects/{pid}/msme/payment-assessment`. New adapters behind the integration manager: **MAITRI** (OFFICIAL_REDIRECT, portal-only) and **CPCB** (PENDING_AUTHORIZATION) — registry now 9 providers, all pending/redirect/demo (none live).
- **UI** — dashboard "MSME Regulatory Intelligence" card (§15) + full `MSME Intelligence` project page: classification & registration status, digital-twin MSME block with provenance icons (✓ only for real official verification), conditional provisions accordion, alerts with evidence, Payment Protection calculator, MAITRI catalogue, dynamic Smart Action Guide, law-version table.

## Government data upgrade (phase 4)

Improves the existing provider layer in place — one adapter architecture, one honest connection vocabulary, zero fabricated data:

- **Shared data.gov.in path** (`data_gov_dataset_call`): one error taxonomy (401/403/404/429/5xx/timeout/network/invalid), pagination, response validation, provenance metadata (`dataset`, `resource_id`, `source_url`, `retrieved_at`, `last_updated`, `total_available`) and a **short-TTL cache of public responses only** (never credentials/private payloads; `cached` flag shown in payloads).
- **UDYAM** — still a DATASET SEARCH (`GOVERNMENT_DATASET_MATCH`), never "UDYAM verification"; state filtering, pagination, cache, match warnings.
- **MCA** — authorized-API architecture preserved (OAuth2, pending); new public **MCA Company Master Data** (RoC-wise) dataset branch labelled `MCA Company Master Data — NOT a live MCA verification`.
- **Pincode** — live authoritative lookup via data.gov.in with structured post-office parsing (office/district/state/circle/region/division) + honest not-found; offline circle index remains `REQUIRES_VERIFICATION`.
- **CPCB air** — real-time air quality via data.gov.in, served as **ENVIRONMENTAL_CONTEXT / REGULATORY FACTOR**; never an approval determination (rule engine decides from project facts).
- **CPCB surface water** (new) — **HISTORICAL / SUPPORTING DATA**; pH/BOD/COD/DO/TDS/turbidity/nitrate/phosphate context only, never shown as current quality.
- **ASI** (new) — **INDUSTRIAL STATISTICAL DATA**; benchmarking/analytics context only, never a company-level approval determination.
- **Connection states** — one shared resolver for both integration surfaces: `CONNECTED / CONFIGURED / CONFIGURED_BUT_OUTBOUND_DISABLED / PENDING_AUTHORIZATION / OFFICIAL_REDIRECT / MANUAL / DEMO` (+ `FAILED` flag). A green CONNECTED badge appears only after a real successful authorized call.
- **State routing (§31/§32)** — MH → **MAITRI** (primary), TN → TN single window; national layer unchanged. MAITRI service intelligence links identified approvals to the (generic, `REQUIRES_VERIFICATION`) single-window route; TAT shown only where officially documented.
- **Rule engine contract** — every result now carries `rule_id`, canonical `result` (`APPLIES / CONDITIONAL / NOT_APPLICABLE / INFORMATION_REQUIRED / REQUIRES_VERIFICATION`), `matched_facts`, `missing_facts`, `explanation`. Missing facts NEVER degrade to `NOT_APPLICABLE`.
- **Approval graph** — nodes carry `verification_status`, `requires_verification`, `information_required`, `official_channel`, `legal_basis`, `facts_used`, `missing_facts`; the graph marks ⚠ verify / ℹ info-needed.
- **Smart Action Guide** — each step carries `action`, `reason`, `blocked_by`, `required_documents`, `official_channel`, `source`, `verification_status` (dashboard card renamed accordingly).
- **Digital twin enrichment** — `GET /projects/{pid}/gov/enrichment` returns 9 provenance blocks (BUSINESS/COMPANY/MSME/LOCATION/ENVIRONMENT/INDUSTRY/APPROVALS/DOCUMENTS/COMPLIANCE); GovDataEnrichment now covers MCA + environment/industry context (with explicit save-to-twin) and renders the blocks.
- New endpoints: `GET /gov/data-status`, `POST /gov/cpcb/air-quality`, `POST /gov/cpcb/surface-water`, `POST /gov/asi/industry-stats`, `GET /gov/state-integration`, `GET /projects/{pid}/gov/enrichment`. Registry now **11 providers**.
- Tests: **125** (33 new gov-data honesty/integration tests incl. mocked live responses, the full HTTP error taxonomy, outbound-disabled honesty, demo separation, context labels, routing, registry consistency).

## MVP architecture convergence (phase 5)

The existing modules were evolved end-to-end toward the final MVP chain: Project Twin → Regulatory Intelligence Core → deterministic Rule Engine → Approval/Service Plan → Dependency + Document + **Decision Trail** → Readiness → Scheme Matching → **Application Package** → **MAITRI Handoff** → **Lifecycle** → **Query + SLA** → **Bottleneck** → Compliance/Inspection → **Alert / Smart Action Guide**. Nothing was rebuilt; everything below reuses existing models/engines.

- **Project Twin (§C)** — `GET /projects/{pid}/gov/enrichment` is the central, provenance-labelled fact source: a PROJECT block (company ids, sector, location, investment, employment, land, capacity, power, water, wastewater, hazardous waste, chemicals, boiler/DG) + 9 enrichment blocks, every fact carrying `source / source_type / verification_state`.
- **Decision Trail (§G)** — new `decision_trail` table (migration `b0005`): every discovery run records one immutable row per evaluated approval rule — rule key + expression, canonical result, triggering facts, missing facts, explanation, legal basis, source URL/status, rule version, engine version, timestamp. `GET /projects/{pid}/decision-trail` answers WHY / WHAT EVIDENCE / WHICH RULE / WHAT IS MISSING. The LLM may explain these rows; it never produces them.
- **Application Package (§M)** — `GET /projects/{pid}/application-package` is generated from actual DB state: twin facts, applicable approvals (APPLICABLE → CONDITIONAL ordered) with checklists/prerequisites/official sources, documents + unresolved validation findings (mismatch expected/found included), missing items, dependency edges, readiness ("submission readiness — never a probability of approval"), open queries, official submission links + REAL/MANUAL/NOT-CLAIMED boundary labels.
- **MAITRI Handoff (§N)** — `POST /projects/{pid}/maitri-handoff`: MH projects get `MANUAL_HANDOFF` (package summary + review checklist + official portal deep link); non-MH projects get an honest `PENDING_AUTHORIZATION` + portal directory pointer. Audited. No submission, officer response, submission ID or approval status is ever claimed.
- **SLA engine (§Q)** — `GET /projects/{pid}/sla`: per-application authority-elapsed vs applicant-paused time from real submission + query records. Statuses ON_TRACK / APPROACHING / BREACHED / PAUSED / COMPLETED / RUNNING_UNCONFIGURED. Base timelines are labelled **CONFIGURED** (or DEMO) — never VERIFIED.
- **Bottleneck engine (§R)** — `GET /projects/{pid}/bottlenecks`: causal, project-specific blockers from approval states + dependency graph + queries + SLA + missing documents, with downstream impact closure and project impact. Explicitly **no AI risk score**.
- **Lifecycle (§O)** — every application payload now carries a state-driven `lifecycle` (DRAFT/READY/SUBMITTED/UNDER_SCRUTINY/QUERY_RAISED/APPLICANT_RESPONSE_REQUIRED/APPLICANT_RESPONDED/APPROVED/REJECTED/CLOSED + SLA status) derived from the stored status, open queries and SLA — demo journeys labelled **SIMULATED**.
- **Department operations view (§V screen 5)** — `GET /ops/department-queue` (admin/reviewer only): read-only cross-project queue with per-application SLA status, open queries and bottleneck counts, explicitly labelled **PROTOTYPE / SIMULATED / READ-ONLY**.
- **Alert / Smart Action Guide (§T)** — now also generates bottleneck-unblock actions (HIGH severity with downstream impact) and SLA breach/approaching actions, on top of the existing query/renewal/document/profile sources.
- **Adapter hardening (§AC/§D)** — 408 → TIMEOUT added to the error taxonomy; UDYAM search uses the documented fields (EnterpriseName/State/District/Pincode/Activities) with deterministic **strong-match candidate scoring**; MCA supports CIN-shaped searches and CompanyStateCode filtering with the same scoring; pincode live parsing includes latitude/longitude.
- **Second-project requirement (§AE)** — `tests/test_mvp.py` proves a TN textile micro-unit and an MH chemicals plant produce different approvals (7+ differing applicabilities; 9 vs 14 APPLIES), classifications, MAITRI relevance, packages, decision trails and bottlenecks.
- Verification: **143/143** pytest (18 new MVP tests), **64/64** govdata live (10 new), **41/41** upgrade live; migration `b0005_decision_trail` applied; `production_blockers: []`.

## Government execution layer (integration upgrade)

NIECP-AI is a regulatory-intelligence + execution-readiness layer, **not** a government portal and **not** a government API wrapper. Execution always happens through one of three honest channels, coordinated by the Government Integration Manager (`backend/app/services/gov_manager.py`):

| Channel | What happens | Where |
|---|---|---|
| `OFFICIAL_REDIRECT` | NIECP prepares everything, then opens the **stored, verified** official portal URL. You file there; nothing is transmitted by NIECP. | `POST /applications/{id}/redirect` |
| `MANUAL` | Copy/download packet, then record the reference, dates and statuses yourself — every entry stored as `USER_ENTERED` behind confirmation gates. | `GET /applications/{id}/manual-packet` |
| `DEMO` | **Internal demonstration only** — synthetic data, synthetic IDs (`NIECP-DEMO-2026-0001`), simulated review → query → response → approval → renewal. Never a government system. | `POST /demo/government/applications` |

`AUTHORIZED_API` (NSWS / TN Single Window / API Setu) is architecturally supported via the Government Integration Registry but ships as `PENDING`/`NOT_AUTHORIZED` with `live=false` — it activates only with formal provider authorization, without rewriting NIECP.

Every demo payload carries: `environment=DEMO · data_source=SYNTHETIC · government_api=NOT_CONNECTED · authorization_status=NOT_AUTHORIZED · live=false`. Demo endpoints are hard-disabled in production deployments (`NIECP_DEMO_ALLOW_IN_PRODUCTION=0` default).



## Government data services (provider integration layer)

Backend-only provider adapters (`backend/app/services/gov_providers.py`) behind the Government Integration Manager — all external calls flow `endpoint → gov_manager.dispatch → adapter`, never from the frontend:

| Adapter | Purpose | Status in this deployment |
|---|---|---|
| `DataGovUdyamAdapter` | UDYAM/MSME **dataset** search via data.gov.in (`GOVERNMENT_DATASET_MATCH` — explicitly **not** a verification API) | `PENDING_AUTHORIZATION` until `NIECP_DATA_GOV_API_KEY` + dataset resource id are provisioned; demo-labelled synthetic search meanwhile |
| `MCAAdapter` | Company/LLP identity, CIN-related info (`MCA_DATA_MATCH` only from an authorized API) | `PENDING_AUTHORIZATION` — official portal + manual CIN entry |
| `PincodeAdapter` | PIN → state/district/post-office (India Post dataset via data.gov.in) | Coarse offline postal-circle index now (always `REQUIRES_VERIFICATION`, districts never guessed); authoritative once the key is provisioned |
| `DigiLockerAdapter` | Requester flow: authorize → consent → retrieve → classify → store (document `GOVERNMENT_RETRIEVED` origin) | `PENDING_AUTHORIZATION` — consent ledger live, retrieval redirects to DigiLocker |
| `NSWSAdapter` / `TamilNaduAdapter` | Execution single-windows | `OFFICIAL_REDIRECT` / `PENDING_AUTHORIZATION` |
| `DemoGovernmentAdapter` | Internal synthetic demo (SIH) | Labelled `DEMO DATA — NOT A LIVE GOVERNMENT CONNECTION` |

Every adapter carries: provider, service, endpoint, method, authentication method, authorization status, environment, supported operations, timeout, retry policy (never on 4xx), schema validation, mapped errors with user-friendly messages, audit logging with correlation ids, and fallback mode. Secrets (`NIECP_DATA_GOV_API_KEY`, `NIECP_MCA_*`, `NIECP_NSWS_*`, `NIECP_DIGILOCKER_*`) live server-side only — payloads carry boolean "configured" flags, never values.

Consent management (§7): `POST /gov/consent` records explicit, revocable consent (provider, service, purpose, data categories, documents, project, timestamp) before any government data exchange; `POST /gov/consent/{id}/revoke` stops future access. User-selected dataset matches are stored as `GovDataReference` rows and enrich the regulatory digital twin (state/district/NIC activity) — the deterministic rule engine still decides applicability.

New surfaces: `GET /gov/services` (§21 cards + test-connection), `POST /gov/udyaam/search|select`, `POST /gov/mca/search`, `POST /gov/pincode-lookup`, `POST /gov/digilocker/request-document`, `GET /projects/{id}/command-center` (§20: readiness, approvals identified, documents ready x/y, critical blockers, integrations active/pending, next best action), `GET /projects/{id}/gov-references`. UI: **Settings → Government integrations** page, Profile → **Gov data** tab, and the Dashboard command-center strip.

Other upgrade surfaces: Query Translator (`POST /projects/{id}/queries/{qid}/translate` — plain-language explanation, what's missing, what's needed, recommended action, response draft outline, always labelled "AI-generated explanation"), audit correlation IDs (`correlation_id`, `integration_mode`, `provider` on every execution event), the spec-shaped `POST /ai/assistant` envelope, and the cinematic voice assistant (`VoiceHUD.tsx` — real microphone amplitude visualisation via Web Audio AnalyserNode, TTS speech-event envelope, full mic/AudioContext cleanup on close, type-instead fallback).
