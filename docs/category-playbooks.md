# Category Playbooks

One page per target category: what buyers typically ask for, the solution we pitch,
what to put in the technical proposal, and the questions to raise at pre-bid.
Keys in brackets match `config/categories.toml`.

---

## 1. AI / Generative AI implementation `[genai]`
**Typical RFP scope:** GenAI platform for internal knowledge search, drafting of notes/letters, summarisation of files, policy Q&A; often "AI Centre of Excellence".
**Solution blueprint:** RAG over departmental documents → LLM (hosted in Indian region or on-prem open-weight model) → guardrails (PII redaction, citation-required answers, prompt-injection filters) → admin console with audit logs.
**Proposal must show:** data-residency approach, model choice rationale (hosted vs. open-weight), evaluation method (accuracy on a gold Q&A set), hallucination controls, Indian-language support, cost per 1,000 queries.
**Pre-bid questions:** Is cloud allowed or on-prem only? Who owns fine-tuned models? Expected users & concurrency? Are GPU servers in scope or provided?

## 2. Chatbots and AI assistants `[chatbot]`
**Typical scope:** Citizen-facing bot on website, WhatsApp, IVR; FAQ + application status + grievance registration; 10–22 languages.
**Blueprint:** Channel adapters (web widget, WhatsApp Business API, IVR/voice bot) → NLU/LLM with RAG on scheme FAQs → integrations to status APIs → live-agent handover → analytics dashboard.
**Proposal must show:** language coverage & speech (ASR/TTS) quality, containment-rate targets, handover flow, WhatsApp template approval plan, accessibility (GIGW).
**Pre-bid:** Who pays WhatsApp conversation charges? Are backend APIs available? Volume per month?

## 3. Automation and workflow digitization `[automation]`
**Typical scope:** e-Office / file tracking, online approvals, RPA for reconciliations, paperless service delivery.
**Blueprint:** Low-code BPM engine with configurable workflows → RPA / AI agents for repetitive data tasks → DSC / Aadhaar e-Sign integration → SLA monitoring dashboard.
**Proposal must show:** process re-engineering method (as-is → to-be), number of workflows configured in phase 1, change management & training plan, integration with existing HRMS / IFMS.
**Pre-bid:** How many processes and departments? Are process documents available? Licensing model preference (per user vs. enterprise)?

## 4. Data analytics and dashboards `[analytics]`
**Typical scope:** MIS, KPI dashboards, data lake / warehouse, predictive analytics, CM / Secretary dashboards.
**Blueprint:** Ingestion from source systems (APIs, DB replication, Excel uploads) → data lake + warehouse → semantic layer → dashboards (Power BI / Superset / custom) → ML models for forecasting & anomaly detection → natural-language querying.
**Proposal must show:** data source inventory, data-quality framework, refresh latency, role-based access, sample dashboard mock-ups.
**Pre-bid:** Number of source systems and data volume? Is BI tool licence provided? Hosting on State Data Centre or cloud?

## 5. OCR / document processing `[ocr]`
**Typical scope:** Scanning and digitisation of records (land, court, municipal), metadata indexing, DMS, AI OCR for Indic scripts and handwriting.
**Blueprint:** On-site scanning units → image cleanup → OCR/ICR (Indic + English) → AI field extraction & classification → human-in-the-loop QC → DMS with full-text search → retention & archival.
**Proposal must show:** pages/day throughput, accuracy commitments per document type, QC sampling plan, security of records in transit, per-page pricing.
**Pre-bid:** Page count and condition of documents? Scanning on-site or off-site? Which languages/scripts? Accuracy acceptance criteria?

## 6. AI-based monitoring and surveillance analytics `[surveillance]`
**Typical scope:** Video analytics on existing CCTV, ANPR, red-light / speed violation, crowd density, face recognition, VMS upgrade, e-challan integration.
**Blueprint:** Edge or central GPU inference → analytics modules (ANPR, ITMS, crowd, intrusion, abandoned object) → VMS integration → alert workflow to control room → e-challan / police systems.
**Proposal must show:** model accuracy in Indian conditions (night, rain, Indian plates), camera compatibility (ONVIF), GPU sizing, privacy & data-retention policy, OEM authorisations.
**Pre-bid:** Camera make/model/resolution inventory? Network bandwidth to control room? Is hardware supply in our scope? Legal basis for face recognition?

## 7. Software development with AI integration `[software]`
**Typical scope:** Web portals, mobile apps, ERP modules, departmental applications with "AI-enabled" features.
**Blueprint:** Microservices / API-first application → AI services as pluggable modules (document verification, chatbot, recommendations, fraud flags) → CI/CD, security audit (CERT-In empanelled auditor), 3–5 years O&M.
**Proposal must show:** SDLC & agile plan, team loading, STQC / security audit plan, accessibility (GIGW / WCAG), source-code ownership and handover.
**Pre-bid:** Who owns IPR? Hosting environment (MeghRaj / NIC / SDC)? Integration list (Aadhaar, DigiLocker, payment gateway, SSO)?

## 8. PoC / pilot projects `[poc]`
**Typical scope:** EoIs, innovation challenges, hackathons, paid pilots of 3–6 months with option to scale.
**Blueprint:** Fixed-scope PoC on a narrow, measurable problem → success metrics agreed upfront → working demo in 4–8 weeks → scale-up roadmap and cost.
**Proposal must show:** clear success criteria, timeline, what the buyer must provide (data, users), scale-up pricing.
**Why prioritise:** low eligibility barriers, short cycles, and a successful pilot creates the "similar work" credential and the inside track for the full RFP.
**Pre-bid:** Is there a follow-on procurement path? Is the PoC paid? Who owns the PoC IP?

## 9. Smart city and citizen services `[smartcity]`
**Typical scope:** ICCC, citizen portals, property tax / trade licence / water billing, grievance management, digital twin.
**Blueprint:** ICCC platform integrating city systems (traffic, solid waste, water SCADA, parking, environment sensors) → citizen service portal + app → grievance management with AI routing & chatbot → city dashboards and digital twin.
**Proposal must show:** integration experience with OEM systems, SLA-based O&M model, citizen adoption plan, interoperability (open standards, IUDX).
**Note:** Usually large SI tenders with high eligibility — often best pursued as an **AI / analytics specialist in a consortium** with a large SI.
**Pre-bid:** List of existing systems to integrate? Is consortium allowed and how many members?

## 10. IT modernization (AI-ready) `[modernization]`
**Typical scope:** Legacy application re-architecture, cloud migration, data-centre upgrades, digital transformation programmes.
**Blueprint:** Assessment (portfolio, 6R strategy) → re-platform / re-architect to cloud-native → data platform modernization → AI-readiness layer (clean data, APIs, governance) → first AI use cases as quick wins.
**Proposal must show:** migration methodology, zero-downtime cutover plan, rollback strategy, cost model (TCO before / after), security & compliance (CERT-In, MeitY cloud guidelines).
**Pre-bid:** Number and tech stack of legacy apps? Target cloud (empanelled CSP)? Are licences transferable?

---

## Reusable proposal sections (keep updated in the bid library)
- Company profile, turnover certificates (CA-signed), certifications
- Similar-work dossiers per category (work order + completion certificate + 1-page case study)
- Key personnel CVs in RFP format (PM, Solution Architect, Data Scientist, ML Engineer, Security Lead)
- Standard approach & methodology, project plan template, risk register
- Security, privacy and responsible-AI policy (bias testing, explainability, human oversight)
- Hosting options: cloud (empanelled CSP), State Data Centre, on-prem GPU sizing sheet
