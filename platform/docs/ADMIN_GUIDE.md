# Administration guide – roles, approvals, settings

## Roles (initial)
Owner/Director · Operations Manager · Dispatcher · Accounts · HR · Customer Support · Sales/Marketing · Fleet/Maintenance ·
Compliance Coordinator · Store/Godown Custodian · System Administrator · Driver · Attached Vehicle Driver · Customer Admin ·
Customer User · Attached Vehicle Owner · Vendor User · CA/External Auditor.

- One person may hold several roles (small team). Permissions are checked on the server for every request.
- **System Administrator** manages users, settings and integrations but **cannot** approve finance – separation of duties.
- External roles (customer/owner/vendor/driver) can only hold portal/app permissions and are always tied to their own record.
- **CA/auditor** users require a purpose and an end date; access stops automatically at the end date.
- Role changes, deactivation and employee exit revoke sessions immediately.

## Two-step sign-in
Each staff user can enable an authenticator-app code from the sidebar link **Enable 2-step**. Strongly recommended for the Owner/Director, Accounts and administrators. If a phone is lost, an administrator verifies the person's identity and uses **Admin › Users › Reset 2-step** (all sessions are signed out).

## Creating users
Admin › Users › + User. Choose the role; link customer/owner/vendor/driver where required. Drivers sign in by phone OTP (no password).
Passwords: 10+ characters with letters and digits. Ask users to change initial passwords.

## Approval matrix (maker-checker; nobody approves their own request)
| Request | Approver permission | Typical holder |
|---|---|---|
| Below-floor quotation price | quote.approve_discount | Owner/Director |
| Credit limit / credit exception | credit.approve | Owner/Director |
| New/changed party bank account | masters.approve | Owner/Director (a different person from the one who entered it) |
| Expense above threshold | accounts.approve + Owner/payment approver above `approval.thresholds.expense` | Owner/Director |
| Procurement above threshold, repairs above threshold | procurement.approve / accounts.approve | Owner/Director |
| Driver/owner settlement, driver earning, driver advance | settlement.approve | Owner/Director |
| Payment (always) | payment.approve; execution by someone other than the preparer | Owner/Director |
| Compliance renewal expense (always) | compliance.approve_renewal | **Owner/Director only** |
| Driver remuneration rule | remuneration.approve | Owner/Director |
| Payroll, salary change | payroll.approve | Owner/Director |
| Budget, campaign, major marketing content | budget.approve / marketing.approve | Owner/Director |
| Claim financial treatment | claim.approve | Owner/Director |
| Tally/import batch commit | accounts.approve (different user from preparer) | Owner/Director |

Change who holds a permission in Admin › Users & roles (audited). With a single director, add a second trusted approver
(e.g. a partner or the CA) for requests the director prepares personally.

## Settings
Admin › Settings lists every business value (credit policy, margins, discount caps, PTL formula, approval thresholds, fuel anomaly
thresholds, maintenance intervals, retention, notification caps, AI budget/routing, GST/TDS/payroll placeholders, company profile…).
Each change needs a reason, creates a new version (history kept) and can be effective from a future date. Financial and safety
policy keys can be changed only by the Owner/Director.

## Integrations, messages, audit
- Admin › Integrations shows each provider's mode (MOCK/LIVE). See INTEGRATIONS.md before connecting anything.
- Admin › Messages: delivery log; complaint/claim/legal/pricing messages are **held** until approved.
- Admin › Audit: filter by record; **Verify chain** checks the tamper-evident audit trail.

## Scheduled checks
The worker runs every 5 minutes (compliance expiry alerts, message delivery, GPS staleness, escalation of overdue exceptions,
recommendations, retention). Control Tower › *Run checks now* triggers them manually.
