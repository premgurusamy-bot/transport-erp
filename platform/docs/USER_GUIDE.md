# User guide – Windows ERP and management

Sign in at the ERP address (e.g. http://localhost:8080) with your email/phone and password. The left menu shows only what
your role allows. Every important action is recorded in the audit trail. Red messages list exactly which checks blocked an action.

## A normal day (Control Tower)
1. **Control Tower** – overnight trips, vehicles ready/blocked (compliance, defects), bookings to plan, credit holds, POD to verify,
   exceptions (sorted: safety/legal/custody first). Close an exception only with a reason.
2. **Approvals** – requests waiting for you (discounts, credit, payments, settlements, renewals, bank details…). You cannot approve your own.
3. Plan dispatch, monitor trips, verify PODs, review expenses, chase collections, reconcile the bank, prepare tomorrow.

## Enquiry → quotation → booking
1. **Enquiries › + Enquiry** (phone/WhatsApp/email/website enquiries arrive here too). Missing details and possible duplicates are flagged.
2. **Quote** – choose own or attached vehicle (enter the owner's quote for attached). The system computes internal cost, floor price and a
   suggested price. A price below the floor needs a reason and management approval; discounts above the cap are refused.
3. **Quotations › Send**, then **Record acceptance** (or the customer accepts in the portal).
4. **Bookings › + Booking** – pick the accepted quotation, fill consignor/consignee (consignee phone enables delivery OTP), packages and weight.
   For PTL tick "customer informed transport is SHARED".
5. Open the booking → **Confirm**. The credit gate runs: OK/warning → confirmed (LR number and package QR labels created);
   blocked → on hold with reasons. Use **Request credit exception** if justified (approver decides).

## Dispatch
1. **Dispatch** – tick one FTL booking (or several PTL bookings) → **Allocate selected**. Candidates are ranked; **Run allocation checks**
   shows every legal/safety/commercial check. Legal and safety failures cannot be overridden.
2. For PTL, choose a vehicle → **PTL consolidation proposals** (provisional; confirm physically when loading).
3. Open the trip: the driver accepts the trip and GPS notice in the app, does the pre-trip inspection and scans every package while loading.
   Generate/enter the e-way bill for each consignment. **Dispatch readiness** turns green → **Authorise dispatch** (enter start odometer).

## During the trip
Trip detail shows events, position source and age (stale positions are shown as stale – never guessed), ETA and delays.
Breakdown/accident/SOS create critical exceptions and incidents automatically.

## Delivery and closing
Driver submits POD (OTP from consignee, or signature/photo). Short/damaged deliveries create blocking exceptions.
**Verify POD** in the trip. Approve the trip's expenses (Accounts › Expenses). **Close trip** with end odometer – this releases the vehicle,
ends temporary driver access and calculates driver pay from approved rules.

## Billing and money
- **Accounts › Invoices** – bookings with verified POD appear under "Ready to bill"; select and **Generate invoice** (GST per configured rule). **Print** for a printable copy.
- **Receipts** – record customer payments; they stay *unconfirmed* until matched with the bank statement.
- **Bank reconciliation** – import the bank CSV daily; exact matches confirm automatically, others wait in the exception queue. Unknown credits are never treated as customer payments.
- **Settlements & payments** – create owner/driver settlements (closed trips / approved earnings), submit for approval, prepare payment,
  a second person executes it (enter the bank UTR, or MOCK bank API in development).
- **Reports** – trial balance, P&L, balance sheet, ageing, GST register, profitability (by service, vehicle, lane, customer). Export CSV/Excel/PDF.
- **Cash flow & budget** – 8-week forecast (labelled FORECAST with assumptions) and budget vs actual.
- **Tally / migration** – export vouchers to Tally XML; import Tally XML (dry run → another user approves → commit; reversible).

## Fleet
Vehicles, compliance documents and **renewals** (Owner/Director approves every renewal expense), safety defects (critical defects block
dispatch until released by a different authorised person), fuel (anomalies go to review – never automatic deductions), maintenance,
tyres, drivers (pay rules need approval), vehicle owners and load requests.

## Other areas
Vendors & procurement (RFQ, comparison, PO, receipt, 3-way match), inventory, godown (verified facilities only), complaints & claims,
insurance and legal (restricted), HR/payroll/SOPs/checklists, marketing (drafts, approvals, caps), AI assistants (advice only).

## Tamil / English
Switch with **EN / தமிழ்** in the menu (translation coverage is being extended; untranslated items show in English).
