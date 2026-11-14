"""Master data endpoints: customers (with de-duplication), owners, vendors, locations, goods, charges, reasons,
vehicle types, facilities, company bank accounts, and maker-checker party bank accounts."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.crud import normalize_name, to_dict
from app.core.deps import Principal, get_db, require
from app.core.errors import AppError, Conflict
from app.core.resource import register_crud
from app.core.security import mask
from app.core.services import on_approval, request_approval
from app.integrations.adapters import get_adapter, gstin_checksum_ok
from app.modules.masters.models import (
    ChargeType, CompanyBankAccount, Contact, Customer, CustomerBranch, Facility, GoodsCategory, Location, PartyBankAccount,
    ReasonCode, RouteDistance, Vendor, VehicleOwner, VehicleType,
)

router = APIRouter(prefix="/api/v1/masters", tags=["masters"])


def _gstin_check(data: dict):
    g = data.get("gstin")
    if g:
        g = g.upper().strip()
        if not gstin_checksum_ok(g):
            raise AppError("invalid_gstin", f"GSTIN {g} fails format/check-digit validation")
        data["gstin"] = g


def _customer_before(db: Session, p, obj: Customer, data: dict, creating: bool):
    _gstin_check(data)
    if "name" in data:
        data["name_normalized"] = normalize_name(data["name"])
        dup = db.execute(select(Customer).where(
            or_(Customer.name_normalized == data["name_normalized"],
                (Customer.gstin == data["gstin"]) if data.get("gstin") else False),
            Customer.id != (obj.id if obj.id else uuid.uuid4()),
        )).scalars().first()
        if dup and not data.pop("confirm_not_duplicate", False):
            raise Conflict("possible_duplicate", f"Possible duplicate of customer {dup.code} - {dup.name}",
                           details={"existing_id": str(dup.id), "existing_code": dup.code})
        if data.get("gstin") and not data.get("state_code"):
            data["state_code"] = data["gstin"][:2]


register_crud(router, "customers", Customer, read_perm="masters.read", write_perm="masters.write", code_field="code",
              code_prefix="CUS", readonly_fields={"name_normalized"}, before_save=_customer_before,
              extra_fields={"confirm_not_duplicate": (bool, False)})
register_crud(router, "customer-branches", CustomerBranch, read_perm="masters.read", write_perm="masters.write")
register_crud(router, "contacts", Contact, read_perm="masters.read", write_perm="masters.write")
register_crud(router, "owners", VehicleOwner, read_perm="owner.read", write_perm="owner.write", code_field="code",
              code_prefix="OWN", before_save=lambda db, p, o, d, c: _gstin_check(d))
register_crud(router, "vendors", Vendor, read_perm="vendor.read", write_perm="vendor.write", code_field="code",
              code_prefix="VEN", before_save=lambda db, p, o, d, c: _gstin_check(d))
register_crud(router, "locations", Location, read_perm="masters.read", write_perm="masters.write", search_fields=("city", "district", "pincode"))
register_crud(router, "route-distances", RouteDistance, read_perm="masters.read", write_perm="masters.write", order_by="km")
register_crud(router, "goods-categories", GoodsCategory, read_perm="masters.read", write_perm="masters.write")
register_crud(router, "charge-types", ChargeType, read_perm="masters.read", write_perm="masters.write")
register_crud(router, "reason-codes", ReasonCode, read_perm="masters.read", write_perm="masters.write", search_fields=("label",))
register_crud(router, "vehicle-types", VehicleType, read_perm="masters.read", write_perm="masters.write")
register_crud(router, "facilities", Facility, read_perm="masters.read", write_perm="masters.write")
register_crud(router, "company-bank-accounts", CompanyBankAccount, read_perm="accounts.read", write_perm="accounts.approve")


# ----------------------------------------------------------------- bank details (maker-checker)
class BankIn(BaseModel):
    party_type: str = Field(pattern="^(owner|vendor|driver|employee|customer)$")
    party_id: uuid.UUID
    account_name: str = Field(min_length=2, max_length=160)
    account_number: str = Field(pattern=r"^\d{6,20}$")
    ifsc: str = Field(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    bank_name: str | None = None
    reason: str = Field(min_length=3)


def bank_out(b: PartyBankAccount, reveal: bool = False) -> dict:
    d = to_dict(b)
    if not reveal:
        d["account_number"] = mask(b.account_number)
    return d


@router.post("/bank-accounts")
def propose_bank(body: BankIn, p: Principal = Depends(require("masters.write")), db: Session = Depends(get_db)):
    """Bank account changes are a top fraud risk: a new account stays `pending` until a different user approves."""
    check = get_adapter("bank").verify_account(body.account_number, body.ifsc)
    b = PartyBankAccount(**body.model_dump(exclude={"reason"}), status="pending",
                         verified_method=f"ifsc_format_{check.mode}" if check.ok else None)
    db.add(b)
    db.flush()
    request_approval(db, p, kind="bank_account", entity="party_bank_account", entity_id=b.id,
                     title=f"New bank account for {body.party_type} {body.account_name} ({mask(body.account_number)})",
                     required_permission="masters.approve", reason=body.reason)
    write_audit(db, actor=p, action="bank_account.propose", entity="party_bank_account", entity_id=b.id,
                after={"party_type": b.party_type, "party_id": str(b.party_id), "account": mask(b.account_number), "ifsc": b.ifsc},
                reason=body.reason)
    return bank_out(b)


@on_approval("bank_account")
def _bank_approved(db: Session, actor, ar):
    b = db.get(PartyBankAccount, uuid.UUID(ar.entity_id))
    if ar.status == "approved":
        for old in db.execute(select(PartyBankAccount).where(
                PartyBankAccount.party_type == b.party_type, PartyBankAccount.party_id == b.party_id,
                PartyBankAccount.status == "active")).scalars():
            old.status = "superseded"
        b.status = "active"
    else:
        b.status = "rejected"


@router.get("/bank-accounts")
def list_bank(party_type: str, party_id: uuid.UUID, p: Principal = Depends(require("masters.read")),
              db: Session = Depends(get_db)):
    reveal = p.can("driver.view_sensitive") or p.can("payment.approve")
    rows = db.execute(select(PartyBankAccount).where(PartyBankAccount.party_type == party_type,
                                                     PartyBankAccount.party_id == party_id)
                      .order_by(PartyBankAccount.created_at.desc())).scalars()
    return [bank_out(b, reveal) for b in rows]


@router.get("/gstin/{gstin}/validate")
def validate_gstin(gstin: str, p: Principal = Depends(require("masters.read"))):
    return get_adapter("gst").validate_gstin(gstin.upper()).__dict__


@router.get("/lookup")
def lookup(p: Principal = Depends(require("masters.read")), db: Session = Depends(get_db)):
    """Compact lists for drop-downs."""
    return {
        "customers": [{"id": str(c.id), "label": f"{c.code} {c.name}"} for c in db.execute(select(Customer).where(Customer.status != "inactive").order_by(Customer.name)).scalars()],
        "locations": [{"id": str(l.id), "label": f"{l.city}, {l.state}", "verified": l.service_verified} for l in db.execute(select(Location).order_by(Location.city)).scalars()],
        "goods_categories": [{"id": str(g.id), "label": g.name, "ptl_allowed": g.ptl_allowed} for g in db.execute(select(GoodsCategory).order_by(GoodsCategory.name)).scalars()],
        "vehicle_types": [{"id": str(v.id), "label": v.name} for v in db.execute(select(VehicleType)).scalars()],
        "owners": [{"id": str(o.id), "label": f"{o.code} {o.name}"} for o in db.execute(select(VehicleOwner).order_by(VehicleOwner.name)).scalars()],
        "vendors": [{"id": str(v.id), "label": f"{v.code} {v.name}", "categories": v.categories, "approved": v.approval_status == "approved"} for v in db.execute(select(Vendor).order_by(Vendor.name)).scalars()],
        "facilities": [{"id": str(f.id), "label": f.name, "verified": f.verified} for f in db.execute(select(Facility)).scalars()],
        "reason_codes": [{"category": r.category, "code": r.code, "label": r.label} for r in db.execute(select(ReasonCode)).scalars()],
        "charge_types": [{"code": c.code, "label": c.name, "kind": c.kind} for c in db.execute(select(ChargeType)).scalars()],
    }
