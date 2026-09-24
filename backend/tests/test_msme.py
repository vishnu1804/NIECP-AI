"""MSME Regulatory Intelligence — classification honesty, versioned §7,
conditional provisions, payment math, MAITRI gating, law version warnings."""
from __future__ import annotations

import random


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _project(client, token, **profile):
    r = client.post("/api/v1/projects", json={"name": f"MSME Test {random.randint(1000000, 9999999)}"}, headers=_auth(token))
    pid = r.json()["project"]["id"]
    patch = {"industry_code": "electronics", "state_code": "TN", **profile}
    r = client.patch(f"/api/v1/projects/{pid}/profile", json=patch, headers=_auth(token))
    assert r.status_code in (200, 201), r.text
    return pid


class TestClassification:
    def test_cannot_classify_without_inputs(self, client, user_token):
        """§1: never claim a classification without the required inputs."""
        pid = _project(client, user_token, machinery_investment=50_000_000)  # turnover missing
        r = client.get(f"/api/v1/projects/{pid}/msme/classification", headers=_auth(user_token)).json()
        assert r["potential_class"] is None
        assert r["status"] == "INFORMATION_REQUIRED"
        assert any("turnover" in m for m in r["missing_inputs"])

    def test_micro_per_current_version(self, client, user_token):
        # v3-2025: micro = inv ≤ 2.5 Cr & TO ≤ 10 Cr
        pid = _project(client, user_token, machinery_investment=20_000_000, annual_turnover=50_000_000)
        r = client.get(f"/api/v1/projects/{pid}/msme/classification", headers=_auth(user_token)).json()
        assert r["potential_class"] == "MICRO"
        assert r["law_version"] == "v3-2025"
        assert "not an official government classification" in r["declaration"]

    def test_small_and_medium_and_above(self, client, user_token):
        p1 = _project(client, user_token, machinery_investment=100_000_000, annual_turnover=500_000_000)
        r1 = client.get(f"/api/v1/projects/{p1}/msme/classification", headers=_auth(user_token)).json()
        assert r1["potential_class"] == "SMALL"
        p2 = _project(client, user_token, machinery_investment=500_000_000, annual_turnover=2_000_000_000)
        r2 = client.get(f"/api/v1/projects/{p2}/msme/classification", headers=_auth(user_token)).json()
        assert r2["potential_class"] == "MEDIUM"
        p3 = _project(client, user_token, machinery_investment=2_000_000_000, annual_turnover=6_000_000_000)
        r3 = client.get(f"/api/v1/projects/{p3}/msme/classification", headers=_auth(user_token)).json()
        assert r3["potential_class"] == "LARGE_OR_ABOVE_LIMITS"

    def test_registration_check(self, client, user_token):
        pid = _project(client, user_token, machinery_investment=10_000_000, annual_turnover=30_000_000)
        r = client.get(f"/api/v1/projects/{pid}/msme/classification", headers=_auth(user_token)).json()
        assert r["registration"]["status"] == "REGISTRATION_MAY_BE_REQUIRED"
        assert r["registration"]["official_source"].startswith("https://")
        # with udyam recorded → provenance USER_PROVIDED, never "verified"
        pid2 = _project(client, user_token, machinery_investment=10_000_000, annual_turnover=30_000_000, udyam_number="UDYAM-TN-03-0099999")
        r2 = client.get(f"/api/v1/projects/{pid2}/msme/classification", headers=_auth(user_token)).json()
        assert r2["registration"]["status"] == "REGISTERED_AS_PER_PROFILE"
        assert "cannot verify" in r2["registration"]["note"]


class TestIntelligence:
    def test_module_payload_and_conditional_provisions(self, client, user_token):
        pid = _project(client, user_token, machinery_investment=20_000_000, annual_turnover=80_000_000)
        r = client.get(f"/api/v1/projects/{pid}/msme/intelligence", headers=_auth(user_token)).json()
        # §11 regulatory profile shape
        for key in ("business_classification", "msme_status", "applicable_msme_provisions", "compliance_risks", "smart_action_guide", "law_versions", "trust_labels"):
            assert key in r
        sections = {p["section"]: p for p in r["applicable_msme_provisions"]}
        assert set(sections) >= {"7", "8", "15", "18", "22", "24", "27"}
        # no blanket applicability: §22 is CONDITIONAL until the buyer flag is set
        assert sections["22"]["applicability"] == "CONDITIONAL"
        assert sections["15"]["applicability"] == "CONDITIONAL"
        assert sections["24"]["applicability"] == "INFORMATIONAL"
        # every provision carries source + verification status + label
        for p in r["applicable_msme_provisions"]:
            assert p["official_source"].startswith("https://")
            assert p["verification_status"] == "REQUIRES_VERIFICATION"
        # §10 version control
        assert r["law_versions"]["current_applied"] == "v3-2025"
        assert len(r["law_versions"]["versions"]) == 3
        assert "may not represent the latest applicable law" in r["law_versions"]["warning"]

    def test_buyer_flag_flips_section_22(self, client, user_token):
        pid = _project(client, user_token, machinery_investment=20_000_000, annual_turnover=80_000_000, buys_from_msme_suppliers=True)
        r = client.get(f"/api/v1/projects/{pid}/msme/intelligence", headers=_auth(user_token)).json()
        sections = {p["section"]: p for p in r["applicable_msme_provisions"]}
        assert sections["22"]["applicability"] == "APPLICABLE"
        alerts = r["compliance_risks"]
        assert any("annual-account" in a["alert"].lower() or "disclosure" in a["alert"].lower() for a in alerts)

    def test_alerts_carry_evidence_and_source(self, client, user_token):
        pid = _project(client, user_token)  # no investment/turnover → classification alert
        r = client.get(f"/api/v1/projects/{pid}/msme/alerts", headers=_auth(user_token)).json()
        assert any(a["section"] == "7" for a in r["alerts"])
        for a in r["alerts"]:
            assert a["why"] and a["recommended_action"] and a["official_source"].startswith("https://")

    def test_maitri_gated_to_maharashtra(self, client, user_token):
        pid_tn = _project(client, user_token, state_code="TN")
        r_tn = client.get(f"/api/v1/projects/{pid_tn}/msme/maitri-services", headers=_auth(user_token)).json()
        assert r_tn["relevant"] is False and r_tn["services"] == []
        pid_mh = _project(client, user_token, state_code="MH")
        r_mh = client.get(f"/api/v1/projects/{pid_mh}/msme/maitri-services", headers=_auth(user_token)).json()
        assert r_mh["relevant"] is True and len(r_mh["services"]) >= 5
        for s in r_mh["services"]:
            assert s["official_channel"] == "https://maitri.maharashtra.gov.in/"
            assert s["verification_status"] == "REQUIRES_VERIFICATION"
        assert "never automates submission" in r_mh["notice"]

    def test_explain_endpoint(self, client, user_token):
        pid = _project(client, user_token, machinery_investment=20_000_000, annual_turnover=80_000_000)
        r = client.get(f"/api/v1/msme/provisions/18/explain", params={"project_id": pid}, headers=_auth(user_token)).json()
        assert r["section"] == "18"
        assert r["plain_language_explanation"]
        assert "MSEFC" in r["plain_language_explanation"] or "Facilitation Council" in r["plain_language_explanation"]
        assert r["official_source"].startswith("https://")
        assert "not legal advice" in r["disclaimer"]
        assert client.get("/api/v1/msme/provisions/999/explain", headers=_auth(user_token)).status_code == 404

    def test_smart_action_guide_dynamic(self, client, user_token):
        pid = _project(client, user_token)  # missing inputs
        g1 = client.get(f"/api/v1/projects/{pid}/msme/smart-action-guide", headers=_auth(user_token)).json()["guide"]
        assert any("Complete missing business information" in g["action"] for g in g1)
        pid2 = _project(client, user_token, machinery_investment=10_000_000, annual_turnover=30_000_000, state_code="MH")
        g2 = client.get(f"/api/v2/../v1/projects/{pid2}/msme/smart-action-guide".replace("/v2/../v1", "/v1"), headers=_auth(user_token)).json()["guide"]
        actions = [g["action"] for g in g2]
        assert any("Check MSME classification" in a for a in actions)
        assert any("UDYAM" in a or "Udyam" in a for a in actions)
        assert any("MAITRI" in a for a in actions)  # MH-specific step
        assert any("official government channel" in a for a in actions)


class TestPaymentProtection:
    def test_delay_detected_and_sections(self, client, user_token):
        pid = _project(client, user_token)
        r = client.post(f"/api/v1/projects/{pid}/msme/payment-assessment", json={
            "supplier_enterprise_class": "MICRO", "invoice_date": "2026-01-05", "supply_date": "2026-01-05",
            "amount": 500000, "payment_terms_days": 45,
        }, headers=_auth(user_token)).json()
        assert r["ok"] is True
        assert r["assessment_type"].startswith("INFORMATIONAL")
        assert r["delayed_payment_flag"] is True
        assert r["timeline"]["days_past_due"] > 0
        assert "15" in r["applicable_sections"] and "18" in r["applicable_sections"]
        assert r["interest_estimate"]["amount"] > 0
        assert "placeholder bank rate" in r["interest_estimate"]["rate_note"] or "verify" in r["interest_estimate"]["rate_note"].lower()
        assert "NOT LEGAL ADVICE" in r["assessment_type"]
        assert any("Facilitation Council" in step or "Samadhaan" in step for step in r["recommended_path"])

    def test_no_delay_and_default_period(self, client, user_token):
        pid = _project(client, user_token)
        r = client.post(f"/api/v1/projects/{pid}/msme/payment-assessment", json={
            "supplier_enterprise_class": "SMALL", "invoice_date": "2026-09-01", "amount": 100000,
        }, headers=_auth(user_token)).json()
        assert r["ok"] is True
        assert r["delayed_payment_flag"] is False
        assert r["timeline"]["period_days"] == 45  # default when no terms
        assert r["interest_estimate"]["amount"] == 0

    def test_non_mse_supplier_honest_scope(self, client, user_token):
        pid = _project(client, user_token)
        r = client.post(f"/api/v1/projects/{pid}/msme/payment-assessment", json={
            "supplier_enterprise_class": "MEDIUM", "invoice_date": "2026-01-05", "amount": 1000000,
            "as_of": "2026-09-01",
        }, headers=_auth(user_token)).json()
        assert r["msmed_relevant"] is False
        assert "MSEFC route may not be available" in r["msmed_note"]
        assert any("contractual remedies" in s for s in r["recommended_path"])

    def test_invalid_dates(self, client, user_token):
        pid = _project(client, user_token)
        r = client.post(f"/api/v1/projects/{pid}/msme/payment-assessment", json={
            "supplier_enterprise_class": "MICRO", "invoice_date": "not-a-date", "amount": 1,
        }, headers=_auth(user_token)).json()
        assert r["ok"] is False and "Invalid invoice date" in r["message"]


class TestAdaptersAndDocs:
    def test_new_adapters_listed(self, client, user_token):
        r = client.get("/api/v1/gov/services", headers=_auth(user_token)).json()
        codes = {s["code"]: s for s in r["services"]}
        assert codes["maitri"]["official_portal_url"] == "https://maitri.maharashtra.gov.in/"
        assert codes["cpcb"]["authorization_status"] == "PENDING_AUTHORIZATION"
        assert codes["maitri"]["supported_operations"] == ["service_catalogue", "official_redirect"]

    def test_law_versions_endpoint(self, client, user_token):
        r = client.get("/api/v1/msme/law-versions", headers=_auth(user_token)).json()
        assert r["current_applied"] == "v3-2025"
        statuses = {v["version"]: v["status"] for v in r["versions"]}
        assert statuses["v3-2025"] == "PENDING_VERIFICATION"
        assert statuses["v2-2020"] == "SUPERSEDED"
        assert statuses["v1-2006"] == "SUPERSEDED"
        assert "may not represent the latest applicable law" in r["warning"]
