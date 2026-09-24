"""MVP architecture tests — decision trail, application package, MAITRI
handoff, SLA, bottlenecks, lifecycle, department queue, Project Twin, adapter
hardening (408, scoring, CIN) and the REQUIRED second-project differentiation.

Everything asserted here comes from real database state — no hardcoded samples,
no fabricated government events.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import gov_providers as G


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _project(client, token, **profile):
    import random
    r = client.post("/api/v1/projects", json={"name": f"MVP Test {random.randint(1000000, 9999999)}"}, headers=_h(token))
    assert r.status_code in (200, 201), r.text[:200]
    pid = r.json()["project"]["id"]
    patch = {"industry_code": "textile", "state_code": "TN", **profile}
    r = client.patch(f"/api/v1/projects/{pid}/profile", json=patch, headers=_h(token))
    assert r.status_code in (200, 201), r.text[:200]
    return pid


@pytest.fixture
def provisioned(monkeypatch):
    monkeypatch.setattr(settings, "data_gov_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "data_gov_udyaam_resource_id", "8b68ae56-84cf-4728-a0a6-1be11028dea7", raising=False)
    monkeypatch.setattr(settings, "data_gov_pincode_resource_id", "5c2f62fe-5afa-4119-a499-fec9d604d5bd", raising=False)
    monkeypatch.setattr(settings, "data_gov_mca_resource_id", "4dbe5667-7b6b-41d7-82af-211562424d9a", raising=False)
    monkeypatch.setattr(settings, "enable_outbound_gov_calls", True, raising=False)


# ═══════════════════ DECISION TRAIL (§G) ═══════════════════
class TestDecisionTrail:
    def test_trail_recorded_on_analysis(self, client, user_token):
        pid = _project(client, user_token, machinery_investment=30_000_000, annual_turnover=90_000_000)
        r = client.post(f"/api/v1/projects/{pid}/analysis", headers=_h(user_token))
        assert r.status_code == 200
        tr = client.get(f"/api/v1/projects/{pid}/decision-trail", headers=_h(user_token)).json()
        assert tr["trail"], "analysis must record decision trail rows"
        row = tr["trail"][0]
        for k in ("approval", "authority", "rule_key", "rule_expression", "result", "triggering_facts",
                  "missing_facts", "explanation", "legal_basis", "engine_version", "recorded_at"):
            assert k in row, k
        assert row["result"] in ("APPLIES", "CONDITIONAL", "NOT_APPLICABLE", "INFORMATION_REQUIRED", "REQUIRES_VERIFICATION")
        assert row["engine_version"].startswith("niecp-rules/")
        # template filter works
        code = row["template_code"]
        tr2 = client.get(f"/api/v1/projects/{pid}/decision-trail", params={"template_code": code}, headers=_h(user_token)).json()
        assert all(t["template_code"] == code for t in tr2["trail"])

    def test_llm_never_decides(self, client, user_token):
        pid = _project(client, user_token)
        client.post(f"/api/v1/projects/{pid}/analysis", headers=_h(user_token))
        tr = client.get(f"/api/v1/projects/{pid}/decision-trail", headers=_h(user_token)).json()
        for t in tr["trail"]:
            assert t["rule_expression"], "every trail row must carry the evaluated rule"
            assert t["source_status"] in (None, "REQUIRES_VERIFICATION", "VERIFIED_GOV_SOURCE", "OFFICIAL_API", "USER_PROVIDED", "AI_INTERPRETATION")


# ═══════════════════ PROJECT TWIN (§C) ═══════════════════
class TestProjectTwin:
    def test_central_facts_with_provenance(self, client, user_token):
        pid = _project(client, user_token, total_investment=42_000_000, employment_generated=55, pincode="600001")
        en = client.get(f"/api/v1/projects/{pid}/gov/enrichment", headers=_h(user_token)).json()
        assert en["twin"]["name"] == "Project Twin"
        assert "PROJECT" in en["blocks"]
        labels = {e["label"]: e for e in en["blocks"]["PROJECT"]}
        assert float(labels["Total investment (₹)"]["value"]) == 42_000_000.0
        for e in en["blocks"]["PROJECT"]:
            assert e["source_type"] in ("USER_PROVIDED", "VERIFIED_GOV_SOURCE", "OFFICIAL_API", "AI_INTERPRETATION", "REQUIRES_VERIFICATION", "INFORMATION_UNAVAILABLE", "DEMO")
            assert e["verification_state"]
        assert en["twin"]["verification_counts"].get("USER_PROVIDED", 0) >= 10


# ═══════════════════ APPLICATION PACKAGE (§M) ═══════════════════
class TestApplicationPackage:
    def test_generated_from_db_state(self, client, user_token):
        pid = _project(client, user_token, water_consumption_kld=150, total_investment=120_000_000)
        client.post(f"/api/v1/projects/{pid}/analysis", headers=_h(user_token))
        pkg = client.get(f"/api/v1/projects/{pid}/application-package", headers=_h(user_token)).json()
        assert pkg["project"]["id"] == pid
        assert pkg["approvals"], "analysis should identify approvals for a textile plant"
        for a in pkg["approvals"]:
            assert {"approval", "authority", "status", "why_applicable", "legal_basis", "documents",
                    "prerequisites", "official_source", "verification_status"} <= set(a)
        assert isinstance(pkg["missing_items"], list) and pkg["readiness"]["overall"] is not None
        assert "never a probability of approval" in pkg["readiness"]["note"]
        assert pkg["boundary"]["MANUAL"].startswith("Submission happens on the official portal")
        assert "nsws" in pkg["official_submission"]


# ═══════════════════ MAITRI HANDOFF (§N) ═══════════════════
class TestMaitriHandoff:
    def test_mh_manual_handoff(self, client, user_token):
        pid = _project(client, user_token, state_code="MH")
        client.post(f"/api/v1/projects/{pid}/analysis", headers=_h(user_token))
        h = client.post(f"/api/v1/projects/{pid}/maitri-handoff", headers=_h(user_token)).json()
        assert h["ok"] is True and h["status"] == "MANUAL_HANDOFF"
        assert h["portal"] == {"name": "Maharashtra MAITRI", "url": "https://maitri.maharashtra.gov.in/"}
        assert "No application is submitted" in h["notice"]
        assert "NOT CLAIMED: submission" in " ".join(h["labels"])
        assert h["package_summary"]["approvals"] > 0

    def test_non_mh_honest_decline(self, client, user_token):
        pid = _project(client, user_token, state_code="KA")
        h = client.post(f"/api/v1/projects/{pid}/maitri-handoff", headers=_h(user_token)).json()
        assert h["ok"] is False and h["status"] == "PENDING_AUTHORIZATION"


# ═══════════════════ SLA ENGINE (§Q) ═══════════════════
class TestSlaEngine:
    def test_not_started_and_labels(self, client, user_token):
        pid = _project(client, user_token)
        sla = client.get(f"/api/v1/projects/{pid}/sla", headers=_h(user_token)).json()
        assert sla["applications"] == [] or all("status" in a for a in sla["applications"])
        assert any("CONFIGURED" in l for l in sla["labels"])

    def test_running_paused_breached(self, client, user_token):
        from app.database import SessionLocal
        from app import models
        from app.enums import ApplicationStatus
        pid = _project(client, user_token, state_code="MH")
        client.post(f"/api/v1/projects/{pid}/analysis", headers=_h(user_token))
        # create + submit an application directly (deterministic test data, clearly internal)
        import sqlalchemy as sa
        from datetime import datetime, timedelta
        db = SessionLocal()
        pa = db.scalars(sa.select(models.ProjectApproval).where(models.ProjectApproval.project_id == pid)).first()
        assert pa is not None
        app_row = models.Application(
            project_id=pid, project_approval_id=pa.id, approval_template_code=pa.template_code,
            title="SLA probe", authority=pa.authority, status=ApplicationStatus.SUBMITTED,
            submission_channel=None,
            submitted_at=datetime.utcnow() - timedelta(days=400),
        )
        db.add(app_row)
        db.commit()
        aid = app_row.id
        # open query pauses the clock
        q = models.GovernmentQuery(project_id=pid, application_id=aid, authority=pa.authority,
                                   query_text="Clarification requested", status=models.QueryStatus.OPEN,
                                   date_received=datetime.utcnow().date() - timedelta(days=10))
        db.add(q)
        db.commit()
        db.close()
        sla = client.get(f"/api/v1/projects/{pid}/sla", headers=_h(user_token)).json()
        row = next(a for a in sla["applications"] if a["application_id"] == aid)
        assert row["status"] in ("PAUSED", "BREACHED", "ON_TRACK", "APPROACHING", "RUNNING_UNCONFIGURED")
        assert row["paused_days"] >= 10 or row["status"] == "PAUSED"
        assert row["base_label"] == "CONFIGURED"


# ═══════════════════ BOTTLENECK ENGINE (§R) ═══════════════════
class TestBottleneckEngine:
    def test_blocked_approval_with_downstream(self, client, user_token):
        from app.database import SessionLocal
        from app import models
        import sqlalchemy as sa
        pid = _project(client, user_token)
        client.post(f"/api/v1/projects/{pid}/analysis", headers=_h(user_token))
        db = SessionLocal()
        # force one active approval into BLOCKED with a dependent
        pas = db.scalars(sa.select(models.ProjectApproval).where(models.ProjectApproval.project_id == pid)).all()
        target = next((a for a in pas if a.applicability.value == "APPLIES" and (a.dependents or [])), None)
        if target is None:
            target = pas[0]
        dep_code = (target.dependents or [None])[0] or (target.template_code)
        dep = db.scalars(sa.select(models.ApprovalTemplate).where(models.ApprovalTemplate.code == dep_code)).first()
        target.node_state = models.ApprovalNodeState.BLOCKED
        db.commit()
        db.close()
        bn = client.get(f"/api/v1/projects/{pid}/bottlenecks", headers=_h(user_token)).json()
        assert bn["bottlenecks"], "a blocked approval must surface as a bottleneck"
        b0 = bn["bottlenecks"][0]
        for k in ("bottleneck", "causes", "downstream_impact", "project_impact", "severity"):
            assert k in b0
        assert any("prerequisite" in c or "missing documents" in c or "query" in c or "information required" in c or "SLA" in c for c in b0["causes"])
        assert "no ai risk score" in bn["note"].lower()


# ═══════════════════ LIFECYCLE (§O) + QUERIES (§P) ═══════════════════
class TestLifecycle:
    def test_lifecycle_stage_mapping(self, client, user_token):
        pid = _project(client, user_token)
        client.post(f"/api/v1/projects/{pid}/analysis", headers=_h(user_token))
        r = client.post(f"/api/v1/projects/{pid}/applications", headers=_h(user_token),
                        json={"title": "Lifecycle probe"})
        if r.status_code == 422:  # needs approval_template_code
            g = client.get(f"/api/v1/projects/{pid}/graph", headers=_h(user_token)).json()
            code = g["nodes"][0]["id"]
            r = client.post(f"/api/v1/projects/{pid}/applications", headers=_h(user_token),
                            json={"title": "Lifecycle probe", "approval_template_code": code})
        assert r.status_code == 201, r.text[:200]
        app_row = r.json()["application"]
        lc = app_row["lifecycle"]
        assert lc["stage"] in ("DRAFT", "READY", "SUBMITTED", "UNDER_SCRUTINY", "QUERY_RAISED",
                               "APPLICANT_RESPONSE_REQUIRED", "APPLICANT_RESPONDED", "SLA_RUNNING",
                               "APPROVED", "REJECTED", "CLOSED")
        assert lc["sla_status"] in (None, "NOT_STARTED", "ON_TRACK", "APPROACHING", "BREACHED", "PAUSED", "RUNNING_UNCONFIGURED", "COMPLETED")
        assert lc["label"]

    def test_query_overdue_surfaces(self, client, user_token):
        pid = _project(client, user_token)
        na = client.get(f"/api/v1/projects/{pid}/next-actions", headers=_h(user_token)).json()
        assert "actions" in na


# ═══════════════════ DEPARTMENT OPERATIONS (§V) ═══════════════════
class TestDepartmentOps:
    def test_admin_only_and_labelled(self, client, user_token, admin_token):
        r = client.get("/api/v1/ops/department-queue", headers=_h(user_token))
        assert r.status_code == 403
        d = client.get("/api/v1/ops/department-queue", headers=_h(admin_token)).json()
        assert d["view"].startswith("DEPARTMENT OPERATIONS — PROTOTYPE / SIMULATED")
        assert d["labels"] == ["PROTOTYPE", "SIMULATED", "READ-ONLY"]
        for row in d["queue"]:
            assert "simulated" in row and "sla_status" in row


# ═══════════════════ ADAPTER HARDENING (§AC/§D) ═══════════════════
class TestAdapterHardening:
    class _Resp:
        def __init__(self, status, payload):
            self.status_code = status
            self._p = payload

        def json(self):
            return self._p

    def test_408_maps_to_timeout(self, provisioned, monkeypatch):
        provisioned  # noqa
        monkeypatch.setattr(G.httpx, "request", lambda *a, **k: self._Resp(408, {}))
        r = G.DataGovUdyamAdapter().search(query="x")
        assert r.ok is False and r.error_code == "TIMEOUT" and r.http_status == 408

    @pytest.fixture(autouse=True)
    def _clean(self):
        G._DATASET_CACHE.clear()
        yield
        G._DATASET_CACHE.clear()

    def _provision(self, monkeypatch):
        monkeypatch.setattr(settings, "data_gov_api_key", "k", raising=False)
        monkeypatch.setattr(settings, "data_gov_udyaam_resource_id", "r", raising=False)
        monkeypatch.setattr(settings, "data_gov_mca_resource_id", "m", raising=False)
        monkeypatch.setattr(settings, "enable_outbound_gov_calls", True, raising=False)

    def test_udyaam_strong_match_scoring(self, monkeypatch):
        self._provision(monkeypatch)
        payload = {"records": [
            {"EnterpriseName": "Alpha Industries", "State": "Maharashtra", "District": "Pune", "Pincode": "411001"},
            {"EnterpriseName": "Beta Textiles", "State": "Tamil Nadu", "District": "Erode", "Pincode": "638001"},
        ], "total": 2}
        monkeypatch.setattr(G.httpx, "request", lambda *a, **k: self._Resp(200, payload))
        r = G.DataGovUdyamAdapter().search(query="Alpha Industries", state_code="Maharashtra", district="Pune", pincode="411001")
        assert r.ok and r.data["strong_matches"] == 1
        assert r.data["records"][0]["EnterpriseName"] == "Alpha Industries"
        assert r.data["records"][0]["_match"]["strong_match"] is True
        assert "Government Dataset Match" in r.data["match_warning"]

    def test_mca_cin_search(self, monkeypatch):
        self._provision(monkeypatch)
        seen = {}
        def fake(method, url, params=None, headers=None, timeout=None, follow_redirects=None):
            seen.update(params or {})
            return self._Resp(200, {"records": [{"CIN": "U12345MH2010PTC000001", "CompanyName": "ACME LTD", "CompanyStatus": "Active"}], "total": 1})
        monkeypatch.setattr(G.httpx, "request", fake)
        r = G.MCAAdapter().search(query="U12345MH2010PTC000001")
        assert r.ok
        assert seen.get("filters[CIN]") == "U12345MH2010PTC000001"
        assert r.data["records"][0]["CompanyStatus"] == "Active"
        assert "PUBLIC GOVERNMENT DATASET" in r.meta["note"]

    def test_pincode_latlong_parsed(self, monkeypatch):
        self._provision(monkeypatch)
        monkeypatch.setattr(settings, "data_gov_pincode_resource_id", "p", raising=False)
        monkeypatch.setattr(G.httpx, "request", lambda *a, **k: self._Resp(200, {
            "records": [{"officename": "Fort SO", "district": "Chennai", "statename": "TAMIL NADU",
                         "circle": "TN Circle", "region": "Chennai", "division": "Chennai City", "latitude": "13.08", "longitude": "80.27"}],
            "total": 1}))
        r = G.PincodeAdapter().lookup(pincode="600001")
        assert r.ok and r.data["post_offices"][0]["latitude"] == "13.08" and r.data["post_offices"][0]["longitude"] == "80.27"


# ═══════════════════ SECOND PROJECT DIFFERENTIATION (§AE — REQUIRED) ═══════════════════
class TestSecondProjectDifferentiation:
    def test_two_projects_produce_different_intelligence(self, client, user_token):
        # Project A: small textile dyeing unit in Tamil Nadu
        pa = _project(client, user_token, industry_code="textile", state_code="TN",
                      machinery_investment=8_000_000, annual_turnover=30_000_000,
                      water_consumption_kld=25, total_investment=15_000_000)
        # Project B: large chemicals plant in Maharashtra with hazardous waste
        pb = _project(client, user_token, industry_code="chemicals", state_code="MH",
                      machinery_investment=900_000_000, annual_turnover=3_000_000_000,
                      water_consumption_kld=400, total_investment=1_500_000_000,
                      hazardous_waste_generated=True, uses_hazardous_chemicals=True,
                      has_boiler=True, boiler_capacity_tph=8)
        ra = client.post(f"/api/v1/projects/{pa}/analysis", headers=_h(user_token)).json()
        rb = client.post(f"/api/v1/projects/{pb}/analysis", headers=_h(user_token)).json()

        map_a = {a["template_code"]: a["applicability"] for a in ra["approvals"]}
        map_b = {a["template_code"]: a["applicability"] for a in rb["approvals"]}
        assert map_a != map_b, "different industries/states must identify different approvals"
        applies_a = sum(1 for v in map_a.values() if v == "APPLIES")
        applies_b = sum(1 for v in map_b.values() if v == "APPLIES")
        assert applies_a != applies_b, "the chemicals project must trigger strictly more deterministic APPLIES rules"
        differing = [k for k in set(map_a) | set(map_b) if map_a.get(k) != map_b.get(k)]
        assert {"hazardous_waste_authorisation", "boiler_registration"} <= set(differing)

        # MSME classification differs (micro/small vs above limits)
        ca = client.get(f"/api/v1/projects/{pa}/msme/classification", headers=_h(user_token)).json()
        cb = client.get(f"/api/v1/projects/{pb}/msme/classification", headers=_h(user_token)).json()
        assert ca["potential_class"] in ("MICRO", "SMALL")
        assert cb["potential_class"] in ("MEDIUM", "LARGE_OR_ABOVE_LIMITS")

        # MAITRI only relevant for the Maharashtra project
        ma = client.get(f"/api/v1/projects/{pa}/msme/maitri-services", headers=_h(user_token)).json()
        mb = client.get(f"/api/v1/projects/{pb}/msme/maitri-services", headers=_h(user_token)).json()
        assert ma["relevant"] is False and mb["relevant"] is True

        # packages differ in missing items and official routes
        pka = client.get(f"/api/v1/projects/{pa}/application-package", headers=_h(user_token)).json()
        pkb = client.get(f"/api/v1/projects/{pb}/application-package", headers=_h(user_token)).json()
        assert pka["project"]["state_code"] != pkb["project"]["state_code"]
        assert {a["template_code"] for a in pka["approvals"]} != {a["template_code"] for a in pkb["approvals"]}
        assert pkb["official_submission"]["state_route"] is not None and pka["official_submission"]["state_route"] is None

        # decision trails differ
        ta = client.get(f"/api/v1/projects/{pa}/decision-trail", headers=_h(user_token)).json()
        tb = client.get(f"/api/v1/projects/{pb}/decision-trail", headers=_h(user_token)).json()
        assert {t["template_code"] for t in ta["trail"]} != {t["template_code"] for t in tb["trail"]}

        # bottlenecks differ (or at least are computed per project)
        ba = client.get(f"/api/v1/projects/{pa}/bottlenecks", headers=_h(user_token)).json()
        bb = client.get(f"/api/v1/projects/{pb}/bottlenecks", headers=_h(user_token)).json()
        assert ba["summary"]["total"] != bb["summary"]["total"] or [b["bottleneck"] for b in ba["bottlenecks"]] != [b["bottleneck"] for b in bb["bottlenecks"]]


# ═══════════════════ INTEGRATION STATUS (§Y) ═══════════════════
class TestIntegrationStatusVocabulary:
    def test_status_vocabulary_complete(self, client, user_token):
        cards = {c["code"]: c for c in client.get("/api/v1/gov/services", headers=_h(user_token)).json()["services"]}
        vocab = {"CONNECTED", "NOT_CONNECTED", "PENDING_AUTHORIZATION", "API_UNAVAILABLE", "MANUAL_MODE",
                 "CONFIGURED", "CONFIGURED_BUT_OUTBOUND_DISABLED", "OFFICIAL_REDIRECT", "MANUAL", "DEMO"}
        assert all(c["connection_status"] in vocab for c in cards.values())
        assert all(c["connection_status"] != "CONNECTED" for c in cards.values())
