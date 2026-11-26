"""Registration of master-data resources with their hooks."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..core.deps import AppError
from ..core.money import D
from ..core.numbering import next_number
from ..models import (
    AccountGroup, Role, Voucher,
    BankAccount, Booking, Branch, ComplianceRule, Consignment, Customer, Department, Driver, DriverAdvance, DriverIncident,
    DutyRoster, Employee, EwayBill, FuelCard, FuelEntry, FuelStation, GstTreatment, Invoice, Item, LeaveRequest, LeaveType,
    Ledger, MaintenanceSchedule, NotificationTemplate, NumberSeries, RateContract, Route, RouteToll, SalaryAdvance,
    StatutoryRegister, TollPlaza, Trip, Tyre, Vehicle, VehicleEvent, Vendor, Warehouse, WarehouseRateCard, Document,
)
from ..services import accounting as acc
from ..services import operations as ops
from .crud import Resource, register


def _customer_ledger(db, user, obj):
    obj.ledger_id = acc.party_ledger(db, "customer", obj.id, obj.name, obj.gstin)


def _customer_save(db, user, obj, data, is_new):
    if obj.gstin and not obj.billing_state_code:
        obj.billing_state_code = obj.gstin[:2]
    if obj.contract_start and obj.contract_end and obj.contract_end < obj.contract_start:
        raise AppError("Contract end date is before start date")
    if not is_new and obj.ledger_id:
        led = db.get(Ledger, obj.ledger_id)
        if led and led.name != obj.name and not db.execute(select(Ledger.id).where(Ledger.name == obj.name, Ledger.id != led.id)).first():
            led.name = obj.name
        if led:
            led.gstin = obj.gstin


def _vendor_ledger(db, user, obj):
    obj.ledger_id = acc.party_ledger(db, "vendor", obj.id, obj.name, obj.gstin)


def _vendor_save(db, user, obj, data, is_new):
    if obj.gstin and not obj.state_code:
        obj.state_code = obj.gstin[:2]


def _bank_ledger(db, user, obj):
    obj.ledger_id = acc.party_ledger(db, "bank", obj.id, f"{obj.bank_name} A/c {obj.account_no[-4:]}")


def _driver_save(db, user, obj, data, is_new):
    if obj.gps_consent and not obj.gps_consent_at:
        obj.gps_consent_at = datetime.now(timezone.utc)
    if not obj.gps_consent:
        obj.gps_consent_at = None


def _driver_ledger(db, user, obj):
    obj.ledger_id = acc.party_ledger(db, "driver", obj.id, obj.name)


def _vehicle_save(db, user, obj, data, is_new):
    if obj.tare_kg and obj.gvw_kg and not obj.payload_kg:
        obj.payload_kg = D(obj.gvw_kg) - D(obj.tare_kg)
    if obj.tare_kg and obj.gvw_kg and D(obj.tare_kg) > D(obj.gvw_kg):
        raise AppError("Tare weight cannot exceed GVW")


def _rate_save(db, user, obj, data, is_new):
    if is_new:
        obj.contract_no = next_number(db, "RATE_CONTRACT", obj.effective_from) if obj.effective_from else None
        obj.version = 1
        if obj.status == "Active" and not user.can("rates:approve"):
            obj.status = "Draft"
    if obj.effective_to and obj.effective_from and obj.effective_to < obj.effective_from:
        raise AppError("Effective-to date is before effective-from")
    if obj.basis in ("distance_slab", "weight_slab"):
        slabs = obj.slabs or []
        if not slabs:
            raise AppError("Slab pricing needs at least one slab")
        for s in slabs:
            if "rate" not in s or s.get("from") is None:
                raise AppError("Each slab needs 'from' and 'rate'")
    if obj.status == "Active" and not is_new and not user.can("rates:approve"):
        raise AppError("Only users with rate approval permission can activate contracts")


def _rate_lock(db, obj):
    used = db.execute(select(Consignment.id).where(Consignment.rate_contract_id == obj.id).limit(1)).first()
    if used:
        return "This contract version has been used in LRs. Use 'Revise' to create a new version with an effective date."
    if obj.status == "Superseded":
        return "Superseded versions are read-only"
    return None


def _booking_save(db, user, obj, data, is_new):
    if is_new:
        obj.booking_no = next_number(db, "BOOKING", obj.booking_date)


def _advance_after(db, user, obj):
    ops.pay_driver_advance(db, user, obj, None)


def _salary_advance_after(db, user, obj):
    emp = db.get(Employee, obj.employee_id)
    cr = ops._credit_ledger_for(db, "Company Cash" if obj.mode == "Cash" else "Bank", None, None, None)
    v = acc.post(db, user, "Payment", obj.advance_date, [{"ledger_id": acc.sys_ledger(db, "EMPLOYEE_ADVANCES"), "debit": obj.amount}, {"ledger_id": cr, "credit": obj.amount}], f"Salary advance to {emp.name}", "salary_advance", obj.id)
    obj.voucher_id = v.id


def _ledger_save(db, user, obj, data, is_new):
    if is_new and obj.opening_balance and not user.can("accounts:cancel"):
        raise AppError("Only senior accounts users can set opening balances")


def _leave_save(db, user, obj, data, is_new):
    if obj.to_date < obj.from_date:
        raise AppError("Leave end date is before start date")
    if not is_new and "status" in data:
        obj.decided_by = user.id


def _ewb_save(db, user, obj, data, is_new):
    from ..core.validators import validate

    err = validate("ewb", obj.ewb_no)
    if err:
        raise AppError(err)
    if obj.valid_until <= obj.ewb_date:
        raise AppError("Valid-until must be after generation time")
    if obj.consignment_id:
        lr = db.get(Consignment, obj.consignment_id)
        if lr:
            lr.eway_bill_no, lr.eway_bill_date, lr.eway_valid_until = obj.ewb_no, obj.ewb_date.date(), obj.valid_until


def _series_save(db, user, obj, data, is_new):
    from sqlalchemy import inspect as sa_inspect

    hist = sa_inspect(obj).attrs.next_no.history
    if not is_new and hist.deleted and obj.next_no < hist.deleted[0]:
        raise AppError("The next number can only be increased – lowering it would create duplicate document numbers")


SEARCH_NAME = ["name", "code"]

register("branches", Resource(Branch, "branches", label="name", search=["name", "code", "city"], title="Branches, warehouses & locations"))
register("bank_accounts", Resource(BankAccount, "company", label="bank_name", search=["bank_name", "account_no"], title="Bank accounts", after_create=_bank_ledger))
register("customers", Resource(Customer, "customers", label="name", search=["name", "code", "gstin", "mobile", "legal_name"], title="Customers", before_save=_customer_save, after_create=_customer_ledger, extra_filters=["category"]))
register("vehicles", Resource(Vehicle, "vehicles", label="registration_no", search=["registration_no", "make", "model", "chassis_no"], title="Vehicles", before_save=_vehicle_save, default_sort="registration_no"))
register("vehicle_events", Resource(VehicleEvent, "vehicles", label="event_type", title="Vehicle purchase / sale / transfer history", creatable=False, updatable=False, date_field="event_date"))
register("drivers", Resource(Driver, "drivers", label="name", search=["name", "code", "mobile", "licence_no"], title="Drivers", restricted={"aadhaar_enc": "drivers:aadhaar", "bank_account_enc": "drivers:aadhaar"}, before_save=_driver_save, after_create=_driver_ledger, default_sort="name"))
register("driver_incidents", Resource(DriverIncident, "drivers", label="kind", search=["description", "challan_no", "location"], title="Accidents, fines & incidents", date_field="incident_date"))
register("duty_roster", Resource(DutyRoster, "drivers", label="roster_date", title="Duty roster", deletable=True, date_field="roster_date"))
register("driver_advances", Resource(DriverAdvance, "drivers", label="advance_date", title="Driver advances", updatable=False, after_create=_advance_after, date_field="advance_date", write_perm="accounts:write"))
register("vendors", Resource(Vendor, "vendors", label="name", search=["name", "code", "gstin", "mobile"], title="Vendors", before_save=_vendor_save, after_create=_vendor_ledger))
register("routes", Resource(Route, "routes", label="code", search=["code", "origin", "destination", "via"], title="Routes"))
register("toll_plazas", Resource(TollPlaza, "routes", label="name", search=["name", "highway", "location"], title="Toll plazas"))
register("route_tolls", Resource(RouteToll, "routes", label="id", title="Route toll plazas", deletable=True))
register("fuel_stations", Resource(FuelStation, "fuel", label="name", search=["name", "location"], title="Fuel stations"))
register("fuel_cards", Resource(FuelCard, "fuel", label="card_no", search=["card_no", "provider"], title="Fuel cards"))
register("fuel_entries", Resource(FuelEntry, "fuel", label="entry_date", title="Diesel entries", creatable=False, updatable=False, date_field="entry_date"))
register("rate_contracts", Resource(RateContract, "rates", label="name", search=["contract_no", "name", "goods_category"], title="Freight rate contracts", before_save=_rate_save, deny_update=_rate_lock, date_field="effective_from"))
register("bookings", Resource(Booking, "bookings", label="booking_no", search=["booking_no", "pickup_address", "drop_address", "goods_description"], title="Bookings", before_save=_booking_save, date_field="booking_date"))
register("maintenance_schedules", Resource(MaintenanceSchedule, "maintenance", label="task", title="Preventive maintenance schedules", deletable=True))
register("tyres", Resource(Tyre, "maintenance", label="serial_no", search=["serial_no", "brand", "size"], title="Tyres & batteries"))
register("eway_bills", Resource(EwayBill, "lr", label="ewb_no", search=["ewb_no", "vehicle_no"], title="E-way bills", before_save=_ewb_save, date_field="ewb_date"))
register("ledgers", Resource(Ledger, "accounts", label="name", search=["name", "code"], title="Ledgers", default_sort="name", before_save=_ledger_save))
register("gst_treatments", Resource(GstTreatment, "invoices", label="name", search=["name", "code", "sac"], title="GST treatments", write_perm="settings:write"))
register("warehouses", Resource(Warehouse, "warehouse", label="name", search=["name", "code"], title="Godowns"))
register("items", Resource(Item, "warehouse", label="name", search=["sku", "name", "hsn", "barcode"], title="Item master"))
register("warehouse_rate_cards", Resource(WarehouseRateCard, "warehouse", label="storage_basis", title="Warehouse rate cards"))
register("documents", Resource(Document, "documents", label="title", search=["title", "doc_number", "tags"], title="Documents", creatable=True, date_field="expiry_date"))
register("departments", Resource(Department, "hr", label="name", title="Departments"))
register("employees", Resource(Employee, "hr", label="name", search=["name", "code", "mobile", "designation"], title="Employees", restricted={"basic": "hr:salary", "hra": "hr:salary", "other_allowances": "hr:salary", "monthly_tds": "hr:salary", "bank_account_enc": "hr:salary", "exit_settlement_amount": "hr:salary"}))
register("leave_types", Resource(LeaveType, "hr", label="name", title="Leave types"))
register("leave_requests", Resource(LeaveRequest, "hr", label="from_date", title="Leave requests", before_save=_leave_save, date_field="from_date"))
register("salary_advances", Resource(SalaryAdvance, "payroll", label="advance_date", title="Salary advances", updatable=False, after_create=_salary_advance_after, date_field="advance_date"))
register("compliance_rules", Resource(ComplianceRule, "compliance", label="name", search=["name", "code", "category"], title="Statutory requirements"))
register("statutory_registers", Resource(StatutoryRegister, "compliance", label="name", title="Statutory registers"))
register("notification_templates", Resource(NotificationTemplate, "notifications", label="event", search=["event", "channel", "body"], title="Notification templates", write_perm="settings:write"))
# Dropdown lookups only (newest first): trips and LRs are created and changed through their own workflows.
register("trips", Resource(Trip, "trips", label="trip_no", title="Trips", creatable=False, updatable=False, lookup_only=True))
register("consignments", Resource(Consignment, "lr", label="lr_no", title="LR / consignments", creatable=False, updatable=False, lookup_only=True))
register("vouchers", Resource(Voucher, "accounts", label="voucher_no", title="Vouchers", creatable=False, updatable=False, lookup_only=True))
register("account_groups", Resource(AccountGroup, "accounts", label="name", title="Account groups", creatable=False, updatable=False, lookup_only=True))
register("roles", Resource(Role, "users", label="name", title="Roles", creatable=False, updatable=False, lookup_only=True))
register("number_series", Resource(NumberSeries, "settings", label="doc_type", search=["doc_type", "fy"], title="Document numbering", creatable=True, before_save=_series_save))
