"""
Idempotent seeding: reference catalogues, an admin bootstrap, and CLEARLY
LABELLED demo data (spec §54).

Demo discipline:
 * every demo record carries is_demo=True on the ORM row;
 * demo application statuses are shown with a DEMO badge in the UI;
 * demo accounts are isolated in their own organization and can be deleted in
   one action from the admin panel;
 * demo content demonstrates platform mechanics only — it never imitates a
   government communication.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..enums import (
    AccountStatus,
    ApplicationStatus,
    DocumentCategory,
    DocumentStatus,
    EnterpriseClass,
    InspectionStatus,
    NotificationType,
    OrgRole,
    OrganizationType,
    PlatformRole,
    ProjectStage,
    ProjectType,
    QueryStatus,
    RenewalStatus,
    SourceStatus,
    SubmissionChannel,
    TaskPriority,
    TaskStatus,
)
from ..security import hash_password
from . import notifications as notification_service
from .approval_engine import run_discovery
from .portal_seed import seed_reference_data

log = logging.getLogger("niecp.seed")


def needs_seeding(db: Session) -> bool:
    return db.scalar(select(func.count(models.User.id))) == 0


def run_seed(db: Session) -> dict[str, object]:
    counts = seed_reference_data(db)

    admin = db.scalars(select(models.User).where(models.User.platform_role == PlatformRole.SYSTEM_ADMIN)).first()
    if admin is None:
        # Bootstrap admin for the demonstration deployment. The password is
        # documented in the README and the account is flagged to force a
        # rotation; production deployments must set their own via the env
        # (NIECP_SECRET_KEY) and rotate immediately.
        admin = models.User(
            email="admin@niecp.local",
            email_normalized="admin@niecp.local",
            password_hash=hash_password("NIECP-Admin!2026"),
            full_name="System Administrator",
            platform_role=PlatformRole.SYSTEM_ADMIN,
            status=AccountStatus.ACTIVE,
            email_verified_at=datetime.utcnow(),
            avatar_color="#7c3aed",
            must_change_password=True,
            onboarding_completed_at=datetime.utcnow(),
        )
        db.add(admin)
        db.flush()
        db.add(models.UserPreference(user_id=admin.id))
        counts["admin_created"] = True  # type: ignore[assignment]
        counts["admin_email"] = "admin@niecp.local"  # type: ignore[assignment]
    db.flush()

    if not db.scalars(select(models.Project).where(models.Project.is_demo.is_(True))).first():
        create_demo_data(db)
    db.commit()
    return counts


def create_demo_data(db: Session) -> None:
    """A fully labelled demo organization + electronics manufacturing project."""
    demo_owner = models.User(
        email="demo@niecp.local",
        email_normalized="demo@niecp.local",
        password_hash=hash_password("Demo!Demo!123"),
        full_name="Demo Applicant",
        platform_role=PlatformRole.MSME,
        status=AccountStatus.ACTIVE,
        email_verified_at=datetime.utcnow(),
        is_demo_account=True,
        avatar_color="#2563eb",
        onboarding_completed_at=datetime.utcnow(),
    )
    db.add(demo_owner)
    db.flush()
    db.add(models.UserPreference(user_id=demo_owner.id, language="en", easy_mode=False))

    org = models.Organization(
        name="Demo Electronics Pvt Ltd [DEMO]",
        org_type=OrganizationType.PRIVATE_LIMITED,
        enterprise_class=EnterpriseClass.MEDIUM,
        is_demo=True,
        state_code="TN",
    )
    db.add(org)
    db.flush()
    demo_owner.organization_id = org.id
    db.add(models.OrganizationMember(organization_id=org.id, user_id=demo_owner.id, org_role=OrgRole.ADMIN, can_submit_applications=True, can_manage_users=True))

    project = models.Project(
        name="Demo Electronics Manufacturing Project [DEMO]",
        slug="demo-electronics",
        description="DEMO DATA — a mid-size PCB assembly and LED luminaire unit to illustrate how NIECP-AI presents an approval map, documents and applications.",
        organization_id=org.id,
        created_by=demo_owner.id,
        stage=ProjectStage.APPROVALS_IN_PROGRESS,
        is_demo=True,
    )
    db.add(project)
    db.flush()

    profile = models.ProjectProfile(
        project_id=project.id,
        organization_name="Demo Electronics Pvt Ltd",
        applicant_name="Demo Applicant",
        contact_email="demo@niecp.local",
        organization_type=OrganizationType.PRIVATE_LIMITED,
        enterprise_class=EnterpriseClass.MEDIUM,
        project_type=ProjectType.NEW,
        industry_code="electronics",
        sub_industry="PCB assembly & LED luminaires",
        project_stage=ProjectStage.APPROVALS_IN_PROGRESS,
        state_code="TN",
        district="Erode",
        city_village="Perundura",
        industrial_area="DEMO — sample industrial area entry",
        in_notified_industrial_area=True,
        land_tenure=models.LandTenure.INDUSTRIAL_PARK_ALLOTMENT,
        land_area_sqm=8000,
        built_up_area_sqm=2400,
        total_investment=85000000,
        machinery_investment=52000000,
        building_investment=18000000,
        employment_generated=120,
        women_employed=36,
        production_type="PCB assembly, LED driver boards and luminaires",
        production_capacity="120,000 units per year",
        raw_materials=["PCB blanks", "SMD components", "LED chips", "Aluminium housings", "Solder paste"],
        chemicals_used=["Isopropyl alcohol", "Flux", "Conformal coating"],
        hazardous_substances=["Solder dross (lead-free)", "Spent IPA"],
        uses_hazardous_chemicals=False,
        water_consumption_kld=6,
        wastewater_generated_kld=3,
        has_etp=False,
        air_emissions_present=True,
        emission_sources=["Reflow oven exhaust", "DG set stack"],
        has_boiler=False,
        has_dg_set=True,
        dg_set_kva=250,
        fire_risk_level="MEDIUM",
        electrical_load_kw=750,
        htaht_connection_required=False,
        e_waste_generated=True,
        plastic_waste_generated=True,
        hazardous_waste_generated=True,
        hazardous_waste_tpa=2.5,
        solid_waste_generated=True,
        uses_batteries=True,
        number_of_employees=120,
        workers_on_site=96,
        is_factory_under_factories_act=True,
        operates_in_shifts=True,
        uses_contract_labour=True,
        domestic_sales_annual=90000000,
        export_annual=30000000,
        is_export_oriented=True,
        completeness={"seeded": True},
    )
    db.add(profile)

    # a few questionnaire answers
    for key, qset, value, field in [
        ("has_dg_set", "dgset", True, "has_dg_set"),
        ("dg_set_kva", "dgset", 250, "dg_set_kva"),
        ("is_factory_under_factories_act", "labour", True, "is_factory_under_factories_act"),
        ("number_of_employees", "labour", 120, "number_of_employees"),
        ("is_export_oriented", "export", True, "is_export_oriented"),
    ]:
        db.add(
            models.QuestionnaireAnswer(
                project_id=project.id, question_key=key, question_set=qset, value=value, why_asked="Demo seed data"
            )
        )

    # documents (metadata only — no fake certificates)
    for title, category, status in [
        ("Certificate of Incorporation [DEMO]", DocumentCategory.BUSINESS, DocumentStatus.PROCESSED),
        ("Udyam Registration Certificate [DEMO]", DocumentCategory.BUSINESS, DocumentStatus.PROCESSED),
        ("Land allotment letter [DEMO]", DocumentCategory.LAND, DocumentStatus.PROCESSED),
    ]:
        db.add(
            models.Document(
                project_id=project.id,
                organization_id=org.id,
                uploaded_by=demo_owner.id,
                title=title,
                original_filename=f"{title.lower().replace(' ', '_')}.pdf",
                stored_filename="demo-no-file.bin",
                category=category,
                status=status,
                mime_type="application/pdf",
                extension=".pdf",
                size_bytes=0,
                sha256="demo",
                is_demo=True,
                verification_status=SourceStatus.DEMO,
                text_extraction_status="NO_FILE",
                notes="Demo metadata entry. No file is attached — upload your own documents to exercise validation.",
            )
        )

    # applications with DEMO statuses
    db.add(
        models.Application(
            project_id=project.id,
            organization_id=org.id,
            approval_template_code="spcb_consent_to_establish",
            title="Consent to Establish — TNPCB [DEMO]",
            authority="Tamil Nadu Pollution Control Board",
            status=ApplicationStatus.SUBMITTED,
            submission_channel=SubmissionChannel.OFFICIAL_PORTAL_BY_USER,
            official_reference="DEMO-REF-0001",
            official_reference_source=SourceStatus.DEMO,
            official_portal_url="https://xgncpc.mcponline.gov.in/",
            submitted_at=datetime.utcnow() - timedelta(days=20),
            submitted_by_user=True,
            status_is_self_reported=True,
            is_demo=True,
            notes="DEMO: a sample application recorded as submitted by the user on the official portal. The reference number is a demo placeholder, not a real TNPCB number.",
        )
    )
    db.add(
        models.Application(
            project_id=project.id,
            organization_id=org.id,
            approval_template_code="factory_licence",
            title="Factory Licence application [DEMO]",
            authority="Directorate of Industrial Safety & Health, Tamil Nadu",
            status=ApplicationStatus.DRAFT,
            submission_channel=SubmissionChannel.NOT_SUBMITTED,
            official_reference_source=SourceStatus.INFORMATION_UNAVAILABLE,
            is_demo=True,
        )
    )

    # renewal, query, inspection, task
    db.add(
        models.Renewal(
            project_id=project.id,
            organization_id=org.id,
            title="GST annual return cycle [DEMO]",
            renewal_type="FILING",
            due_date=date.today() + timedelta(days=45),
            status=RenewalStatus.UPCOMING,
            reminder_days=[90, 60, 30, 7],
            source_status=SourceStatus.DEMO,
            is_demo=True,
        )
    )
    db.add(
        models.GovernmentQuery(
            project_id=project.id,
            authority="Tamil Nadu Pollution Control Board [DEMO]",
            reference_number="DEMO-QRY-0001",
            query_text="DEMO SAMPLE QUERY — Please submit the water balance diagram and details of the proposed effluent disposal route.",
            date_received=date.today() - timedelta(days=6),
            deadline=date.today() + timedelta(days=9),
            status=QueryStatus.OPEN,
            required_documents=["Water balance diagram", "Effluent disposal details"],
            source_status=SourceStatus.DEMO,
            is_demo=True,
            ai_explanation="The Board is asking how water flows through your process and where the wastewater will go. Prepare the water balance diagram and the disposal route description.",
            ai_suggested_steps=["Prepare the water balance diagram", "Describe the effluent disposal route", "Attach both to the query response and record it"],
        )
    )
    db.add(
        models.Inspection(
            project_id=project.id,
            department="Factories Inspectorate [DEMO sample entry]",
            inspection_type="FACTORY",
            status=InspectionStatus.SCHEDULED,
            inspection_date=date.today() + timedelta(days=15),
            source_status=SourceStatus.DEMO,
            is_demo=True,
            checklist=[
                {"item": "Approved plan available at site", "done": False},
                {"item": "Statutory registers up to date", "done": False},
                {"item": "Fire extinguishers inspected and tagged", "done": False},
                {"item": "PPE in use by workers", "done": False},
            ],
        )
    )
    db.add(
        models.ComplianceTask(
            project_id=project.id,
            organization_id=org.id,
            title="Upload fire NOC when received [DEMO]",
            description="Demo task to illustrate the task list and its link to the document centre.",
            task_type="DOCUMENT",
            status=TaskStatus.OPEN,
            priority=TaskPriority.HIGH,
            due_date=date.today() + timedelta(days=30),
            source_status=SourceStatus.DEMO,
            is_demo=True,
            generated_by_agent="COMPLIANCE",
        )
    )
    db.add(
        models.Notification(
            user_id=demo_owner.id,
            project_id=project.id,
            organization_id=org.id,
            notification_type=NotificationType.SYSTEM,
            title="Demo data loaded [DEMO]",
            body="This project and its records are demo data. Government statuses shown here are demo placeholders, not real government communications. Delete demo data any time from the admin panel.",
            severity="INFO",
        )
    )

    # regulatory change radar — DEMO samples, explicitly unverified
    db.add(
        models.RegulatoryChange(
            title="DEMO SAMPLE — Illustrative change entry",
            change_type=models.ChangeType.FORM_CHANGE,
            what_changed="This is a sample entry showing how verified regulatory changes will appear: what changed, who may be affected, why it matters, the source and a recommended review action.",
            who_may_be_affected="Demo electronics manufacturing unit",
            why_it_matters="Sample explanation of impact for the demo unit.",
            recommended_review="Replace this sample with real verified entries from official gazette monitoring.",
            affected_categories=["ENVIRONMENT", "SAFETY"],
            affected_industries=["electronics"],
            affected_states=["TN"],
            source_url="https://egazette.gov.in/",
            publisher="NIECP-AI demo seed",
            detected_at=datetime.utcnow(),
            verification_status=models.ChangeVerification.UNVERIFIED_REPORT,
            is_demo=True,
        )
    )

    db.flush()
    run_discovery(db, project, actor=demo_owner)
    from . import readiness as readiness_service
    readiness_service.compute_readiness(db, project)
    log.info("demo data created for org %s project %s", org.id, project.id)
