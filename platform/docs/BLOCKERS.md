# External prerequisites register (genuine blockers only)

Development has continued around every item below using MOCK adapters. None of these blocks using the core ERP.

| # | Prerequisite | Needed for | Who acts | Status |
|---|---|---|---|---|
| X-01 | Bank corporate API / host-to-host or authorised aggregator credentials and corporate authorisation | Automatic statement fetch, payment initiation | Owner + bank | Not available – CSV statement import works now |
| X-02 | GSP/ASP (or NIC) credentials and authorisation for GSTIN verification, e-invoice IRN, e-way bill | Live GST/IRN/e-way | Owner + CA + GSP | Not available – MOCK |
| X-03 | Income-tax / ERI access (if eligible) | AIS/26AS/TDS workflows | CA | Not available – manual CA workflow |
| X-04 | Tally version/edition and preferred integration method | Live sync (file XML works now) | Accountant | To confirm |
| X-05 | WhatsApp Business API provider + approved templates | WhatsApp messages | Owner | Not available – MOCK |
| X-06 | SMS (DLT-registered sender/templates) and email (SMTP/API) credentials | OTP, notifications | Owner | Not available – MOCK (OTP shown on screen in development only) |
| X-07 | Payment gateway merchant account | Online customer payments | Owner | Not available – MOCK |
| X-08 | Maps/geocoding/routing provider key | Accurate distances/ETA | Owner | Not available – lane master + straight-line estimate |
| X-09 | GPS trackers (3) + vendor API/SDK documentation | Tracker failover | Owner/fleet | Hardware not procured – webhook ready |
| X-10 | DVRs (3), cameras (6), 4G/5G routers/SIMs + vendor streaming SDK | Live camera, clips | Owner/fleet | Hardware not procured – MOCK stream token |
| X-11 | Cloud hosting account (India region preferred) + S3-compatible object storage | Staging/production | Owner | Not available – Docker compose + encrypted local storage |
| X-12 | AI provider API key(s) and budget approval | Language-model assistants | Owner | Not configured – deterministic MOCK assistant |
| X-13 | Google Business Profile / Meta / YouTube / LinkedIn API access | Publishing | Owner | Not available – MOCK publish |
| X-14 | CA review of GST mode, rates, TDS, e-way thresholds, payroll statutory settings | Correct tax/statutory figures | CA | Pending |
| X-15 | Insurer policy documents (motor, GIT/cargo, liability) | Accurate claims workflow | Owner | Pending |
| X-16 | Real vehicle RC, permits, insurance, fitness, PUC, tax documents and driver licences | Dispatch gates will block until entered | Compliance coordinator | Pending |
| X-17 | Professional verification of basement godown (approved use, fire, structure, access) | Any godown custody | Owner + professionals | Pending – blocked in system |
| X-18 | Android SDK / signing key for release APKs | Installable signed APKs | Developer/Owner | Debug APK builds configured in CI; release signing key needed |
| X-19 | Container network in build environment | Building Docker images | Developer | The development sandbox has no container DNS; images must be built on the Windows PC or CI (see DEPLOYMENT.md) |
