"""Government data provider adapters (integration upgrade §1–§6, §16–§18).

Every adapter carries the full metadata contract: provider, service, endpoint,
HTTP method, authentication method, authorization status, environment,
supported operations, timeout, retry policy, response validation, error
mapping, audit logging hook, last-verified timestamp and fallback mode.

TRUTH PROTOCOL (unchanged, hardened)
------------------------------------
* A provider is LIVE only after a real, successful authenticated response has
  been received and recorded. Nothing is ever represented as connected before
  that (§19 of the previous upgrade, §4 here).
* Dataset lookups are labelled GOVERNMENT_DATASET_MATCH — a dataset is NOT a
  verification API (§3).
* When credentials/authorization are missing the adapter reports
  PENDING_AUTHORIZATION and offers the official portal / manual fallback.
* The DemoGovernmentAdapter produces clearly synthetic data only.

All credentials come from server-side settings (config.py) and are never
serialized to any API payload (§2).
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import httpx

from ..config import settings
from ..enums import IntegrationMode, SourceStatus

# ═══════════════════════════════════════════════════ error taxonomy (§17) ══


class AdapterErrorCode:
    AUTH_REQUIRED = "AUTH_REQUIRED"                      # 401
    AUTHORIZATION_UNAVAILABLE = "AUTHORIZATION_UNAVAILABLE"  # 403
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"        # 404
    RATE_LIMITED = "RATE_LIMITED"                        # 429
    PROVIDER_ERROR = "PROVIDER_ERROR"                    # 5xx
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    NOT_PROVISIONED = "NOT_PROVISIONED"                  # no credentials configured
    DISABLED = "DISABLED"                                # outbound calls disabled by deployment


_USER_MESSAGES: dict[str, str] = {
    AdapterErrorCode.AUTH_REQUIRED: "Government service authentication is required. Please continue through the official portal.",
    AdapterErrorCode.AUTHORIZATION_UNAVAILABLE: "Authorization is pending with the government provider. Please continue through the official portal.",
    AdapterErrorCode.RESOURCE_UNAVAILABLE: "The requested government record could not be found.",
    AdapterErrorCode.RATE_LIMITED: "The government service is rate-limiting requests. Please try again in a few minutes.",
    AdapterErrorCode.PROVIDER_ERROR: "Government service is temporarily unavailable. Your data is safe — please retry shortly or continue through the official portal.",
    AdapterErrorCode.TIMEOUT: "The government service did not respond in time. Please retry — or continue through the official portal.",
    AdapterErrorCode.NETWORK: "The government service could not be reached. Please continue through the official portal.",
    AdapterErrorCode.INVALID_RESPONSE: "The government service returned an unexpected response. Nothing was stored.",
    AdapterErrorCode.NOT_PROVISIONED: "This integration is awaiting official partner authorization. You can continue through the official portal.",
    AdapterErrorCode.DISABLED: "Outbound government API calls are disabled in this deployment. Please continue through the official portal.",
}


def user_message(code: str | None) -> str:
    return _USER_MESSAGES.get(code or "", "Government service is temporarily unavailable.")


# ═══════════════ data.gov.in shared dataset path + cache (§2, §28) ══

# Context labels for public-data operations. These describe how a result MAY be
# used — they never create a legal requirement by themselves.
ENVIRONMENTAL_CONTEXT = "ENVIRONMENTAL_CONTEXT"
HISTORICAL_SUPPORTING_DATA = "HISTORICAL_SUPPORTING_DATA"
INDUSTRIAL_STATISTICAL_DATA = "INDUSTRIAL_STATISTICAL_DATA"

_DATASET_CACHE: dict[str, tuple[float, dict]] = {}


def _dataset_cache_get(key: str) -> dict | None:
    ttl = max(0, int(getattr(settings, "data_gov_cache_ttl_seconds", 300)))
    hit = _DATASET_CACHE.get(key)
    if hit and ttl and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _dataset_cache_put(key: str, value: dict) -> None:
    # Public dataset responses only, small bounded cache; never credentials,
    # tokens or user-supplied/private payloads.
    _DATASET_CACHE[key] = (time.time(), value)
    if len(_DATASET_CACHE) > 256:
        _DATASET_CACHE.pop(next(iter(_DATASET_CACHE)))


def _tokens(value: Any) -> set[str]:
    import re as _re
    return {w for w in _re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(w) > 1}


def _match_score(query: str, record: dict, name_fields: list[str], extra_checks: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Deterministic candidate scoring (0-100) for dataset matches. Name token
    overlap + exact auxiliary matches (state/district/pincode). Never a
    verification — only a ranking aid for the user's confirmation."""
    q_tokens = _tokens(query)
    name = " ".join(str(_record_pick(record, *name_fields) or "") for _ in [0])
    r_tokens = _tokens(name)
    overlap = q_tokens & r_tokens if q_tokens and r_tokens else set()
    score = int(60 * len(overlap) / max(1, len(q_tokens))) + int(25 * len(overlap) / max(1, len(r_tokens))) if (q_tokens and r_tokens) else 0
    matched_on = [f"name~{sorted(overlap)[:3]}"] if overlap else []
    for rec_field, value in (extra_checks or []):
        if value and str(_record_pick(record, rec_field) or "").strip().lower() == str(value).strip().lower():
            score += 15
            matched_on.append(rec_field)
    return {"score": min(100, score), "strong_match": score >= 70, "matched_on": matched_on}


def _record_pick(record: dict, *names: str) -> Any:
    """Case-insensitive, whitespace-tolerant field pick for dataset records
    whose column names vary between resources."""
    lowered = {str(k).strip().lower(): v for k, v in (record or {}).items()}
    for n in names:
        key = str(n).strip().lower()
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return None


def data_gov_dataset_call(
    adapter: "BaseProviderAdapter",
    *,
    operation: str,
    resource_id: str,
    filters: dict[str, str] | None = None,
    limit: int = 10,
    offset: int = 0,
    dataset_name: str | None = None,
    context_label: str | None = None,
    result_note: str = "",
) -> AdapterResult:
    """THE shared data.gov.in dataset access path.

    One honest error taxonomy (401/403/404/429/5xx/timeout/network/invalid),
    pagination, response validation, provenance metadata and a short-TTL cache
    of PUBLIC responses. A successful call proves a GOVERNMENT_DATASET_MATCH
    retrieved from a VERIFIED_GOV_SOURCE — it is NEVER a verification of the
    user, their registration or their documents, and environmental/industrial
    context never by itself creates an approval requirement.
    """
    corr = "COR-" + uuid.uuid4().hex[:12]
    base = dict(provider=adapter.meta.provider, service=adapter.meta.service,
                operation=operation, correlation_id=corr, provider_code=adapter.meta.code)
    if not (settings.data_gov_api_key and resource_id):
        return AdapterResult(ok=False, mode=IntegrationMode.PENDING_AUTHORIZATION.value,
                             error_code=AdapterErrorCode.NOT_PROVISIONED, **base,
                             fallback_hint={"mode": adapter.meta.fallback_mode,
                                            "official_portal_url": adapter.meta.official_portal_url})
    if not settings.enable_outbound_gov_calls:
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value,
                             error_code=AdapterErrorCode.DISABLED, **base,
                             user_message=("Credentials are configured, but outbound government API calls are disabled in this "
                                           "deployment (CONFIGURED_BUT_OUTBOUND_DISABLED). Continue through the official portal."),
                             fallback_hint={"mode": adapter.meta.fallback_mode,
                                            "official_portal_url": adapter.meta.official_portal_url})
    cache_key = "|".join([resource_id, operation, str(limit), str(offset), str(sorted((filters or {}).items()))])
    cached = _dataset_cache_get(cache_key)
    if cached is not None:
        return AdapterResult(ok=True, mode=IntegrationMode.LIVE.value, http_status=cached.get("_http_status", 200),
                             data=cached["data"], verification_status="GOVERNMENT_DATASET_MATCH",
                             source_status=SourceStatus.VERIFIED_GOV_SOURCE.value,
                             meta={**cached["meta"], "cached": True,
                                   "cache_note": "Served from NIECP's short-TTL cache of the public dataset response."}, **base)
    started = time.monotonic()
    params: dict[str, Any] = {"api-key": settings.data_gov_api_key, "format": "json", "limit": limit, "offset": offset}
    for k, v in (filters or {}).items():
        if v not in (None, ""):
            params[f"filters[{k}]"] = v
    resp, _st, err = adapter._http("GET", f"{settings.data_gov_base_url}/{resource_id}", params=params)
    latency = int((time.monotonic() - started) * 1000)
    if err or resp is None:
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, latency_ms=latency, error_code=err, **base)
    if resp.status_code in (401, 403):
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency,
                             error_code=AdapterErrorCode.AUTH_REQUIRED if resp.status_code == 401 else AdapterErrorCode.AUTHORIZATION_UNAVAILABLE, **base)
    if resp.status_code == 404:
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=404, latency_ms=latency,
                             error_code=AdapterErrorCode.RESOURCE_UNAVAILABLE, **base)
    if resp.status_code == 408:
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=408, latency_ms=latency,
                             error_code=AdapterErrorCode.TIMEOUT, **base)
    if resp.status_code == 429:
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=429, latency_ms=latency,
                             error_code=AdapterErrorCode.RATE_LIMITED, **base)
    if resp.status_code >= 500:
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency,
                             error_code=AdapterErrorCode.PROVIDER_ERROR, **base)
    try:
        payload = resp.json()
    except Exception:
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency,
                             error_code=AdapterErrorCode.INVALID_RESPONSE, **base)
    if not isinstance(payload, dict) or not (("records" in payload) or ("items" in payload)):
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency,
                             error_code=AdapterErrorCode.INVALID_RESPONSE, **base)
    records = payload.get("records") or payload.get("items") or []
    if not isinstance(records, list):
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency,
                             error_code=AdapterErrorCode.INVALID_RESPONSE, **base)
    meta: dict[str, Any] = {
        "dataset": dataset_name or adapter.meta.service,
        "resource_id": resource_id,
        "source_url": f"{settings.data_gov_base_url}/{resource_id}",
        "catalogue": "https://data.gov.in/",
        "retrieved_at": datetime.utcnow().isoformat(),
        "last_updated": payload.get("updated_date") or payload.get("last_updated") or None,
        "total_available": payload.get("total") if isinstance(payload.get("total"), int) else len(records),
        "cached": False,
    }
    if context_label:
        meta["context_label"] = context_label
    if result_note:
        meta["note"] = result_note
    data: dict[str, Any] = {"records": records[:limit], "count": len(records[:limit])}
    if filters:
        data["filters_applied"] = {k: v for k, v in filters.items() if v}
    if records:
        _dataset_cache_put(cache_key, {"data": data, "meta": meta, "_http_status": resp.status_code})
    return AdapterResult(ok=True, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency,
                         data=data, verification_status="GOVERNMENT_DATASET_MATCH",
                         source_status=SourceStatus.VERIFIED_GOV_SOURCE.value, meta=meta, **base)


@dataclass
class AdapterResult:
    """Normalised result every adapter returns. `mode` is always one of the
    IntegrationMode values so the UI can label honestly."""
    ok: bool
    provider: str
    service: str
    operation: str
    mode: str                                   # IntegrationMode value
    provider_code: str = ""                     # registry code (udyam_dataset, pincode, …)
    data: dict[str, Any] = field(default_factory=dict)
    verification_status: str = "NOT_VERIFIED"   # GOVERNMENT_DATASET_MATCH / NOT_VERIFIED / REQUIRES_VERIFICATION / DEMO
    source_status: str = SourceStatus.REQUIRES_VERIFICATION.value
    error_code: str | None = None
    http_status: int | None = None
    latency_ms: int | None = None
    correlation_id: str = ""
    user_message: str = ""
    fallback_hint: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "provider_code": self.provider_code or None,
            "service": self.service,
            "operation": self.operation,
            "mode": self.mode,
            "data": self.data,
            "verification_status": self.verification_status,
            "source_status": self.source_status,
            "error_code": self.error_code,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "correlation_id": self.correlation_id,
            "message": self.user_message or (None if self.ok else user_message(self.error_code)),
            "fallback": self.fallback_hint,
            "meta": self.meta,
        }


# ═══════════════════════════════════════════════════ adapter metadata (§1) ══

@dataclass
class ProviderMeta:
    code: str
    provider: str
    service: str
    endpoint: str | None
    http_method: str = "GET"
    authentication_method: str = "None (public dataset)"
    authorization_status: str = "NOT_AUTHORIZED"
    environment: str = "OFFICIAL_REDIRECT"
    modes: list[str] = field(default_factory=list)
    supported_operations: list[str] = field(default_factory=list)
    timeout_seconds: int = 12
    max_retries: int = 1
    fallback_mode: str = IntegrationMode.OFFICIAL_REDIRECT.value
    official_portal_url: str | None = None
    documentation_url: str | None = None
    data_categories: list[str] = field(default_factory=list)
    consent_required: bool = False
    notes: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "provider": self.provider,
            "service": self.service,
            "endpoint_host": (self.endpoint.split("/")[2] if self.endpoint and self.endpoint.startswith("http") else self.endpoint),
            "http_method": self.http_method,
            "authentication_method": self.authentication_method,
            "authorization_status": self.authorization_status,
            "environment": self.environment,
            "modes": self.modes,
            "supported_operations": self.supported_operations,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "fallback_mode": self.fallback_mode,
            "official_portal_url": self.official_portal_url,
            "documentation_url": self.documentation_url,
            "data_categories": self.data_categories,
            "consent_required": self.consent_required,
            "notes": self.notes,
        }


# ═════════════════════════════════════════════════════ base adapter ══

class BaseProviderAdapter:
    meta: ProviderMeta

    def configured(self) -> bool:
        return True

    def credentials_present(self) -> dict[str, bool]:
        """Which server-side credentials exist — booleans only, never values."""
        return {}

    # -- HTTP with timeout + retry policy (§1, §17, §19) --
    def _http(self, method: str, url: str, *, params: dict | None = None,
              headers: dict | None = None) -> tuple[Any, int | None, str | None]:
        """Returns (response|None, http_status|None, error_code|None).
        Retries ONLY on timeout/network errors, never on 4xx (§17).
        Honours the deployment-wide outbound-call kill-switch."""
        if settings.enable_outbound_gov_calls is False:
            return None, None, AdapterErrorCode.DISABLED
        attempts = 1 + max(0, settings.gov_api_max_retries)
        last_code: str | None = None
        for _ in range(attempts):
            try:
                resp = httpx.request(
                    method, url, params=params, headers=headers,
                    timeout=self.meta.timeout_seconds, follow_redirects=True,
                )
                return resp, resp.status_code, None
            except httpx.TimeoutException:
                last_code = AdapterErrorCode.TIMEOUT
            except httpx.TransportError:
                last_code = AdapterErrorCode.NETWORK
        return None, None, last_code


# ═══════════════════════════════ DataGov / UDYAM dataset (§3) ══

class DataGovUdyamAdapter(BaseProviderAdapter):
    """data.gov.in UDYAM/MSME dataset search.

    THIS IS A DATASET SEARCH, NOT A REGISTRATION VERIFICATION API. Results are
    labelled GOVERNMENT_DATASET_MATCH. Without DATA_GOV_API_KEY + the dataset
    resource id (both server-side settings), the adapter runs in DEMO mode with
    clearly synthetic records so the enrichment workflow can be demonstrated.
    """

    def __init__(self) -> None:
        provisioned = bool(settings.data_gov_api_key and settings.data_gov_udyaam_resource_id)
        self.meta = ProviderMeta(
            code="udyam_dataset",
            provider="Ministry of Micro, Small and Medium Enterprises (via data.gov.in)",
            service="UDYAM/MSME registration dataset search",
            endpoint=f"{settings.data_gov_base_url}/{settings.data_gov_udyaam_resource_id}" if settings.data_gov_udyaam_resource_id else None,
            http_method="GET",
            authentication_method="data.gov.in API key (server-side header/query param — never exposed)",
            authorization_status="AUTHORIZED" if provisioned else "PENDING_AUTHORIZATION",
            environment="LIVE" if provisioned else ("DEMO" if settings.allow_demo_workflows else "NOT_AVAILABLE"),
            modes=[IntegrationMode.LIVE.value] if provisioned else ([IntegrationMode.DEMO.value] if settings.allow_demo_workflows else [IntegrationMode.NOT_AVAILABLE.value]),
            supported_operations=["dataset_search", "select_match"],
            fallback_mode=IntegrationMode.MANUAL.value,
            official_portal_url="https://udyamregistration.gov.in/",
            documentation_url="https://data.gov.in/",
            data_categories=["Enterprise name", "State", "District", "NIC activity", "Registration date"],
            notes=(
                "Dataset search (GOVERNMENT_DATASET_MATCH) — not a real-time UDYAM verification API. "
                "Provision DATA_GOV_API_KEY + data_gov_udyaam_resource_id server-side for live dataset search."
            ),
        )

    def credentials_present(self) -> dict[str, bool]:
        return {"DATA_GOV_API_KEY": bool(settings.data_gov_api_key), "DATA_GOV_UDYAAM_RESOURCE_ID": bool(settings.data_gov_udyaam_resource_id)}

    def _validate(self, payload: Any) -> bool:
        """data.gov.in pattern: {"records": [...]} or {"items": ...} — tolerate both."""
        return isinstance(payload, dict) and (("records" in payload) or ("items" in payload) or ("result" in payload))

    def search(self, *, query: str, state_code: str | None = None, district: str | None = None,
               pincode: str | None = None, activity: str | None = None, limit: int = 10, offset: int = 0) -> AdapterResult:
        """Dataset search over the documented UDYAM fields (State, District,
        Pincode, RegistrationDate, EnterpriseName, CommunicationAddress,
        Activities) with deterministic candidate scoring (strong_match).
        GOVERNMENT_DATASET_MATCH, never 'UDYAM verification'."""
        provisioned = bool(settings.data_gov_api_key and settings.data_gov_udyaam_resource_id)
        if provisioned:
            filters: dict[str, str] = {}
            if query:
                filters["EnterpriseName"] = query
            if state_code:
                filters["State"] = state_code
            if district:
                filters["District"] = district
            if pincode:
                filters["Pincode"] = pincode
            if activity:
                filters["Activities"] = activity
            result = data_gov_dataset_call(
                self, operation="dataset_search", resource_id=settings.data_gov_udyaam_resource_id,
                filters=filters, limit=max(1, min(int(limit), 50)), offset=max(0, int(offset)),
                dataset_name="UDYAM/MSME registration dataset (data.gov.in)",
                result_note=self.meta.notes,
            )
            if result.ok:
                for rec in result.data.get("records", []):
                    rec["_match"] = _match_score(query, rec, ["EnterpriseName", "enterprise_name"],
                                                 [("State", state_code), ("District", district), ("Pincode", pincode)])
                result.data["records"] = sorted(result.data["records"], key=lambda r: -r["_match"]["score"])
                result.data["strong_matches"] = sum(1 for r in result.data["records"] if r["_match"]["strong_match"])
                result.data["match_warning"] = ("Government Dataset Match — Source: data.gov.in · Status: Source-backed. "
                                                "This is NOT a real-time UDYAM verification; confirm on the official Udyam portal.")
            return result
        if settings.allow_demo_workflows:
            from . import demo_government
            return self._demo_search(query=query, state_code=state_code, correlation_id="COR-" + uuid.uuid4().hex[:12])
        return AdapterResult(ok=False, mode=IntegrationMode.NOT_AVAILABLE.value, error_code=AdapterErrorCode.NOT_PROVISIONED,
                             provider=self.meta.provider, provider_code=self.meta.code, service=self.meta.service, operation="dataset_search",
                             fallback_hint={"mode": IntegrationMode.MANUAL.value, "official_portal_url": self.meta.official_portal_url})

    def _demo_search(self, *, query: str, state_code: str | None, correlation_id: str) -> AdapterResult:
        from . import demo_government
        q = (query or "").lower()
        pool = [
            {"enterprise_name": "Demo Electronics Private Limited [DEMO]", "is_demo": True, "_mode": "DEMO", "udyam_reference": "UDYAM-TN-03-0001234 [SYNTHETIC]", "state": "Tamil Nadu", "district": "Chennai", "nic_activity": "Manufacture of electronic components (NIC 261)", "registration_date": "2024-06-12", "enterprise_type": "Small"},
            {"enterprise_name": "Demo Precision Components [DEMO]", "is_demo": True, "_mode": "DEMO", "udyam_reference": "UDYAM-TN-11-0005678 [SYNTHETIC]", "state": "Tamil Nadu", "district": "Coimbatore", "nic_activity": "Manufacture of electronic assemblies (NIC 26)", "registration_date": "2023-11-03", "enterprise_type": "Micro"},
            {"enterprise_name": "Demo Circuit Assembly LLP [DEMO]", "is_demo": True, "_mode": "DEMO", "udyam_reference": "UDYAM-TN-01-0009012 [SYNTHETIC]", "state": "Tamil Nadu", "district": "Chennai", "nic_activity": "PCB assembly and testing (NIC 260)", "registration_date": "2025-02-20", "enterprise_type": "Micro"},
        ]
        records = [r for r in pool if not q or q in r["enterprise_name"].lower() or any(w in r["nic_activity"].lower() for w in q.split() if len(w) > 3)]
        return AdapterResult(
            ok=True, mode=IntegrationMode.DEMO.value, correlation_id=correlation_id,
            provider=self.meta.provider, provider_code=self.meta.code, service=self.meta.service, operation="dataset_search",
            data={"records": records, "count": len(records),
                  "demo": dict(demo_government.METADATA)},
            verification_status="DEMO", source_status=SourceStatus.DEMO.value,
            user_message="DEMO DATA — NOT A LIVE GOVERNMENT CONNECTION. Synthetic records for demonstrating the enrichment workflow.",
            meta={"note": "Provision DATA_GOV_API_KEY + dataset resource id for live data.gov.in dataset search.",
                  "official_portal_url": self.meta.official_portal_url},
        )


# ═══════════════════════════════════════ MCA company data (§4) ══

class MCAAdapter(BaseProviderAdapter):
    """MCA company identity intelligence. Programmatic MCA access requires
    formal authorization — until then: PENDING_AUTHORIZATION + official
    portal. No company information is ever fabricated."""

    def __init__(self) -> None:
        provisioned = bool(settings.mca_api_base_url and settings.mca_client_id and settings.mca_client_secret)
        dataset = bool(settings.data_gov_api_key and settings.data_gov_mca_resource_id)
        ops = (["company_search", "profile_compare"] if provisioned else []) + (["company_dataset_search"] if dataset else [])
        self.meta = ProviderMeta(
            code="mca",
            provider="Ministry of Corporate Affairs",
            service="Company/LLP identity — authorized MCA API (pending) and the public Company Master Data dataset",
            endpoint=settings.mca_api_base_url or (f"{settings.data_gov_base_url}/{settings.data_gov_mca_resource_id}" if dataset else None),
            http_method="GET",
            authentication_method=("OAuth2 client credentials (server-side only)" if provisioned else ("data.gov.in API key (server-side only)" if dataset else "Not provisioned")),
            authorization_status="AUTHORIZED" if provisioned else "PENDING_AUTHORIZATION",
            environment="LIVE" if provisioned else "PENDING_AUTHORIZATION",
            modes=([IntegrationMode.LIVE.value] if provisioned else []) + ([IntegrationMode.LIVE.value, IntegrationMode.PENDING_AUTHORIZATION.value] if dataset else [IntegrationMode.PENDING_AUTHORIZATION.value, IntegrationMode.OFFICIAL_REDIRECT.value]),
            supported_operations=ops,
            fallback_mode=IntegrationMode.OFFICIAL_REDIRECT.value,
            official_portal_url="https://www.mca.gov.in/",
            documentation_url="https://www.mca.gov.in/content/mca/global/en/data-and-reports.html",
            data_categories=["Company name", "CIN", "ROC", "Registration status", "Company category", "Company sub-category",
                             "Company class", "Authorized capital", "Paid-up capital", "Registration date", "Registered office",
                             "State", "Industrial classification"],
            notes=("Live MCA verification requires an authorized MCA API (OAuth2, server-side) — MCA_DATA_MATCH is reported "
                   "only from such a response. The public RoC-wise Company Master Data dataset via data.gov.in is labelled "
                   "'MCA Company Master Data' (GOVERNMENT_DATASET_MATCH) and is NOT a live verification API."),
        )

    def credentials_present(self) -> dict[str, bool]:
        return {"MCA_API_BASE_URL": bool(settings.mca_api_base_url), "MCA_CLIENT_ID": bool(settings.mca_client_id), "MCA_CLIENT_SECRET": bool(settings.mca_client_secret)}

    def search(self, *, query: str, state_code: str | None = None, limit: int = 10, offset: int = 0) -> AdapterResult:
        corr = "COR-" + uuid.uuid4().hex[:12]
        base = dict(provider=self.meta.provider, service=self.meta.service, operation="company_search", correlation_id=corr, provider_code=self.meta.code)
        if not (settings.mca_api_base_url and settings.mca_client_id and settings.mca_client_secret):
            # Public Company Master Data dataset (data.gov.in) — labelled as a
            # DATASET, never as a live MCA verification API. CIN-shaped queries
            # search the CIN column; names search CompanyName.
            if settings.data_gov_api_key and settings.data_gov_mca_resource_id:
                cin_shaped = bool(re.fullmatch(r"[A-Za-z][0-9]{5}[A-Za-z]{2}[0-9]{4}[A-Za-z]{3}[0-9]{6}", (query or "").strip()))
                filters: dict[str, str] = {}
                if query:
                    filters["CIN" if cin_shaped else "CompanyName"] = query
                if state_code:
                    filters["CompanyStateCode"] = state_code
                result = data_gov_dataset_call(
                    self, operation="company_dataset_search", resource_id=settings.data_gov_mca_resource_id,
                    filters=filters, limit=max(1, min(int(limit), 50)),
                    offset=max(0, int(offset)),
                    dataset_name="MCA Company Master Data — RoC-wise (data.gov.in)",
                    result_note=("Public MCA Company Master Data — CIN, CompanyName, ROC code, category/sub-category, class, "
                                 "authorized/paid-up capital, registration date, registered office, listing status, CompanyStatus, "
                                 "state code, Indian/Foreign, NIC industrial classification where published. "
                                 "This is a PUBLIC GOVERNMENT DATASET, not a live MCA verification API."),
                )
                if result.ok:
                    for rec in result.data.get("records", []):
                        rec["_match"] = _match_score(query, rec, ["CompanyName", "company_name"],
                                                     [("CompanyStateCode", state_code), ("CIN", query if cin_shaped else None)])
                    result.data["records"] = sorted(result.data["records"], key=lambda r: -r["_match"]["score"])
                    result.data["strong_matches"] = sum(1 for r in result.data["records"] if r["_match"]["strong_match"])
                    result.data["match_warning"] = ("MCA Company Master Data (public dataset) — NOT a live MCA verification. "
                                                    "Confirm CIN and status on the official MCA portal.")
                return result
            return AdapterResult(ok=False, mode=IntegrationMode.PENDING_AUTHORIZATION.value, error_code=AdapterErrorCode.NOT_PROVISIONED, **base,
                                 fallback_hint={"mode": IntegrationMode.OFFICIAL_REDIRECT.value, "official_portal_url": self.meta.official_portal_url,
                                                "manual_steps": ["Search the company on the official MCA portal", "Note the CIN and registered details", "Record them in the project profile (CIN field)"]})
        if not settings.enable_outbound_gov_calls:
            return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, error_code=AdapterErrorCode.DISABLED, **base)
        started = time.monotonic()
        try:
            resp, status_code, err = self._http("GET", f"{settings.mca_api_base_url.rstrip('/')}/companies", params={"q": query},
                                                headers={"Authorization": f"Bearer {settings.mca_client_secret}", "X-Client-Id": settings.mca_client_id})
            latency = int((time.monotonic() - started) * 1000)
            if err or resp is None:
                return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, latency_ms=latency, error_code=err, **base)
            mapping = {401: AdapterErrorCode.AUTH_REQUIRED, 403: AdapterErrorCode.AUTHORIZATION_UNAVAILABLE, 404: AdapterErrorCode.RESOURCE_UNAVAILABLE, 429: AdapterErrorCode.RATE_LIMITED}
            if resp.status_code in mapping:
                return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency, error_code=mapping[resp.status_code], **base)
            if resp.status_code >= 500:
                return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency, error_code=AdapterErrorCode.PROVIDER_ERROR, **base)
            payload = resp.json()
            if not isinstance(payload, dict) or "companies" not in payload:
                return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency, error_code=AdapterErrorCode.INVALID_RESPONSE, **base)
            return AdapterResult(ok=True, mode=IntegrationMode.LIVE.value, http_status=resp.status_code, latency_ms=latency,
                                 data={"companies": payload["companies"][:10]}, verification_status="MCA_DATA_MATCH",
                                 source_status=SourceStatus.VERIFIED_GOV_SOURCE.value, meta={"dataset": "Authorized MCA API", "retrieved_at": datetime.utcnow().isoformat()}, **base)
        except Exception:
            return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, error_code=AdapterErrorCode.PROVIDER_ERROR, **base)


# ═══════════════════════════════════════ Pincode / location (§5) ══

# Coarse offline index: PIN first-two-digits → postal circle. Public knowledge
# of the India Post PIN structure; deliberately coarse and ALWAYS labelled
# REQUIRES_VERIFICATION with an "user confirms" requirement — the authoritative
# source is the data.gov.in dataset when its API key is provisioned.
# Exact-prefix specials (handled before the coarse ranges)
_PIN_EXACT: dict[str, tuple[str, str]] = {
    "403": ("Goa", "GOA"),
    "744": ("Andaman & Nicobar Islands", "ANDAMAN_NICOBAR"),
    "737": ("Sikkim", "SIKKIM"),
    "682": ("Kerala", "KERALA"),
    "605": ("Puducherry", "PUDUCHERRY"),
}

# Coarse offline index: PIN first-two-digits → postal circle. Public knowledge
# of the India Post PIN structure; deliberately coarse and ALWAYS labelled
# REQUIRES_VERIFICATION with a "user confirms" requirement — the authoritative
# source is the data.gov.in dataset when its API key is provisioned.
_PIN_CIRCLE_INDEX: list[tuple[range, str, str]] = [
    (range(11, 12), "Delhi", "DELHI"),
    (range(12, 14), "Haryana", "HARYANA"),
    (range(14, 17), "Punjab / Chandigarh", "PUNJAB"),
    (range(17, 18), "Himachal Pradesh", "HIMACHAL_PRADESH"),
    (range(18, 20), "Jammu & Kashmir / Ladakh", "JAMMU_KASHMIR"),
    (range(20, 24), "Uttar Pradesh", "UTTAR_PRADESH"),
    (range(24, 25), "Uttarakhand / Uttar Pradesh (verify)", "UTTARAKHAND"),
    (range(25, 29), "Uttar Pradesh", "UTTAR_PRADESH"),
    (range(30, 35), "Rajasthan", "RAJASTHAN"),
    (range(36, 40), "Gujarat / Dadra-Nagar Haveli / Daman (verify)", "GUJARAT"),
    (range(40, 41), "Maharashtra (Mumbai region)", "MAHARASHTRA"),
    (range(41, 45), "Maharashtra", "MAHARASHTRA"),
    (range(45, 49), "Madhya Pradesh", "MADHYA_PRADESH"),
    (range(49, 50), "Chhattisgarh", "CHHATTISGARH"),
    (range(50, 51), "Telangana", "TELANGANA"),
    (range(51, 55), "Andhra Pradesh", "ANDHRA_PRADESH"),
    (range(56, 60), "Karnataka", "KARNATAKA"),
    (range(60, 65), "Tamil Nadu", "TAMIL_NADU"),
    (range(67, 70), "Kerala / Mahe (verify)", "KERALA"),
    (range(70, 75), "West Bengal", "WEST_BENGAL"),
    (range(75, 78), "Odisha", "ODISHA"),
    (range(78, 79), "Assam", "ASSAM"),
    (range(79, 80), "North-East (Arunachal/Meghalaya/Mizoram/Nagaland/Manipur/Tripura — verify)", "NORTH_EAST"),
    (range(80, 85), "Bihar / Jharkhand (verify)", "BIHAR")]


class PincodeAdapter(BaseProviderAdapter):
    """PIN → state/district/post-office. Authoritative source: data.gov.in
    India Post dataset (needs DATA_GOV_API_KEY + resource id). Fallback: the
    coarse offline circle index (user confirms). Never guesses a district."""

    def __init__(self) -> None:
        provisioned = bool(settings.data_gov_api_key and settings.data_gov_pincode_resource_id)
        self.meta = ProviderMeta(
            code="pincode",
            provider="India Post (via data.gov.in)",
            service="PIN code → state / district / post office lookup",
            endpoint=f"{settings.data_gov_base_url}/{settings.data_gov_pincode_resource_id}" if settings.data_gov_pincode_resource_id else None,
            http_method="GET",
            authentication_method="data.gov.in API key (server-side only)" if provisioned else "Offline index (no API call)",
            authorization_status="AUTHORIZED" if provisioned else "PENDING_AUTHORIZATION",
            environment="LIVE" if provisioned else "OFFLINE_INDEX",
            modes=[IntegrationMode.LIVE.value] if provisioned else [IntegrationMode.MANUAL.value],
            supported_operations=["pincode_lookup"],
            fallback_mode=IntegrationMode.MANUAL.value,
            official_portal_url="https://www.indiapost.gov.in/",
            documentation_url="https://data.gov.in/",
            data_categories=["Pincode", "State", "District", "Post office"],
            notes="Location data feeds the Regulatory Digital Twin. Offline index is coarse (postal circle) and always requires user confirmation.",
        )

    def credentials_present(self) -> dict[str, bool]:
        return {"DATA_GOV_API_KEY": bool(settings.data_gov_api_key), "DATA_GOV_PINCODE_RESOURCE_ID": bool(settings.data_gov_pincode_resource_id)}

    @staticmethod
    def _valid_pin(pin: str) -> bool:
        return bool(re.fullmatch(r"[1-9][0-9]{5}", (pin or "").strip()))

    def lookup(self, *, pincode: str) -> AdapterResult:
        corr = "COR-" + uuid.uuid4().hex[:12]
        base = dict(provider=self.meta.provider, service=self.meta.service, operation="pincode_lookup", correlation_id=corr)
        pin = (pincode or "").strip()
        if not self._valid_pin(pin):
            return AdapterResult(ok=False, mode=IntegrationMode.MANUAL.value, error_code=AdapterErrorCode.INVALID_RESPONSE, **base,
                                 user_message="That does not look like a valid 6-digit Indian PIN code. Please check and re-enter.")
        if settings.data_gov_api_key and settings.data_gov_pincode_resource_id:
            result = data_gov_dataset_call(
                self, operation="pincode_lookup", resource_id=settings.data_gov_pincode_resource_id,
                filters={"pincode": pin}, limit=20,
                dataset_name="India Post pincode dataset (data.gov.in)",
            )
            if result.ok:
                shaped = []
                for r in result.data.get("records", []):
                    shaped.append({
                        "office": _record_pick(r, "officename", "office", "post_office", "branch office name"),
                        "pincode": _record_pick(r, "pincode"),
                        "district": _record_pick(r, "district"),
                        "state": _record_pick(r, "statename", "state name", "state"),
                        "circle": _record_pick(r, "circle"),
                        "region": _record_pick(r, "region"),
                        "division": _record_pick(r, "division"),
                        "latitude": _record_pick(r, "latitude", "lat"),
                        "longitude": _record_pick(r, "longitude", "lon", "long"),
                    })
                first = shaped[0] if shaped else {}
                result.data.update({
                    "pincode": pin,
                    "post_offices": shaped,
                    "district": (first or {}).get("district"),
                    "state": (first or {}).get("state"),
                    "matches": len(shaped),
                })
                if not shaped:
                    # live authoritative answer: this PIN has no records — honest not-found
                    result.ok = False
                    result.error_code = AdapterErrorCode.RESOURCE_UNAVAILABLE
                    result.user_message = "The authoritative pincode dataset returned no records for that PIN — re-check or enter state/district manually."
                    result.fallback_hint = {"official_portal_url": self.meta.official_portal_url}
            return result
        # offline coarse index (exact prefixes first)
        circle, state_code = _PIN_EXACT.get(pin[:3], (None, None))
        if circle is None:
            prefix = int(pin[:2])
            for rng, c, s in _PIN_CIRCLE_INDEX:
                if prefix in rng:
                    circle, state_code = c, s
                    break
        if circle is not None:
            return AdapterResult(
                ok=True, mode=IntegrationMode.MANUAL.value, correlation_id=corr,
                provider=self.meta.provider, provider_code=self.meta.code, service=self.meta.service, operation="pincode_lookup",
                data={"pincode": pin, "postal_circle": circle, "state_code": state_code, "district": None,
                      "precision": "POSTAL_CIRCLE_ONLY", "state_requires_confirmation": "verify" in circle.lower()},
                verification_status="REQUIRES_VERIFICATION", source_status=SourceStatus.AI_INTERPRETATION.value,
                user_message="Offline postal-circle match — please confirm the state and enter the district; provision DATA_GOV_API_KEY for authoritative lookups.",
                fallback_hint={"official_portal_url": self.meta.official_portal_url}, meta={"note": self.meta.notes},
            )
        return AdapterResult(ok=False, mode=IntegrationMode.MANUAL.value, correlation_id=corr,
                             provider=self.meta.provider, service=self.meta.service, operation="pincode_lookup",
                             error_code=AdapterErrorCode.RESOURCE_UNAVAILABLE, user_message="PIN prefix not in the offline index — enter state/district manually or use the official India Post lookup.",
                             fallback_hint={"official_portal_url": self.meta.official_portal_url})


# ═══════════════════════════════ DigiLocker requester (§6) ══

class DigiLockerAdapter(BaseProviderAdapter):
    """DigiLocker REQUESTER integration. Architecturally complete (authorize →
    consent → request → retrieve → classify → store/reference → audit) but
    activates only with official partner authorization. Without it:
    PENDING_AUTHORIZATION + official redirect. No fake calls, ever."""

    def __init__(self) -> None:
        provisioned = bool(settings.digilocker_client_id and settings.digilocker_client_secret)
        self.meta = ProviderMeta(
            code="digilocker",
            provider="DigiLocker (MeitY) via API Setu",
            service="User-consented document retrieval (requester)",
            endpoint=settings.digilocker_base_url,
            http_method="GET",
            authentication_method="OAuth2 authorization code + consent (server-side client secret)" if provisioned else "Not provisioned",
            authorization_status="AUTHORIZED" if provisioned else "PENDING_AUTHORIZATION",
            environment="LIVE" if provisioned else "PENDING_AUTHORIZATION",
            modes=[IntegrationMode.LIVE.value] if provisioned else [IntegrationMode.PENDING_AUTHORIZATION.value, IntegrationMode.OFFICIAL_REDIRECT.value],
            supported_operations=["authorize_url", "consent", "request_document", "retrieve_document"] if provisioned else ["consent"],
            fallback_mode=IntegrationMode.OFFICIAL_REDIRECT.value,
            official_portal_url="https://www.digilocker.gov.in/",
            documentation_url="https://apisetu.gov.in/",
            data_categories=["Issued documents (user-consented)"],
            consent_required=True,
            notes="DigiLocker integration is awaiting official partner authorization.",
        )

    def credentials_present(self) -> dict[str, bool]:
        return {"DIGILOCKER_CLIENT_ID": bool(settings.digilocker_client_id), "DIGILOCKER_CLIENT_SECRET": bool(settings.digilocker_client_secret)}

    def authorize_url(self, *, state: str) -> AdapterResult:
        corr = "COR-" + uuid.uuid4().hex[:12]
        base = dict(provider=self.meta.provider, service=self.meta.service, operation="authorize_url", correlation_id=corr)
        if not (settings.digilocker_client_id and settings.digilocker_client_secret):
            return AdapterResult(ok=False, mode=IntegrationMode.PENDING_AUTHORIZATION.value, error_code=AdapterErrorCode.NOT_PROVISIONED, **base,
                                 fallback_hint={"mode": IntegrationMode.OFFICIAL_REDIRECT.value,
                                                "official_portal_url": self.meta.official_portal_url,
                                                "manual_steps": ["Open DigiLocker", "Download the issued document", "Upload it in NIECP Documents — the pipeline classifies and pre-validates it"]})
        return AdapterResult(ok=False, mode=IntegrationMode.LIVE.value, error_code=AdapterErrorCode.AUTHORIZATION_UNAVAILABLE, **base,
                             user_message="OAuth flow requires the deployed callback configuration. Continue through the official portal meanwhile.")


# ═══════════════════════ NSWS / Tamil Nadu single window ══


class CPCBAdapter(BaseProviderAdapter):
    """CPCB — environmental CONTEXT via the public real-time air-quality dataset
    (data.gov.in) where provisioned; consents themselves remain with SPCB/PCC
    portals. Air-quality observations are ENVIRONMENTAL_CONTEXT / a REGULATORY
    FACTOR only: project facts + industry + location + applicable rules (the
    deterministic rule engine) decide applicability — never the AQI alone."""

    def __init__(self) -> None:
        air = bool(settings.data_gov_api_key and settings.data_gov_cpcb_air_resource_id)
        self.meta = ProviderMeta(
            code="cpcb",
            provider="Central Pollution Control Board",
            service="Environmental context — real-time air quality (data.gov.in) & consent portal redirection",
            endpoint=f"{settings.data_gov_base_url}/{settings.data_gov_cpcb_air_resource_id}" if air else None,
            http_method="GET",
            authentication_method="data.gov.in API key (server-side only)" if air else "Not provisioned",
            authorization_status="AUTHORIZED" if air else "PENDING_AUTHORIZATION",
            environment="LIVE" if air else "OFFICIAL_REDIRECT",
            modes=[IntegrationMode.LIVE.value, IntegrationMode.PENDING_AUTHORIZATION.value] if air else [IntegrationMode.OFFICIAL_REDIRECT.value, IntegrationMode.PENDING_AUTHORIZATION.value],
            supported_operations=["air_quality_context"] if air else [],
            fallback_mode=IntegrationMode.OFFICIAL_REDIRECT.value,
            official_portal_url="https://cpcb.nic.in/",
            documentation_url="https://data.gov.in/",
            data_categories=["Real-time air quality (station observations: pollutant min/max/avg, last update)", "Emission/effluent standards"],
            notes=("Air-quality data is ENVIRONMENTAL CONTEXT / a REGULATORY FACTOR — it never by itself means an approval is "
                   "required. Environmental consents are handled by SPCB/PCC portals (portal directory); applicability is "
                   "decided only by NIECP's deterministic rule engine over project facts."),
        )

    def credentials_present(self) -> dict[str, bool]:
        return {"DATA_GOV_API_KEY": bool(settings.data_gov_api_key), "DATA_GOV_CPCB_AIR_RESOURCE_ID": bool(settings.data_gov_cpcb_air_resource_id)}

    def air_quality_context(self, *, city: str | None = None, state: str | None = None, limit: int = 25) -> AdapterResult:
        """Real-time station observations (state/city/pollutant/avg/min/max/last_update).
        ENVIRONMENTAL CONTEXT — never an approval determination."""
        filters = {"city": city, "state": state}
        return data_gov_dataset_call(
            self, operation="air_quality_context", resource_id=settings.data_gov_cpcb_air_resource_id,
            filters=filters, limit=max(1, min(int(limit), 100)),
            dataset_name="CPCB real-time air quality monitoring (data.gov.in)",
            context_label=ENVIRONMENTAL_CONTEXT,
            result_note=("ENVIRONMENTAL CONTEXT / REGULATORY FACTOR — station pollutant observations (fields may include state, "
                         "city, station, last_update, pollutant_id, min/max/avg values). This does NOT mean an approval is or is "
                         "not required; applicability is decided by the rule engine on project facts."),
        )


class SurfaceWaterAdapter(BaseProviderAdapter):
    """CPCB surface-water quality — HISTORICAL / SUPPORTING DATA via data.gov.in.
    Observations (pH, BOD, COD, dissolved oxygen, TDS, turbidity, nitrate,
    phosphate where published) are historical monitoring records: never presented
    as current water quality and never an approval determination."""

    def __init__(self) -> None:
        prov = bool(settings.data_gov_api_key and settings.data_gov_surface_water_resource_id)
        self.meta = ProviderMeta(
            code="cpcb_surface_water",
            provider="Central Pollution Control Board (via data.gov.in)",
            service="Surface water quality — HISTORICAL / SUPPORTING observations",
            endpoint=f"{settings.data_gov_base_url}/{settings.data_gov_surface_water_resource_id}" if prov else None,
            http_method="GET",
            authentication_method="data.gov.in API key (server-side only)" if prov else "Not provisioned",
            authorization_status="AUTHORIZED" if prov else "PENDING_AUTHORIZATION",
            environment="LIVE" if prov else "OFFICIAL_REDIRECT",
            modes=[IntegrationMode.LIVE.value, IntegrationMode.PENDING_AUTHORIZATION.value] if prov else [IntegrationMode.OFFICIAL_REDIRECT.value, IntegrationMode.PENDING_AUTHORIZATION.value],
            supported_operations=["water_quality_context"] if prov else [],
            fallback_mode=IntegrationMode.OFFICIAL_REDIRECT.value,
            official_portal_url="https://cpcb.nic.in/",
            documentation_url="https://data.gov.in/",
            data_categories=["pH", "BOD", "COD", "Dissolved oxygen", "TDS", "Turbidity", "Nitrate", "Phosphate (where published)"],
            notes=("HISTORICAL / SUPPORTING DATA: water observations are historical monitoring records used for environmental "
                   "context only. They are never displayed as current water quality and never by themselves create an approval "
                   "requirement — the rule engine decides applicability from project facts."),
        )

    def credentials_present(self) -> dict[str, bool]:
        return {"DATA_GOV_API_KEY": bool(settings.data_gov_api_key), "DATA_GOV_SURFACE_WATER_RESOURCE_ID": bool(settings.data_gov_surface_water_resource_id)}

    def water_quality_context(self, *, state: str | None = None, location: str | None = None, limit: int = 25) -> AdapterResult:
        filters = {"state": state, "location": location, "station": location}
        return data_gov_dataset_call(
            self, operation="water_quality_context", resource_id=settings.data_gov_surface_water_resource_id,
            filters=filters, limit=max(1, min(int(limit), 100)),
            dataset_name="CPCB surface water quality — historical (data.gov.in)",
            context_label=HISTORICAL_SUPPORTING_DATA,
            result_note=("HISTORICAL / SUPPORTING DATA — historical monitoring observations for environmental context. Not "
                         "current water quality; not an approval determination."),
        )


class ASIAdapter(BaseProviderAdapter):
    """Annual Survey of Industries / factory-sector supporting data — INDUSTRIAL
    STATISTICAL DATA for benchmarking, sector statistics, context and analytics.
    Historical industrial statistics never determine whether a particular
    company legally requires an approval."""

    def __init__(self) -> None:
        prov = bool(settings.data_gov_api_key and settings.data_gov_asi_resource_id)
        self.meta = ProviderMeta(
            code="asi_industrial",
            provider="Ministry of Statistics and Programme Implementation (via data.gov.in)",
            service="Annual Survey of Industries — factory-sector statistical context",
            endpoint=f"{settings.data_gov_base_url}/{settings.data_gov_asi_resource_id}" if prov else None,
            http_method="GET",
            authentication_method="data.gov.in API key (server-side only)" if prov else "Not provisioned",
            authorization_status="AUTHORIZED" if prov else "PENDING_AUTHORIZATION",
            environment="LIVE" if prov else "OFFICIAL_REDIRECT",
            modes=[IntegrationMode.LIVE.value, IntegrationMode.PENDING_AUTHORIZATION.value] if prov else [IntegrationMode.OFFICIAL_REDIRECT.value, IntegrationMode.PENDING_AUTHORIZATION.value],
            supported_operations=["industry_statistics_context"] if prov else [],
            fallback_mode=IntegrationMode.OFFICIAL_REDIRECT.value,
            official_portal_url="https://mospi.gov.in/",
            documentation_url="https://data.gov.in/",
            data_categories=["Sector statistics", "Factory-sector benchmarks", "Aggregate indicators"],
            notes=("INDUSTRIAL STATISTICAL DATA — sector-level benchmarking/analytics context only. Historical statistics never "
                   "determine whether a particular company legally requires an approval; the rule engine decides from project facts."),
        )

    def credentials_present(self) -> dict[str, bool]:
        return {"DATA_GOV_API_KEY": bool(settings.data_gov_api_key), "DATA_GOV_ASI_RESOURCE_ID": bool(settings.data_gov_asi_resource_id)}

    def industry_statistics_context(self, *, industry: str | None = None, state: str | None = None, limit: int = 25) -> AdapterResult:
        filters = {"industry": industry, "state": state}
        return data_gov_dataset_call(
            self, operation="industry_statistics_context", resource_id=settings.data_gov_asi_resource_id,
            filters=filters, limit=max(1, min(int(limit), 100)),
            dataset_name="Annual Survey of Industries / factory sector (data.gov.in)",
            context_label=INDUSTRIAL_STATISTICAL_DATA,
            result_note=("INDUSTRIAL STATISTICAL DATA — sector statistics and benchmarks for context/analytics only. Never a "
                         "determination of approval requirements for a specific company."),
        )


class MAITRIAdapter(BaseProviderAdapter):
    """Maharashtra MAITRI — state investor facilitation portal. This is an
    OFFICIAL PORTAL integration (no authorized API): NIECP-AI surfaces the
    relevant service catalogue and deep-links the official portal only.
    Submission is never automated."""

    def __init__(self) -> None:
        self.meta = ProviderMeta(
            code="maitri",
            provider="Maharashtra Industry, Trade & Investment Facilitation (MAITRI)",
            service="State single-window facilitation & incentive services (Maharashtra)",
            endpoint=None,
            authentication_method="Not provisioned (portal accounts are the user's own)",
            authorization_status="PENDING_AUTHORIZATION",
            environment="OFFICIAL_REDIRECT",
            modes=[IntegrationMode.OFFICIAL_REDIRECT.value, IntegrationMode.PENDING_AUTHORIZATION.value],
            supported_operations=["service_catalogue", "official_redirect"],
            fallback_mode=IntegrationMode.OFFICIAL_REDIRECT.value,
            official_portal_url="https://maitri.maharashtra.gov.in/",
            documentation_url="https://maitri.maharashtra.gov.in/",
            data_categories=["Project details (entered by the user on the portal)"],
            consent_required=False,
            notes="Relevant for projects in Maharashtra (state_code=MH). Service catalogue is authored guidance — confirm on the official portal.",
        )

    def credentials_present(self) -> dict[str, bool]:
        return {"MAITRI_API": False}


class NSWSAdapter(BaseProviderAdapter):
    def __init__(self) -> None:
        provisioned = bool(settings.nsws_client_id and settings.nsws_client_secret)
        self.meta = ProviderMeta(
            code="nsws",
            provider="National Single Window System (NSWS)",
            service="Common application route for central & state approvals",
            endpoint=None,
            http_method="POST",
            authentication_method="Provider onboarding + OAuth2 (not provisioned)" if not provisioned else "OAuth2 client credentials (server-side)",
            authorization_status="AUTHORIZED" if provisioned else "PENDING",
            environment="LIVE" if provisioned else "OFFICIAL_REDIRECT",
            modes=[IntegrationMode.LIVE.value] if provisioned else [IntegrationMode.OFFICIAL_REDIRECT.value, IntegrationMode.PENDING_AUTHORIZATION.value],
            supported_operations=["submit_application", "fetch_status", "fetch_queries"] if provisioned else [],
            fallback_mode=IntegrationMode.OFFICIAL_REDIRECT.value,
            official_portal_url="https://www.nsws.gov.in/",
            documentation_url="https://www.nsws.gov.in/",
            data_categories=["Application details", "Status"],
            notes="NSWS adapter activates without rewriting NIECP once NSWS authorizes API access (credentials server-side).",
        )

    def credentials_present(self) -> dict[str, bool]:
        return {"NSWS_CLIENT_ID": bool(settings.nsws_client_id), "NSWS_CLIENT_SECRET": bool(settings.nsws_client_secret)}


class TamilNaduAdapter(BaseProviderAdapter):
    def __init__(self) -> None:
        self.meta = ProviderMeta(
            code="tn_single_window",
            provider="Tamil Nadu Single Window (Guidance Tamil Nadu)",
            service="State approvals facilitation and single window",
            endpoint=None,
            authentication_method="Not provisioned",
            authorization_status="PENDING_AUTHORIZATION",
            environment="OFFICIAL_REDIRECT",
            modes=[IntegrationMode.OFFICIAL_REDIRECT.value, IntegrationMode.PENDING_AUTHORIZATION.value],
            supported_operations=[],
            fallback_mode=IntegrationMode.OFFICIAL_REDIRECT.value,
            official_portal_url="https://www.guidancetamilnadu.in/",
            documentation_url="https://www.guidancetamilnadu.in/",
            data_categories=["Application details", "Status"],
            notes="State single-window API authorization pending; department portals (TNPCB etc.) remain available via the portal directory.",
        )


# ═══════════════════════════════════ Demo government (§18) ══

class DemoGovernmentAdapter(BaseProviderAdapter):
    """Internal NIECP demonstration adapter — see services/demo_government.py
    for the full synthetic workflow (submit → review → query → response →
    decision → renewal). Here it also provides synthetic dataset matches for
    the enrichment flow, always labelled."""

    def __init__(self) -> None:
        from . import demo_government
        self.meta = ProviderMeta(
            code=demo_government.PROVIDER_CODE,
            provider="NIECP Demo Government",
            service="Internal demonstration workflow (synthetic)",
            endpoint=None,
            authentication_method="None — internal sandbox",
            authorization_status="NOT_AUTHORIZED",
            environment="DEMO",
            modes=[IntegrationMode.DEMO.value],
            supported_operations=["submit", "status", "queries", "respond", "documents", "approvals", "dataset_search"],
            fallback_mode=IntegrationMode.DEMO.value,
            official_portal_url=None,
            data_categories=["Synthetic demonstration data"],
            consent_required=False,
            notes="INTERNAL NIECP DEMO. Synthetic data only; never a government API. DEMO DATA — NOT A LIVE GOVERNMENT CONNECTION.",
        )


# ═══════════════════════════════════════════════ adapter registry ══

# ═══════════════════════════════ state-based routing (§31) ══
# Maharashtra → MAITRI (primary state integration); Tamil Nadu → TN single
# window. National adapters (NSWS / API Setu / DigiLocker) stay available
# everywhere; the state layer is chosen dynamically from project state.
_STATE_PRIMARY_INTEGRATION: dict[str, dict[str, str]] = {
    "MH": {"code": "maitri", "name": "Maharashtra MAITRI",
           "official_portal_url": "https://maitri.maharashtra.gov.in/",
           "mode": "OFFICIAL_REDIRECT",
           "reason": "Maharashtra projects route to MAITRI as the primary state single-window facilitation integration."},
    "TN": {"code": "tn_single_window", "name": "Tamil Nadu Single Window (Guidance Tamil Nadu)",
           "official_portal_url": "https://www.guidancetamilnadu.in/",
           "mode": "OFFICIAL_REDIRECT",
           "reason": "Tamil Nadu projects route to Guidance Tamil Nadu as the primary state single-window facilitation integration."},
}


def primary_state_integration(state_code: str | None) -> dict[str, str] | None:
    return _STATE_PRIMARY_INTEGRATION.get((state_code or "").upper())


def all_adapters() -> list[BaseProviderAdapter]:
    return [DataGovUdyamAdapter(), MCAAdapter(), PincodeAdapter(), CPCBAdapter(), SurfaceWaterAdapter(), ASIAdapter(), DigiLockerAdapter(), NSWSAdapter(), TamilNaduAdapter(), MAITRIAdapter(), DemoGovernmentAdapter()]


def get_adapter(code: str) -> BaseProviderAdapter | None:
    return {a.meta.code: a for a in all_adapters()}.get(code)
