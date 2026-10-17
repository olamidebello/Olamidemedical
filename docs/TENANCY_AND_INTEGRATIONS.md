# Hospital tenancy and connected-care integrations

## Deployment on the existing server

The implementation must first be present in the GitHub revision being deployed. The playbook pulls that revision, runs synthetic tests, stops the medical service, backs up the existing installation (including its SQLite database/WAL), installs the code and GUI, migrates existing data, provisions a separate platform administrator, and starts an unprivileged service on port 8095. Existing Nginx and TLS routing is retained. Failures leave the service stopped with recovery archives under `/var/backups/olamidemedical`; restore code and database together after reviewing the failure. The archive can contain sensitive records and needs protected off-server retention.

From a checkout containing this implementation:

```bash
cp ansible/tenancy-vars.example.yml /root/medical-tenancy-private.yml
ansible-vault encrypt /root/medical-tenancy-private.yml
ansible-vault edit /root/medical-tenancy-private.yml
ansible-playbook -i localhost, ansible/deploy-multitenant.yml \
  --ask-vault-pass -e @/root/medical-tenancy-private.yml
```

Replace the placeholder using `ansible-vault edit` before deployment. For a feature branch add `-e medical_revision=<branch-name>`. The default existing database path is `/opt/olamidemedical/data/hospital.db`; select the actual existing path before migration. The playbook does not set up a fresh server or a database cluster.

Sign in at `https://olamidemedical.health` with the configured platform username (default `platformadmin`) and the password in Vault. No password is committed, generated as a default, or printed. Reruns preserve an existing platform password. Existing hospital admins are not silently elevated to platform super admin.

For manual local setup:

```bash
python3 server.py --create-user platformadmin --role super_admin
```

## Independent hospitals and advanced administration

Existing data and accounts migrate into **Existing Hospital**, hospital ID 1. In Hospital administration, the platform administrator can register hospitals, edit names/contact information, view account/patient counts, and suspend/reactivate hospitals. Suspension revokes sessions and blocks login and device ingestion for that hospital. Shared access originating from a suspended hospital is blocked.

Staff & access supports hospital account creation, roles, password resets, suspension/restoration and session revocation. Hospital admins can manage only their own hospital's staff. The last active hospital admin is protected; admins cannot suspend/demote themselves. Patient account identity cannot be changed by switching its role. Usernames are globally unique across this platform instance.

Clinical queries, mutations, appointment conflicts, pharmacy stock, invoices, patient portals and local audit trails are scoped by hospital ID. Request payloads cannot choose the hospital for a clinical record. Database triggers reject cross-hospital links and tenant reassignment. MRNs can repeat across hospitals. Shared SQLite tables provide application and database-guard isolation, not separate database servers or separate encryption keys per hospital.

## Patient mobility across hospitals

1. A care-team member enrolls an existing local patient in Patient mobility. The platform creates a random portability code, storing its hash and displaying the code once. A lost code currently requires operator-assisted recovery; there is no self-service code reset.
2. A source hospital admin/clinician records a documented patient authorization reference, selects a destination hospital and an expiry date (at most one year), then grants sharing of that source hospital's chart.
3. Destination hospital staff search with the exact portability code. There is no unrestricted name search or global patient browser. Knowing a code alone grants no access.
4. The destination reviews allowed source records as read-only and registers a new local patient or links an existing local patient after checking name and date of birth. It adds new encounters, notes, orders and other care records through its normal hospital workspaces.
5. Linked authorized staff can update the shared name/date of birth/phone profile with version checks and a retained previous profile. Local historical demographics and other hospitals' charts are not silently rewritten. The shared profile includes the last modifying hospital/user.
6. The source can revoke access; expiry and revocation are checked on every portability request. Locally created records are retained. Onward sharing conveys only the onward hospital's own chart, never another hospital's source records.

Sharing honors the recipient's clinical role, excludes foreign draft notes and preliminary results, and excludes billing/internal messaging from the portability view. The authorization reference records the operator's evidence; this release does not independently verify a patient's signature or implement legal cross-border consent rules. This works between hospitals registered in this platform instance, including hospitals in different countries; it does not connect arbitrary outside EHR systems. Identity matching remains a human-reviewed workflow, not biometric identity proof or automatic duplicate merging.

## Device integration hub

Hospital admins register a device/gateway with its name, manufacturer, model and input protocol. The device token is displayed once; only its hash is stored. Rotate tokens or disable devices from the GUI. Clinical staff can inspect the hospital's pending observations; platform super admins cannot read device data across hospitals.

Send HTTPS POST requests to `/api/device-ingest` with `Authorization: Bearer <device-token>` and `Content-Type: application/json`. Tokens bind the device to a hospital; a payload cannot select a hospital. `patient_id` must identify a patient already registered locally. A gateway must resolve the device's patient identifier to that local ID before sending. This implementation does not automatically associate measurements with patients based on bed numbers or device location.

Normalized JSON example (synthetic values):

```json
{
  "patient_id": 1,
  "message_id": "monitor-001-reading-0001",
  "code": "8867-4",
  "value": 72,
  "unit": "/min",
  "observed_at": "2026-10-17T03:00:00Z"
}
```

The FHIR subset accepts a single numeric `Observation` with `id`, final/amended/corrected `status`, `subject.reference` of `Patient/<local-id>`, a LOINC code, UCUM `valueQuantity`, and timezone-aware `effectiveDateTime`. It does not implement a full FHIR server, bundles, component observations, imaging, waveforms or vendor authentication profiles. Amended/corrected readings need a distinct message ID; prior readings are never overwritten.

Ingestion validates finite numeric values, local patient ownership, protocol and timestamps. Duplicate device/message IDs with identical content return the existing reading; conflicting content returns 409. Original device/time/code/value/unit and review provenance are retained. Tokens and clinical payloads are not written to server access logs by the application.

Readings remain **pending** until a clinician/nurse/admin accepts or rejects them. Accepted supported vital codes create a new local vital record; they do not overwrite an existing signed chart. The original observation time remains in the linked device reading; the vital creation time records when review occurred. Repeated acceptance is rejected. Clinical range checks, alarm thresholds, calibration and unit conversions are not implemented.

| LOINC | Vital field | Required UCUM unit |
|---|---|---|
| 8310-5 | Temperature | Cel |
| 8867-4 | Pulse | /min |
| 8480-6 | Systolic pressure | mm[Hg] |
| 8462-4 | Diastolic pressure | mm[Hg] |
| 59408-5 | Oxygen saturation | % |
| 29463-7 | Weight | kg |

Other numeric codes/units can be stored as pending telemetry but cannot be posted to vitals without an approved mapping. Separate adapters are needed for HL7 v2/MLLP, DICOM/PACS, serial/USB, proprietary monitor SDKs, lab analyzers and ventilators. There is no device-control channel, alarm delivery guarantee, or claim of universal device compatibility.

## Verification

```bash
python3 -m unittest discover -s tests -v
npm ci --prefix tests/browser --no-audit --no-fund
npm test --prefix tests/browser
ansible-playbook -i localhost, ansible/deploy-multitenant.yml --syntax-check
```

Tests use synthetic local data. Actual device interoperability, production deployment, recovery restoration and cross-border policy validation require environment-specific checks.

## Registration and private-practice management

The login page includes hospital/practice onboarding requests and single-use invitation redemption. New hospital requests remain pending until a platform administrator approves or rejects them. Approval creates the hospital and returns one seven-day invitation for its first administrator. No email is sent automatically; the operator must deliver the invitation through an approved private channel.

Hospital admins register employees with employee number, name, contact, department and job title. Staff and patient invitations bind the user to a hospital and fixed role. A patient invitation must be bound to an existing local patient record; a staff invitation can link an active unlinked employee. Codes are hashed, expiring, revocable and single-use. Redeeming an invitation does not permit selecting another role/hospital/patient. Employment records and access accounts are separate; suspend a linked account before marking its employee inactive.

The organization types are hospital, clinic, private doctor and private nurse. Private doctors/nurses have local professional profiles, specialties, license number/jurisdiction/expiry, credential-review status, consultation fee/currency and linked clinician/nurse accounts. Availability slots reject overlapping times and require explicit timezones. A credential review is a hospital attestation, not a regulator/license verification integration. Billing fees are catalog information, not automatic card charging.

## Knowledge, AI and staff assistance

Knowledge articles have categories, source references, reviewer names and draft/published/archive states. Nurses and pharmacists see published articles; admins/clinicians author and review them. Staff aid requests track questions, urgency, assignment, responses and resolution. Immediate emergencies must use the hospital's emergency escalation channel; these queues do not guarantee real-time response.

The OpenAI-backed assistant is a clinical-education and knowledge-navigation tool for admins, clinicians and nurses. A platform administrator enables it per hospital. A server-side API key is also required. Published local knowledge sources are supplied as context, but patient charts, device data and cross-hospital records are not retrieved for AI requests. Users must confirm that their questions contain no patient identifiers/private data. Responses are drafts requiring human review and cannot issue orders, sign charts or silently alter clinical data. `store: false` is sent to the Responses API; this does not by itself imply zero provider retention or a healthcare data agreement.

A local key can live in the Git-ignored `.env.local` file. For explicit deployment from a control machine that holds that file, add `-e medical_ai_env_file=/absolute/path/to/.env.local`; Ansible copies it with protected permissions to `/etc/olamidemedical/ai.env`. Do not commit the file or put its contents in shell arguments. The default model is configurable with `OPENAI_MODEL` (currently `gpt-4.1-mini`). The UI reports whether hospital permission and provider credentials are configured.

Official API implementation reference: https://developers.openai.com/api/docs/guides/text

## Telemedicine

The telemedicine workspace supports local patient/provider scheduling, waiting/in-progress/completed/cancelled visit states, consent references, two-party authenticated consultation chat, browser WebRTC audio/video, microphone/camera toggles, screen sharing and leaving a call. Patients see only their visits; clinicians/nurses see assigned visits. Reception/admin staff can coordinate schedules but cannot read consultation signaling/chat unless they are an assigned participant. Clinical care notes remain in the patient's normal charting workspace. Visits do not generate prescriptions or diagnoses automatically.

Participants need an active visit and recorded consent before accessing chat/media signaling. Browser camera/microphone access requires HTTPS and user permission. Browser media travels directly between peers or through the configured TURN relay; application signaling uses authenticated local APIs. Chat persists locally; obsolete media signaling is not exposed after visit completion. Recording, multiparty visits, file transfer, e-prescribing, interpreter dial-in, automated notifications and insurance network integration are not implemented.

Configure TURN for reliable connectivity across restrictive networks:

```bash
ansible-playbook -i localhost, ansible/configure-telemedicine-relay.yml \
  --ask-vault-pass -e @/root/medical-turn-private.yml
```

The encrypted variables must include `medical_turn_public_ip` and a unique URL-safe `medical_turn_secret` of at least 32 characters. The relay playbook manages `/etc/turnserver.conf`, installs coturn, and writes `/etc/olamidemedical/turn.env`. It requires explicit network access to UDP/TCP 3478 and the selected UDP relay port range (default 49160–49200); it does not open provider or host firewalls. The application mints one-hour TURN credentials. TURN over TLS/443 and real multi-network call testing remain deployment tasks. Without relay configuration, the GUI indicates the limitation rather than claiming all calls will connect.

## Insurance and charity workflows

Insurance menus cover local payer records, patient policies/coverage dates, manual eligibility references, prior authorizations/units, invoice-linked claims and immutable remittance/adjustment postings. Links must reference the same local patient/hospital. Advancing a claim beyond draft requires an external payer reference; no electronic submission or eligibility exchange is simulated. Remittances are bounded by the outstanding claim amount and update calculated claim settlement status. They do not automatically create a patient payment or collect funds. EDI/X12 transactions, clearinghouses, contracted payer APIs, denial appeals, automated coding and insurer-specific rules require separate integrations.

Charity organizations have registration identifiers, contacts and status. Patient sponsorships link a local patient, charity and invoice with a financial reference/status. These record administrative pledges/payments entered by staff; they do not verify charity status, move funds or charge a donor.

Coupon controls support fixed-cent/percentage discounts, minimum invoice amounts, optional maximum discounts, expiry and usage limits. Redemption is transactional, recalculates the discount on the server, preserves the original amount, and updates the open invoice balance. An invoice may redeem one coupon, before any payments or nonvoid claims exist. References are unique; prior redemptions cannot be edited. Tax recalculation, coupon refunds and reversing a redeemed discount require a separate financial-correction workflow.

## Alerts

Alerts have severity, staff audience, assignment, due time, acknowledgment/resolution state and a resolution response. Audience and hospital filters run on the backend. New device observations create pending-review alerts for clinical staff. The deployed alert worker checks low stock, stock expiry, professional credentials, coverage, authorizations and coupon expiry every five minutes. Conditions produce deduplicated durable alerts for review; resolved alerts are not automatically reopened for recurring conditions in this version.

The current delivery channel is the in-application queue. External email, SMS, push, paging, escalation SLAs and physiologic device alarm interpretation are not connected. It must not be used as a bedside alarm or emergency-response system.

## Advanced closed-loop care and safety workflows

The Safety Command Center aggregates unresolved critical-result tasks, referral follow-ups, medication-review drafts, transition tasks, safety reports, pending device observations and urgent staff requests. Counts and identity-review candidates remain local to the hospital. Similar name/date-of-birth records are flagged for human identity review; they are never automatically merged.

Critical-result tasks reference a finalized local result, responsible staff member, severity and deadline. Acknowledgment/read-back records a server-generated user/time; the assigned owner or hospital admin must acknowledge before resolving. A resolution outcome is required and closed communications are immutable. These features do not interpret result severity automatically or provide a guaranteed emergency notification channel.

Referral follow-up records receiving-provider acceptance and the eventual consultation/outcome before completion. Medication reconciliation records its information source, reviewed list, discrepancies, documented resolution and server-generated reviewer/time; completed reviews are immutable and do not automatically change medication orders. Care-transition tasks track an owner, deadline, contact attempts and outcome. Safety event reports document the event, immediate response, investigation and hospital-admin closure summary. They do not automate clinical judgments, prescribing or incident culpability.

The alert worker creates durable overdue-review alerts for critical-result, referral and transition tasks. Review cadence is five minutes and external paging/SMS is not connected. These queues must not replace clinical emergency processes.

Design references (workflow guidance, not a claim of certification or platform exclusivity):

- ONC SAFER Guides — patient identification, results follow-up and clinician communication: https://healthit.gov/clinical-quality-and-safety/safer-guides/
- AHRQ MATCH medication-reconciliation toolkit: https://www.ahrq.gov/patient-safety/settings/hospital/match/index.html

No claim is made that these features are unavailable in other platforms. The distinguishing implementation here is their combination with hospital isolation, ownership checks, explicit review and traceable workflows.
