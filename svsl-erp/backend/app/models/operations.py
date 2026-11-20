"""Rate contracts, bookings, LR (consignments), trips, expenses, driver ops, FASTag."""
from __future__ import annotations

from sqlalchemy import UniqueConstraint

from .base import (
    JSON, ActiveMixin, AuditMixin, Base, Boolean, Column, Date, DateTime, F, Integer, Money, Numeric, Qty, Rate,
    String, Text,
)
from .masters import VEHICLE_TYPES

FREIGHT_BASES = [
    "per_trip", "per_turn", "per_vehicle", "per_km", "per_tonne", "per_kg", "per_piece", "per_load",
    "monthly_fixed", "route_fixed", "distance_slab", "weight_slab",
]
TRIP_STAGES = [
    "Booked", "Vehicle Allocated", "Driver Allocated", "LR Generated", "Loading", "Dispatched", "In Transit",
    "Delivered", "POD Collected", "Closed", "Billed", "Settled", "Cancelled",
]
EXPENSE_CATEGORIES = [
    "Diesel", "Toll", "Parking", "RTO / Check Post", "Loading", "Unloading", "Driver Bata", "Food",
    "Police / Fine", "Repair on Road", "Weighbridge", "Tyre Puncture", "Phone", "Other",
]


class RateContract(AuditMixin, Base):
    """A negotiated rate. Revisions create a new version; history is never overwritten."""

    __tablename__ = "rate_contracts"
    __table_args__ = (UniqueConstraint("contract_no", "version", name="uq_rate_contract_version"),)
    contract_no = F(String(30), "Contract no.", required=True, readonly=True)
    version = F(Integer, "Version", default=1, readonly=True)
    name = F(String(160), "Description", required=True)
    customer_id = F(Integer, "Customer", fk="customers.id", ref="customers", required=True)
    route_id = F(Integer, "Route (blank = any)", fk="routes.id", ref="routes")
    vehicle_type = F(String(40), "Vehicle type (blank = any)", options=[""] + VEHICLE_TYPES)
    goods_category = F(String(80), "Goods / material (blank = any)")
    basis = F(String(20), "Freight basis", options=FREIGHT_BASES, required=True)
    rate = F(Rate, "Rate (₹)", default=0, help="Per unit of the basis; monthly amount for monthly_fixed; route amount for route_fixed")
    min_freight = F(Money, "Minimum guaranteed freight (₹)", default=0)
    min_weight_kg = F(Numeric(10, 0), "Minimum chargeable weight (kg)", default=0)
    slabs = Column(JSON, nullable=True, info={"label": "Slabs", "help": "[{from, to, rate, mode: 'flat'|'per_unit'}]"})
    monthly_trips_included = F(Integer, "Trips included per month (monthly contracts)", default=0)
    extra_trip_rate = F(Money, "Rate per extra trip (₹)", default=0)
    waiting_free_hours = F(Numeric(6, 2), "Free waiting hours", default=0)
    waiting_rate_per_hour = F(Money, "Waiting charge per hour (₹)", default=0)
    detention_free_days = F(Numeric(6, 2), "Free detention days", default=0)
    detention_rate_per_day = F(Money, "Detention per day (₹)", default=0)
    loading_charge = F(Money, "Loading charge (₹)", default=0)
    unloading_charge = F(Money, "Unloading charge (₹)", default=0)
    extra_stop_charge = F(Money, "Additional stop charge (₹ per stop)", default=0)
    return_load_mode = F(String(10), "Return load charging", options=["none", "percent", "fixed"], default="none")
    return_load_value = F(Rate, "Return load % or amount", default=0)
    gst_treatment_id = F(Integer, "GST treatment", fk="gst_treatments.id", ref="gst_treatments")
    effective_from = F(Date, "Effective from", required=True)
    effective_to = F(Date, "Effective to")
    status = F(String(12), "Status", options=["Draft", "Active", "Superseded", "Expired"], default="Active")
    revision_reason = F(Text, "Revision reason")
    remarks = F(Text, "Remarks")


class Booking(AuditMixin, Base):
    __tablename__ = "bookings"
    booking_no = F(String(30), "Booking no.", unique=True, readonly=True)
    booking_date = F(Date, "Booking date", required=True)
    customer_id = F(Integer, "Customer", fk="customers.id", ref="customers", required=True)
    source = F(String(20), "Source", options=["Office", "Phone", "Email", "Customer Portal"], default="Office")
    pickup_address = F(Text, "Pickup / loading address", required=True)
    drop_address = F(Text, "Delivery address", required=True)
    route_id = F(Integer, "Route", fk="routes.id", ref="routes")
    required_date = F(Date, "Vehicle required on", required=True)
    vehicle_type = F(String(40), "Vehicle type", options=[""] + VEHICLE_TYPES)
    vehicles_required = F(Integer, "No. of vehicles", default=1)
    goods_description = F(String(200), "Goods")
    weight_kg = F(Numeric(12, 2), "Approx. weight (kg)")
    quantity = F(Qty, "Quantity")
    status = F(String(15), "Status", options=["Requested", "Confirmed", "Rejected", "Converted", "Cancelled"], default="Requested")
    trip_id = F(Integer, "Trip", fk="trips.id", ref="trips", readonly=True)
    contact_person = F(String(120), "Contact at site")
    contact_phone = F(String(15), "Contact phone")
    remarks = F(Text, "Remarks")


class Trip(AuditMixin, Base):
    __tablename__ = "trips"
    trip_no = Column(String(30), unique=True, nullable=False)
    trip_date = Column(Date, nullable=False)
    branch_id = Column(Integer, nullable=True)
    customer_id = Column(Integer, nullable=True, index=True)
    booking_id = Column(Integer, nullable=True)
    route_id = Column(Integer, nullable=True)
    from_place = Column(String(120))
    to_place = Column(String(120))
    vehicle_id = Column(Integer, nullable=True, index=True)
    driver_id = Column(Integer, nullable=True, index=True)
    co_driver_id = Column(Integer, nullable=True)
    stage = Column(String(20), nullable=False, default="Booked")
    start_km = Column(Numeric(10, 0))
    end_km = Column(Numeric(10, 0))
    planned_departure = Column(DateTime(timezone=True))
    loading_at = Column(DateTime(timezone=True))
    dispatched_at = Column(DateTime(timezone=True))
    expected_delivery_at = Column(DateTime(timezone=True))
    delivered_at = Column(DateTime(timezone=True))
    pod_received_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    fuel_opening_litres = Column(Numeric(8, 2))
    fuel_closing_litres = Column(Numeric(8, 2))
    advance_to_driver = Column(Money, default=0)
    advance_from_customer = Column(Money, default=0)
    is_return = Column(Boolean, default=False, nullable=False)
    return_of_trip_id = Column(Integer, nullable=True)
    trip_days = Column(Numeric(5, 1))
    waiting_hours = Column(Numeric(6, 2), default=0)
    detention_days = Column(Numeric(6, 2), default=0)
    remarks = Column(Text)
    billed = Column(Boolean, default=False, nullable=False)
    driver_settlement_id = Column(Integer, nullable=True)
    cancel_reason = Column(Text)


class TripEvent(Base):
    __tablename__ = "trip_events"
    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, nullable=False, index=True)
    at = Column(DateTime(timezone=True), nullable=False)
    stage = Column(String(20), nullable=False)
    note = Column(Text)
    user_id = Column(Integer)
    odometer = Column(Numeric(10, 0))
    lat = Column(Numeric(9, 6))
    lng = Column(Numeric(9, 6))


class TripExpense(AuditMixin, Base):
    __tablename__ = "trip_expenses"
    trip_id = Column(Integer, nullable=False, index=True)
    expense_date = Column(Date, nullable=False)
    category = Column(String(30), nullable=False)
    amount = Column(Money, nullable=False)
    litres = Column(Numeric(8, 2))
    rate = Column(Rate)
    paid_by = Column(String(20), nullable=False, default="Driver Cash")  # Driver Cash / Company Cash / Bank / Fuel Card / FASTag / Vendor Credit
    vendor_id = Column(Integer)
    bill_no = Column(String(60))
    remarks = Column(Text)
    entered_via = Column(String(20), default="Office")
    approved = Column(Boolean, default=True, nullable=False)
    voucher_id = Column(Integer)
    fuel_entry_id = Column(Integer)
    document_id = Column(Integer)


class Consignment(AuditMixin, Base):
    """Lorry Receipt (LR)."""

    __tablename__ = "consignments"
    lr_no = Column(String(40), unique=True, nullable=False)
    lr_date = Column(Date, nullable=False, index=True)
    branch_id = Column(Integer)
    customer_id = Column(Integer, nullable=False, index=True)
    customer_gstin = Column(String(15))
    billing_party = Column(String(12), default="Customer")  # Customer / Consignor / Consignee
    consignor_name = Column(String(200), nullable=False)
    consignor_gstin = Column(String(15))
    consignor_address = Column(Text)
    consignor_phone = Column(String(15))
    consignee_name = Column(String(200), nullable=False)
    consignee_gstin = Column(String(15))
    consignee_address = Column(Text)
    consignee_phone = Column(String(15))
    loading_address = Column(Text)
    delivery_address = Column(Text)
    from_place = Column(String(120), nullable=False)
    to_place = Column(String(120), nullable=False)
    route_id = Column(Integer)
    distance_km = Column(Numeric(8, 1))
    trip_id = Column(Integer, index=True)
    vehicle_id = Column(Integer)
    vehicle_no = Column(String(15))
    vehicle_type = Column(String(40))
    driver_id = Column(Integer)
    driver_name = Column(String(120))
    driver_mobile = Column(String(15))
    driver_licence = Column(String(20))
    load_type = Column(String(4), default="FTL", nullable=False)
    is_return = Column(Boolean, default=False, nullable=False)
    original_lr_id = Column(Integer)
    goods_value = Column(Money, default=0)
    customer_invoice_no = Column(String(120))
    customer_invoice_date = Column(Date)
    eway_bill_no = Column(String(12))
    eway_bill_date = Column(Date)
    eway_valid_until = Column(DateTime(timezone=True))
    einvoice_ref = Column(String(80))
    packages = Column(Integer, default=0)
    quantity = Column(Qty, default=0)
    weight_kg = Column(Numeric(12, 2), default=0)
    charged_weight_kg = Column(Numeric(12, 2), default=0)
    rate_contract_id = Column(Integer)
    freight_basis = Column(String(20))
    freight_rate = Column(Rate, default=0)
    freight_inputs = Column(JSON)
    freight_breakdown = Column(JSON)
    basic_freight = Column(Money, default=0)
    loading_charges = Column(Money, default=0)
    unloading_charges = Column(Money, default=0)
    waiting_charges = Column(Money, default=0)
    detention_charges = Column(Money, default=0)
    extra_stop_charges = Column(Money, default=0)
    other_charges = Column(Money, default=0)
    other_charges_note = Column(String(200))
    total_freight = Column(Money, default=0, nullable=False)
    advance_freight = Column(Money, default=0, nullable=False)
    balance_freight = Column(Money, default=0, nullable=False)
    payment_terms = Column(String(20), default="To Be Billed")  # Paid / To Pay / To Be Billed
    gst_paid_by = Column(String(20), default="Consignor")
    risk = Column(String(20), default="Owner's Risk")
    remarks = Column(Text)
    customer_authorization = Column(String(160))
    status = Column(String(20), default="Booked", nullable=False)  # Booked/Loaded/In Transit/Delivered/POD Received/Billed/Cancelled
    delivered_at = Column(DateTime(timezone=True))
    receiver_name = Column(String(120))
    receiver_phone = Column(String(15))
    delivery_remarks = Column(Text)
    shortage_qty = Column(Qty, default=0)
    damage_qty = Column(Qty, default=0)
    pod_received_at = Column(DateTime(timezone=True))
    pod_document_id = Column(Integer)
    invoice_id = Column(Integer, index=True)
    revision = Column(Integer, default=0, nullable=False)
    cancelled_at = Column(DateTime(timezone=True))
    cancel_reason = Column(Text)
    cancelled_by = Column(Integer)
    verify_token = Column(String(40))


class ConsignmentItem(Base):
    __tablename__ = "consignment_items"
    id = Column(Integer, primary_key=True)
    consignment_id = Column(Integer, nullable=False, index=True)
    description = Column(String(200), nullable=False)
    hsn = Column(String(8))
    packages = Column(Integer, default=0)
    package_type = Column(String(30))
    quantity = Column(Qty, default=0)
    uom = Column(String(10), default="NOS")
    weight_kg = Column(Numeric(12, 2), default=0)
    value = Column(Money, default=0)


class DeliveryPoint(Base):
    __tablename__ = "delivery_points"
    id = Column(Integer, primary_key=True)
    consignment_id = Column(Integer, nullable=False, index=True)
    sequence = Column(Integer, default=1)
    consignee_name = Column(String(200))
    address = Column(Text, nullable=False)
    contact = Column(String(60))
    packages = Column(Integer, default=0)
    status = Column(String(15), default="Pending")
    delivered_at = Column(DateTime(timezone=True))
    receiver_name = Column(String(120))


class LRAmendment(Base):
    __tablename__ = "lr_amendments"
    id = Column(Integer, primary_key=True)
    consignment_id = Column(Integer, nullable=False, index=True)
    at = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(Integer)
    authorized_by = Column(String(120), nullable=False)
    reason = Column(Text, nullable=False)
    before = Column(JSON)
    after = Column(JSON)
    revision = Column(Integer)


class DriverAdvance(AuditMixin, Base):
    __tablename__ = "driver_advances"
    driver_id = F(Integer, "Driver", fk="drivers.id", ref="drivers", required=True)
    advance_date = F(Date, "Date", required=True)
    amount = F(Money, "Amount (₹)", required=True)
    trip_id = F(Integer, "Trip", fk="trips.id", ref="trips")
    mode = F(String(20), "Paid by", options=["Cash", "Bank"], default="Cash", required=True)
    purpose = F(String(40), "Purpose", options=["Trip Advance", "Salary Advance", "Personal Loan", "Other"], default="Trip Advance")
    remarks = F(Text, "Remarks")
    voucher_id = F(Integer, "Voucher", fk="vouchers.id", ref="vouchers", readonly=True)
    settlement_id = F(Integer, "Settled in", readonly=True)


class DriverSettlement(AuditMixin, Base):
    __tablename__ = "driver_settlements"
    settlement_no = Column(String(30), unique=True, nullable=False)
    driver_id = Column(Integer, nullable=False, index=True)
    settlement_date = Column(Date, nullable=False)
    period_from = Column(Date)
    period_to = Column(Date)
    trip_ids = Column(JSON, default=list)
    trip_days = Column(Numeric(6, 1), default=0)
    bata_total = Column(Money, default=0)
    food_total = Column(Money, default=0)
    trip_allowance_total = Column(Money, default=0)
    km_allowance_total = Column(Money, default=0)
    driver_paid_expenses = Column(Money, default=0)
    advances_total = Column(Money, default=0)
    fines_recovered = Column(Money, default=0)
    other_deductions = Column(Money, default=0)
    net_payable = Column(Money, default=0)
    status = Column(String(15), default="Posted")
    voucher_id = Column(Integer)
    remarks = Column(Text)
    details = Column(JSON)


class DutyRoster(AuditMixin, Base):
    __tablename__ = "duty_roster"
    __table_args__ = (UniqueConstraint("roster_date", "driver_id", name="uq_roster_date_driver"),)
    roster_date = F(Date, "Date", required=True)
    driver_id = F(Integer, "Driver", fk="drivers.id", ref="drivers", required=True)
    vehicle_id = F(Integer, "Vehicle", fk="vehicles.id", ref="vehicles")
    shift = F(String(10), "Shift", options=["Day", "Night", "Full Day", "Off"], default="Full Day")
    notes = F(String(200), "Notes")


class LocationPing(Base):
    __tablename__ = "location_pings"
    id = Column(Integer, primary_key=True)
    driver_id = Column(Integer, nullable=False, index=True)
    trip_id = Column(Integer, index=True)
    at = Column(DateTime(timezone=True), nullable=False)
    lat = Column(Numeric(9, 6), nullable=False)
    lng = Column(Numeric(9, 6), nullable=False)
    accuracy_m = Column(Numeric(8, 1))


class FastagTransaction(Base):
    __tablename__ = "fastag_transactions"
    id = Column(Integer, primary_key=True)
    txn_id = Column(String(80), unique=True, nullable=False)
    txn_at = Column(DateTime(timezone=True), nullable=False)
    vehicle_no = Column(String(15), nullable=False)
    vehicle_id = Column(Integer, index=True)
    plaza_name = Column(String(200))
    amount = Column(Money, nullable=False)
    txn_type = Column(String(10), default="Debit")
    provider = Column(String(60))
    trip_id = Column(Integer, index=True)
    match_status = Column(String(15), default="Unmatched")
    import_batch = Column(String(40))
    imported_at = Column(DateTime(timezone=True))


class Complaint(AuditMixin, Base):
    __tablename__ = "complaints"
    complaint_no = Column(String(30), unique=True, nullable=False)
    customer_id = Column(Integer, nullable=False, index=True)
    consignment_id = Column(Integer)
    subject = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(15), default="Open", nullable=False)
    response = Column(Text)
    resolved_at = Column(DateTime(timezone=True))
