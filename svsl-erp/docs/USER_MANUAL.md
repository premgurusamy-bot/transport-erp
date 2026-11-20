# User manual

The menu on the left (☰ on phones) shows only the screens your role allows. Language: English / தமிழ் at the top.
Every list has search; click a row to open it. Amounts are in ₹ with Indian grouping (12,34,567.00), dates DD-MM-YYYY.

## Daily operations

### 1. Booking → trip
* **Bookings → + New** (phone/email requests) – portal bookings from customers appear here automatically.
* *Create trip* on a booking, or **Trips → + New trip**: customer, route (fills From/To and expected transit time),
  vehicle and driver. The system refuses a vehicle that is on another trip, under maintenance or whose
  insurance/FC/PUC has expired, and a driver whose licence has expired.

### 2. LR (lorry receipt)
* **LR → + New LR** (or *+ LR* inside a trip). Choose customer and trip; consignor details fill from the customer.
* Add goods lines (description, HSN, packages, quantity, weight, value) and optional extra delivery points.
* *Freight from: Rate contract* shows the calculation live (e.g. 1 trip × ₹12,000 + loading). Choose *Manual entry*
  for a spot rate and give the reason.
* Enter the e-way bill number if goods value is above ₹50,000 (configurable) – dispatch is blocked without it.
* **Generate LR** → number is assigned. Open it to print **PDF** (all copies), **single copy** or **Thermal 80 mm**,
  share by **WhatsApp** / **email**, record the **e-way bill** / Part-B vehicle change, mark **delivered**, **upload POD**.
* **Amend** (permitted users): only changed fields, who authorised it and why – before/after values are kept.
  **Cancel**: reason required; billed or delivered LRs cannot be cancelled.
* The QR code on the LR opens a verification page that confirms the LR is genuine.

### 3. Trip progress
Open the trip: *Loading started → Dispatch* (enter starting km) *→ In transit → Delivered* (receiver) *→ POD collected
→ Close trip* (closing km, fuel left, waiting hours, detention days). Add expenses at any time (*+ Expense*: diesel,
toll, parking, RTO, loading, bata, food…, paid by driver cash / company cash / bank / fuel card / FASTag / vendor
credit). Each expense is posted to accounts automatically. The trip shows revenue, expenses, profit and km/L.

### 4. Billing
* **Invoices → + New invoice / note**: choose the document (tax invoice, bill of supply, proforma, debit note,
  credit note, advance receipt), customer and basis:
  *LR-wise / Consolidated* (tick unbilled LRs), *Trip-wise*, *Monthly contract* (period; extra trips beyond the
  included number are charged automatically), *Warehouse* (storage & handling computed from stock), *Manual lines*.
* GST is applied from the customer/contract treatment; reverse-charge invoices show the tax payable by the recipient.
* Open an invoice for **PDF**, **WhatsApp**, **Email**, **E-invoice JSON** / **Record IRN from portal**, **Cancel**
  (reason; a reversal is posted; LRs return to unbilled).
* **Receipts**: customer, amount, TDS deducted, bank/cash, cheque/UTR – allocated to oldest bills or to bills you pick.

### 5. Driver advances & settlement
**Fleet → Driver advances & settlement**: give advances (*Advances* tab). *Settlement* tab shows, per driver, trips
not yet settled with bata, food, trip and km allowances, expenses the driver paid, advances and fines → net payable.
*Post settlement* (optionally pay now).

### 6. Diesel, maintenance, tolls
* **Diesel & fuel → + Diesel entry** (non-trip fills) – trip fills are entered in the trip. *Mileage* tab: km/L per
  fill, abnormal fills flagged.
* **Maintenance → + Job card** (vehicle goes off-road) → *Complete* with parts, labour, GST, bill → posted to accounts
  or as a vendor bill. *Due* tab lists services due by km/date (set up in *Schedules*).
* **Tyres**: fit / remove / rotate / retread / scrap with odometer → km run and cost per km.
* **Tolls & FASTag**: upload the FASTag statement, then *Book to trip* for matched debits.

### 7. Godown
**Warehouse → + Inward / outward**: type (inward, outward, transfer, damage, shortage, adjustment, count), godown,
customer, vehicle, items with batch and packages. Scan barcodes / QR labels with a scanner or the phone camera.
Outward more than available stock is refused. *Labels* prints QR labels for items/batches.

### 8. Purchase
**Purchase**: purchase orders → *Receive* (GRN) → vendor bill (GST input, RCM, TDS) → *Pay vendor*.

### 9. Accounts
**Vouchers** (journal, payment, receipt, contra – debit must equal credit), **Ledgers** (balances, click for the
ledger statement with PDF/Excel), **Bank reconciliation** (import statement, match entries), **Tally export / import**.

### 10. HR
**Employees**, **Attendance** (pick employees or drivers and the date), **Payroll** (*Compute* → check → *Post to
accounts* → payslips).

### 11. Compliance & documents
**Compliance**: overdue / due-soon filings. Open one → status, **ARN / acknowledgement** from the government portal
and upload the acknowledgement → *Acknowledged*. **Documents**: upload RC, insurance, permits, licences, agreements
with expiry dates (alerts), new versions, download.

### 12. Reports
**Reports**: choose a report, set dates/filters, *Run*, and export **Excel / PDF / CSV**.

## Customer portal (customers)
Sign in → *Shipments* (status, vehicle, expected/actual delivery, LR and POD download), *Book vehicle*, *Invoices*
(PDF), *Payments*, *Statement* (PDF/Excel), *Complaints*.

## Driver app (drivers, on the phone)
Sign in → tap a trip → *Loading done*, *Start trip* (odometer), *Delivered* (receiver), *Upload POD* (camera),
*Expense*, *Diesel*, *Receipt photo*, *Incident* (breakdown/accident/fine). Tick *Share my location during trips*
only if you agree; location is sent only while a trip is active and can be switched off at any time.
