"""Bootstrap reference data and (optionally) clearly-marked DEMO data.

    python -m app.seed                 # roles, chart of accounts, GST treatments, compliance rules, templates, admin user
    python -m app.seed --demo          # + DEMO masters & transactions (use only on a training database)

Nothing here invents real business identifiers: company GSTIN/PAN/bank details are left blank for the
administrator to enter in Settings → Company. Demo records are prefixed "DEMO" and use the non-existent
state code 00 in vehicle numbers so they can never be mistaken for real vehicles.
"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core.numbering import DEFAULT_PREFIXES, financial_year
from .core.permissions import DEFAULT_ROLES
from .core.security import hash_password
from .db import SessionLocal
from .models import (
    ComplianceRule, Department, GstTreatment, LeaveType, NotificationTemplate, NumberSeries, Role, StatutoryRegister, User,
)
from .services import accounting as acc
from .services import notify
from .services import settings as app_settings

VERIFY = "Default configuration – confirm applicability, rate and notification with your GST practitioner before use."

GST_TREATMENTS = [
    ("GTA_RCM_5", "GTA – Reverse charge @5% (tax paid by recipient)", "GTA", "996791", 5, "RCM", False,
     "GST on this supply is payable by the recipient under reverse charge.", "Notification 13/2017-CT(Rate) as amended – GTA services to specified recipients (factory, registered person, body corporate, partnership firm, etc.) where GTA has not opted for forward charge."),
    ("GTA_FCM_5", "GTA – Forward charge @5% (no ITC)", "GTA", "996791", 5, "FCM", False,
     "GTA has opted to pay GST under forward charge @5%; input tax credit not availed.", "Notification 11/2017-CT(Rate) Sl. 9 as amended; requires annual declaration (Annexure V) before the FY."),
    ("GTA_FCM_18", "GTA – Forward charge @18% (with ITC)", "GTA", "996791", 18, "FCM", True,
     "GTA has opted to pay GST under forward charge with input tax credit.", "Verify the current rate for GTA forward charge with ITC (the earlier 12% option was revised under the 2025 rate rationalisation)."),
    ("GTA_EXEMPT", "GTA – Exempt supply", "GTA", "996791", 0, "EXEMPT", False,
     "Exempt supply of goods transport service.", "Notification 12/2017-CT(Rate) – e.g. agricultural produce, freight ≤ ₹1,500 per consignment / ≤ ₹750 for a single consignee, services to unregistered persons not covered by RCM. Confirm eligibility per transaction."),
    ("VEH_HIRE_GTA", "Vehicle hire to a GTA – Exempt", "Vehicle Hire (with operator)", "996601", 0, "EXEMPT", False,
     "Renting of goods carriage to a GTA – exempt.", "Notification 12/2017-CT(Rate) as amended."),
    ("VEH_HIRE_18", "Vehicle hire with operator (non-GTA) – Forward charge @18%", "Vehicle Hire (with operator)", "996601", 18, "FCM", True,
     "", "Verify the applicable rate for renting of goods carriage with operator to non-GTA customers."),
    ("WAREHOUSE_18", "Warehousing / storage @18%", "Warehousing", "996729", 18, "FCM", True, "", "Storage and warehousing services (other than agricultural produce)."),
    ("HANDLING_18", "Cargo handling @18%", "Handling", "996719", 18, "FCM", True, "", "Cargo handling services."),
]

COMPLIANCE_RULES = [
    ("GSTR1", "GSTR-1 (outward supplies)", "GST", "Monthly", 11, 1, True, "GST portal", "Monthly filers. QRMP taxpayers file quarterly by the 13th – change frequency if under QRMP."),
    ("GSTR3B", "GSTR-3B (summary return & tax payment)", "GST", "Monthly", 20, 1, True, "GST portal", "QRMP due dates are 22nd/24th by state – adjust if applicable."),
    ("GSTR9", "GSTR-9 annual return", "GST", "Annual", 31, 9, True, "GST portal", "Optional/exempt below the notified turnover – confirm each year."),
    ("GSTR9C", "GSTR-9C reconciliation statement", "GST", "Annual", 31, 9, False, "GST portal", "Applicable only above the notified turnover threshold."),
    ("GTA_ANNEX_V", "GTA forward-charge option (Annexure V)", "GST", "Annual", 31, 0, False, "GST portal", "Enable if you opt for forward charge; due before the start of the FY (15 March)."),
    ("TDS_PAY", "TDS / TCS payment (Challan 281)", "TDS", "Monthly", 7, 1, True, "Income-tax portal", "March deductions are due on 30 April."),
    ("TDS_24Q", "TDS return – salaries (24Q)", "TDS", "Quarterly", 31, 1, True, "TRACES / Income-tax portal", "Q4 return is due on 31 May."),
    ("TDS_26Q", "TDS return – non-salary (26Q)", "TDS", "Quarterly", 31, 1, True, "TRACES / Income-tax portal", "Q4 return is due on 31 May."),
    ("ADV_TAX", "Advance tax instalment", "Income Tax", "Quarterly", 15, 0, True, "Income-tax portal", "15 Jun / 15 Sep / 15 Dec / 15 Mar."),
    ("TAX_AUDIT", "Tax audit report (Form 3CD)", "Income Tax", "Annual", 30, 6, True, "Income-tax portal", "If accounts are liable to tax audit."),
    ("ITR", "Income-tax return", "Income Tax", "Annual", 31, 7, True, "Income-tax portal", "31 October for audit cases; 31 July otherwise – adjust."),
    ("EPF_ECR", "EPF ECR & payment", "EPF", "Monthly", 15, 1, True, "EPFO unified portal", "Applicable once 20 or more employees are employed."),
    ("ESI", "ESI contribution", "ESI", "Monthly", 15, 1, True, "ESIC portal", "Applicable once 10 or more employees are employed."),
    ("PT_TN", "Professional tax (Tamil Nadu local body)", "Professional Tax", "Half-Yearly", 30, 0, True, "Local body (Corporation / Municipality)", "Confirm the due date and slabs with your local body."),
    ("TN_LWF", "Tamil Nadu Labour Welfare Fund", "Labour", "Annual", 31, 10, False, "TN Labour Welfare Board", "Annual contribution – verify applicability."),
    ("MV_TAX", "Motor vehicle tax (quarterly, if applicable)", "Transport", "Quarterly", 30, 1, False, "Parivahan / RTO", "Vehicle-wise road tax validity is tracked on each vehicle."),
]

REGISTERS = [
    ("Register of Wages", "Code on Wages / Payment of Wages Act"), ("Register of Attendance (Muster Roll)", "Labour laws"),
    ("Register of Accidents", "Motor Transport Workers Act / ESI"), ("Register of Fines & Deductions", "Payment of Wages Act"),
    ("Register of Advances", "Payment of Wages Act"), ("Vehicle Log Book", "Motor Vehicles Act / internal control"),
]


def bootstrap(db: Session, admin_password: str | None = None) -> str | None:
    """Idempotent. Returns the generated admin password if a new admin user was created."""
    acc.ensure_chart(db)
    roles = {r.name: r for r in db.execute(select(Role)).scalars()}
    for name, (desc, perms) in DEFAULT_ROLES.items():
        if name not in roles:
            r = Role(name=name, description=desc, permissions=perms, is_system=True)
            db.add(r)
            roles[name] = r
    db.flush()
    app_settings.company(db)
    have = {t.code for t in db.execute(select(GstTreatment)).scalars()}
    for code, name, stype, sac, rate, mech, itc, note, basis in GST_TREATMENTS:
        if code not in have:
            db.add(GstTreatment(code=code, name=name, service_type=stype, sac=sac, gst_rate=rate, charge_mechanism=mech, itc_eligible=itc, invoice_note=note, legal_basis=f"{basis} {VERIFY}", verified=False))
    have = {r.code for r in db.execute(select(ComplianceRule)).scalars()}
    for code, name, cat, freq, day, off, appl, auth, note in COMPLIANCE_RULES:
        if code not in have:
            db.add(ComplianceRule(code=code, name=name, category=cat, frequency=freq, due_day=day, due_month_offset=off, applicable=appl, authority=auth, description=note, verify_note="Default due date – verify against the latest government notification and extensions."))
    have = {(t.event, t.channel) for t in db.execute(select(NotificationTemplate)).scalars()}
    for event, channel, subject, body, rcpt in notify.DEFAULT_TEMPLATES:
        if (event, channel) not in have:
            db.add(NotificationTemplate(event=event, channel=channel, subject=subject, body=body, recipients=rcpt, is_active=True))
    fy = financial_year(date.today())
    have = {(s.doc_type, s.fy) for s in db.execute(select(NumberSeries)).scalars()}
    for doc, prefix in DEFAULT_PREFIXES.items():
        if (doc, fy) not in have:
            db.add(NumberSeries(doc_type=doc, fy=fy, branch_code="", prefix=prefix, next_no=1, padding=5, pattern="{prefix}{fy}/{no}"))
    if not db.execute(select(LeaveType)).first():
        for n, d, paid in (("Casual Leave", 12, True), ("Sick Leave", 12, True), ("Earned Leave", 15, True), ("Loss of Pay", 0, False)):
            db.add(LeaveType(name=n, days_per_year=d, paid=paid))
    if not db.execute(select(Department)).first():
        for n in ("Administration", "Operations", "Accounts", "Fleet & Workshop", "Warehouse", "HR"):
            db.add(Department(name=n))
    have = {r.name for r in db.execute(select(StatutoryRegister)).scalars()}
    for n, act in REGISTERS:
        if n not in have:
            db.add(StatutoryRegister(name=n, act=act, columns=["Particulars", "Amount", "Remarks"]))
    db.flush()
    generated = None
    if not db.execute(select(User)).first():
        pw = admin_password or os.environ.get("INITIAL_ADMIN_PASSWORD")
        if not pw:
            pw = generated = "Svsl@" + secrets.token_urlsafe(9)
        db.add(User(username="admin", full_name="System Administrator", password_hash=hash_password(pw), role_id=roles["Super Admin"].id, must_change_password=True))
    from .services.people import generate_compliance

    generate_compliance(db, fy)
    db.flush()
    return generated


def demo(db: Session) -> None:
    """DEMO data for training. Never load into the production database."""
    from .models import Branch, Customer, Driver, Employee, FuelStation, RateContract, Route, Vehicle, Vendor, Warehouse
    from .services.operations import create_lr, create_trip
    from .core.deps import CurrentUser

    if db.execute(select(Customer).where(Customer.code == "DEMO-C1")).first():
        return
    sys_user = CurrentUser(id=1, username="admin", full_name="Admin", role="Super Admin", permissions=["*"])
    db.add(Branch(code="DEMO-HO", name="DEMO Head Office (Coimbatore)", kind="Head Office", city="Coimbatore", state="Tamil Nadu", state_code="33"))
    db.add(Warehouse(code="DEMO-WH1", name="DEMO Godown 1"))
    custs = [
        Customer(code="DEMO-C1", name="DEMO Auto Components Customer", category="Auto Components", billing_city="Coimbatore", billing_state="Tamil Nadu", billing_state_code="33", credit_limit=500000, credit_days=30, gst_registration="Unregistered", remarks="DEMO DATA"),
        Customer(code="DEMO-C2", name="DEMO Automobile OEM Customer", category="Automobile OEM", billing_city="Bengaluru", billing_state="Karnataka", billing_state_code="29", credit_limit=1500000, credit_days=45, gst_registration="Unregistered", remarks="DEMO DATA"),
        Customer(code="DEMO-C3", name="DEMO Industrial Monthly Contract Customer", category="Industrial", billing_city="Coimbatore", billing_state="Tamil Nadu", billing_state_code="33", credit_limit=800000, credit_days=30, gst_registration="Unregistered", remarks="DEMO DATA"),
    ]
    for c in custs:
        db.add(c)
    db.flush()
    for c in custs:
        c.ledger_id = acc.party_ledger(db, "customer", c.id, c.name)
    vtypes = ["Trailer (40 ft)", "Closed Body Truck", "Open Body Truck", "Container (32 ft)", "Multi-Axle Truck", "LCV / Tempo"]
    vehicles = []
    for i in range(1, 25):
        v = Vehicle(registration_no=f"TN00DM{i:04d}", vehicle_type=vtypes[i % len(vtypes)], make="DEMO", model="DEMO", ownership="Owned", gvw_kg=25000, tare_kg=9000, payload_kg=16000, expected_kmpl=4.0, current_odometer=100000 + i * 1000,
                    insurance_expiry=date.today() + timedelta(days=10 + i * 12), fc_expiry=date.today() + timedelta(days=60 + i * 9), puc_expiry=date.today() + timedelta(days=20 + i * 5), status="Available", remarks="DEMO VEHICLE – replace with your real fleet")
        db.add(v)
        vehicles.append(v)
    drivers = []
    for i in range(1, 9):
        d = Driver(code=f"DEMO-D{i}", name=f"DEMO Driver {i}", mobile=f"90000000{i:02d}", licence_no=f"DEMO-DL-{i:04d}", licence_class="HGMV", licence_expiry=date.today() + timedelta(days=20 + i * 40), monthly_salary=18000, daily_bata=400, food_allowance_per_day=150, trip_allowance=200, employment_status="Active", status="Available", remarks="DEMO DATA")
        db.add(d)
        drivers.append(d)
    db.add(Employee(code="DEMO-E1", name="DEMO Office Staff", joining_date=date.today() - timedelta(days=400), basic=15000, hra=5000, other_allowances=2000, pf_applicable=True, esi_applicable=False))
    vend = Vendor(code="DEMO-V1", name="DEMO Fuel Station Vendor", category="Diesel / Fuel", state_code="33", credit_days=15)
    db.add(vend)
    db.flush()
    db.add(FuelStation(name="DEMO Fuel Station", company="Other", vendor_id=vend.id, credit_account=True))
    r1 = Route(code="DEMO-CBE-MAA", origin="Coimbatore", destination="Chennai", distance_km=505, est_hours=11, est_toll=2800, origin_state_code="33", destination_state_code="33")
    r2 = Route(code="DEMO-CBE-BLR", origin="Coimbatore", destination="Bengaluru", distance_km=365, est_hours=8, est_toll=1600, origin_state_code="33", destination_state_code="29")
    db.add_all([r1, r2])
    db.flush()
    rc_t = acc.sys_ledger(db, "CASH")  # ensure chart
    gta = db.execute(select(GstTreatment).where(GstTreatment.code == "GTA_RCM_5")).scalar_one()
    db.add(RateContract(contract_no="DEMO-RC1", version=1, name="DEMO Coimbatore → Chennai per trip", customer_id=custs[0].id, route_id=r1.id, basis="per_trip", rate=12000, loading_charge=500, unloading_charge=500, gst_treatment_id=gta.id, effective_from=date.today() - timedelta(days=200), status="Active"))
    db.add(RateContract(contract_no="DEMO-RC2", version=1, name="DEMO Components per number", customer_id=custs[1].id, basis="per_piece", rate=45, min_freight=15000, gst_treatment_id=gta.id, effective_from=date.today() - timedelta(days=200), status="Active"))
    db.add(RateContract(contract_no="DEMO-RC3", version=1, name="DEMO Monthly dedicated vehicle", customer_id=custs[2].id, basis="monthly_fixed", rate=165000, monthly_trips_included=26, extra_trip_rate=6000, gst_treatment_id=gta.id, effective_from=date.today() - timedelta(days=200), status="Active"))
    db.flush()
    t = create_trip(db, sys_user, {"trip_date": date.today(), "customer_id": custs[0].id, "route_id": r1.id, "vehicle_id": vehicles[0].id, "driver_id": drivers[0].id, "remarks": "DEMO trip"})
    create_lr(db, sys_user, {"customer_id": custs[0].id, "trip_id": t.id, "route_id": r1.id, "consignor_name": "DEMO Consignor", "consignee_name": "DEMO Consignee", "from_place": "Coimbatore", "to_place": "Chennai",
                             "goods_value": 40000, "items": [{"description": "DEMO auto components", "packages": 40, "quantity": 400, "weight_kg": 6000, "hsn": "8708"}]})
    db.flush()


def main() -> None:
    db = SessionLocal()
    try:
        pw = bootstrap(db)
        if "--demo" in sys.argv:
            demo(db)
        db.commit()
        if pw:
            print("\n  Initial administrator created.\n  Username: admin\n  Password:", pw, "\n  You must change it at first sign-in.\n")
        print("Bootstrap complete." + (" DEMO data loaded." if "--demo" in sys.argv else ""))
    finally:
        db.close()


if __name__ == "__main__":
    main()
