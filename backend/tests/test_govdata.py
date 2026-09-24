"""Government data upgrade — honesty and integration tests.

Covers: live data.gov.in responses (mocked HTTP), the full error taxonomy
(401/403/404/429/5xx/timeout/outbound-disabled/missing-credentials), provenance,
dataset-vs-verification labelling, CPCB air / surface water / ASI context
labels, MAITRI/TN state routing, registry consistency, demo separation, the
rule-engine result contract, graph + Smart Action Guide fields.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import gov_providers as G


# ─────────────────────────── helpers ───────────────────────────
class FakeResp:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        if isinstance(self._p, Exception):
            raise self._p
        return self._p


@pytest.fixture(autouse=True)
def _clean_cache():
    G._DATASET_CACHE.clear()
    yield
    G._DATASET_CACHE.clear()


@pytest.fixture
def provisioned(monkeypatch):
    """Provision the data.gov.in datasets server-side and enable outbound calls."""
    monkeypatch.setattr(settings, "data_gov_api_key", "test-key-123", raising=False)
    monkeypatch.setattr(settings, "data_gov_udyaam_resource_id", "8b68ae56-84cf-4728-a0a6-1be11028dea7", raising=False)
    monkeypatch.setattr(settings, "data_gov_pincode_resource_id", "5c2f62fe-5afa-4119-a499-fec9d604d5bd", raising=False)
    monkeypatch.setattr(settings, "data_gov_mca_resource_id", "4dbe5667-7b6b-41d7-82af-211562424d9a", raising=False)
    monkeypatch.setattr(settings, "data_gov_cpcb_air_resource_id", "3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69", raising=False)
    monkeypatch.setattr(settings, "data_gov_surface_water_resource_id", "19697d76-442e-4d76-aeae-13f8a17c91e1", raising=False)
    monkeypatch.setattr(settings, "data_gov_asi_resource_id", "ad35de76-4435-403a-8914-7dbaa907e9d6", raising=False)
    monkeypatch.setattr(settings, "enable_outbound_gov_calls", True, raising=False)


def _mock_http(monkeypatch, status=200, payload=None, raise_exc=None, calls=None):
    def fake_request(method, url, params=None, headers=None, timeout=None, follow_redirects=None):
        if calls is not None:
            calls.append({"url": url, "params": params})
        if raise_exc is not None:
            raise raise_exc
        return FakeResp(status, payload if payload is not None else {"records": [], "total": 0})
    monkeypatch.setattr(G.httpx, "request", fake_request)


# ─────────────────── UDYAM dataset (live, mocked) ───────────────────
class TestUdyamDataset:
    def test_live_response_provenance_and_honesty(self, client, user_token, provisioned, monkeypatch):
        calls = []
        _mock_http(monkeypatch, 200, {"records": [{"enterprise_name": "Acme", "state": "Maharashtra"}], "total": 1, "updated_date": "2026-08-01"}, calls=calls)
        r = G.DataGovUdyamAdapter().search(query="Acme", state_code="MH")
        assert r.ok and r.mode == "LIVE"
        assert r.verification_status == "GOVERNMENT_DATASET_MATCH"      # dataset, not verification
        assert r.source_status == "VERIFIED_GOV_SOURCE"                  # real gov response received
        assert "NOT a real-time UDYAM verification" in r.data["match_warning"]
        assert r.meta["retrieved_at"] and r.meta["source_url"].endswith("8b68ae56-84cf-4728-a0a6-1be11028dea7")
        assert r.meta["last_updated"] == "2026-08-01" and r.meta["total_available"] == 1
        # api-key went to the server-side call, never into result payloads
        assert calls[0]["params"]["api-key"] == "test-key-123"
        blob = repr(r.to_payload())
        assert "test-key-123" not in blob
        assert r.data["filters_applied"] == {"EnterpriseName": "Acme", "State": "MH"}

    def test_pagination_params_reach_api(self, client, user_token, provisioned, monkeypatch):
        calls = []
        _mock_http(monkeypatch, 200, {"records": [], "total": 0}, calls=calls)
        G.DataGovUdyamAdapter().search(query="x", limit=5, offset=10)
        assert calls[0]["params"]["limit"] == 5 and calls[0]["params"]["offset"] == 10

    def test_cache_second_call_hits_no_http(self, provisioned, monkeypatch):
        calls = []
        _mock_http(monkeypatch, 200, {"records": [{"a": 1}], "total": 1}, calls=calls)
        a = G.DataGovUdyamAdapter()
        assert a.search(query="k").ok
        r2 = a.search(query="k")
        assert len(calls) == 1 and r2.meta["cached"] is True and r2.meta["cache_note"]

    @pytest.mark.parametrize("status,code", [(401, "AUTH_REQUIRED"), (403, "AUTHORIZATION_UNAVAILABLE"), (404, "RESOURCE_UNAVAILABLE"), (429, "RATE_LIMITED"), (503, "PROVIDER_ERROR")])
    def test_http_error_taxonomy(self, provisioned, monkeypatch, status, code):
        _mock_http(monkeypatch, status, {})
        r = G.DataGovUdyamAdapter().search(query="x")
        assert r.ok is False and r.error_code == code and r.http_status == status

    def test_timeout_and_invalid_response(self, provisioned, monkeypatch):
        import httpx
        _mock_http(monkeypatch, raise_exc=httpx.TimeoutException("t"))
        assert G.DataGovUdyamAdapter().search(query="x").error_code == "TIMEOUT"
        _mock_http(monkeypatch, 200, {"unexpected": "shape"})
        assert G.DataGovUdyamAdapter().search(query="x").error_code == "INVALID_RESPONSE"

    def test_outbound_disabled_honest(self, provisioned, monkeypatch):
        monkeypatch.setattr(settings, "enable_outbound_gov_calls", False, raising=False)
        r = G.DataGovUdyamAdapter().search(query="x")
        assert r.ok is False and r.error_code == "DISABLED"
        assert "CONFIGURED_BUT_OUTBOUND_DISABLED" in r.user_message

    def test_dataset_never_called_verification(self, provisioned, monkeypatch):
        _mock_http(monkeypatch, 200, {"records": [{"enterprise_name": "Acme"}], "total": 1})
        p = G.DataGovUdyamAdapter().search(query="Acme").to_payload()
        blob = repr(p).upper()
        assert "GOVERNMENT_DATASET_MATCH" in blob and "VERIFIED UDYAM" not in blob

    def test_demo_separation(self, monkeypatch):
        """Demo records are DEMO-labelled, never GOVERNMENT_DATASET_MATCH."""
        monkeypatch.delattr(settings, "data_gov_api_key", raising=False)
        monkeypatch.setattr(settings, "data_gov_api_key", "", raising=False)
        monkeypatch.setattr(settings, "data_gov_udyaam_resource_id", "", raising=False)
        monkeypatch.setattr(settings, "allow_demo_workflows", True, raising=False)
        r = G.DataGovUdyamAdapter().search(query="Demo Electronics")
        assert r.ok and r.mode == "DEMO" and r.verification_status == "DEMO"
        assert "NOT A LIVE GOVERNMENT CONNECTION" in r.user_message
        assert all(rec.get("is_demo") for rec in r.data["records"])


# ─────────────────── MCA public dataset ───────────────────
class TestMcaDataset:
    def test_company_master_data_label(self, provisioned, monkeypatch):
        _mock_http(monkeypatch, 200, {"records": [{"company_name": "ACME LTD", "cin": "U12345MH2010PTC000001", "company_status": "Active"}], "total": 1})
        m = G.MCAAdapter()
        r = m.search(query="ACME")
        assert r.ok and r.operation == "company_dataset_search"
        assert "MCA Company Master Data" in r.meta["dataset"]
        assert "NOT a live MCA verification" in r.data["match_warning"]
        assert r.verification_status == "GOVERNMENT_DATASET_MATCH"
        # authorized-API architecture preserved: credentials surface stays
        assert set(m.credentials_present()) == {"MCA_API_BASE_URL", "MCA_CLIENT_ID", "MCA_CLIENT_SECRET"}

    def test_without_any_provisioning_still_pending_authorization(self, monkeypatch):
        monkeypatch.setattr(settings, "data_gov_api_key", "", raising=False)
        monkeypatch.setattr(settings, "data_gov_mca_resource_id", "", raising=False)
        monkeypatch.setattr(settings, "mca_api_base_url", "", raising=False)
        r = G.MCAAdapter().search(query="x")
        assert r.ok is False and r.mode == "PENDING_AUTHORIZATION" and r.error_code == "NOT_PROVISIONED"
        assert r.fallback_hint["official_portal_url"] == "https://www.mca.gov.in/"


# ─────────────────── Pincode live lookup ───────────────────
class TestPincodeLive:
    def test_structured_parse_and_provenance(self, provisioned, monkeypatch):
        _mock_http(monkeypatch, 200, {"records": [
            {"officename": "Fort St. George SO", "pincode": "600001", "district": "Chennai", "statename": "TAMIL NADU", "circle": "Tamil Nadu Circle", "region": "Chennai Region", "division": "Chennai City Division"},
            {"officename": "Anna Road SO", "pincode": "600001", "district": "Chennai", "statename": "TAMIL NADU", "circle": "Tamil Nadu Circle", "region": "Chennai Region", "division": "Chennai City Division"},
        ], "total": 2})
        r = G.PincodeAdapter().lookup(pincode="600001")
        assert r.ok and r.mode == "LIVE" and r.verification_status == "GOVERNMENT_DATASET_MATCH"
        assert r.data["district"] == "Chennai" and r.data["matches"] == 2
        assert r.data["post_offices"][0]["circle"] == "Tamil Nadu Circle"
        assert r.meta["retrieved_at"] and r.meta["cached"] is False

    def test_zero_records_is_honest_not_found(self, provisioned, monkeypatch):
        _mock_http(monkeypatch, 200, {"records": [], "total": 0})
        r = G.PincodeAdapter().lookup(pincode="999999")
        assert r.ok is False and r.error_code == "RESOURCE_UNAVAILABLE"
        assert "returned no records" in r.user_message

    def test_offline_fallback_stays_requires_verification(self, monkeypatch):
        monkeypatch.setattr(settings, "data_gov_api_key", "", raising=False)
        monkeypatch.setattr(settings, "data_gov_pincode_resource_id", "", raising=False)
        r = G.PincodeAdapter().lookup(pincode="600001")
        assert r.ok and r.verification_status == "REQUIRES_VERIFICATION"
        assert r.data["precision"] == "POSTAL_CIRCLE_ONLY"


# ─────────────────── CPCB air / water / ASI context ───────────────────
class TestEnvironmentalContext:
    def test_air_quality_context_label(self, provisioned, monkeypatch):
        _mock_http(monkeypatch, 200, {"records": [{"station": "Bandra", "city": "Mumbai", "pollutant_id": "PM2.5", "avg_value": "41", "last_update": "2026-09-23 06:00:00"}], "total": 1})
        r = G.CPCBAdapter().air_quality_context(city="Mumbai")
        assert r.ok and r.meta["context_label"] == "ENVIRONMENTAL_CONTEXT"
        assert r.data["records"][0]["pollutant_id"] == "PM2.5"
        assert "NOT mean an approval" in r.meta["note"]

    def test_surface_water_labelled_historical(self, provisioned, monkeypatch):
        _mock_http(monkeypatch, 200, {"records": [{"station": "Wardha", "ph": "7.4", "bod": "2.1", "do": "6.2"}], "total": 1})
        r = G.SurfaceWaterAdapter().water_quality_context(state="MH")
        assert r.ok and r.meta["context_label"] == "HISTORICAL_SUPPORTING_DATA"
        assert "Not current water quality" in r.meta["note"]
        assert r.verification_status == "GOVERNMENT_DATASET_MATCH"  # the retrieval is real; the label governs use

    def test_asi_labelled_statistical(self, provisioned, monkeypatch):
        _mock_http(monkeypatch, 200, {"records": [{"industry": "Textiles", "state": "MH"}], "total": 1})
        r = G.ASIAdapter().industry_statistics_context(industry="Textiles")
        assert r.ok and r.meta["context_label"] == "INDUSTRIAL_STATISTICAL_DATA"
        assert "never" in r.meta["note"].lower()


# ─────────────────── registry & status consistency ───────────────────
class TestRegistryConsistency:
    def test_adapters_registry_and_cards_agree(self, client, user_token):
        from app.services.gov_manager import service_cards
        r = client.get("/api/v1/gov/services", headers=_h(user_token)).json()
        cards = {c["code"]: c for c in r["services"]}
        assert len(cards) == 11
        assert {"cpcb_surface_water", "asi_industrial"} <= set(cards)
        for code, card in cards.items():
            assert card["connection_status"] in {"CONNECTED", "CONFIGURED", "CONFIGURED_BUT_OUTBOUND_DISABLED",
                                                 "PENDING_AUTHORIZATION", "OFFICIAL_REDIRECT", "MANUAL", "DEMO"}
        assert cards["niecp_demo_government"]["connection_status"] == "DEMO"
        sc = {c["code"]: c["connection_status"] for c in service_cards(_db(client))}
        assert sc == {k: v["connection_status"] for k, v in cards.items()}

    def test_no_connected_without_real_success(self, client, user_token, provisioned, monkeypatch):
        """Credentials alone (even + outbound) never produce CONNECTED until a
        successful call is recorded — and outbound-disabled never hides it."""
        monkeypatch.setattr(settings, "enable_outbound_gov_calls", False, raising=False)
        cards = {c["code"]: c for c in client.get("/api/v1/gov/services", headers=_h(user_token)).json()["services"]}
        assert cards["udyam_dataset"]["connection_status"] == "CONFIGURED_BUT_OUTBOUND_DISABLED"
        assert cards["pincode"]["connection_status"] == "CONFIGURED_BUT_OUTBOUND_DISABLED"
        assert all(c["connection_status"] != "CONNECTED" for c in cards.values())

    def test_data_status_endpoint(self, client, user_token, provisioned, monkeypatch):
        monkeypatch.setattr(settings, "enable_outbound_gov_calls", False, raising=False)
        d = client.get("/api/v1/gov/data-status", headers=_h(user_token)).json()
        by = {x["dataset"]: x for x in d["datasets"]}
        assert by["UDYAM/MSME registration dataset"]["connection_state"] == "CONFIGURED_BUT_OUTBOUND_DISABLED"
        assert d["cache_scope"].startswith("PUBLIC")

    def test_state_routing(self, client, user_token):
        mh = client.get("/api/v1/gov/state-integration", params={"state_code": "MH"}, headers=_h(user_token)).json()
        tn = client.get("/api/v1/gov/state-integration", params={"state_code": "TN"}, headers=_h(user_token)).json()
        ka = client.get("/api/v1/gov/state-integration", params={"state_code": "KA"}, headers=_h(user_token)).json()
        assert mh["primary_state_integration"]["code"] == "maitri" and mh["primary_state_integration"]["mode"] == "OFFICIAL_REDIRECT"
        assert tn["primary_state_integration"]["code"] == "tn_single_window"
        assert ka["primary_state_integration"] is None

    def test_integration_payload_shares_vocabulary(self, client, user_token):
        integ = client.get("/api/v1/integrations", headers=_h(user_token)).json()["integrations"]
        vocab = {"CONNECTED", "CONFIGURED", "CONFIGURED_BUT_OUTBOUND_DISABLED", "PENDING_AUTHORIZATION",
                 "OFFICIAL_REDIRECT", "MANUAL", "DEMO"}
        assert integ and all(i["connection_state"] in vocab for i in integ)
        # services endpoint agrees with the integration store on shared codes
        cards = {c["code"]: c["connection_status"] for c in client.get("/api/v1/gov/services", headers=_h(user_token)).json()["services"]}
        for i in integ:
            if i["code"] in cards:
                assert cards[i["code"]] == i["connection_state"], (i["code"], cards[i["code"]], i["connection_state"])


# ─────────────────── env context endpoints + save-to-twin ───────────────────
class TestContextEndpoints:
    def test_endpoints_label_and_usage_rule(self, client, user_token, provisioned, monkeypatch):
        _mock_http(monkeypatch, 200, {"records": [{"station": "S1", "pollutant_id": "PM2.5"}], "total": 1})
        H = _h(user_token)
        pid = _project(client, user_token)
        aq = client.post("/api/v1/gov/cpcb/air-quality", headers=H, json={"project_id": pid, "city": "Mumbai"}).json()
        assert aq["ok"] and aq["context_label"] == "ENVIRONMENTAL_CONTEXT" and "never" in aq["usage_rule"].lower()
        sw = client.post("/api/v1/gov/cpcb/surface-water", headers=H, json={"project_id": pid, "location": "Wardha"}).json()
        assert sw["context_label"] == "HISTORICAL_SUPPORTING_DATA"
        asi = client.post("/api/v1/gov/asi/industry-stats", headers=H, json={"project_id": pid, "industry": "electronics"}).json()
        assert asi["context_label"] == "INDUSTRIAL_STATISTICAL_DATA"

    def test_save_creates_provenance_labelled_reference(self, client, user_token, provisioned, monkeypatch):
        _mock_http(monkeypatch, 200, {"records": [{"station": "S1"}], "total": 1})
        H = _h(user_token)
        pid = _project(client, user_token)
        client.post("/api/v1/gov/cpcb/air-quality", headers=H, json={"project_id": pid, "city": "Mumbai", "save_to_project": True})
        refs = client.get(f"/api/v1/projects/{pid}/gov-references", headers=H).json()["references"]
        env = [r for r in refs if "air quality" in (r["service"] or "").lower()]
        assert env and env[0]["is_demo"] is False and env[0]["verification_status"] == "GOVERNMENT_DATASET_MATCH"

    def test_enrichment_blocks_and_provenance(self, client, user_token):
        H = _h(user_token)
        pid = _project(client, user_token)
        en = client.get(f"/api/v1/projects/{pid}/gov/enrichment", headers=H).json()
        assert set(en["blocks"]) == {"PROJECT", "BUSINESS", "COMPANY", "MSME", "LOCATION", "ENVIRONMENT", "INDUSTRY", "APPROVALS", "DOCUMENTS", "COMPLIANCE"}
        for block in en["blocks"].values():
            for entry in block:
                assert {"value", "source", "source_type", "verification_state"} <= set(entry)


# ─────────────────── MAITRI service intelligence ───────────────────
class TestMaitriIntelligence:
    def test_approval_links_and_tat_honesty(self, client, user_token):
        H = _h(user_token)
        pid = _project(client, user_token, state_code="MH")
        mt = client.get(f"/api/v1/projects/{pid}/msme/maitri-services", headers=H).json()
        assert mt["relevant"] and mt["approval_links"] is not None
        for s in mt["services"]:
            assert "sub_department" in s and "tat_days" in s and s["tat_note"]
        for al in mt["approval_links"]:
            assert al["state"] == "Maharashtra" and al["verification_status"] == "REQUIRES_VERIFICATION"
            assert al["mapping_type"] in ("ROUTED_VIA_SINGLE_WINDOW_FACILITATION", "ENTRY_POINT")
            assert al["official_channel"] == "https://maitri.maharashtra.gov.in/"


# ─────────────────── rule engine result contract ───────────────────
class TestRuleEngineContract:
    def test_missing_facts_never_not_applicable(self):
        from app.ai.rule_engine import RuleContext, evaluate_rule
        ctx = RuleContext.build({})
        r = evaluate_rule("water_consumption_kld >= 100", ctx, "t.missing")
        d = r.as_dict()
        assert d["result"] == "INFORMATION_REQUIRED" and d["produced"] == "UNKNOWN"
        assert "water_consumption_kld" in d["missing_facts"] and d["explanation"]

    def test_canonical_states_and_fields(self):
        from app.ai.rule_engine import RuleContext, evaluate_rule
        ctx = RuleContext.build({"total_investment": 2_000_000})
        d1 = evaluate_rule("total_investment >= 1000000", ctx, "t.yes").as_dict()
        assert d1["result"] == "APPLIES" and d1["rule_id"] == "t.yes" and d1["matched_facts"]
        d2 = evaluate_rule("total_investment < 10", ctx, "t.no").as_dict()
        assert d2["result"] == "NOT_APPLICABLE"
        d3 = evaluate_rule("total_investment >== oops", ctx, "t.bad").as_dict()
        assert d3["result"] == "REQUIRES_VERIFICATION" and d3["error"]
        for d in (d1, d2, d3):
            assert {"rule_id", "result", "matched_facts", "missing_facts", "explanation"} <= set(d)

    def test_graph_and_approvals_payload_fields(self, client, user_token):
        H = _h(user_token)
        pid = _project(client, user_token)
        client.post(f"/api/v1/projects/{pid}/analysis", headers=H)
        g = client.get(f"/api/v1/projects/{pid}/graph", headers=H).json()
        if g["nodes"]:
            n = g["nodes"][0]
            assert {"information_required", "requires_verification", "verification_status", "official_channel", "legal_basis", "facts_used", "missing_facts"} <= set(n)

    def test_smart_action_guide_fields(self, client, user_token):
        H = _h(user_token)
        pid = _project(client, user_token)
        na = client.get(f"/api/v1/projects/{pid}/next-actions", headers=H).json()
        assert na["actions"]
        for a in na["actions"]:
            assert {"action", "reason", "verification_status", "blocked_by", "required_documents"} <= set(a)


# ─────────────────── shared helpers ───────────────────
def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _db(client):
    from app.database import SessionLocal
    return SessionLocal()


def _project(client, token, **profile):
    import random
    r = client.post("/api/v1/projects", json={"name": f"GovData Test {random.randint(1000000, 9999999)}"}, headers=_h(token))
    assert r.status_code in (200, 201), f"project create failed: {r.status_code} {r.text[:300]}"
    pid = r.json()["project"]["id"]
    if profile:
        client.patch(f"/api/v1/projects/{pid}/profile", json={"industry_code": "electronics", **profile}, headers=_h(token))
    return pid
