# Real-world pilot checklist (after development – not yet started)

Nothing in this list has been done. Each item needs real evidence (photos, screenshots, exports, signed notes) recorded in
the pilot log. **A simulated test is never real-world verification.**

## A. Before the pilot (external actions – see BLOCKERS.md)
- [ ] Build and start the Docker stack on the office PC (or a cloud VM); run seed **without** `--demo`; change Owner password.
- [ ] Set real company profile (name, GSTIN, address) in Settings › `company.profile`.
- [ ] CA reviews and sets: GST mode per customer, `tax.gst_rates`, `tax.tds_rates`, `eway.value_threshold`, `payroll.statutory`.
- [ ] Owner sets: margins/discount caps, credit policy, approval thresholds, AI budget.
- [ ] Replace the three placeholder vehicles with real registrations, RC payload, measured body dimensions, tank capacity, baseline km/l.
- [ ] Enter every vehicle compliance document with validity (insurance, road tax, permit, fitness, PUC, RC) and upload scans.
- [ ] Create driver records, licences (class + validity), approved remuneration rules; create driver users (phones).
- [ ] Verify service locations and lane distances/tolls; mark only verified ones.
- [ ] Create staff users with correct roles; ensure a second approver exists.
- [ ] Company bank account(s) with opening balances; customer credit profiles approved.
- [ ] Install the Driver App on each driver's phone; install the Management App for the Owner.
- [ ] Decide SMS/WhatsApp provider; until live, deliver OTPs/updates manually (do not expose dev OTPs: `GRL_EXPOSE_DEV_OTP=false`).

## B. Pilot with the three own vehicles
- [ ] Real enquiry → quotation → booking → credit check (FTL).
- [ ] Allocation checks pass only with valid documents; deliberately expired document blocks dispatch.
- [ ] Driver accepts trip, inspection, package scanning, LR printed, e-way bill entered manually from the GST portal.
- [ ] Phone GPS during trip: positions appear with source and age; switch phone off → shows stale/last known (no invented position).
- [ ] Tracker failover (when trackers fitted): phone off → tracker positions used and labelled.
- [ ] Cameras/DVR (when fitted): 30-day local recording verified on actual hardware; live view via gateway; incident clip preserved under legal hold.
- [ ] Delivery with OTP POD; one partial/short delivery exercise; exception handled and closed with reason.
- [ ] Real expenses (fuel, toll) with photos; fuel anomaly review exercise.
- [ ] Invoice issued; customer pays; real bank statement imported; reconciliation matches; trial balance balanced.
- [ ] Driver earning calculated, approved, settled and paid; driver confirms the statement.
- [ ] PTL: two customers' consignments on one vehicle; separate LR/labels/POD; each customer sees only their own tracking.
- [ ] Compliance renewal end-to-end with Owner approval and payment evidence.
- [ ] Offline: phone in airplane mode for part of a trip; events sync afterwards with correct times; no duplicates.
- [ ] Security: staff role change removes access; ex-employee cannot sign in; customer cannot see another customer's data.
- [ ] Backup to an external drive; restore into a separate database; verification passes; time recorded (first RTO evidence).
- [ ] Tally parallel run for the pilot period; reconcile trial balances; accountant/CA sign-off before switching the authoritative system.

## C. Expansion (only after pilot acceptance)
- [ ] Attached vehicle owners onboarded (KYC, bank accounts approved, owner portal), first attached trips and settlements.
- [ ] Customers onboarded to the portal; vendors to the vendor portal.
- [ ] Live integrations one at a time (bank, GSP/e-way/IRN, SMS/WhatsApp, payment gateway, maps), each sandbox-tested first.
- [ ] Production launch decision by the Owner/Director.

## Unavoidable external actions required for the pilot
Real vehicle/driver documents; CA review of tax/statutory settings; a machine to host the system (office PC with Docker Desktop or a
cloud VM); drivers' Android phones; an SMS or WhatsApp channel for OTPs (or controlled manual OTP delivery during the pilot); bank
statement access (CSV download); optionally trackers/DVRs and their vendor API documentation; a signing key for release APKs.
