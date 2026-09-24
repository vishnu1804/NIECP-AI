# NIECP-AI Upgrade Audit (Phase 1 — AUDIT before EXTEND)

Date: 2026-09-22 · Method: full read of routers/services/models/components against the
Master Upgrade Prompt. Verdict: **the existing application already implements the large
majority of the required systems. The upgrade is additive: no database deletion, no auth
replacement, no engine replacement, no page duplication.**

## 1. Inventory (what exists today)

| Layer | Assets |
|---|---|
| Backend | FastAPI + SQLAlchemy, 10 routers ≈ 90 endpoints, 40+ ORM entities, Alembic baseline, 50 passing tests |
| Auth | JWT + rotating refresh, org isolation, RBAC (OrgRole/PlatformRole), audit-logged |
| Regulatory engine | Deterministic rule engine (sandboxed parser, Kleene 3-valued logic), 46 approval rules, 19 industries — LLM never overrides it |
| Approval engine | Analysis (APPLIES/CONDITIONAL/NOT_APPLICABLE/UNKNOWN), dependency graph (46 nodes/42 edges/7 layers), critical path |
| Documents | Upload, versioning, AI classification/extraction/pre-validation with honest NO_TEXT/low-confidence paths |
| Readiness | 5-component explainable readiness (profile/documents/eligibility/prerequisites/applications) — declared "not a probability of approval" |
| Next Best Action | `next_action.next_best_actions()` computed from real project state |
| Applications | DRAFT→READY_TO_APPLY→…→APPROVED workflow, prepare/confirm gates, self-reported status gate, official-reference gate, renewal auto-creation |
| Queries | GovernmentQuery entity with deterministic decomposition (`ai_explanation`, `ai_suggested_steps`) |
| Integrations | `gov_integrations.py` manager: 6 providers, honest statuses (CONNECTED only after a successful real call), health probes, IntegrationLog, "official portal" fallbacks |
| Portals | 49-entry GovernmentPortal registry with verification status + last-verified timestamps |
| Assistant | Intent router → 16 tools, RAG with confidence floor, sensitive-action CONFIRM/CANCEL gates, voice session logging |
| Voice | VoiceHUD: Web Speech STT, **real** Web Audio AnalyserNode mic metering, TTS, state machine incl. error states, mic cleanup, confirmation gates |
| Frontend | 23 pages, floating AI button already present, PWA + offline queue, i18n en/ta/hi |
| Demo | Labelled demo org/project [DEMO], is_demo discipline, seeded readiness 28% |

## 2. Reuse as-is (no changes)

Auth/RBAC · rule engine · approval engine · dependency graph/critical path · document
pipeline · readiness · next best action · notifications · renewals · PWA · i18n · audit
retention · existing 6-provider integration manager (extended, not replaced).

## 3. Extend (exists but needs upgrade)

| System | Gap |
|---|---|
| Integration manager | No formal `IntegrationMode` (LIVE/UAT/SANDBOX/OFFICIAL_REDIRECT/MANUAL/DEMO/…) or `AuthorizationStatus` vocabulary; no demo channel |
| Applications | No `integration_mode`/`correlation_id`/`provider` columns; no execution-options decision endpoint (§24); no official-redirect packet endpoint; no manual download packet |
| Queries | Decomposition exists but not the full translator shape (original → plain language → what's missing → what's needed → recommended action → response preparation + AI disclaimer) |
| Audit | No `correlation_id` / `integration_mode` / `provider` columns; actions like `DEMO_SUBMITTED`, `OFFICIAL_REDIRECT_OPENED`, `VOICE_COMMAND_EXECUTED` not yet recorded |
| Voice UI | Functional but visually basic; no cinematic voice-reactive core, no activation sound, no mute, no type-input fallback panel, TTS envelope not wired, no action chips |
| Government page | Portal list exists; no registry cards (NSWS / TN SWS / API Setu / NIECP Demo) with authorization + environment + capabilities |

## 4. Missing (to build — all additive)

1. `IntegrationMode`, `AuthorizationStatus` enums + `USER_CONFIRMED`/`USER_RESPONDED` application states.
2. **DemoGovernmentAdapter** + demo status engine (synthetic ID `NIECP-DEMO-YYYY-NNNN`, dwell-based progression SUBMITTED→UNDER_REVIEW→QUERY_RAISED→(user)→USER_RESPONDED→UNDER_REVIEW→APPROVED, synthetic queries/conditions all labelled, renewal hook).
3. `/demo/government/*` endpoints (applications POST/GET/status/queries/response, documents/{id}, approvals GET, advance control) — internal, clearly non-government, disabled in production deployments.
4. **OfficialRedirectAdapter** — redirect packet from stored verified portal URLs only; audit `OFFICIAL_REDIRECT_OPENED`.
5. **ManualApplicationAdapter** — copy/download packet endpoint; recording already exists via PATCH + status gates (reused).
6. **GovernmentIntegrationRegistry** table + seed (NSWS, TN SWS, API Setu as `PENDING_AUTHORIZATION`, NIECP Demo as `DEMO` — all `live:false`) + `/integration-registry` endpoint.
7. **Query Translator** service + endpoint with the full §21 shape and "AI-generated explanation" disclaimer.
8. Audit columns + new action types incl. `correlation_id` propagation.
9. `POST /ai/assistant` spec-shaped alias over the existing assistant (adds `actions` chips).
10. Frontend: cinematic `<VoiceReactiveCore>` canvas (real mic amplitude; TTS boundary envelope), activation sound, mic/stop/mute/close controls, type-input fallback, action chips, integration columns on Applications, registry cards on Government page, translator panel on Queries.

## 5. Duplicates / broken

None found. (VoiceHUD is the single assistant surface; Layout already mounts one floating
button — both will be upgraded in place, not duplicated.)

## 6. Non-negotiables preserved during upgrade

- DEMO is never presented as LIVE; every demo payload carries `environment=DEMO`,
  `data_source=SYNTHETIC`, `government_api=NOT_CONNECTED`, `authorization_status=NOT_AUTHORIZED`, `live=false`.
- No fabricated government URLs/APIs/IDs/statuses; portal URLs only from the stored registry.
- No government-facing action without explicit confirmation; audit trail for every step.
- Rule engine stays the sole source of applicability truth; LLM explains only.

## 7. Implementation status (per prompt §59) — COMPLETE

| Phase | Scope | Status |
|---|---|---|
| 1 | Audit | ✅ this document |
| 2 | Government Integration Manager | ✅ `services/gov_manager.py` + existing `gov_integrations.py` (extended) |
| 3 | DemoGovernmentAdapter | ✅ `services/demo_government.py`, `POST /demo/government/applications` |
| 4 | OfficialRedirectAdapter | ✅ `gov_manager.official_redirect`, `POST …/redirect` |
| 5 | ManualApplicationAdapter | ✅ `gov_manager.manual_packet`, `GET …/manual-packet` (+ existing manual gates reused) |
| 6–10 | Connect approval engine, documents, critical path, roadmap, applications | ✅ execution-options endpoint + integration_mode propagation + renewal/compliance hooks |
| 11 | Query Translator | ✅ `services/query_translator.py`, `POST …/queries/{qid}/translate` |
| 12 | Government registry | ✅ `GovernmentIntegrationRegistry` + `GET /integration-registry` |
| 13 | Audit logs | ✅ correlation_id / integration_mode / provider + DEMO_SUBMITTED, OFFICIAL_REDIRECT_OPENED, QUERY_RECORDED, QUERY_RESPONSE_SUBMITTED, MANUAL_PACKET_GENERATED, VOICE_COMMAND events |
| 14 | Global ASK NIECP voice assistant | ✅ upgraded VoiceHUD, floating labelled orb button |
| 15 | Project-aware voice AI | ✅ existing intent-router tools + action affordances (§56 chips) |
| 16 | Real microphone visualisation | ✅ Web Audio AnalyserNode → amplitude + time-domain waveform ring |
| 17 | TTS voice-reactive visualisation | ✅ speech-event envelope (browser TTS exposes no stream; hook documented for stream-TTS providers) |
| 18 | Accessibility + mobile | ✅ keyboard (Esc/Enter), aria roles, visible status, type-instead fallback, responsive core |
| 19 | Security hardening | ✅ production demo gate, no secrets in frontend, confirmation gates preserved, sanitized transcripts |
| 20 | End-to-end testing | ✅ 63 pytest + 41 live checks (`backend/scripts/verify_upgrade_live.py`) |

Verification: `cd backend && python -m pytest tests/ -q` → 63 passed ·
`python backend/scripts/verify_upgrade_live.py` → 41 passed · `npx vite build` → ok.


## Phase 3 audit — MSME Regulatory Intelligence (2026-09-23)

- Knowledge layer versioned (3 §7 versions with amendment/effective/status); superseded kept; standing freshness warning surfaced everywhere.
- Classification refuses to classify without inputs; registration check is USER-PROVIDED/RECOMMENDED only — no 'verified UDYAM' claim anywhere in the MSME path.
- All 15 MSMED provisions conditional; §22 gated on buyer flag; §§15-18 gated on supplier class; §24/§27 informational.
- Payment assessment: honest date math, placeholder rate disclosed, NOT LEGAL ADVICE framing, non-MSE out-of-scope honesty.
- MAITRI: OFFICIAL_REDIRECT only, MH-gated, no automated submission, official portal links only.
- CPCB adapter: PENDING_AUTHORIZATION stub — no fabricated calls.
- Registry synced: 9 providers; secrets still backend-only; audit events written for MSME views/assessments.
- Verification: 92/92 pytest (16 new MSME tests), 39/39 verify_govdata_live (13 new), 41/41 verify_upgrade_live, b0004 applied (annual_turnover, buys_from_msme_suppliers), production_blockers [].


## Phase 4 audit — Government data upgrade (2026-09-23)

- No new provider architecture: existing adapters extended; 2 new adapters (surface water, ASI) reuse the same base/meta/dispatch path. Registry 11 providers.
- Single connection-state resolver shared by gov_manager.service_cards and gov_integrations — statuses cannot contradict; CONNECTED only after a real successful authorized call; CONFIGURED_BUT_OUTBOUND_DISABLED surfaced (previously 'AUTHORIZED' credentials could read as CONNECTED — fixed).
- Provider calls now keyed by provider CODE in IntegrationLog (fixes last-success lookup mismatch).
- Dataset responses carry full provenance + TTL cache (public data only); API keys never in payloads (test asserts).
- Environment/industry data explicitly labelled ENVIRONMENTAL_CONTEXT / HISTORICAL_SUPPORTING_DATA / INDUSTRIAL_STATISTICAL_DATA with usage_rule; endpoints never create approval requirements; rule engine remains sole authority.
- Rule results: canonical result states; missing facts → INFORMATION_REQUIRED (never NOT_APPLICABLE); broken rules → REQUIRES_VERIFICATION.
- MAITRI: MH primary routing; approval links are authored/generic (ROUTED_VIA_SINGLE_WINDOW_FACILITATION), all REQUIRES_VERIFICATION; TAT never invented.
- No DB migration required: provenance stored in existing GovDataReference JSON columns (match_payload/enrichment).
- Verification: 125/125 pytest (33 new), 54/54 verify_govdata_live (15 new), 41/41 verify_upgrade_live; production_blockers []


## Phase 5 audit — MVP architecture convergence (2026-09-23)

- REUSE-first: no duplicate engines — decision trail is a new table (b0005) but package/SLA/bottleneck/lifecycle are state-driven computations over existing models (Application, GovernmentQuery, ProjectApproval, DocumentValidation, readiness snapshot).
- Decision trail rows are written inside run_discovery only (single writer); immutable; carry rule expression + canonical result + facts + engine version. LLM is explanation-only (architecture §AI preserved).
- MAITRI handoff: MANUAL_HANDOFF for MH only; audited; review checklist; no submission claims. Non-MH → PENDING_AUTHORIZATION + portal directory.
- SLA base days labelled CONFIGURED/DEMO, never VERIFIED; pause semantics from real open-query records; breach never converted into success.
- Bottlenecks: purely causal (state+graph+queries+SLA+docs); no risk score; downstream impact via dependents closure over active approvals only.
- Department view admin/reviewer-gated; PROTOTYPE / SIMULATED / READ-ONLY labels on the view itself and simulated rows.
- 408 mapped to TIMEOUT in the shared dataset path; documented UDYAM/MCA field filters + deterministic candidate scoring (ranking aid only, never verification).
- AE satisfied: two-project test proves different approvals/classification/MAITRI/packages/trails/bottlenecks.
- Verification: 143/143 pytest, 64/64 govdata live, 41/41 upgrade live, b0005 applied, production_blockers [].
