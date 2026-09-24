"""MSMED Act, 2006 — regulatory knowledge layer (MSME Regulatory Intelligence).

HONESTY CONTRACT
----------------
* Every summary here is an AUTHORED digest of the Act's provisions, not a
  quotation of legal text. Each entry carries verification_status =
  REQUIRES_VERIFICATION and the official source (India Code / msme.gov.in) so
  the user can always check the original.
* Section applicability is NEVER automatic — msme_engine evaluates the
  conditions against the project profile.
* §7 classification limits are VERSIONED: the classification thresholds have
  changed (2006 original → MSMED (Amendment) Act 2018, effective 01.07.2020 →
  2025 revision announced in Union Budget 2025-26). The engine applies the
  latest version and the API surfaces the version table + a freshness warning.
* Nothing here claims to be the latest applicable law — see VERSION_WARNING.
"""
from __future__ import annotations

from typing import Any

SOURCE_INDIA_CODE = "https://www.indiacode.nic.in/handle/123456789/1977"
SOURCE_MSME = "https://msme.gov.in/"
SOURCE_UDYAM = "https://udyamregistration.gov.in/"
SOURCE_SAMADHAAN = "https://samadhaan.msme.gov.in/"
SOURCE_MAITRI = "https://maitri.maharashtra.gov.in/"

VERIFICATION_STATUS = "REQUIRES_VERIFICATION"
AUTHORED_NOTE = "Authored digest for navigation — verify against the Act text at the official source before relying on it."

VERSION_WARNING = (
    "MSMED classification thresholds have been amended more than once (2006 original; MSMED (Amendment) Act, "
    "2018 effective 01.07.2020; 2025 revision announced in Union Budget 2025-26). NIECP-AI applies the latest "
    "version in this knowledge base, but you MUST verify the currently-applicable notification on the official "
    "portal before relying on a classification. This knowledge base may not represent the latest applicable law."
)

# ═════════════════════════ §7 classification — VERSIONED (§10) ═════════════════════════
LAW_VERSIONS: list[dict[str, Any]] = [
    {
        "version": "v3-2025",
        "act": "Micro, Small and Medium Enterprises Development Act, 2006 — §7 (as amended)",
        "amendment": "Union Budget 2025-26 revision of investment & turnover limits",
        "effective_date": "2025-04-01",
        "source": SOURCE_MSME,
        "status": "PENDING_VERIFICATION",
        "status_note": "Announced in Budget 2025-26; confirm the exact effective date/notification on msme.gov.in before relying on these limits.",
        "sections": ["7"],
        "classification": {
            "MICRO": {"investment_max_cr": 2.5, "turnover_max_cr": 10},
            "SMALL": {"investment_max_cr": 25, "turnover_max_cr": 100},
            "MEDIUM": {"investment_max_cr": 125, "turnover_max_cr": 500},
        },
        "note": "Composite criteria (investment in plant & machinery/equipment AND annual turnover). Both must fall within the class limits.",
    },
    {
        "version": "v2-2020",
        "act": "Micro, Small and Medium Enterprises Development Act, 2006 — §7 (as amended)",
        "amendment": "MSMED (Amendment) Act, 2018 — investment + turnover composite criteria",
        "effective_date": "2020-07-01",
        "source": SOURCE_MSME,
        "status": "SUPERSEDED",
        "status_note": "Replaced by the 2025 revision (verify the supersession on the official portal).",
        "sections": ["7"],
        "classification": {
            "MICRO": {"investment_max_cr": 1, "turnover_max_cr": 5},
            "SMALL": {"investment_max_cr": 10, "turnover_max_cr": 50},
            "MEDIUM": {"investment_max_cr": 50, "turnover_max_cr": 250},
        },
        "note": "Historical version retained for version control (§10).",
    },
    {
        "version": "v1-2006",
        "act": "Micro, Small and Medium Enterprises Development Act, 2006 — §7 (original)",
        "amendment": "Original enactment (investment-only criteria)",
        "effective_date": "2006-10-02",
        "source": SOURCE_INDIA_CODE,
        "status": "SUPERSEDED",
        "status_note": "Historical version retained for version control.",
        "sections": ["7"],
        "classification": {
            "MANUFACTURING_MICRO": {"investment_max_lakh": 25},
            "MANUFACTURING_SMALL": {"investment_max_lakh": 500},
            "MANUFACTURING_MEDIUM": {"investment_max_lakh": 1000},
        },
        "note": "Pre-2018 investment-only criteria. Historical reference only.",
    },
]

# The version the engine applies (latest first entry). Not hard-coded as "current law
# forever" — the API always exposes the full table + VERSION_WARNING.
CURRENT_VERSION_ID = LAW_VERSIONS[0]["version"]

RBI_BANK_RATE_FALLBACK = 0.09  # used ONLY as a labelled placeholder for §15 interest math
RBI_BANK_RATE_NOTE = "Placeholder reference rate — verify the current RBI bank rate; the actual §15 rate is 3× the RBI bank rate with compound interest, monthly rests."

# ═══════════════════════════════════ PROVISIONS (§1, §9) ═══════════════════════════════

def P_(**kw) -> dict[str, Any]:
    kw.setdefault("verification_status", VERIFICATION_STATUS)
    kw.setdefault("authored_note", AUTHORED_NOTE)
    kw.setdefault("act", "MSMED Act, 2006")
    return kw


PROVISIONS: dict[str, dict[str, Any]] = {
    "7": P_(
        section="7", title="Classification of enterprises",
        topic="MSME classification",
        summary=(
            "Enterprises are classified as Micro, Small or Medium based on composite criteria: investment in plant "
            "and machinery or equipment AND annual turnover, as notified from time to time."
        ),
        applicability_conditions=["Any enterprise engaging in manufacture/production or providing services", "Investment and turnover figures available"],
        required_inputs=["machinery_investment", "annual_turnover", "activity type (manufacturing/services)"],
        required_documents=["Udyam registration certificate (if registered)", "Audited accounts / ITR turnover figures (user-provided)"],
        trigger="Always evaluated when the project has investment or turnover data",
        recommended_action="Check classification; if Micro/Small, consider Udyam registration (§8) and the resulting benefits",
        authority="Ministry of MSME, Government of India",
        official_source=SOURCE_MSME,
        legal_basis_note="Classification thresholds are notification-driven and versioned — see LAW_VERSIONS.",
    ),
    "8": P_(
        section="8", title="Memorandum of registration (Udyam)",
        topic="MSME registration / formalisation",
        summary=(
            "Micro and Small enterprises should file a memorandum of registration (Udyam Registration) on the "
            "official portal; no fee is charged. Medium enterprises file as per the rules but the MSME benefit "
            "framework (e.g., delayed-payment protection) targets Micro & Small suppliers."
        ),
        applicability_conditions=["Enterprise classifies as Micro or Small under §7", "Not already registered (check Udyam number in profile)"],
        required_inputs=["current classification", "udyam_number (if any)", "PAN", "organization details"],
        required_documents=["Aadhaar/PAN of entrepreneur", "Business address proof", "Bank details (per Udyam portal)"],
        trigger="Profile classifies as MICRO/SMALL and udyam_number is missing",
        recommended_action="Register on the official Udyam portal (free) and record the Udyam number in the project profile",
        authority="Ministry of MSME (Udyam portal)",
        official_source=SOURCE_UDYAM,
        legal_basis_note="Also governed by Udyam Registration Rules, 2020 (verify current rules).",
    ),
    "9": P_(
        section="9", title="Promotion and development measures",
        topic="Government support",
        summary="The Central Government may specify measures for promotion and development of MSMEs (schemes, guidelines, programmes).",
        applicability_conditions=["Enterprise is Micro/Small/Medium", "Scheme-specific conditions apply per scheme"],
        required_inputs=["classification", "industry", "state"],
        required_documents=["Scheme-specific (see NIECP-AI scheme matching)"],
        trigger="Classification exists and scheme matching is available",
        recommended_action="Review the Schemes module for scheme-specific, criteria-based matching (separate from this Act)",
        authority="Ministry of MSME",
        official_source=SOURCE_MSME,
        legal_basis_note="Informational pointer — actual scheme eligibility is evaluated by NIECP-AI's scheme engine with its own documented criteria.",
    ),
    "10": P_(
        section="10", title="Credit facilities",
        topic="Credit",
        summary="Policies/Directions may be issued to banks and financial institutions for timely and smooth credit to MSMEs.",
        applicability_conditions=["Enterprise needs institutional credit"],
        required_inputs=["classification", "banking relationships"],
        required_documents=["Udyam certificate (commonly required by lenders)", "Project report, financials"],
        trigger="Classification is MICRO or SMALL",
        recommended_action="Keep the Udyam certificate current; ask your lender about MSME credit policies (NIECP-AI does not intermediate credit)",
        authority="RBI / Department of Financial Services (policy)",
        official_source=SOURCE_MSME,
        legal_basis_note="Informational — RBI directions govern implementation.",
    ),
    "11": P_(
        section="11", title="Procurement preference / central purchases",
        topic="Procurement-related provisions",
        summary=(
            "The Central Government may direct its departments/undertakings to procure exclusively or preferentially "
            "from Micro and Small enterprises, per notified policy (e.g., public procurement policy for MSEs)."
        ),
        applicability_conditions=["Enterprise is Micro or Small", "Enterprise supplies to Central Government departments/PSUs"],
        required_inputs=["classification", "does the enterprise sell to government buyers?"],
        required_documents=["Udyam registration", "NSIC/other empanelment where the buyer requires it (verify per buyer policy)"],
        trigger="Classification is MICRO or SMALL AND the project indicates government supply interest (CONDITIONAL until confirmed)",
        recommended_action="If you supply to government buyers, keep Udyam + empanelment current; check buyer-specific MSE procurement conditions",
        authority="Ministry of MSME / procuring departments",
        official_source=SOURCE_MSME,
        legal_basis_note="Procurement percentages/targets are policy-driven; verify the current policy.",
    ),
    "15": P_(
        section="15", title="Liability of buyer to make interest payment",
        topic="Delayed payments",
        summary=(
            "Where a buyer fails to make payment to a Micro/Small supplier beyond the agreed payment period, or in "
            "the absence of an agreement beyond the day immediately following acceptance (with the notified default "
            "period — commonly cited as 45 days per the 2018 amendment and Udyam portal guidance), the buyer is "
            "liable to pay compound interest with monthly rests at three times the RBI bank rate."
        ),
        applicability_conditions=["Supplier is a registered Micro/Small enterprise", "Goods/services supplied and accepted (or deemed accepted)", "Payment delayed beyond the applicable period"],
        required_inputs=["invoice_date", "supply/acceptance date", "payment terms (days)", "amount", "supplier classification", "payment_date (if paid)"],
        required_documents=["Invoice(s)", "Delivery/challan proof", "Udyam certificate of the supplier", "Correspondence"],
        trigger="Payment Protection assessment detects a delay for a Micro/Small supplier",
        recommended_action="Compute the assessment, raise a written claim with interest, then use Samadhaan / MSEFC (§18) if unpaid",
        authority="MSE Facilitation Council (enforcement via §18)",
        official_source=SOURCE_SAMADHAAN,
        legal_basis_note="The exact default period and rate require verification against the current Act text and RBI bank rate.",
    ),
    "16": P_(
        section="16", title="Interest payable to supplier",
        topic="Delayed payments",
        summary="Interest at the §15 rate is payable to the Micro/Small supplier on the amount due, irrespective of anything contrary in any agreement (subject to the Act's provisions).",
        applicability_conditions=["Amounts due to a Micro/Small supplier remain unpaid"],
        required_inputs=["same as §15"],
        required_documents=["same as §15"],
        trigger="Detected alongside §15",
        recommended_action="Include statutory interest in the claim computation (see Payment Protection)",
        authority="MSE Facilitation Council",
        official_source=SOURCE_SAMADHAAN,
        legal_basis_note="Verify against current text.",
    ),
    "17": P_(
        section="17", title="Recovery of amount due",
        topic="Delayed payments — recovery",
        summary="Provisions for recovery of amounts due to Micro/Small suppliers (institutional mechanisms backing the interest/due recovery process).",
        applicability_conditions=["A §15/§16 amount remains unpaid after follow-up"],
        required_inputs=["unpaid principal + computed interest", "supplier Udyam registration"],
        required_documents=["Claim application to the Facilitation Council", "Invoices and delivery evidence"],
        trigger="Delay flagged and informal recovery failed (CONDITIONAL)",
        recommended_action="File a reference with the MSE Facilitation Council (§18)",
        authority="MSE Facilitation Council / State Government",
        official_source=SOURCE_SAMADHAAN,
        legal_basis_note="Verify against current text.",
    ),
    "18": P_(
        section="18", title="Reference to MSE Facilitation Council",
        topic="MSEFC pathway",
        summary=(
            "A supplier may approach the MSE Facilitation Council of the State where the buyer's premises are "
            "located, for pending payment matters; the Council conducts proceedings (with the micro/small-enterprise "
            "declaration requirement) and its awards are enforceable (as a decree, per the Act's provisions)."
        ),
        applicability_conditions=["Supplier is Micro/Small with Udyam registration", "Payment pending beyond the statutory period", "Reference not already decided between the parties"],
        required_inputs=["buyer state (council jurisdiction)", "unpaid amount", "invoice/acceptance dates"],
        required_documents=["Udyam registration", "Case memorandum with invoices", "Proof of supply/acceptance"],
        trigger="Delayed payment confirmed AND informal claim unsuccessful",
        recommended_action="Prepare the MSEFC reference for the buyer's State council; track via the Samadhaan portal",
        authority="MSE Facilitation Council (buyer's State)",
        official_source=SOURCE_SAMADHAAN,
        legal_basis_note="Council procedure per §18 read with §§20-21 and the MSMED Rules.",
    ),
    "20": P_(
        section="20", title="Establishment of MSE Facilitation Councils",
        topic="MSEFC",
        summary="State Governments establish one or more MSE Facilitation Councils for the purposes of the Act.",
        applicability_conditions=["Informational — council infrastructure exists in every State"],
        required_inputs=[], required_documents=[],
        trigger="Shown as part of the MSEFC pathway context",
        recommended_action="Locate the council for the buyer's State via the Samadhaan portal / State MSME department",
        authority="State Governments",
        official_source=SOURCE_SAMADHAAN,
        legal_basis_note="Informational.",
    ),
    "21": P_(
        section="21", title="Composition of MSE Councils",
        topic="MSEFC",
        summary="Specifies the composition of Facilitation Councils (Chairperson and members representing MSME interests, banks, State bodies).",
        applicability_conditions=["Informational"],
        required_inputs=[], required_documents=[],
        trigger="Shown as part of the MSEFC pathway context",
        recommended_action="Informational",
        authority="State Governments",
        official_source=SOURCE_SAMADHAAN,
        legal_basis_note="Informational.",
    ),
    "22": P_(
        section="22", title="Buyer's disclosure of unpaid amounts in annual accounts",
        topic="Annual-account disclosure",
        summary="Buyers must disclose, in their annual statements of accounts, the principal amount and interest due to Micro/Small suppliers remaining unpaid beyond the appointed day.",
        applicability_conditions=["The enterprise is a BUYER procuring from Micro/Small suppliers"],
        required_inputs=["does the enterprise buy from Micro/Small suppliers?", "accounting period"],
        required_documents=["Annual accounts working papers"],
        trigger="Profile indicates the enterprise buys from MSME suppliers (CONDITIONAL — needs confirmation)",
        recommended_action="If you procure from MSME suppliers, ensure the §22 disclosure in your annual accounts (with your accountant)",
        authority="Company auditor / MCA reporting framework",
        official_source=SOURCE_INDIA_CODE,
        legal_basis_note="Verify disclosure format against current text/accounting standards.",
    ),
    "23": P_(
        section="23", title="Interest not deductible for tax",
        topic="Tax treatment",
        summary="The amount of interest payable/preferred under §§15-16 is not, for income-tax purposes, deductible from the buyer's income.",
        applicability_conditions=["The enterprise is a BUYER paying §15/§16 interest"],
        required_inputs=["buyer scenario confirmed"],
        required_documents=["Tax computation working papers"],
        trigger="§15/§16 liability exists for the enterprise as buyer",
        recommended_action="Discuss the non-deductibility with your tax advisor (NIECP-AI gives no tax advice)",
        authority="Income Tax Department (read with the Income-tax Act)",
        official_source=SOURCE_INDIA_CODE,
        legal_basis_note="Informational pointer; consult a tax professional.",
    ),
    "24": P_(
        section="24", title="Overriding effect",
        topic="General",
        summary="The MSMED Act's provisions (Chapter V — delayed payments) have effect notwithstanding anything inconsistent contained in any other law or instrument (subject to the Act's own exceptions, including the 2018 amendment's conditions).",
        applicability_conditions=["Informational — relevant when contracts attempt to waive MSME protections"],
        required_inputs=[], required_documents=[],
        trigger="Displayed for awareness in Payment Protection results",
        recommended_action="Informational — inconsistent contract terms may be ineffective; seek legal counsel for specifics",
        authority="—",
        official_source=SOURCE_INDIA_CODE,
        legal_basis_note="Informational.",
    ),
    "27": P_(
        section="27", title="Penalties",
        topic="Penalties",
        summary="Contraventions of the registration-related provisions (e.g., §8 read with §26) attract penalties as specified in the Act (summary digest — verify quantum in the current text).",
        applicability_conditions=["Relevant when registration obligations are breached"],
        required_inputs=["registration status"],
        required_documents=[],
        trigger="Registration check finds an unregistered Micro/Small enterprise (informational severity)",
        recommended_action="Regularise the registration via the Udyam portal",
        authority="Adjudicating officer per the Act",
        official_source=SOURCE_INDIA_CODE,
        legal_basis_note="Penalty amounts have been amended historically — verify the current text.",
    ),
}

# ═══════════════════════ Maharashtra MAITRI service layer (§8) ═══════════════════════
# Portal URL is the verified official channel. Individual deep links are NOT
# fabricated — every entry points to the official MAITRI portal and each service
# is labelled REQUIRES_VERIFICATION (confirm the live catalogue on the portal).

def M_(**kw) -> dict[str, Any]:
    kw.setdefault("state_code", "MH")
    kw.setdefault("official_channel", SOURCE_MAITRI)
    kw.setdefault("verification_status", "REQUIRES_VERIFICATION")
    kw.setdefault("integration_mode", "OFFICIAL_REDIRECT")
    kw.setdefault("sub_department", None)
    kw.setdefault("description", kw.get("why"))
    # TAT is shown ONLY where officially documented — NIECP-AI does not invent
    # turnaround times. None means "not officially documented in our sources".
    kw.setdefault("tat_days", None)
    kw.setdefault("tat_note", "Turnaround time not officially documented in NIECP-AI's sources — confirm on the MAITRI portal.")
    kw.setdefault("approval_links", [])
    kw.setdefault("note", "Confirm the current service catalogue and requirements on the official MAITRI portal.")
    return kw


MAITRI_SERVICES: list[dict[str, Any]] = [
    M_(code="maitri_registration", name="Investor registration & project registration",
       department="Maharashtra Industrial Development (via MAITRI portal)",
       why="Entry point for state investor facilitation — registers your project with the State for single-window processing.",
       required_info=["Business identity", "Project details", "Investment & employment figures"],
       dependency="Business registration (company/LLP/partnership)",
       keywords=["NEW_PROJECT", "APPROVALS_IN_PROGRESS"]),
    M_(code="maitri_approval_facilitation", name="Single-window approval facilitation",
       department="MAITRI facilitation desk",
       sub_department="Concerned department desk (assigned per service)",
       why="Routes state approvals (power, water, land, pollution, labour) through the state single window.",
       required_info=["Approval map (NIECP-AI analysis)", "Site details", "Sector details"],
       dependency="Project registration on MAITRI",
       approval_links=[
           {"approval": "Consent to Establish (CTE)", "authority": "Maharashtra Pollution Control Board (MPCB)",
            "mapping_type": "ROUTED_VIA_SINGLE_WINDOW_FACILITATION", "verification_status": "REQUIRES_VERIFICATION",
            "note": "Commonly routed via the state single window — confirm the corresponding MAITRI service on the official portal. NIECP-AI does not map specific MAITRI service IDs."},
           {"approval": "Consent to Operate (CTO)", "authority": "Maharashtra Pollution Control Board (MPCB)",
            "mapping_type": "ROUTED_VIA_SINGLE_WINDOW_FACILITATION", "verification_status": "REQUIRES_VERIFICATION",
            "note": "Commonly routed via the state single window — confirm on the official portal."},
           {"approval": "Factory/establishment registrations (state desks)", "authority": "Concerned Maharashtra departments",
            "mapping_type": "ROUTED_VIA_SINGLE_WINDOW_FACILITATION", "verification_status": "REQUIRES_VERIFICATION",
            "note": "Department desks vary — confirm the live catalogue on the official portal."},
       ],
       keywords=["APPLIES", "ENVIRONMENT", "UTILITIES", "LABOUR"]),
    M_(code="maitri_incentives", name="Industrial promotion / incentive claims",
       department="State industries department (per applicable state policy)",
       why="State incentive packages (per the then-current policy) are processed through MAITRI; eligibility depends on sector/district/investment.",
       required_info=["Udyam registration", "Investment proof", "Policy-specific declarations"],
       dependency="Udyam registration; policy-specific conditions apply",
       keywords=["MICRO", "SMALL", "MEDIUM"]),
    M_(code="maitri_land", name="Industrial land/allotment enquiry (MIDC-linked)",
       department="MIDC (via MAITRI facilitation)",
       why="For projects seeking industrial plot allotment or MIDC tenancy changes.",
       required_info=["Land requirement", "District preference", "Project profile"],
       dependency="Project registration",
       keywords=["LAND_IDENTIFIED", "PLANNING"]),
    M_(code="maitri_power", name="Industrial power connection facilitation (MSEDCL-linked)",
       department="MSEDCL (via MAITRI facilitation)",
       why="HT/LT industrial connection facilitation for manufacturing units.",
       required_info=["Sanctioned/required load (kW)", "Site documents"],
       dependency="Premises/land documentation",
       keywords=["HT_CONNECTION", "POWER"]),
    M_(code="maitri_expansion", name="Expansion/modification facilitation",
       department="MAITRI facilitation desk",
       why="For existing Maharashtra units undertaking expansion (capacity, product line).",
       required_info=["Existing approvals", "Expansion investment"],
       dependency="Existing unit registrations",
       keywords=["EXPANSION"]),
]


def maitri_for_state(state_code: str | None) -> list[dict[str, Any]]:
    """MAITRI is Maharashtra's portal — only relevant for MH projects."""
    if (state_code or "").upper() != "MH":
        return []
    return MAITRI_SERVICES


# Authored guidance on how known state approvals relate to the MAITRI route.
# mapping_type is always ROUTED_VIA_SINGLE_WINDOW_FACILITATION (generic) —
# NIECP-AI never claims a specific MAITRI service ID or a live API mapping.
MAITRI_APPROVAL_ROUTES: list[dict[str, Any]] = [
    {
        "approval_category": "ENVIRONMENT",
        "authority_match": ["MPCB", "MAHARASHTRA POLLUTION CONTROL BOARD"],
        "maitri_service_code": "maitri_approval_facilitation",
        "mapping_type": "ROUTED_VIA_SINGLE_WINDOW_FACILITATION",
        "verification_status": "REQUIRES_VERIFICATION",
        "note": "Environmental consents (MPCB CTE/CTO) are commonly facilitated via the state single window — confirm the corresponding MAITRI service on the official portal.",
    },
    {
        "approval_category": None,
        "authority_match": None,
        "maitri_service_code": "maitri_registration",
        "mapping_type": "ENTRY_POINT",
        "verification_status": "REQUIRES_VERIFICATION",
        "note": "Project registration is the MAITRI entry point for state facilitation.",
    },
]


def maitri_route_for_approval(category: str | None, authority: str | None) -> dict[str, Any] | None:
    """Authored route for one approval (category/authority) — REQUIRES_VERIFICATION."""
    auth = (authority or "").upper()
    for route in MAITRI_APPROVAL_ROUTES:
        if route.get("approval_category") and category and route["approval_category"] == str(category).upper():
            return route
        if route.get("authority_match") and any(a in auth for a in route["authority_match"]):
            return route
    # fall back to the generic entry point
    return MAITRI_APPROVAL_ROUTES[-1]
