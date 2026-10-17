# Daily charting and staff scheduling

## Role-focused workspace

Navigation groups care/charting, daily operations, people/schedules, finance/assistance and administration. The dashboard opens common role-specific workflows and loads recent counts concurrently. Record editors use named patient/staff/payer/invoice/medication and other linked-record selectors. Linked chart records filter by selected patient; the backend independently checks all relationships. Lists currently cap at 500 records and selectors cover those loaded records; larger deployments need server pagination and searching.

## Nursing Station and Doctor Workspace

Select a patient by name/MRN; patients assigned to the staff member's rosters appear first. Each chart template opens a structured blank draft with the actual time of care in the user's local timezone. Times are stored with timezone/UTC normalization. Every entry records author, hospital, patient, care time, creation time and version. Signing adds server-generated signing time. Other staff see signed entries and their own drafts; local administrators can inspect local drafts.

Nursing templates cover shift assessment, vital signs (including respiratory rate), pain/reassessment, medication administration/omissions/reactions, intake/output, nursing care plans, wounds/skin, devices/lines, mobility/safety, education, progress, shift handover and discharge/transfer. Doctors have admission, daily progress, problems, medical orders, results review, consultation, procedure, treatment review, discharge summary and clinical handover templates.

Blank fields remain unrecorded. Choosing “Use as a new draft” requires explicit review and saves no entry until the user submits. It never carries a signature forward. “Review & sign” requires explicit confirmation; signed entries cannot be updated or deleted, including through database guards. A correction/addendum creates a new entry linked to the original signed record, with a mandatory correction reason and its own author/time/signature. Draft edits use optimistic version checks.

Template entries are chart documentation. A textual medication/order entry does not automatically dispense stock, execute an order, administer a drug, submit a claim, or replace the separate operational workflows. Patient portal access to the new ward entries is not implemented. Authorized hospital mobility views include signed entries under the source hospital's sharing rules.

AI can organize a user-supplied de-identified educational draft into headings. It is not given a patient chart, must not invent facts, and returns review-only text. It cannot save or sign entries. Staff must manually verify any copied text. Per-hospital AI enablement, configured credentials and the per-user request budget apply.

## Staff scheduling

Daily, weekly and monthly views show staff member/role, department, time interval, responsibility, on-call primary/backup status, supervisor/covering account, assignments, attendance and handover. Hospital admins assign shifts and patients. Shifts require active local clinician/nurse accounts, explicit timezones and a duration of at most 24 hours. Overlapping duties and approved leave block assignment.

Staff see their own shifts and shifts they supervise. They clock themselves in/out; future/out-of-window check-in is rejected. Scheduled absences can be reported. A handover can be completed only with a signed local handover entry and signed handovers for every assigned patient within the shift's care window. Each patient/chart entry remains separately signed; the roster handover flag does not create clinical content.

Leave requests are submitted by staff and approved/rejected by a hospital admin. Approval is blocked until overlapping duties are covered. Swap requests require two scheduled shifts of the same clinical role, acceptance by the requested colleague and admin approval. Shift versions, active staff, other duties and leave are rechecked before applying the swap. Replacements must have the same clinical role and be free of schedule/leave conflicts. Attendance, assignments and approvals are audited.

The supervisor dashboard shows current shifts, inpatients without a current assignment, overlapping duties and pending handovers. “Find replacement” calculates availability deterministically; it does not claim to assess clinical competency, staffing ratios, labor law, fatigue or credential suitability. Those remain supervisor responsibilities. There is no payroll/timeclock hardware integration, overtime engine or automatic rostering optimizer in this release.
