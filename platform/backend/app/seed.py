"""Initial master data and roles.

    python -m app.seed                 # roles, chart, integrations, reference masters, the 3 own vehicles, admin user
    python -m app.seed --demo          # + clearly-labelled SYNTHETIC demo customers/drivers/owner/vendor for training

Idempotent: safe to run more than once. The owner password is taken from GRL_ADMIN_PASSWORD or generated and printed once.
"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crud import normalize_name
from app.core.db import SessionLocal, utcnow
from app.core.rbac import DEFAULT_ROLES, EXTERNAL_ROLES
from app.core.security import hash_password
from app.integrations.adapters import REGISTRY
from app.modules.finance.posting import seed_chart
from app.modules.fleet.models import ComplianceItem, Driver, Vehicle
from app.modules.masters.models import (
    ChargeType, CompanyBankAccount, Contact, Customer, Facility, GoodsCategory, Location, ReasonCode, RouteDistance, Vendor,
    VehicleOwner, VehicleType,
)
from app.modules.people.models import ChecklistTemplate, Sop
from app.modules.platform.models import IntegrationProvider, Role, User

LOCATIONS = [  # city, district, state, code, lat, lng, verified service location
    ("Coimbatore", "Coimbatore", "Tamil Nadu", "33", 11.0168, 76.9558, True),
    ("Tiruppur", "Tiruppur", "Tamil Nadu", "33", 11.1085, 77.3411, True),
    ("Erode", "Erode", "Tamil Nadu", "33", 11.3410, 77.7172, True),
    ("Salem", "Salem", "Tamil Nadu", "33", 11.6643, 78.1460, True),
    ("Chennai", "Chennai", "Tamil Nadu", "33", 13.0827, 80.2707, True),
    ("Madurai", "Madurai", "Tamil Nadu", "33", 9.9252, 78.1198, True),
    ("Tiruchirappalli", "Tiruchirappalli", "Tamil Nadu", "33", 10.7905, 78.7047, True),
    ("Pollachi", "Coimbatore", "Tamil Nadu", "33", 10.6573, 77.0107, True),
    ("Bengaluru", "Bengaluru Urban", "Karnataka", "29", 12.9716, 77.5946, False),
    ("Kochi", "Ernakulam", "Kerala", "32", 9.9312, 76.2673, False),
    ("Hyderabad", "Hyderabad", "Telangana", "36", 17.3850, 78.4867, False),
]
LANES = [("Coimbatore", "Chennai", 505, 1100), ("Coimbatore", "Tiruppur", 52, 120), ("Coimbatore", "Erode", 100, 200),
         ("Coimbatore", "Salem", 165, 350), ("Coimbatore", "Madurai", 215, 450), ("Coimbatore", "Bengaluru", 365, 900),
         ("Coimbatore", "Kochi", 190, 400), ("Tiruppur", "Chennai", 460, 1000), ("Erode", "Chennai", 400, 850),
         ("Salem", "Chennai", 340, 750), ("Coimbatore", "Tiruchirappalli", 215, 420), ("Coimbatore", "Pollachi", 42, 0)]

GOODS = [("GEN", "General goods (packed)", None, ["general"], [], True, False),
         ("TEX", "Textiles / garments", None, ["textile"], ["odorous", "liquid", "chemical"], True, False),
         ("MACH", "Machinery / spares", None, ["machinery", "heavy"], ["fragile"], True, False),
         ("FMCG", "FMCG / food (packed, ambient)", None, ["food"], ["chemical", "odorous"], True, False),
         ("FRAG", "Fragile (glass, electronics)", None, ["fragile"], ["heavy"], True, False),
         ("CHEM", "Non-hazardous chemicals (sealed)", None, ["chemical"], ["food", "textile"], False, True),
         ("HAZ", "Hazardous goods (any class)", "UN-various", ["hazardous"], ["food", "textile", "general"], False, True),
         ("TEMP", "Temperature-sensitive", None, ["temperature"], [], False, True),
         ("ODR", "Odorous goods (fish, hides)", None, ["odorous"], ["food", "textile"], False, True)]

CHARGES = [("freight", "Freight", "freight", True), ("loading", "Loading charges", "accessorial", True),
           ("unloading", "Unloading charges", "accessorial", True), ("hamali", "Hamali", "accessorial", True),
           ("detention", "Detention / waiting", "accessorial", True), ("crane", "Crane / Hydra", "accessorial", True),
           ("toll_reimb", "Toll (reimbursement)", "pass_through", False), ("cancellation", "Cancellation charge", "accessorial", True)]

REASONS = [("cancellation", "CUSTOMER", "Customer cancelled", "வாடிக்கையாளர் ரத்து"), ("cancellation", "NO_VEHICLE", "No suitable vehicle", None),
           ("cancellation", "CONVERT_PTL", "Converted to PTL", None), ("delay", "TRAFFIC", "Traffic / road block", "போக்குவரத்து நெரிசல்"),
           ("delay", "BREAKDOWN", "Vehicle breakdown", "வாகன பழுது"), ("delay", "LOADING", "Loading delay at customer", None),
           ("delay", "WEATHER", "Weather", "வானிலை"), ("claim", "DAMAGE", "Cargo damage", None), ("claim", "SHORTAGE", "Shortage", None),
           ("exception", "COUNT", "Package count mismatch", None), ("exception", "SEAL", "Seal broken/mismatch", None),
           ("override", "CUSTOMER_PRIORITY", "Customer priority (commercial)", None)]

CHECKLISTS = [
    ("OPS-DAILY", "Operations daily close", "daily", "operations", "operations_manager", "dispatcher",
     ["All active trips have fresh tracking or a call log", "All deliveries have POD submitted", "Exceptions assigned", "Next-day plan prepared"]),
    ("ACC-DAILY", "Accounts daily close", "daily", "accounts", "accounts", "owner_director",
     ["Bank statement imported", "Unmatched items reviewed", "Expenses reviewed", "Collections calls logged"]),
    ("FLEET-WEEKLY", "Fleet weekly check", "weekly", "fleet", "fleet_maintenance", "operations_manager",
     ["Compliance expiries reviewed", "Fuel anomalies reviewed", "Maintenance due scheduled", "Tyre inspection"]),
    ("MGMT-MONTHLY", "Management monthly review", "monthly", "management", "owner_director", None,
     ["P&L reviewed", "Budget vs actual reviewed", "Receivables >60 days reviewed", "Backup restore drill evidence checked", "Access review (users/roles)"]),
    ("SEC-WEEKLY", "Security weekly review", "weekly", "security", "system_admin", "owner_director",
     ["Audit chain verified", "Failed logins reviewed", "Inactive users disabled", "Backups succeeded"]),
]

SOPS = [("SOP-DISPATCH", "Dispatch authorisation", "operations",
         ["Confirm booking and credit status", "Run allocation checks", "Pre-trip inspection by driver", "Load and scan every package",
          "Generate/verify LR and e-way bill", "Driver acknowledgement and GPS notice", "Authorise dispatch in ERP"]),
        ("SOP-POD", "Delivery and POD", "operations",
         ["Arrive and record event", "Count packages with receiver", "Record exceptions with photos", "Capture OTP/signature/photo",
          "Office verifies POD within 24 hours"]),
        ("SOP-INCIDENT", "Accident / emergency", "operations",
         ["Ensure human safety first - call 108/112", "Inform Operations Manager immediately (SOS in app)", "Protect cargo if safe",
          "Record photos, location, witnesses", "Police reference where required", "Notify insurer within policy deadline",
          "Inform customer with verified facts only (approved message)"]),
        ("SOP-BANK", "Daily bank reconciliation", "accounts",
         ["Import statement", "Review auto-matches", "Resolve suggested matches", "Never treat unmatched credit as customer payment",
          "Escalate items older than 3 days"])]


def seed_roles(db: Session):
    for code, (name, perms) in DEFAULT_ROLES.items():
        r = db.execute(select(Role).where(Role.code == code)).scalar_one_or_none()
        if not r:
            db.add(Role(code=code, name=name, permissions=sorted(set(perms)), is_external=code in EXTERNAL_ROLES))
        else:
            # Add newly introduced default permissions; never remove customisations
            r.permissions = sorted(set(r.permissions) | set(perms)) if not r.is_external else sorted(set(perms))
    db.flush()


def seed_reference(db: Session):
    loc = {}
    for city, dist, state, sc, lat, lng, ver in LOCATIONS:
        l = db.execute(select(Location).where(Location.city == city, Location.state == state)).scalar_one_or_none()
        if not l:
            l = Location(city=city, district=dist, state=state, state_code=sc, lat=lat, lng=lng, service_verified=ver,
                         service_notes=None if ver else "Not verified - do not advertise until route/partner/capacity verified")
            db.add(l)
            db.flush()
        loc[city] = l
    for a, b, km, toll in LANES:
        if not db.execute(select(RouteDistance).where(RouteDistance.origin_id == loc[a].id, RouteDistance.destination_id == loc[b].id)).first():
            db.add(RouteDistance(origin_id=loc[a].id, destination_id=loc[b].id, km=Decimal(km), toll_estimate=Decimal(toll), source="manual_estimate"))
    for code, name, hz, tags, inc, ptl, special in GOODS:
        if not db.execute(select(GoodsCategory).where(GoodsCategory.code == code)).first():
            db.add(GoodsCategory(code=code, name=name, hazard_class=hz, tags=tags, incompatible_tags=inc, ptl_allowed=ptl, requires_special_approval=special))
    for code, name, kind, gst in CHARGES:
        if not db.execute(select(ChargeType).where(ChargeType.code == code)).first():
            db.add(ChargeType(code=code, name=name, kind=kind, gst_applicable=gst))
    for cat, code, label, ta in REASONS:
        if not db.execute(select(ReasonCode).where(ReasonCode.category == cat, ReasonCode.code == code)).first():
            db.add(ReasonCode(category=cat, code=code, label=label, label_ta=ta))
    vt = {}
    for code, name, body, tons, length in (("7T-22FT", "7 ton 22 ft", "open", 7, 22), ("12T-20FT", "12 ton 20 ft", "open", 12, 20)):
        v = db.execute(select(VehicleType).where(VehicleType.code == code)).scalar_one_or_none()
        if not v:
            v = VehicleType(code=code, name=name, body_type=body, nominal_tons=Decimal(tons), length_ft=Decimal(length))
            db.add(v)
            db.flush()
        vt[code] = v
    if not db.execute(select(Facility).where(Facility.code == "OFFICE")).first():
        db.add(Facility(code="OFFICE", name="G ROAD LINES Office", kind="office", verified=True, verification_notes="Office (not a warehouse)"))
    if not db.execute(select(Facility).where(Facility.code == "BASEMENT")).first():
        db.add(Facility(code="BASEMENT", name="Basement godown (concept)", kind="godown", area_sqft=Decimal("1000"), length_ft=Decimal("40"),
                        width_ft=Decimal("25"), ceiling_ft=Decimal("8"), max_vehicle_type="Small vehicles only - large lorries NOT assumed to access",
                        verified=False, verification_notes=("NOT VERIFIED. Requires confirmation of approved building use, fire safety, "
                                                            "ventilation, drainage, structural/floor loads, exits, access and local authority "
                                                            "requirements by qualified professionals before any commercial use."),
                        safety_checklist={k: None for k in ("approved_use", "fire_noc", "extinguishers", "ventilation", "drainage",
                                                             "floor_load", "exits", "ramp_access", "lighting", "cctv", "insurance")}))
    if not db.execute(select(CompanyBankAccount)).first():
        db.add(CompanyBankAccount(name="Primary current account", bank_name="(configure)", account_number_masked="XXXX0000", ledger_code="1010"))
        db.add(CompanyBankAccount(name="Cash", bank_name="Cash", account_number_masked="-", ledger_code="1000", is_cash=True))
    db.flush()
    # Initial own fleet - editable records, NOT permanent limits
    fleet = [("TN00GR0001", vt["7T-22FT"], 7000, "22", "MGV"), ("TN00GR0002", vt["7T-22FT"], 7000, "22", "MGV"),
             ("TN00GR0003", vt["12T-20FT"], 12000, "20", "HGV")]
    for reg, t, payload, length, cls in fleet:
        if not db.execute(select(Vehicle).where(Vehicle.registration == reg)).first():
            db.add(Vehicle(registration=reg, ownership="own", vehicle_type_id=t.id, body_type="open", vehicle_class=cls, payload_kg=payload,
                           length_ft=Decimal(length), width_ft=Decimal("7.5"), height_ft=None, tank_litres=Decimal("160" if payload == 7000 else "220"),
                           baseline_kmpl=Decimal("6.0" if payload == 7000 else "4.5"), home_location_id=loc["Coimbatore"].id,
                           gps_device_id=f"TRK-{reg[-4:]}", dvr_device_id=f"DVR-{reg[-4:]}", status="unavailable"))
    for code, title, freq, dept, owner, backup, items in CHECKLISTS:
        if not db.execute(select(ChecklistTemplate).where(ChecklistTemplate.code == code)).first():
            db.add(ChecklistTemplate(code=code, title=title, frequency=freq, department=dept, owner_role=owner, backup_role=backup, items=items))
    for code, title, dept, steps in SOPS:
        if not db.execute(select(Sop).where(Sop.code == code)).first():
            db.add(Sop(code=code, title=title, department=dept, steps=steps, status="draft", version=1, purpose=title,
                       change_note="Initial draft - requires Owner/Director approval"))
    for kind, a in REGISTRY.items():
        if not db.execute(select(IntegrationProvider).where(IntegrationProvider.kind == kind)).first():
            db.add(IntegrationProvider(kind=kind, adapter=a.name, mode=a.mode, notes="Mock adapter. Live use needs credentials/authorisation."))
    db.flush()
    return loc


def seed_admin(db: Session) -> str | None:
    if db.execute(select(User).where(User.email == "owner@groadlines.local")).first():
        return None
    pw = os.environ.get("GRL_ADMIN_PASSWORD") or ("Grl" + secrets.token_urlsafe(9) + "1")
    u = User(name="Owner / Director", email="owner@groadlines.local", password_hash=hash_password(pw))
    u.roles = [db.execute(select(Role).where(Role.code == "owner_director")).scalar_one()]
    db.add(u)
    db.flush()
    return pw


def seed_demo(db: Session, loc: dict) -> dict:
    """SYNTHETIC data for training/testing only - names start with 'DEMO'."""
    pwd = os.environ.get("GRL_DEMO_PASSWORD", "Demo@12345")
    roles = {r.code: r for r in db.execute(select(Role)).scalars()}
    out = {}

    def user(email, name, role_codes, **scope):
        u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not u:
            u = User(name=name, email=email, password_hash=hash_password(pwd), **scope)
            u.roles = [roles[c] for c in role_codes]
            db.add(u)
            db.flush()
        return u
    for c in ("operations_manager", "dispatcher", "accounts", "hr", "customer_support", "fleet_maintenance", "compliance_coordinator",
              "store_custodian", "sales_marketing", "system_admin"):
        user(f"{c.replace('_', '.')}@demo.local", f"DEMO {c.replace('_', ' ').title()}", [c])
    customers = []
    for i, (name, gstin, st) in enumerate((("DEMO Kovai Textiles Pvt Ltd", "33AAACK1234A1Z5", "33"), ("DEMO Chennai Pumps Ltd", "33AAACC5678B1Z2", "33"))):
        c = db.execute(select(Customer).where(Customer.name == name)).scalar_one_or_none()
        if not c:
            c = Customer(code=f"CUS-D{i + 1:03d}", name=name, name_normalized=normalize_name(name), state_code=st, status="active",
                         billing_address="DEMO address", gst_mode="RCM")
            db.add(c)
            db.flush()
            db.add(Contact(customer_id=c.id, name=f"{name} contact", email=f"buyer{i + 1}@demo.local", phone=f"90000000{i + 1:02d}"))
        customers.append(c)
        user(f"customer{i + 1}@demo.local", f"DEMO Customer {i + 1} Admin", ["customer_admin"], customer_id=c.id)
    out["customers"] = [str(c.id) for c in customers]
    o = db.execute(select(VehicleOwner).where(VehicleOwner.code == "OWN-D001")).scalar_one_or_none()
    if not o:
        o = VehicleOwner(code="OWN-D001", name="DEMO Murugan Transports", phone="9000000101", kyc_status="verified")
        db.add(o)
        db.flush()
    user("owner1@demo.local", "DEMO Owner", ["vehicle_owner"], owner_id=o.id)
    av = db.execute(select(Vehicle).where(Vehicle.registration == "TN99DM0009")).scalar_one_or_none()
    if not av:
        av = Vehicle(registration="TN99DM0009", ownership="attached", owner_id=o.id, body_type="open", vehicle_class="HGV", payload_kg=15000,
                     length_ft=Decimal("24"), width_ft=Decimal("7.5"), status="available")
        db.add(av)
        db.flush()
    v = db.execute(select(Vendor).where(Vendor.code == "VEN-D001")).scalar_one_or_none()
    if not v:
        v = Vendor(code="VEN-D001", name="DEMO Sri Hamali Services", categories=["hamali", "loading"], approval_status="approved", service_areas=["Coimbatore"])
        db.add(v)
        db.flush()
    user("vendor1@demo.local", "DEMO Vendor", ["vendor_user"], vendor_id=v.id)
    today = date.today()
    for i, (name, phone, cat, owner_id) in enumerate((("DEMO Driver Ravi", "9000000201", "company", None), ("DEMO Driver Kumar", "9000000202", "company", None),
                                                     ("DEMO Driver Selvam", "9000000203", "company", None), ("DEMO Attached Driver Arun", "9000000204", "attached", o.id))):
        d = db.execute(select(Driver).where(Driver.phone == phone)).scalar_one_or_none()
        if not d:
            d = Driver(code=f"DRV-D{i + 1:03d}", name=name, phone=phone, category=cat, owner_id=owner_id, licence_number=f"TN99 2020000{i}",
                       licence_classes=["MGV", "HGV", "TRANS"], licence_valid_to=today + timedelta(days=900))
            db.add(d)
            db.flush()
            db.add(ComplianceItem(subject_type="driver", subject_id=d.id, kind="licence", number=d.licence_number, valid_to=d.licence_valid_to))
        u = db.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
        if not u:
            u = User(name=name, phone=phone, driver_id=d.id)
            u.roles = [roles["attached_driver" if cat == "attached" else "driver"]]
            db.add(u)
    for vv in db.execute(select(Vehicle)).scalars():
        for kind, days in (("insurance", 300), ("road_tax", 200), ("fitness", 250), ("puc", 120), ("rc", 3000), ("national_permit", 365)):
            if not db.execute(select(ComplianceItem).where(ComplianceItem.subject_id == vv.id, ComplianceItem.kind == kind)).first():
                db.add(ComplianceItem(subject_type="vehicle", subject_id=vv.id, kind=kind, number=f"DEMO-{kind.upper()}", valid_from=today - timedelta(days=30),
                                      valid_to=today + timedelta(days=days), verification="verified", meta={"synthetic": True}))
        if vv.status == "unavailable":
            vv.status = "available"
    db.flush()
    return out


def run(demo: bool = False):
    db = SessionLocal()
    try:
        seed_roles(db)
        seed_chart(db)
        loc = seed_reference(db)
        pw = seed_admin(db)
        if demo:
            seed_demo(db, loc)
        db.commit()
        print("Seed complete.")
        if pw:
            print("\n  Owner login: owner@groadlines.local")
            print(f"  Password:    {pw}\n  (Change it after first sign-in. This is shown only once.)\n")
        if demo:
            print("Demo users (SYNTHETIC): e.g. operations.manager@demo.local, accounts@demo.local, customer1@demo.local, owner1@demo.local,"
                  " vendor1@demo.local - password from GRL_DEMO_PASSWORD (default Demo@12345). Drivers sign in by OTP: phones 9000000201-204.")
    finally:
        db.close()


if __name__ == "__main__":
    run(demo="--demo" in sys.argv)
