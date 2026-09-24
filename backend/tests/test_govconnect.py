"""Government data services — provider adapters, consent, enrichment,
command center. Honesty invariants: dataset ≠ verification, nothing shows
CONNECTED without a real authenticated success, no credentials in payloads,
no fabricated company/registration data."""
from __future__ import annotations

import json
import random


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _project(client, token, **profile):
    r = client.post("/api/v1/projects", json={"name": f"GovData Test {random.randint(1000000, 9999999)}"}, headers=_auth(token))
    assert r.status_code == 201, r.text
    pid = r.json()["project"]["id"]
    client.patch(f"/api/v1/projects/{pid}/profile", json={"industry_code": "electronics", "state_code": "TN", **profile}, headers=_auth(token))
    return pid


class TestServiceCards:
    def test_cards_and_statuses(self, client, user_token):
        r = client.get("/api/v1/gov/services", headers=_auth(user_token))
        assert r.status_code == 200
        body = r.json()
        codes = {c["code"] for c in body["services"]}
        assert {"udyam_dataset", "mca", "pincode", "digilocker", "nsws", "tn_single_window", "niecp_demo_government"} <= codes
        # §4/§6: not-provisioned providers are honest
        by = {c["code"]: c for c in body["services"]}
        assert by["mca"]["authorization_status"] == "PENDING_AUTHORIZATION"
        assert "awaiting official partner authorization" in (by["digilocker"]["notice"] or "").lower()
        assert by["niecp_demo_government"]["environment"] == "DEMO"
        # nothing is reported connected (no credentials provisioned in tests)
        assert body["summary"]["active"] == 0
        assert "until a real successful authenticated response" in body["summary"]["declaration"]
        # §2: credential values never leave the server — booleans only
        blob = json.dumps(body)
        assert all(isinstance(v, bool) for c in body["services"] for v in c["credentials_configured"].values())
        from app.config import settings as _settings
        for secret_value in (_settings.data_gov_api_key, _settings.mca_client_secret, _settings.nsws_client_secret, _settings.digilocker_client_secret):
            if secret_value:
                assert secret_value not in blob

    def test_pincode_test_connection(self, client, user_token):
        r = client.post("/api/v1/gov/services/pincode/test", json={"probe": {"pincode": "600001"}}, headers=_auth(user_token))
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["state_code"] == "TAMIL_NADU"
        assert body["verification_status"] == "REQUIRES_VERIFICATION"  # coarse offline index
        assert body["mode"] == "MANUAL"

    def test_unknown_service(self, client, user_token):
        assert client.post("/api/v1/gov/services/does_not_exist/test", json={}, headers=_auth(user_token)).status_code == 404


class TestPincode:
    def test_valid_invalid(self, client, user_token):
        ok = client.post("/api/v1/gov/pincode-lookup", json={"pincode": "641045"}, headers=_auth(user_token)).json()
        assert ok["ok"] is True and ok["data"]["state_code"] == "TAMIL_NADU"
        assert ok["data"]["district"] is None  # never guesses a district
        bad = client.post("/api/v1/gov/pincode-lookup", json={"pincode": "1234"}, headers=_auth(user_token)).json()
        assert bad["ok"] is False and "valid 6-digit" in bad["message"]

    def test_apply_to_profile(self, client, user_token):
        pid = _project(client, user_token)
        r = client.post("/api/v1/gov/pincode-lookup", json={"pincode": "600001", "project_id": pid, "apply_to_profile": True}, headers=_auth(user_token)).json()
        assert r["applied_to_profile"]["pincode"] == "600001"
        prof = client.get(f"/api/v1/projects/{pid}/profile", headers=_auth(user_token)).json()
        assert (prof.get("profile") or prof).get("pincode") == "600001"


class TestUdyamDataset:
    def test_demo_search_labelled(self, client, user_token):
        r = client.post("/api/v1/gov/udyaam/search", json={"query": "electronics", "state_code": "TN"}, headers=_auth(user_token)).json()
        assert r["ok"] is True
        assert r["mode"] == "DEMO" and r["verification_status"] == "DEMO"
        assert "DEMO DATA — NOT A LIVE GOVERNMENT CONNECTION" in r["message"]
        assert all("[DEMO]" in rec["enterprise_name"] and "[SYNTHETIC]" in rec["udyam_reference"] for rec in r["data"]["records"])

    def test_select_requires_confirmation(self, client, user_token):
        pid = _project(client, user_token)
        rec = {"enterprise_name": "Demo Electronics Private Limited [DEMO]", "udyam_reference": "UDYAM-TN-03-0001234 [SYNTHETIC]", "state": "Tamil Nadu", "district": "Chennai", "nic_activity": "Manufacture of electronic components (NIC 261)", "is_demo": True}
        r422 = client.post("/api/v1/gov/udyaam/select", json={"project_id": pid, "record": rec, "confirmation": False}, headers=_auth(user_token))
        assert r422.status_code == 422
        r = client.post("/api/v1/gov/udyaam/select", json={"project_id": pid, "record": rec, "confirmation": True}, headers=_auth(user_token)).json()
        assert r["ok"] is True
        assert r["reference"]["verification_status"] == "GOVERNMENT_DATASET_MATCH"
        assert "NOT a real-time verification" in r["reference"]["verification_label"]
        assert r["reference"]["is_demo"] is True
        refs = client.get(f"/api/v1/projects/{pid}/gov-references", headers=_auth(user_token)).json()["references"]
        assert refs and refs[0]["external_id"].startswith("UDYAM-TN")

    def test_select_enriches_profile(self, client, user_token):
        pid = _project(client, user_token, state_code="MH")  # deliberately different state
        rec = {"enterprise_name": "Demo Precision Components [DEMO]", "udyam_reference": "UDYAM-TN-11-0005678 [SYNTHETIC]", "state": "Tamil Nadu", "district": "Coimbatore", "nic_activity": "Manufacture of electronic assemblies (NIC 26)", "is_demo": True}
        r = client.post("/api/v1/gov/udyaam/select", json={"project_id": pid, "record": rec, "confirmation": True}, headers=_auth(user_token)).json()
        assert r["reference"]["applied"].get("state_code") == "TN"
        prof = (client.get(f"/api/v1/projects/{pid}/profile", headers=_auth(user_token)).json())
        prof = prof.get("profile") or prof
        assert prof.get("state_code") == "TN" and prof.get("district") == "Coimbatore"


class TestMCA:
    def test_pending_authorization(self, client, user_token):
        r = client.post("/api/v1/gov/mca/search", json={"query": "Demo Electronics Private Limited"}, headers=_auth(user_token)).json()
        assert r["ok"] is False
        assert r["mode"] == "PENDING_AUTHORIZATION"
        assert r["error_code"] == "NOT_PROVISIONED"
        assert "authorization" in r["message"].lower()
        assert r["fallback"]["official_portal_url"] == "https://www.mca.gov.in/"
        assert r["fallback"]["manual_steps"]
        # no fabricated company data
        assert "companies" not in json.dumps(r.get("data", {}))


class TestConsentAndDigiLocker:
    def test_consent_flow_and_gate(self, client, user_token):
        pid = _project(client, user_token)
        denied = client.post("/api/v1/gov/consent", json={"project_id": pid, "provider": "digilocker", "service": "Document retrieval", "purpose": "Fetch incorporation certificate", "accepted": False}, headers=_auth(user_token))
        assert denied.status_code == 201 and denied.json()["status"] == "DENIED"
        r = client.post("/api/v1/gov/consent", json={
            "project_id": pid, "provider": "digilocker", "service": "DigiLocker document retrieval (requester)",
            "purpose": "Fetch my issued Certificate of Incorporation for this project",
            "data_categories": ["Issued documents"], "documents_requested": ["Certificate of Incorporation"],
            "integration_mode": "PENDING_AUTHORIZATION", "accepted": True,
        }, headers=_auth(user_token))
        assert r.status_code == 201
        consent_id = r.json()["consent_id"]
        assert "revoke this consent" in r.json()["consent_text_shown"]
        listed = client.get("/api/v1/gov/consent", headers=_auth(user_token)).json()["consents"]
        assert any(c["consent_id"] == consent_id and c["status"] == "GRANTED" for c in listed)

        # retrieval is honest: consent present but integration not authorized
        req = client.post("/api/v1/gov/digilocker/request-document", json={"project_id": pid, "consent_id": consent_id, "document_type": "Certificate of Incorporation"}, headers=_auth(user_token)).json()
        assert req["ok"] is False
        assert "awaiting official partner authorization" in req["message"]
        assert req["fallback"]["official_portal_url"].startswith("https://www.digilocker.gov.in")
        assert "Upload it under Documents" in " ".join(req["fallback"]["manual_steps"])

        # revoke blocks further requests
        rv = client.post(f"/api/v1/gov/consent/{consent_id}/revoke", headers=_auth(user_token)).json()
        assert rv["status"] == "REVOKED"
        blocked = client.post("/api/v1/gov/digilocker/request-document", json={"project_id": pid, "consent_id": consent_id, "document_type": "Certificate of Incorporation"}, headers=_auth(user_token))
        assert blocked.status_code == 409

    def test_request_without_consent(self, client, user_token):
        pid = _project(client, user_token)
        r = client.post("/api/v1/gov/digilocker/request-document", json={"project_id": pid, "consent_id": 999999, "document_type": "PAN card"}, headers=_auth(user_token))
        assert r.status_code == 404


class TestCommandCenter:
    def test_payload(self, client, user_token):
        pid = _project(client, user_token, total_investment=250000000, number_of_employees=30)
        client.post(f"/api/v1/projects/{pid}/analysis", headers=_auth(user_token))
        r = client.get(f"/api/v1/projects/{pid}/command-center", headers=_auth(user_token)).json()
        assert {"readiness", "approvals_identified", "documents_ready", "critical_blockers", "integrations", "applications", "next_best_actions"} <= set(r)
        assert isinstance(r["readiness"]["overall"], int)
        assert "not a probability of approval" in r["readiness"]["disclaimer"]
        assert "/" in r["documents_ready"]
        assert r["integrations"]["note"].startswith("'Active' counts only provider-authorized")
        assert isinstance(r["next_best_actions"], list)


class TestAuditTrail:
    def test_provider_calls_audited(self, client, user_token, admin_token):
        pid = _project(client, user_token)
        client.post("/api/v1/gov/pincode-lookup", json={"pincode": "600001", "project_id": pid, "apply_to_profile": True}, headers=_auth(user_token))
        ev = client.get("/api/v1/admin/audit", params={"action": "GOV_DATA_PINCODE_LOOKUP", "limit": 5}, headers=_auth(admin_token)).json()["events"]
        assert ev and ev[0]["provider"] == "India Post (via data.gov.in)"
        assert ev[0]["correlation_id"].startswith("COR-")
