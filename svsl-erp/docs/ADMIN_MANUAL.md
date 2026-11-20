# Administrator manual

## Roles and permissions

| Role | Typical person | Can do |
|---|---|---|
| Super Admin | IT / system owner | Everything, including restore and creating other admins |
| Owner | Proprietor / partner | Everything |
| General Manager | GM | All operations & finance, cancellations, rate approval; no user admin / restore |
| Accountant | Accounts | Invoices (incl. cancel & credit notes), vouchers, purchase, compliance, payroll |
| Transport Manager | Ops head | Bookings, LR (incl. amend/cancel), trips, vehicles, drivers, routes, fuel |
| Dispatch Operator | Dispatcher | Bookings, LR, trips, fuel entries |
| Warehouse Manager | Godown in-charge | Godown stock, inward/outward, labels |
| Fleet Manager | Workshop / fleet | Vehicles, maintenance, tyres, fuel, tolls, purchase |
| HR Manager | HR | Employees, drivers, attendance, payroll, Aadhaar/bank numbers |
| Driver | Each driver | Driver app only – own trips |
| Customer | Customer staff | Customer portal only – own data |

*Users → Roles* lets you edit the permissions of non-full-access roles or create custom roles. Permission
`x:write` includes `x:read`. Special permissions: `lr:cancel`, `lr:amend`, `invoices:cancel`, `accounts:cancel`,
`rates:approve`, `drivers:aadhaar`, `hr:salary`, `backup:restore`.

## Users

* *Users → + User*. Give each person their own login; never share passwords.
* Customer portal login: role **Customer** + select the customer (or *Customers → open → Create portal login*).
* Driver app login: role **Driver** + select the driver. Drivers open the same address on their phone and can
  *Add to home screen* (PWA).
* New users must change their password at first sign-in. 5 wrong passwords lock the account for 15 minutes
  (*Unlock* in the user form). *Reset 2FA* if a phone is lost.
* Disabling a user ends all their sessions immediately.

## Numbering

*Settings → Numbering*. Every document type has a series per financial year (`{prefix}{fy}/{no}` → e.g.
`SVSL/LR/2026-27/00001`). The next number can be increased, never decreased; the database also enforces
uniqueness. A new FY starts at 1 automatically using the previous year's prefix and format.

## GST configuration

*Settings → GST treatments*: each treatment has SAC, rate, mechanism (FCM / RCM / EXEMPT / NIL) and ITC flag.
Assign a default treatment to customers and/or rate contracts; the invoice screen can override it. Place of supply
follows the recipient's GSTIN state (registered) or the customer state code. Enable e-invoicing in *Settings → Gst*
only after confirming applicability.

## Books lock

*Settings → Accounts → lock before* – no voucher (invoice, receipt, expense…) can be posted with a date before
this. Use after monthly / annual closing.

## Alerts & notifications

*Settings → Alerts* – expiry reminder days (30/15/7/1), abnormal fuel tolerance %, delay grace hours, POD pending
days, contract renewal days, credit-limit warning %. *Settings → Notifications* switches email / WhatsApp / SMS on;
*Settings → Notification templates* edits texts (placeholders in `{braces}`). *Settings → Integrations* shows what is
configured and has a *Send test* button.

## Backups & restore

See DEPLOYMENT.md. *Backup* screen: Backup now, download ZIP / pg_dump, Verify, Restore (type RESTORE).
*Export all data* gives one Excel workbook with every table (secrets excluded).

## Audit

*Audit trail* records every create / update / cancel / amend / post / restore / login-related admin action with
user, time, IP, before and after values and reason. *Users → Login history* lists successful and failed sign-ins;
*Sessions* lists active sessions with an *End* button.

## Data retention

*Settings → Retention*: notification log and login history are pruned after the configured days. Business records,
vouchers and the audit trail are never deleted automatically.
