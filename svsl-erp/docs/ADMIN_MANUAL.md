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
`SVL/LR/2026-27/00001`). The next number can be increased, never decreased; the database also enforces
uniqueness. A new FY starts at 1 automatically using the previous year's prefix and format.

## Document layouts (invoices, LR, reports)

*Settings → Document layouts* changes how printed PDFs look, separately for **Invoices & notes**, **LR (A4)**,
**LR (thermal roll)** and **Reports & statements**:

* **Page** – paper size (A4 / A5 / Letter / Legal), orientation, margins, font size, footer text, page numbers.
* **Header** – logo position (left / right / centre / none) and size; which company details print (legal name,
  address, GSTIN, PAN, CIN, contact); extra header lines; document titles (e.g. rename "TAX INVOICE" to
  "FREIGHT BILL", "LORRY RECEIPT" to "GOODS CONSIGNMENT NOTE").
* **Colours** – accent colour, table borders, table header background.
* **Copies** – which copies print, one page each (e.g. *Original for Recipient*, *Duplicate for Supplier*; LR:
  Consignor / Consignee / Driver / Office). Freight amounts can be hidden on chosen LR copies.
* **Columns** – show/hide, rename, re-order and size the columns of the invoice and LR goods tables
  (the description column always prints).
* **Sections** – QR code, bank details, amount in words, tax summary, terms, declaration, delivery points,
  driver details, acknowledgement box, signature-box labels, extra note, watermarks for proforma / cancelled.
* **Signature & stamp images** – upload the authorised signatory's signature and the company seal (PNG with a
  transparent background works best); they print in the signature box.

**Preview PDF** shows the unsaved layout on your latest real document (or a marked SAMPLE). **Save layout**
applies it to every print from then on (reprints of old documents use the new layout too – the data never
changes, only the look). **Reset to default** restores the original design. GST-mandatory wording such as the
reverse-charge statement is always printed. Every layout change is recorded in the audit trail.

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

## Sample data & factory reset
* **Sample data:** every release includes `A_PRIME_ERP_SAMPLE_DATA.zip` – three months of clearly marked DEMO customers, vehicles
  (state code 00), drivers, trips, LRs, invoices, receipts, maintenance, stock and payroll, with balanced books. Load it with
  **Admin → Backup → Restore from file** and type RESTORE. Restoring a sample replaces all business data, but always keeps
  your users and passwords, company profile and settings. An automatic backup is taken first.
  To build the file yourself on an empty database: `svsl-server sample-backup A_PRIME_ERP_SAMPLE_DATA.zip` (or
  `python svsl_server.py sample-backup …` in `backend/`).
* **Factory reset** (Admin → Backup → Factory reset…; needs the *Restore backups* permission, your password and typing RESET)
  deletes all customers, vehicles, drivers, vendors, routes, trips, LRs, invoices, vouchers and ledgers, stock, HR/payroll
  records and uploaded documents. It keeps users and roles, the company profile, settings and document layouts, GST
  treatments, compliance rules, message templates, leave types, departments, statutory registers, account groups, backup
  history and the audit trail; the system ledgers, document numbering and this year's compliance calendar are recreated.
  A full verified backup is taken first, so a reset can be undone with Restore. The reset is recorded in the audit trail.
  Portal and driver logins linked to deleted customers/drivers are disabled.

## Audit

*Audit trail* records every create / update / cancel / amend / post / restore / login-related admin action with
user, time, IP, before and after values and reason. *Users → Login history* lists successful and failed sign-ins;
*Sessions* lists active sessions with an *End* button.

## Data retention

*Settings → Retention*: notification log and login history are pruned after the configured days. Business records,
vouchers and the audit trail are never deleted automatically.
