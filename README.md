# Olamide Medical

Runnable hospital management foundation with a responsive browser workspace, SQLite persistence, authenticated APIs, seven roles, and a restricted patient portal. Python 3.12+; no third-party runtime dependencies.

## Start locally

```bash
python server.py --create-user administrator --role admin
python server.py
```

Open http://127.0.0.1:8080. No default password or demonstration patient records are installed. Passwords must contain at least 12 characters.

Create additional accounts using `--role clinician`, `nurse`, `pharmacist`, `reception`, or `billing`. After registering a patient, create a portal account:

```bash
python server.py --create-user patient1 --role patient --patient-id 1
```

All accounts use the same database selected by `DATABASE_PATH` (default `data/hospital.db`).

## Implemented workflows

* Registration: generated unique MRNs, demographics, contact, emergency contact and insurance text fields.
* Scheduling: provider/department appointments, exact-time conflict rejection, check-in/completion/cancellation status, referrals and authorization tracking.
* Chart records: encounters, history, allergies, medications, notes, vitals, orders, diagnostic results, care plans, immunizations, care teams and text documents/consents.
* Signed notes and final results become immutable. Addenda are new records referencing the original in their text; this is not a full clinical signature system.
* Pharmacy: inventory, expiry and reorder fields, prescriptions, pharmacist verification, stock-linked dispensing, insufficient/expired-stock rejection and duplicate dispensing protection. Administration records link to a patient's medication and are immutable.
* Capacity: bed assignment with one active bed per patient and occupied/available/cleaning/maintenance states. Encounter and bed updates are separate operations.
* Revenue: charges stored in integer cents, partial manual payments, overpayment rejection, automatic paid status and immutable payment ledger. These are accounting records, not card processing.
* Operations: message records, workqueues, specialty case records and population outreach tracking.
* Patient portal: patient-scoped reads, final results only, appointment requests and message creation. No self-registration, proxies or document uploads.
* Administration: CLI account creation, module role permissions, read/write/login audit events, search, JSON export, overview counts and optimistic concurrency checks.

Every displayed module has a database-backed list and create/edit form subject to role restrictions. Patient IDs and linked record IDs are entered explicitly. This first version uses shared record editors rather than specialized clinical screens.

## Scope against the requested enterprise suite

| Area | Current implementation | Remaining work |
|---|---|---|
| Core access and navigation | Role workspace, module search, sign-out | MFA/SSO, department-scoped access, inactivity lock, account lifecycle GUI |
| Registration/access | Demographics, MRNs, appointments, referrals | Duplicate merge, eligibility transactions, waitlists, scheduling rules, reminders |
| Clinical care | Structured records and manual status workflows | Order catalogs/sets, clinical decision support, drug interactions, reconciliation, validated electronic signatures |
| Inpatient/nursing | Vitals, care plans, medication administration, beds | Barcode verification, monitor feeds, flowsheets, handoffs, discharge automation |
| Pharmacy | Verification and stock-linked dispensing | Formulary, multiple lots, suppliers/purchasing, controlled substances, e-prescribing network |
| Specialty care | Generic specialty/procedure records | Dedicated ED, surgery, anesthesia, oncology, radiology, pathology and other specialty workflows |
| Billing | Charges and manual payment ledger | Coding, payer contracts, claims/EDI, eligibility, payment gateways, financial assistance |
| Portal/mobile | Responsive patient-scoped web access | Native apps, video visits, proxy access, remote monitoring, temporary sharing |
| Analytics | Workspace counts and JSON export | Quality measures, cohort query engine, trends and report designer |
| Interoperability | Internal JSON API | Validated FHIR/HL7, DICOM/PACS, external record exchange and device integrations |
| AI | Not implemented | Credential setup, vendor agreement, clinician review, evaluations and approved use cases |

This is an original implementation, not an Epic product or a complete replacement for a certified enterprise EHR. The advanced capabilities above are not represented as working integrations.

## API

POST `/api/login` with username/password sets an HttpOnly SameSite cookie. GET `/api/me` returns the schema and authorized modules. Every data module supports GET `/api/{module}`, POST `/api/{module}`, and PATCH `/api/{module}/{id}`. PATCH requires the current `version`. Clinical links are checked for matching patient IDs. Mutating authenticated requests require `X-Requested-With: OlamideMedical`. GET `/api/audit` is administrator-only. GET `/health` is public. Lists are capped at 500 records, and overview counts represent the retrieved records, not enterprise census totals.

## Deployment

```bash
docker compose up -d --build
docker compose exec medical python server.py --create-user administrator --role admin
```

The compose service binds only to loopback. Place a TLS reverse proxy in front of it; `COOKIE_SECURE=1` requires HTTPS. For local non-TLS development use `python server.py`. The image runs as a non-root user. Preserve the `hospital-data` volume, take encrypted SQLite online backups, and test restoration. Do not copy a live SQLite database without its WAL; use SQLite's backup API.

Before real patient use, complete an independent security and clinical review, access controls for each department, encryption/key management, durable audit retention, database migrations, backup recovery, monitoring, high availability, and applicable privacy/compliance requirements. This code has not been certified or assessed for real clinical use. Standard-library HTTP serving and SQLite are intended here for development/small single-instance evaluation, not a production hospital cluster.

## Verification

```bash
python -m unittest discover -s tests -v
python -m py_compile server.py
node --check static/app.js
```

Integration tests exercise registration through billing, appointment conflicts, signed-note immutability, stale edit rejection, cross-patient links, portal isolation, stock dispensing and duplicate-dispense prevention.
