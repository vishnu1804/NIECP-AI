"""
Seed corpus for the retrieval (RAG) engine (spec §36).

HONESTY LABELLING
-----------------
Each entry states explicitly what it is:
  * OFFICIAL_SUMMARY  — a plain-language summary written by NIECP-AI of an
    official publication, with a citation and URL to the primary source. It is
    a *secondary* source: the assistant always points the user to the primary.
  * PROCEDURE         — NIECP-AI's own operational guidance on how to use the
    platform. Not a statement of law.

Retrieved chunks are always returned with their source, publisher, date and
section so the UI can render the citation block required by spec §37.
"""
from __future__ import annotations

from typing import Any

OFFICIAL_SUMMARY = "OFFICIAL_SUMMARY"
PROCEDURE = "PROCEDURE"


def K(  # noqa: N802
    title: str,
    body: str,
    *,
    doc_kind: str = OFFICIAL_SUMMARY,
    publisher: str,
    url: str | None = None,
    citation: str | None = None,
    published_on: str | None = None,
    section: str | None = None,
    language: str = "en",
    topics: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "body": body.strip(),
        "doc_kind": doc_kind,
        "publisher": publisher,
        "url": url,
        "citation": citation,
        "published_on": published_on,
        "section": section,
        "language": language,
        "topics": topics or [],
    }


KNOWLEDGE: list[dict[str, Any]] = [
    # ══════════════════════════════════════════════════ ENVIRONMENTAL LAW ══
    K(
        "Consent to Establish and Consent to Operate — what they are",
        """
The Water (Prevention and Control of Pollution) Act, 1974 and the Air (Prevention
and Control of Pollution) Act, 1981 require a person proposing to establish any
industry, operation or process, or to extend or alter an existing one, to obtain
the previous consent of the State Pollution Control Board. This prior consent is
commonly called Consent to Establish (CTE). A separate consent is required before
the unit begins to discharge trade effluent into a stream, well, sewer or on land,
or to emit air pollutants; this is Consent to Operate (CTO).

Practical consequence for an industrial project:
  * CTE is obtained at the planning stage, before construction.
  * CTO is obtained after construction and after installing the pollution control
    systems, and before commencing production.
  * Both are granted subject to conditions, and CTO carries a validity period.
  * Applications are generally filed online through the State Board's consent
    management system, and CPCB operates a national single-window route that
    forwards applications to the concerned State Board.

What the consent order contains matters more than the fact of consent: it records
the discharge and emission standards, the monitoring obligations, the waste
handling conditions and the validity period. Renewal must be applied for before
expiry, and operating after expiry is treated as operating without consent.

Because industry categorisation, form requirements, fee slabs and validity periods
are prescribed by each State Board and are amended from time to time, the current
position must always be confirmed on the concerned State Board's own portal.
""",
        publisher="Water (Prevention and Control of Pollution) Act, 1974 and Air (Prevention and Control of Pollution) Act, 1981; State Pollution Control Board consent manuals",
        url="https://cpcb.nic.in/",
        citation="Water Act, 1974 — Sections 25, 26; Air Act, 1981 — Sections 21, 22",
        topics=["consent", "ct", "cte", "cto", "pollution", "spcb", "water act", "air act"],
    ),
    K(
        "Environmental Clearance under the EIA Notification, 2006",
        """
Projects listed in the Schedule to the Environment Impact Assessment Notification
S.O. 1533(E) dated 14 September 2006 (as amended) require prior Environmental
Clearance before construction or operation. Clearance is granted either by the
Ministry of Environment, Forest and Climate Change (Category A projects) or by the
State Environment Impact Assessment Authority (Category B projects), depending on
the project's Schedule entry and its size/capacity.

The normal sequence is:
  1. Submit Form 1 with the project details and a pre-feasibility report through
     PARIVESH, the MoEFCC single-window portal.
  2. For projects requiring an Environmental Impact Assessment study, the appraisal
     authority issues Terms of Reference.
  3. The EIA study is carried out, followed by public consultation where required.
  4. Appraisal by the State/central Expert Appraisal Committee and then by the
     regulatory authority, which issues the clearance order with conditions.
  5. Compliance reports are filed periodically for the validity period of the
     clearance.

Stage-wise time limits are prescribed in the Notification. Categories, thresholds
and the delegation of powers to SEIAAs are amended frequently — a project that was
outside the Schedule last year may be inside it now, and vice versa. Always check
the current Schedule entry for the exact activity and capacity before concluding
that clearance is, or is not, required.
""",
        publisher="Ministry of Environment, Forest and Climate Change",
        url="https://parivesh.nic.in/",
        citation="EIA Notification S.O. 1533(E) dated 14 September 2006, as amended",
        topics=["environmental clearance", "eia", "parivesh", "moefcc", "seiaa", "category a", "category b"],
    ),
    K(
        "Hazardous and Other Waste authorisation and the manifest system",
        """
The Hazardous and Other Wastes (Management and Transboundary Movement) Rules, 2016
require the occupier of a facility generating, storing, treating or disposing of
hazardous and other waste to obtain authorisation from the State Pollution Control
Board. The Rules also regulate collection and transport, packaging and labelling,
storage, treatment and disposal.

Key operational obligations that an authorised generator must plan for:
  * Waste must be stored safely, in labelled containers, in a designated area, for
    the period allowed by the authorisation.
  * Waste may be sent only to an authorised recycler, re-refiner, co-processing
    facility or treatment, storage and disposal facility (TSDF).
  * Each movement of waste is documented through the manifest system prescribed in
    the Rules; copies are retained and reconciled.
  * Annual returns are filed with the State Board in the prescribed form.
  * Accidents must be reported to the concerned authority.

Authorisation is typically granted together with, or after, Consent to Operate, and
its validity is stated in the order. Because the schedules listing waste categories
and the thresholds for co-processing have been amended, the classification of a
specific waste stream should be confirmed with the State Board rather than assumed.
""",
        publisher="Ministry of Environment, Forest and Climate Change",
        url="https://moef.gov.in/",
        citation="Hazardous and Other Wastes (Management and Transboundary Movement) Rules, 2016",
        topics=["hazardous waste", "authorisation", "manifest", "tsdf", "recycler", "annual return"],
    ),
    K(
        "Extended Producer Responsibility — e-waste, plastic and battery waste",
        """
Three separate rule sets place extended producer responsibility obligations on
businesses, each administered through a CPCB-hosted online portal:

E-waste: the E-Waste (Management) Rules, 2022 require producers of electrical and
electronic equipment to register with the CPCB, declare the quantity placed on the
market, and meet collection and recycling targets through registered recyclers.
The framework introduced a marketable EPR certificate mechanism. Bulk consumers and
recyclers have their own registration and return obligations.

Plastic waste: the Plastic Waste Management Rules, 2016 (as amended) require
producers, importers and brand owners of plastic packaging to register on the
centralised EPR portal, declare category-wise quantities and meet EPR targets, with
obligations also falling on registered plastic waste processors.

Battery waste: the Battery Waste Management Rules, 2022 require producers of
batteries and cells to register on the CPCB battery-waste portal and meet recovery
and recycling targets, with EPR certificates used to evidence compliance.

Two points are routinely misunderstood:
  * Registration is a *continuing* obligation with periodic returns, not a one-time
    permission.
  * Importing or assembling a product that contains a battery or electronic
    sub-assembly can make the business a "producer" even when it does not
    manufacture the component itself.

Because targets, exemptions and portal processes have been amended repeatedly, the
current obligations for a specific product category must be read from the CPCB
portal for that rule set.
""",
        publisher="Central Pollution Control Board",
        url="https://cpcb.nic.in/",
        citation="E-Waste (Management) Rules, 2022; Plastic Waste Management Rules, 2016; Battery Waste Management Rules, 2022",
        topics=["epr", "e-waste", "plastic waste", "battery waste", "cpcb", "producer", "registration"],
    ),
    K(
        "Groundwater extraction — no-objection certificate regime",
        """
Regulation of groundwater extraction by industrial, infrastructure and other
project units operates through directions issued under the Environment (Protection)
Act, 1986 and administered by the Central Ground Water Authority, and, in several
states, by a State Groundwater Authority created under state legislation. Some
functions have been delegated to states.

The assessment is area-based: an assessment unit is classified according to the
stage of groundwater development, and the conditions attached to a no-objection
certificate depend on that classification and on whether the unit is in a notified
or non-notified area.

Typical conditions attached to a NOC include:
  * Rainwater harvesting structures to be constructed and maintained.
  * Water metering and periodic submission of abstraction data.
  * Water audit / water conservation measures.
  * Restrictions on the number and depth of wells.
  * No transfer of the NOC to another entity or purpose without permission.

A NOC is granted for a limited period and must be renewed. Applying for a NOC while
the consent to establish process is running is normal practice, because the water
balance in the project report is common to both. Always confirm which authority is
competent for the specific district, since this varies by state.
""",
        publisher="Central Ground Water Authority / Ministry of Jal Shakti",
        url="https://cgwa-noc.gov.in/",
        citation="Directions issued under Section 5 of the Environment (Protection) Act, 1986; applicable state groundwater legislation",
        topics=["groundwater", "noc", "cgwa", "borewell", "rainwater harvesting", "water"],
    ),
    # ══════════════════════════════════════════════════════════ FACTORIES ══
    K(
        "Factories Act, 1948 — registration, licensing and the duties of an occupier",
        """
The Factories Act, 1948 applies to premises where a manufacturing process is carried
on with the aid of power and the worker strength crosses the statutory threshold,
or where it is carried on without the aid of power above a higher threshold. State
Factories Rules prescribe the registration and licensing procedure, the forms, the
fees and the licence validity.

What a licence applicant normally needs ready:
  * Approved site and building plans, section and elevation, with the layout of
    machinery.
  * Details of the manufacturing process, raw materials, intermediates and products,
    including quantities.
  * Machinery list with installed power.
  * Stability certificate for the building structure.
  * Occupational health and safety arrangements: first aid, ambulance room,
    occupational health centre, safety officer where required, personal protective
    equipment policy.
  * Welfare amenities: canteen, rest room, drinking water, latrines, creche where
    the prescribed number of women workers are employed.
  * Fire NOC and pollution consents where applicable.

Ongoing obligations once licensed include statutory registers and notices, periodic
testing and examination of plant, medical examinations of workers in specified
processes, and reporting of accidents and dangerous occurrences. Where hazardous
chemicals above the threshold quantities listed in the Manufacture, Storage and
Import of Chemical Hazardous Chemical Rules, 1989 are handled, additional
obligations arise: notification to the authority, an on-site emergency plan, safety
reports in specified cases, and periodic mock drills.

Thresholds, forms and licence validity are state-specific. The Act is central
legislation; the Rules are made by each State.
""",
        publisher="Ministry of Labour and Employment; State Directorates of Industrial Safety and Health",
        url="https://www.labour.gov.in/",
        citation="Factories Act, 1948; Manufacture, Storage and Import of Chemical Hazardous Chemical Rules, 1989",
        topics=["factory", "factories act", "licence", "occupier", "safety", "mah", "emergency plan"],
    ),
    K(
        "Fire safety NOC — provisional and final",
        """
Fire safety requirements for buildings are set by state legislation: most states
have a Fire Service Act or Fire Prevention and Life Safety Measures Act, and the
building bye-laws of the local body incorporate fire provisions. The competent
authority is the state Fire and Rescue Services department or a Directorate of Fire
Safety.

The usual pattern is two-stage:
  * A provisional (or plan-approval) NOC is obtained at the design stage, on the
    basis of the building plan showing means of escape, access for fire tenders,
    and the proposed fire protection systems.
  * A final NOC is obtained after construction and installation, following a site
    inspection that tests hydrants and sprinklers, detection and alarm systems,
    extinguishers, smoke management, emergency lighting and signage.

For industrial occupancies, the inspection commonly examines storage arrangement and
aisle widths, separation of flammable storage, earthing and static control, hot-work
permit systems, and the availability of water for fire fighting. NOCs are
time-bound and must be renewed; several states require periodic renewal with a
fresh inspection or a self-certification by an empanelled agency.

Thresholds (built-up area, height, occupancy type) and renewal cycles differ
substantially between states and are amended frequently. The state Fire Service
portal is the authoritative source for the current requirement.
""",
        publisher="State Fire and Rescue Services departments",
        citation="Respective State Fire Service / Fire Prevention and Life Safety Measures Act and building bye-laws",
        topics=["fire", "noc", "fire safety", "sprinkler", "hydrant", "occupancy"],
    ),
    K(
        "Electrical safety — CEA Regulations and HT supply",
        """
The Electricity Act, 2003 provides the framework for electrical safety. The Central
Electricity Authority (Measures relating to Safety and Electric Supply) Regulations,
2023 superseded the 2010 Regulations and prescribe measures for safe operation of
generation, transmission, distribution and use of electricity, including requirements
for protective equipment, earthing, clearances, testing and the appointment of
qualified persons.

For an industrial unit, the practical path is:
  1. Apply to the distribution licensee for the required sanction load; high tension
     (HT) supply involves a separate application, technical scrutiny, and an
     agreement.
  2. Install the electrical plant in accordance with the sanctioned single-line
     diagram, using a licensed electrical contractor and under a licensed
     supervisor.
  3. Complete testing: insulation resistance, earth resistance, relay settings and
     coordination, protection scheme approval where required.
  4. Obtain approval from the state Electrical Inspectorate for the installation
     where the voltage or capacity crosses the prescribed threshold.
  5. Joint inspection by the licensee and the inspectorate, followed by energisation.

Installations are subject to periodic re-inspection and renewal of approval under the
state rules. Diesel generator sets are covered both by the electrical safety regime
and by the pollution consent conditions (noise and emission limits, stack height).
""",
        publisher="Central Electricity Authority / State Electrical Inspectorates",
        url="https://cea.nic.in/",
        citation="Electricity Act, 2003; CEA (Measures relating to Safety and Electric Supply) Regulations, 2023",
        topics=["electrical", "ht", "cea", "inspectorate", "discom", "transformer", "dg set"],
    ),
    K(
        "PESO licensing — petroleum, gas cylinders and explosives",
        """
The Petroleum and Explosives Safety Organization (PESO), under the Ministry of
Commerce and Industry (DPIIT), administers licensing for the storage and handling of
petroleum and petroleum products under the Petroleum Act, 1934 and the Petroleum
Rules, 2002; for explosives under the Explosives Act, 1884 and Explosives Rules,
2008; for gas cylinders under the Gas Cylinders Rules, 2016; and for unfired static
and mobile pressure vessels under the SMPV(U) Rules, 2016.

An industrial unit commonly encounters PESO licensing through:
  * Storage of diesel for generator sets and fleet fueling.
  * Storage of LPG cylinders or a bulk LPG installation.
  * Storage of flammable solvents, paints and chemicals classified as petroleum.
  * Compressed gas cylinders used in welding, cutting and process applications.
  * Ammonia or other refrigeration installations, and pressure vessels.

The licence application requires a site layout demonstrating the prescribed
separation distances from buildings, boundaries, roads and ignition sources, details
of the storage installation, and the fire protection provided. Licences are renewed
periodically and premises are inspected.

Exempt quantities and licence classes are specified in the rules and have been
amended; a small store may be exempt while a modest increase in quantity takes it
into a licensed class. Compute against the current rule text.
""",
        publisher="Petroleum and Explosives Safety Organization",
        url="https://peso.gov.in/",
        citation="Petroleum Act, 1934; Petroleum Rules, 2002; Explosives Rules, 2008; Gas Cylinders Rules, 2016; SMPV(U) Rules, 2016",
        topics=["peso", "petroleum", "diesel storage", "lpg", "gas cylinder", "explosives", "licence"],
    ),
    # ═══════════════════════════════════════════════════════════ LABOUR ══
    K(
        "Statutory labour registrations for a new industrial unit",
        """
A new industrial establishment in India typically encounters the following labour
registrations, each with its own trigger:

Provident fund: establishments employing the notified number of persons are covered
under the Employees' Provident Funds and Miscellaneous Provisions Act, 1952.
Registration is done through the EPFO establishment portal, after which monthly
contributions and returns (the electronic challan-cum-return) must be filed.

Employees' State Insurance: factories and specified establishments employing the
notified number or more persons, with employees within the prescribed wage ceiling,
are covered under the Employees' State Insurance Act, 1948, which provides medical
care and cash benefits funded by employer and employee contributions.

Contract labour: where contract labour is engaged above the notified threshold, the
principal employer must obtain registration under the Contract Labour (Regulation and
Abolition) Act, 1970, and every contractor must hold a licence. The employer remains
responsible for specified welfare amenities, and non-compliance can result in the
principal employer being liable to pay wages.

Building and other construction workers: construction work above the prescribed cost
or area threshold requires registration of the establishment with the state BOCW
Welfare Board and payment of cess.

Shops and establishments: commercial premises that are not factories are generally
registered under the state Shops and Establishations Act, which governs working
hours, weekly holidays, leave and record-keeping.

Professional tax: employers in states that levy it must register and file periodic
returns on salaries.

Labour welfare fund: several states require employer contributions to a state
Labour Welfare Fund.

Coverage thresholds, wage ceilings and filing cycles are amended by notification and
vary by state. Verify the currently notified figure for each registration before
concluding that it does or does not apply.
""",
        publisher="Ministry of Labour and Employment; EPFO; ESIC; State Labour Departments",
        url="https://shramsuvidha.gov.in/",
        citation="EPF & MP Act, 1952; ESI Act, 1948; Contract Labour (R&A) Act, 1970; BOCW Act, 1996; State Shops & Establishments Acts",
        topics=["epfo", "esic", "pf", "esi", "contract labour", "bocw", "shops", "professional tax", "labour"],
    ),
    # ══════════════════════════════════════════════════ BUSINESS / TAX ══
    K(
        "Business identity documents that downstream approvals depend on",
        """
Almost every industrial approval in India is issued in the name of a legal entity,
and the identity documents of that entity are the first thing every application asks
for. Getting these right early prevents re-work later:

Entity registration: a company or LLP is incorporated with the Registrar of Companies
through the MCA portal and receives a Corporate Identity Number or LLP identification
number. A proprietorship or partnership relies on its own registration documents and,
in most states, the Shops and Establishations registration or a GST registration as its
identity.

PAN: the Permanent Account Number of the entity is required for tax purposes and is
the primary identifier for GST, Udyam, EPFO, ESIC and most state portals.

GSTIN: registration under the Central GST Act, 2017 depends on turnover and on
specific compulsory-registration categories. The GSTIN is asked for on the majority of
consent, licence and incentive applications.

Udyam registration: the MSME identity, obtained through self-declaration using Aadhaar
and PAN, generating a permanent Udyam Registration Number. It is asked for when
claiming MSME-specific benefits and by many state single-window systems.

The practical sequencing point is that a change in the entity's name, constitution or
registered address after consents are granted usually requires the consents to be
amended or re-applied for. Deciding the entity structure before applying for land and
consent avoids that re-work.
""",
        publisher="Ministry of Corporate Affairs; Income Tax Department; GST Network; Ministry of MSME",
        url="https://www.mca.gov.in/",
        citation="Companies Act, 2013; LLP Act, 2008; Income Tax Act, 1961; CGST Act, 2017; MSMED Act, 2006",
        topics=["pan", "gstin", "cin", "udyam", "incorporation", "registration", "entity"],
    ),
    K(
        "MSME classification and the Udyam registration process",
        """
The classification of micro, small and medium enterprises is prescribed under the
Micro, Small and Medium Enterprises Development Act, 2006 and the notification issued
under it (S.O. 2119(E) dated 26 June 2020, as amended). Classification is based on
two criteria: investment in plant and machinery or equipment, and annual turnover.
Composite criteria apply, and both a manufacturing enterprise and a service enterprise
are covered.

Udyam registration is a self-declaration process carried out on the Udyam
Registration portal using the Aadhaar of the authorised signatory and the PAN of the
enterprise. The portal generates a permanent Udyam Registration Number and a
certificate that can be printed. No fee is prescribed for registration on the official
portal.

Two consequences matter for compliance planning:
  * The classification figures declared must be consistent with GST and income-tax
    returns, because the registration is validated against those records.
  * Crossing a classification limit requires the registration to be updated, and
    several incentives and procurement preferences are tied to a specific class.

Because the classification limits are set by notification and have been revised, the
current limits must be read from the Ministry of MSME's own notification rather than
recalled.
""",
        publisher="Ministry of Micro, Small & Medium Enterprises",
        url="https://udyamregistration.gov.in/",
        citation="MSMED Act, 2006; Notification S.O. 2119(E) dated 26 June 2020 as amended",
        topics=["udyam", "msme", "classification", "micro", "small", "medium", "registration"],
    ),
    # ═══════════════════════════════════════════════ FOOD / PHARMA / BIS ══
    K(
        "FSSAI licensing for a food manufacturing unit",
        """
No person may commence or carry on a food business except under a licence or a
registration issued under the Food Safety and Standards Act, 2006 and the Food Safety
and Standards (Licensing and Registration of Food Businesses) Regulations, 2011. The
level of authorisation depends on the nature, capacity and turnover of the activity:
small operators register, larger operators obtain a state licence from the State Food
Safety Commissioner, and specified categories and capacities require a central licence
from FSSAI.

For a manufacturing unit the application typically requires:
  * The layout plan of the premises showing the process flow from raw material receipt
    to dispatch, with equipment placement.
  * The list of equipment and installed capacity.
  * The food categories and products proposed, mapped to the standards in the
    Regulations.
  * A water test report from an accredited laboratory.
  * Details of technical and quality control personnel.
  * A food safety management system plan, and where applicable the arrangements for
    recall, traceability and labelling.
  * Health/medical certificates for food handlers where the licensing authority
    requires them.

Licences are issued for a period of one to five years as elected by the applicant and
must be renewed before expiry; periodic returns are also required for certain
categories. Turnover and capacity thresholds that determine registration versus state
licence versus central licence are specified in the Regulations and have been amended.
""",
        publisher="Food Safety and Standards Authority of India",
        url="https://www.fssai.gov.in/",
        citation="Food Safety and Standards Act, 2006; FSS (Licensing and Registration of Food Businesses) Regulations, 2011",
        topics=["fssai", "food", "licence", "foscos", "food safety", "hygiene"],
    ),
    K(
        "Drug manufacturing licence and GMP compliance",
        """
Manufacture, sale and distribution of drugs are regulated under the Drugs and
Cosmetics Act, 1940 and the Drugs and Cosmetics Rules, 1945. A manufacturing licence
is granted by the state licensing authority for the categories applied for, following
inspection of the premises, plant, equipment and quality-control arrangements. Certain
categories — including new drugs and specified biologics — are licensed by the Central
Drugs Standard Control Organisation.

Inspection focuses on Good Manufacturing Practice as prescribed in Schedule M to the
Rules: premises and layout designed to prevent cross-contamination, qualified
production and quality-control personnel, validated processes and analytical methods,
a documented quality management system, stability programme, and records that permit
batch traceability.

The licence is granted for the period prescribed in the Rules and must be renewed.
Schedule M requirements were revised with a phased compliance timeline, and the
applicable version and transition dates should be confirmed with the licensing
authority rather than assumed.

A drug manufacturing unit also needs the general industrial permissions: pollution
consents, factory licence, and, where hazardous chemicals above threshold quantities
are handled, the on-site emergency plan and safety report obligations under the
MSIHC Rules.
""",
        publisher="State Drug Control Administrations; Central Drugs Standard Control Organisation",
        url="https://cdsco.gov.in/",
        citation="Drugs and Cosmetics Act, 1940; Drugs and Cosmetics Rules, 1945 (Schedule M)",
        topics=["drug", "pharma", "cdsco", "gmp", "schedule m", "licence", "manufacturing"],
    ),
    K(
        "Compulsory product certification — BIS and Quality Control Orders",
        """
Product certification in India operates through two mechanisms that are often
confused:

Quality Control Orders (QCOs): individual ministries issue QCOs under the Bureau of
Indian Standards Act, 2016 for products where conformity to a specified Indian
Standard is made compulsory. Once a QCO is in force for a product, that product cannot
be manufactured, imported, distributed, sold or stored without a BIS licence, and each
manufacturing location requires its own licence.

Compulsory Registration Scheme (CRS): administered by BIS for electronics and IT goods
notified by MeitY, where products must be tested in a BIS-recognised laboratory and
registered before being placed on the market.

For a manufacturer the practical steps are: identify the exact Indian Standard that
applies to the product; get samples tested in a recognised laboratory; apply on the BIS
portal for the relevant scheme, declaring the factory location and the manufacturing
process; and after grant, maintain the surveillance requirements including periodic
testing, marking and record-keeping. Foreign manufacturers must appoint an Authorised
Indian Representative.

Which products are covered changes continuously as ministries issue new QCOs. The
current notification list for the specific product and standard is the only reliable
source.
""",
        publisher="Bureau of Indian Standards; Ministry of Electronics and Information Technology",
        url="https://www.bis.gov.in/",
        citation="Bureau of Indian Standards Act, 2016; Compulsory Certification Schemes and Quality Control Orders",
        topics=["bis", "isi", "crs", "quality control order", "certification", "electronics", "standard"],
    ),
    # ══════════════════════════════════════════════════════ TRADE / EXPORT ══
    K(
        "Importer Exporter Code and export promotion authorisations",
        """
The Foreign Trade (Development and Regulation) Act, 1992 and the Foreign Trade Policy
issued under it govern imports and exports. An Importer Exporter Code (IEC) issued by
the Directorate General of Foreign Trade is required for import into and export from
India, subject to the exemptions notified by DGFT. The IEC is permanent but must be
updated annually on the DGFT portal as notified.

Exporters commonly use:
  * Advance Authorisation — duty-free import of inputs physically incorporated in the
    exported product, against an export obligation, based on notified standard
    input-output norms or a norms-fixation committee approval.
  * EPCG — duty-free import of capital goods against an export obligation to be
    discharged over the prescribed period.
  * Remission schemes — remission of duties, taxes and cess on exported products,
    claimed through the notified route against shipping bills.
  * Interest equalisation support where notified for eligible exporters.

Authorisations are applied for on the DGFT portal with the IEC, GSTIN, PAN, bank
details and AD code. Export obligations are monitored, and failure to discharge them
attracts the consequences prescribed in the policy.

The Foreign Trade Policy and its handbooks are revised, and specific schemes are
notified and closed to new applications from time to time. Read the current policy
text for the scheme being claimed.
""",
        publisher="Directorate General of Foreign Trade, Ministry of Commerce & Industry",
        url="https://www.dgft.gov.in/",
        citation="Foreign Trade (Development and Regulation) Act, 1992; Foreign Trade Policy and DGFT Handbook of Procedures",
        topics=["iec", "dgft", "export", "import", "advance authorisation", "epcg", "foreign trade policy"],
    ),
    # ═══════════════════════════════════════════════ PLATFORM PROCEDURES ══
    K(
        "How NIECP-AI decides what applies to your project",
        """
NIECP-AI uses a deterministic rule engine, not a language model, to decide which
approvals are potentially applicable to a project. This is deliberate: a regulatory
gate should never depend on a probabilistic model output.

How it works:
  1. Your Master Project Profile supplies a set of facts: industry, state, investment,
     built-up area, water use, waste streams, worker strength, export activity, and so
     on.
  2. Each approval in the catalogue has one or more rules written as explicit
     conditions over those facts, for example "has a boiler" or "built-up area above a
     threshold" or "industry is in the chemical sector".
  3. The engine evaluates every rule and produces one of four results:
       APPLIES — a rule matched on facts you provided.
       NOT_APPLICABLE — a rule evaluated to false on facts you provided.
       CONDITIONAL — applicability depends on information you have not supplied yet.
       UNKNOWN — the facts needed to decide are missing entirely.
  4. Every result carries the matched rule keys and the specific facts used, so the
     reasoning is inspectable rather than asserted.

What the engine will never do:
  * It will not present a planning-level indication as a legal determination. Each
    result is paired with the statute it is derived from and a "confirm with the
    authority" action.
  * It will not invent a requirement that has no rule behind it.
  * It will not override a deterministic rule with a language-model opinion.

If a rule matched but you believe it should not have applied, the approval card shows
the exact condition and the exact profile fact that triggered it — correct the fact and
the analysis re-runs.
""",
        doc_kind=PROCEDURE,
        publisher="NIECP-AI platform documentation",
        topics=["rule engine", "how it works", "applicability", "ai", "method", "deterministic"],
    ),
    K(
        "How NIECP-AI validates an uploaded document",
        """
When you upload a document, the Document Agent runs a sequence of checks and reports
each one separately, with a severity and an explanation. The checks are:

  * Readability — can text be extracted at all, and how much? A scan that yields almost
    no text is flagged as low quality, not treated as valid.
  * Classification — the extracted text is compared against the vocabulary of known
    document types, and the closest match is reported with a confidence score.
  * Field extraction — identifiers such as PAN, GSTIN, CIN, Udyam number, dates and
    reference numbers are extracted by pattern matching.
  * Profile comparison — extracted identifiers and the entity name and address are
    compared against your Master Project Profile. Matches are reported as matches;
    mismatches are reported as mismatches with both values shown.
  * Expiry — where a date pattern is recognised as an expiry or validity date, it is
    compared against today's date.
  * Completeness — required fields for the document category are checked against what
    was found.

What the result means: these are AI interpretations of an image or PDF that NIECP-AI
has read. They are useful for catching an obviously wrong upload, a wrong name, or an
expired certificate before you file an application. They are not a legal opinion, and
they cannot establish that a document is genuine or that an authority will accept it.
Only the issuing authority can do that.

For that reason every validation finding is labelled AI_INTERPRETATION, and findings
that would affect a filing carry an explicit "manual verification required" note.
""",
        doc_kind=PROCEDURE,
        publisher="NIECP-AI platform documentation",
        topics=["document validation", "ocr", "classification", "upload", "document", "ai"],
    ),
    K(
        "What NIECP-AI does and does not do with government systems",
        """
NIECP-AI is an approval and compliance navigator. It is not a government authority,
not an agent of any authority, and not a submission channel unless a verified official
integration has been provisioned by the deploying agency.

What it does:
  * Builds and maintains your project profile and document repository.
  * Determines which approvals may apply, using deterministic rules and published
    statutes, with the source shown for every result.
  * Prepares an application package, produces a checklist and a readiness score, and
    tells you what is missing.
  * Opens the official government portal for you at the point of submission.
  * Tracks the application afterwards using the status information you confirm, and
    helps you respond to queries, prepare for inspections and manage renewals.

What it does not do:
  * It does not submit an application to a government authority unless you explicitly
    confirm and a verified integration is connected.
  * It does not generate an application number, acknowledgement number, licence number
    or approval decision. Those come only from the authority.
  * It does not show a live government status that it has not obtained from a verified
    source or from you. Status fields you enter are labelled as self-reported.
  * It does not guarantee that any approval will be granted.

When an integration is not provisioned, the Integration Manager shows NOT_CONNECTED or
MANUAL_MODE and the platform offers a redirect to the official portal with a
transparent explanation. A missing integration is reported as missing; it is never
simulated as successful.
""",
        doc_kind=PROCEDURE,
        publisher="NIECP-AI platform documentation",
        topics=["integration", "government", "submission", "honesty", "what it does", "limits", "portal"],
    ),
    K(
        "Reading the Application Readiness score correctly",
        """
The readiness score is a preparation measure, not a probability of approval. It answers
"how ready is my paperwork and process to file", not "will the authority approve me".
No honest system can answer the second question, because the decision belongs to the
authority and depends on facts the authority verifies itself.

The score is composed of weighted components, and every component is broken down into
the individual checks that produced it:

  * Profile completeness — how many of the facts that rules and applications depend on
    have been supplied. Missing facts reduce the score and, more importantly, are
    listed.
  * Documents — how many of the documents required by your applicable approvals are
    present, correctly classified, matched to your profile and unexpired.
  * Eligibility information — how many of the criteria for the schemes and approvals
    you are pursuing can be evaluated from your data, versus how many are unevaluable.
  * Prerequisites — how many upstream approvals in your dependency graph are complete.
  * Application readiness — whether the specific application package you are preparing
    has all mandatory fields and attachments.

A score of 100% means your preparation is complete according to the requirements
NIECP-AI has on record, all of which are shown with their sources. It does not mean an
approval is assured. A low score tells you precisely what to fix, and the Next Best
Action engine turns the largest gap into the single next thing to do.
""",
        doc_kind=PROCEDURE,
        publisher="NIECP-AI platform documentation",
        topics=["readiness", "score", "probability", "calculation", "dashboard"],
    ),
    K(
        "Land use conversion and building plan sanction — the sequence that most often delays a project",
        """
Two approvals cause more industrial project delay than any environmental one, because
they are prerequisites for almost everything downstream and are administered by local
authorities with variable capacity: conversion of land use, and sanction of the building
plan.

Land use conversion: land recorded in revenue records as agricultural generally cannot
lawfully be used for industry without a conversion or change-of-land-use order from the
revenue or planning authority. The application requires title documents, revenue
records, a survey sketch and a site plan showing the proposed use, and the order is
subject to a fee or betterment charge. Where the plot is already inside a notified
industrial zone that permits the use, conversion may not be required — but that must be
confirmed with the authority, not assumed from the zone name.

Building plan sanction: erection of the building or shed requires sanction of the plan
under the local building bye-laws, with architectural and structural drawings certified
by a registered architect and structural engineer, compliance with zoning, setbacks,
floor area ratio and height limits, and the local provisions for rainwater harvesting
or renewable energy. Many states operate online building-permission systems with
prescribed time limits or auto-sanction mechanisms.

Occupancy: after construction, a completion or occupancy certificate is issued following
inspection. Occupying before the certificate is prohibited under most bye-laws, and the
certificate is commonly required for utilities, factory licensing and pollution consent
to operate.

The sequencing consequence is that consent to establish can often be applied for in
parallel with building plan sanction, but consent to operate and the factory licence
usually require the completed structure and its occupancy documentation. Planning the
application calendar around this dependency is where most of the schedule saving lies.
""",
        publisher="State revenue departments, town and country planning authorities and local bodies",
        citation="Respective State Land Revenue Code / Town and Country Planning Act; Municipal Acts and building bye-laws",
        topics=["land", "conversion", "building plan", "occupancy", "sanction", "na", "construction"],
    ),
    K(
        "Industrial siting: notified industrial areas, SEZs and greenfield sites",
        """
Where a project is sited changes which authority is the first point of contact and how
many separate applications are needed.

Inside a notified industrial area or park: the development authority is usually the
allotting body and issues the allotment letter or lease deed, which carries conditions
on the timeline for construction, the permitted use, and reporting obligations. Many
such authorities also host or route the state single-window application, so consents
can be obtained through a common form. The lease conditions are contractual and
separate from statutory consents — both must be satisfied.

Inside a Special Economic Zone: the SEZ framework provides a distinct approval route
through the Board of Approval and the Development Commissioner, with different
procedural and fiscal treatment. Units in an SEZ do not follow the ordinary state
consent route in the same way.

On a greenfield private site: the unit deals directly with the revenue authority for
conversion, the local body for building sanction, the State Board for consents, and the
factories inspectorate for the licence, usually with the state single-window system
coordinating. This route involves more separate applications but more control over the
site.

Practical implication for the profile: the location facts you enter — whether the plot
is in a notified industrial area, the tenure, and the zoning classification — determine
which rules fire. Entering these accurately is the single highest-value thing you can
do for the quality of the approval analysis.
""",
        publisher="State industrial development corporations; Ministry of Commerce & Industry (SEZ)",
        citation="SEZ Act, 2005; respective State industrial development authority Acts and lease conditions",
        topics=["industrial area", "sez", "siting", "land", "allotment", "greenfield", "park"],
    ),
    K(
        "Managing renewals so approvals do not lapse",
        """
Most industrial permissions are time-bound. Lapse is the most avoidable compliance
failure, and its consequences are disproportionate: operating on an expired consent or
licence is generally treated as operating without it.

Permissions that carry a validity period typically include: consent to operate from the
State Pollution Control Board; factory licences; fire NOCs; boiler certificates;
electrical installation approvals; hazardous waste authorisations; petroleum and gas
cylinder storage licences; food and drug licences; and trade licences from local bodies.
Statutory filings recur independently of any validity period: provident fund and ESI
contributions and returns, GST returns, professional tax returns, annual returns to the
Registrar of Companies, and periodic compliance reports attached to environmental
clearances.

A workable renewal discipline:
  1. On receipt of every order, record the issue date, the validity period stated in
     that order, and the renewal lead time prescribed or advised.
  2. Set reminders well before the renewal window opens — many applications must be
     filed a specified number of days before expiry to avoid a gap.
  3. Keep the documents that the renewal application will require current, because a
     renewal often asks for fresh analytical reports, test certificates or updated
     plans.
  4. Treat a renewal as a new application for the purpose of lead time, not as a
     formality.

NIECP-AI's renewal engine derives due dates from the dates you record, sends reminders
at the intervals you configure, and links each renewal to the document and approval it
belongs to. It never assumes a validity period that the order itself does not state.
""",
        doc_kind=PROCEDURE,
        publisher="NIECP-AI platform documentation",
        topics=["renewal", "expiry", "validity", "compliance", "calendar", "lapse"],
    ),
    K(
        "Responding to a query from a government authority",
        """
A query — sometimes called a deficiency memo, show-cause notice, or a request for
additional information — is a normal part of an application process, not a sign that the
application is failing. How it is handled largely determines the outcome.

Practical approach:
  1. Record the exact text of the query, the date received, and the deadline stated.
     Where no deadline is stated, note that fact and seek clarification rather than
     assuming one.
  2. Identify what is actually being asked for: a document, an explanation, a
     clarification of a technical parameter, a correction, or a site visit arrangement.
     Queries frequently bundle several distinct requests; separate them.
  3. For each request, locate the supporting document. If it does not exist, decide
     whether it must be created (a fresh test report, an undertaking, a revised drawing)
     and how long that takes. This is usually the critical path.
  4. Draft the response point by point, referencing the query paragraph numbers, and
     attach documents in the same order.
  5. Have the response reviewed and approved before it is filed. If a technical
     parameter is being restated, check it against the original consent or licence
     application, because an inconsistency between two filings is itself a problem.
  6. File through the channel the authority specified — the online portal, email, or
     physical submission — and keep the acknowledgement.
  7. Record the outcome and update the application status.

Where the query asks for something that was not previously disclosed, the response
becomes part of the permanent record for that permission and for any future renewal, so
accuracy matters more than speed.
""",
        doc_kind=PROCEDURE,
        publisher="NIECP-AI platform documentation",
        topics=["query", "deficiency", "response", "show cause", "notice", "application"],
    ),
    K(
        "Preparing for an inspection",
        """
Inspections are conducted by pollution control boards, factory inspectorates, fire
services, food and drug authorities, electrical inspectorates and local bodies. The
purpose is to verify that what was declared in the application matches what exists on
site, and that the conditions in the order are being complied with.

Preparation that reliably goes well:
  * Keep the order file at the site: the consent or licence, with its conditions, and
    the application it was based on.
  * Maintain the statutory registers and records the order requires — effluent and
    emission monitoring data, hazardous waste manifests, accident and dangerous
    occurrence records, boiler and pressure vessel test certificates, calibration
    records.
  * Verify the physical state against the declared state: does the effluent treatment
    plant operate at the declared capacity, are the stacks at the declared height, is
    the storage arrangement as shown on the approved layout, are the fire systems
    functional and tested, are escape routes unobstructed.
  * Reconcile declared quantities with actuals: raw material consumption, water use,
    waste generation and product output should be consistent with what was declared.
  * Have the responsible person available and briefed, and ensure workers are using the
    personal protective equipment the safety system requires.
  * Document any deviation yourself before the inspection and have a corrective action
    plan with dates. A deviation disclosed with a plan is treated very differently from
    one discovered.

After the inspection, record the findings verbatim, list corrective actions with owners
and dates, and follow up in writing where the authority has asked for something. If a
deficiency notice follows, it becomes a query and is handled as one.
""",
        doc_kind=PROCEDURE,
        publisher="NIECP-AI platform documentation",
        topics=["inspection", "audit", "site visit", "preparation", "checklist", "compliance"],
    ),
]
