"""
Dynamic industry questionnaire (spec §4, §5).

Question selection is deterministic:
  1. start from the industry's declared question sets;
  2. for "Other" industries, derive sets from the free-text description;
  3. additionally, every question whose absence currently makes a catalogue rule
     UNDECIDABLE (UNKNOWN) is included — the questionnaire fills exactly the
     gaps the approval analysis reports;
  4. questions already answered, or provably irrelevant (their gate question
     was answered "no"), are dropped.

Each question carries `why_asked` so the UI can explain itself — the questionnaire
never asks an arbitrary question.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..ai.rule_engine import RuleContext, evaluate_rule, missing_facts_for
from ..knowledge.data.industries import INDUSTRY_BY_CODE, question_sets_from_description
from ..enums import Applicability
from ..services.profile_facts import build_facts

QUESTION_BANK: dict[str, list[dict[str, Any]]] = {
    "core": [
        {"key": "organization_name", "type": "text", "label": "Registered name of the business", "label_ta": "வணிகத்தின் பதிவு பெயர்", "label_hi": "व्यवसाय का पंजीकृत नाम", "field": "organization_name", "required": True},
        {"key": "organization_type", "type": "select", "label": "Type of organization", "field": "organization_type", "options": ["INDIVIDUAL", "PROPRIETORSHIP", "PARTNERSHIP", "LLP", "PRIVATE_LIMITED", "PUBLIC_LIMITED", "COOPERATIVE", "TRUST_SOCIETY", "PSU", "OTHER"], "required": True},
        {"key": "pan", "type": "text", "label": "PAN of the business (if available)", "field": "pan", "placeholder": "ABCDE1234F"},
        {"key": "gstin", "type": "text", "label": "GSTIN (if registered)", "field": "gstin"},
        {"key": "cin", "type": "text", "label": "CIN / LLP identification (if company or LLP)", "field": "cin"},
        {"key": "udyam_number", "type": "text", "label": "Udyam registration number (if registered)", "field": "udyam_number"},
    ],
    "operations": [
        {"key": "production_type", "type": "text", "label": "What will the unit produce or do?", "field": "production_type", "required": True},
        {"key": "production_capacity", "type": "text", "label": "Production capacity (e.g. units per year)", "field": "production_capacity"},
        {"key": "raw_materials", "type": "list", "label": "Main raw materials", "field": "raw_materials"},
    ],
    "water": [
        {"key": "water_consumption_kld", "type": "number", "label": "Water consumption (kilo-litres per day)", "field": "water_consumption_kld", "why": "Water use decides groundwater NOC, consent conditions and water connection requirements."},
        {"key": "wastewater_generated_kld", "type": "number", "label": "Wastewater / effluent generated (kilo-litres per day)", "field": "wastewater_generated_kld", "why": "Effluent quantity and characteristics drive consent-to-operate conditions."},
        {"key": "has_etp", "type": "boolean", "label": "Is an effluent treatment plant installed or planned?", "field": "has_etp"},
        {"key": "has_stp", "type": "boolean", "label": "Is a sewage treatment plant installed or planned?", "field": "has_stp"},
    ],
    "air": [
        {"key": "air_emissions_present", "type": "boolean", "label": "Will the unit emit smoke, dust, fumes or gases?", "field": "air_emissions_present", "why": "Air emissions determine the Air Act consent and stack requirements."},
        {"key": "emission_sources", "type": "list", "label": "Main emission sources (boiler, chimney, process vents…)", "field": "emission_sources"},
    ],
    "waste": [
        {"key": "hazardous_waste_generated", "type": "boolean", "label": "Will the unit generate hazardous waste (oils, chemicals, contaminated material)?", "field": "hazardous_waste_generated", "why": "Hazardous waste generation requires authorisation and manifest compliance."},
        {"key": "hazardous_waste_tpa", "type": "number", "label": "Approximate hazardous waste quantity (tonnes per year)", "field": "hazardous_waste_tpa"},
        {"key": "solid_waste_generated", "type": "boolean", "label": "Will the unit generate solid waste for disposal?", "field": "solid_waste_generated"},
        {"key": "biomedical_waste_generated", "type": "boolean", "label": "Will the unit generate bio-medical waste?", "field": "biomedical_waste_generated"},
        {"key": "construction_demolition_waste", "type": "boolean", "label": "Will construction & demolition waste be generated?", "field": "construction_demolition_waste"},
    ],
    "ewaste": [
        {"key": "e_waste_generated", "type": "boolean", "label": "Will the unit generate or handle e-waste (electronic scrap, end-of-life equipment)?", "field": "e_waste_generated", "why": "E-waste rules impose registration and EPR obligations."},
    ],
    "plastic": [
        {"key": "plastic_waste_generated", "type": "boolean", "label": "Will the unit generate plastic / packaging waste?", "field": "plastic_waste_generated", "why": "Plastic packaging triggers EPR registration."},
    ],
    "battery": [
        {"key": "uses_batteries", "type": "boolean", "label": "Will the products or operations use batteries?", "field": "uses_batteries", "why": "Battery Waste Rules impose producer obligations even on assemblers."},
        {"key": "battery_waste_generated", "type": "boolean", "label": "Will the unit handle used batteries?", "field": "battery_waste_generated"},
    ],
    "chemicals": [
        {"key": "uses_hazardous_chemicals", "type": "boolean", "label": "Will hazardous chemicals be stored or used?", "field": "uses_hazardous_chemicals", "why": "Threshold quantities decide MAH obligations under the MSIHC Rules."},
        {"key": "chemicals_used", "type": "list", "label": "List the main chemicals / solvents", "field": "chemicals_used"},
        {"key": "hazardous_substances", "type": "list", "label": "List hazardous substances and approximate quantities", "field": "hazardous_substances"},
        {"key": "is_mah_directed", "type": "boolean", "label": "Has the unit been classified as a Major Accident Hazard (MAH) installation?", "field": "is_mah_directed"},
    ],
    "fire": [
        {"key": "fire_risk_level", "type": "select", "label": "How would you describe the fire risk?", "field": "fire_risk_level", "options": ["LOW", "MEDIUM", "HIGH"], "why": "Fire risk and building size decide the Fire NOC requirement."},
    ],
    "boiler": [
        {"key": "has_boiler", "type": "boolean", "label": "Will a boiler or thermic fluid heater be installed?", "field": "has_boiler", "why": "Boilers must be registered and certified under the Indian Boilers Act."},
        {"key": "boiler_capacity_tph", "type": "number", "label": "Boiler capacity (tonnes per hour of steam)", "field": "boiler_capacity_tph"},
    ],
    "dgset": [
        {"key": "has_dg_set", "type": "boolean", "label": "Will a diesel generator set be installed?", "field": "has_dg_set", "why": "DG sets need consent conditions and electrical approval."},
        {"key": "dg_set_kva", "type": "number", "label": "DG set capacity (kVA)", "field": "dg_set_kva"},
    ],
    "electrical": [
        {"key": "electrical_load_kw", "type": "number", "label": "Connected electrical load (kW)", "field": "electrical_load_kw", "why": "Load decides DISCOM sanction and electrical inspectorate approval."},
        {"key": "htaht_connection_required", "type": "boolean", "label": "Will you need an HT (high tension) connection?", "field": "htaht_connection_required"},
    ],
    "labour": [
        {"key": "number_of_employees", "type": "number", "label": "Total employees expected", "field": "number_of_employees", "why": "Employee count triggers EPFO, ESIC and other labour registrations."},
        {"key": "workers_on_site", "type": "number", "label": "Workers on site at peak", "field": "workers_on_site"},
        {"key": "is_factory_under_factories_act", "type": "boolean", "label": "Is the unit a factory under the Factories Act (manufacturing process with workers)?", "field": "is_factory_under_factories_act", "why": "This decides factory licensing versus shops & establishments registration."},
        {"key": "uses_contract_labour", "type": "boolean", "label": "Will contract labour be engaged?", "field": "uses_contract_labour", "why": "Contract labour above thresholds requires principal-employer registration."},
        {"key": "operates_in_shifts", "type": "boolean", "label": "Will the unit operate in shifts?", "field": "operates_in_shifts"},
    ],
    "food": [
        {"key": "food_products", "type": "list", "label": "Food products to be manufactured / packed", "field": "extra.food_products", "why": "Product category decides the FSSAI licence level and standards that apply."},
    ],
    "pharma": [
        {"key": "drug_categories", "type": "list", "label": "Drug categories (tablets, injectables, APIs…)", "field": "extra.drug_categories", "why": "Categories decide the licence form and Schedule M requirements."},
    ],
    "mining": [
        {"key": "mineral_type", "type": "text", "label": "Mineral to be extracted", "field": "extra.mineral_type"},
        {"key": "lease_area", "type": "number", "label": "Lease / quarry area (hectares)", "field": "extra.lease_area", "why": "Area decides the environmental clearance category."},
    ],
    "construction": [
        {"key": "built_up_area_sqm", "type": "number", "label": "Total built-up area (square metres)", "field": "built_up_area_sqm", "why": "Built-up area decides building permission route and EIA applicability for construction projects."},
    ],
    "logistics": [
        {"key": "fleet_size", "type": "number", "label": "Number of vehicles in the fleet", "field": "extra.fleet_size"},
        {"key": "warehouse_area_sqm", "type": "number", "label": "Warehouse area (square metres)", "field": "built_up_area_sqm"},
    ],
    "renewable": [
        {"key": "renewable_capacity_mw", "type": "number", "label": "Installed / planned capacity (MW)", "field": "extra.renewable_capacity_mw", "why": "Capacity decides connectivity route and approval level."},
        {"key": "renewable_technology", "type": "select", "label": "Technology", "field": "extra.renewable_technology", "options": ["SOLAR_PV", "SOLAR_THERMAL", "WIND", "BIOGAS", "BIOMASS", "HYDRO", "GREEN_HYDROGEN", "BESS", "OTHER"]},
    ],
    "textile": [
        {"key": "wet_processing", "type": "boolean", "label": "Does the unit do wet processing (dyeing / bleaching / printing)?", "field": "extra.wet_processing", "why": "Wet processing attracts ZLD/CETP conditions in many states."},
    ],
    "export": [
        {"key": "is_export_oriented", "type": "boolean", "label": "Will the unit export goods or services?", "field": "is_export_oriented", "why": "Export activity requires an IEC and may unlock export schemes."},
        {"key": "export_annual", "type": "number", "label": "Expected annual exports (₹)", "field": "export_annual"},
        {"key": "import_annual", "type": "number", "label": "Expected annual imports (₹)", "field": "import_annual"},
    ],
    "biotech": [
        {"key": "biological_agents", "type": "boolean", "label": "Will biological agents / GMOs be handled?", "field": "extra.biological_agents", "why": "Handling biological material attracts biosafety and bio-medical waste rules."},
        {"key": "containment_level", "type": "select", "label": "Containment level (if known)", "field": "extra.containment_level", "options": ["BSL_1", "BSL_2", "BSL_3", "NOT_KNOWN"]},
    ],
    "recycling": [
        {"key": "input_material", "type": "text", "label": "Main input material to be recycled / recovered", "field": "extra.input_material"},
    ],
    "it": [
        {"key": "it_export", "type": "boolean", "label": "Will software / ITES services be exported?", "field": "is_export_oriented"},
        {"key": "data_centre", "type": "boolean", "label": "Does the project include a data centre?", "field": "extra.data_centre"},
    ],
    "automobile": [
        {"key": "paint_shop", "type": "boolean", "label": "Will there be a paint shop?", "field": "extra.paint_shop", "why": "Paint shops are a major VOC source affecting consent conditions."},
    ],
    "engineering": [
        {"key": "surface_treatment", "type": "boolean", "label": "Will surface treatment (plating / anodising / pickling) be done?", "field": "extra.surface_treatment", "why": "Metal finishing effluent strongly affects consent conditions."},
    ],
    "agri": [
        {"key": "produce_handled", "type": "text", "label": "Main produce handled / processed", "field": "extra.produce_handled"},
        {"key": "cold_chain", "type": "boolean", "label": "Is cold-chain storage involved?", "field": "extra.cold_chain"},
    ],
}

GATES: dict[str, list[str]] = {
    "water": [],
    "air": ["air_emissions_present"],
    "waste": [],
    "boiler": ["has_boiler"],
    "dgset": ["has_dg_set"],
    "battery": ["uses_batteries", "battery_waste_generated"],
}


def _industry_question_sets(project: models.Project) -> list[str]:
    profile = project.profile
    code = (profile.industry_code if profile else None) or ""
    sets: list[str] = ["core", "operations"]
    if code == "other":
        desc = " ".join(str(x or "") for x in (profile.industry_other_description, profile.production_type, profile.sub_industry, project.description)) if profile else ""
        sets.extend(question_sets_from_description(desc))
    else:
        ind = INDUSTRY_BY_CODE.get(code)
        if ind:
            sets.extend(ind.get("question_sets") or [])
    # dedupe, preserve order
    seen: set[str] = set()
    out = []
    for s in sets:
        if s not in seen and s in QUESTION_BANK:
            seen.add(s)
            out.append(s)
    return out


def build_questionnaire(db: Session, project: models.Project) -> dict[str, Any]:
    """Compute the dynamic question list from industry + current gaps."""
    profile = project.profile
    facts = build_facts(project, profile)
    ctx = RuleContext.build(facts)
    answered_keys = {a.question_key for a in db.scalars(select(models.QuestionnaireAnswer).where(models.QuestionnaireAnswer.project_id == project.id))}

    sets = _industry_question_sets(project)

    # gap-driven additions: facts referenced by currently-undecidable rules
    templates = db.scalars(select(models.ApprovalTemplate).where(models.ApprovalTemplate.is_active.is_(True))).all()
    rules = db.scalars(select(models.ApprovalRule).where(models.ApprovalRule.is_active.is_(True))).all()
    rules_by_template: dict[int, list[models.ApprovalRule]] = {}
    for r in rules:
        rules_by_template.setdefault(r.template_id, []).append(r)
    for tpl in templates:
        for rule in rules_by_template.get(tpl.id, []):
            result = evaluate_rule(rule.condition, ctx, rule.rule_key)
            if result.produced == "UNKNOWN":
                for qset in _sets_for_fact_keys(result.facts_missing):
                    if qset not in sets:
                        sets.append(qset)

    questions: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for qset in sets:
        gate = GATES.get(qset, [])
        gate_open = all(facts.get(g) not in (None, "", False, []) for g in gate)
        for q in QUESTION_BANK.get(qset, []):
            key = q["key"]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            # gate-closed questions are hidden entirely (spec: don't ask irrelevant questions)
            if not gate_open and qset in ("air", "boiler", "dgset", "battery"):
                # keep the gate question itself, drop the rest
                if key not in gate:
                    continue
            item = dict(q)
            item["question_set"] = qset
            item["answered"] = key in answered_keys or _fact_filled(facts, q.get("field"))
            if key not in answered_keys and not item["answered"]:
                questions.append(item)

    return {
        "question_sets": sets,
        "questions": questions,
        "answered_count": len(seen_keys) - len(questions),
        "total_count": len(seen_keys),
    }


def _fact_filled(facts: dict[str, Any], field: str | None) -> bool:
    if not field:
        return False
    val = facts.get(field.removeprefix("extra."))
    return val not in (None, "", [], False)


def _sets_for_fact_keys(keys: list[str]) -> list[str]:
    mapping = {
        "has_boiler": ["boiler"], "boiler_capacity_tph": ["boiler"],
        "has_dg_set": ["dgset"], "dg_set_kva": ["dgset"],
        "water_consumption_kld": ["water"], "wastewater_generated_kld": ["water"],
        "air_emissions_present": ["air"], "emission_sources": ["air"],
        "hazardous_waste_generated": ["waste"], "hazardous_waste_tpa": ["waste"],
        "e_waste_generated": ["ewaste"], "plastic_waste_generated": ["plastic"],
        "uses_batteries": ["battery"], "battery_waste_generated": ["battery"],
        "uses_hazardous_chemicals": ["chemicals"], "hazardous_substances": ["chemicals"],
        "fire_risk_level": ["fire"], "electrical_load_kw": ["electrical"], "htaht_connection_required": ["electrical"],
        "number_of_employees": ["labour"], "workers_on_site": ["labour"], "uses_contract_labour": ["labour"],
        "is_factory_under_factories_act": ["labour"],
        "built_up_area_sqm": ["construction"], "is_export_oriented": ["export"],
        "export_annual": ["export"], "import_annual": ["export"],
    }
    out: list[str] = []
    for k in keys:
        for s in mapping.get(k, []):
            if s not in out:
                out.append(s)
    return out


def save_answers(db: Session, project: models.Project, answers: list[dict[str, Any]], user: models.User | None) -> int:
    """Persist questionnaire answers into the profile (typed columns when they
    map, `extra` otherwise). Returns count saved."""
    profile = project.profile
    if profile is None:
        profile = models.ProjectProfile(project_id=project.id)
        db.add(profile)
        db.flush()
    saved = 0
    for ans in answers:
        key = ans.get("key")
        if not key:
            continue
        value = ans.get("value")
        field = ans.get("field") or key
        qset = ans.get("question_set") or "custom"
        why = ans.get("why_asked")
        row = db.scalars(
            select(models.QuestionnaireAnswer).where(
                models.QuestionnaireAnswer.project_id == project.id,
                models.QuestionnaireAnswer.question_key == key,
            )
        ).first()
        if row is None:
            row = models.QuestionnaireAnswer(project_id=project.id, question_key=key)
            db.add(row)
        row.value = value
        row.question_set = qset
        row.answered_by = user.id if user else None
        row.why_asked = why
        _set_profile_value(profile, field, value)
        saved += 1
    db.flush()
    return saved


def _coerce(value: Any, current: Any) -> Any:
    """Coerce incoming JSON values to the profile column type."""
    if value is None:
        return None
    if isinstance(current, bool) or (current is None and isinstance(value, bool)):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
    if isinstance(current, (int, float)) and not isinstance(current, bool):
        try:
            return float(value) if isinstance(current, float) else int(float(value))
        except (TypeError, ValueError):
            return None
    return value


def _set_profile_value(profile: models.ProjectProfile, field: str, value: Any) -> None:
    if field.startswith("extra."):
        extra = dict(profile.extra or {})
        extra[field[6:]] = value
        profile.extra = extra
        return
    if field == "industry_code":
        profile.industry_code = value
        return
    if hasattr(profile, field):
        current = getattr(profile, field)
        coerced = _coerce(value, current)
        if coerced is not None or value is None:
            setattr(profile, field, coerced)
