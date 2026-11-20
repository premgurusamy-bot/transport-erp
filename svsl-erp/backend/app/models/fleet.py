"""Fuel, maintenance & workshop, tyres/batteries."""
from __future__ import annotations

from .base import JSON, AuditMixin, Base, Boolean, Column, Date, DateTime, F, Integer, Money, Numeric, Rate, String, Text

MAINT_CATEGORIES = [
    "Preventive Service", "Engine Oil", "Tyres", "Battery", "Brake", "Clutch", "Engine Repair", "Gear Box",
    "Electrical", "Body Work", "Accident Repair", "Suspension", "AC", "Other",
]


class FuelEntry(AuditMixin, Base):
    __tablename__ = "fuel_entries"
    entry_date = F(Date, "Date", required=True)
    vehicle_id = F(Integer, "Vehicle", fk="vehicles.id", ref="vehicles", required=True)
    driver_id = F(Integer, "Driver", fk="drivers.id", ref="drivers")
    trip_id = F(Integer, "Trip", fk="trips.id", ref="trips")
    station_id = F(Integer, "Fuel station", fk="fuel_stations.id", ref="fuel_stations")
    fuel_card_id = F(Integer, "Fuel card", fk="fuel_cards.id", ref="fuel_cards")
    litres = F(Numeric(8, 2), "Litres", required=True)
    rate = F(Rate, "Rate per litre (₹)", required=True)
    amount = F(Money, "Amount (₹)", readonly=True)
    odometer = F(Numeric(10, 0), "Odometer (km)", required=True)
    full_tank = F(Boolean, "Full tank", default=True)
    payment_mode = F(String(20), "Payment", options=["Cash", "Bank", "Fuel Card", "Vendor Credit", "Driver Cash"], default="Vendor Credit")
    bill_no = F(String(60), "Bill no.")
    entered_via = F(String(20), "Entered via", options=["Office", "Driver App"], default="Office")
    voucher_id = F(Integer, "Voucher", fk="vouchers.id", ref="vouchers", readonly=True)
    remarks = F(Text, "Remarks")


class MaintenanceSchedule(AuditMixin, Base):
    __tablename__ = "maintenance_schedules"
    vehicle_id = F(Integer, "Vehicle", fk="vehicles.id", ref="vehicles", required=True)
    task = F(String(40), "Task", options=MAINT_CATEGORIES, required=True)
    interval_km = F(Numeric(8, 0), "Every (km)")
    interval_days = F(Integer, "Every (days)")
    last_done_date = F(Date, "Last done on")
    last_done_km = F(Numeric(10, 0), "Last done at (km)")
    remind_before_km = F(Numeric(8, 0), "Remind before (km)", default=500)
    remind_before_days = F(Integer, "Remind before (days)", default=7)
    is_active = F(Boolean, "Active", default=True)


class MaintenanceJob(AuditMixin, Base):
    __tablename__ = "maintenance_jobs"
    job_no = Column(String(30), unique=True, nullable=False)
    vehicle_id = Column(Integer, nullable=False, index=True)
    category = Column(String(40), nullable=False)
    job_type = Column(String(15), default="Breakdown")  # Preventive / Breakdown / Accident
    vendor_id = Column(Integer)
    workshop = Column(String(160))
    date_in = Column(Date, nullable=False)
    date_out = Column(Date)
    odometer = Column(Numeric(10, 0))
    complaint = Column(Text)
    work_done = Column(Text)
    parts = Column(JSON, default=list)  # [{name, part_no, qty, rate, amount}]
    labour_amount = Column(Money, default=0)
    parts_amount = Column(Money, default=0)
    gst_amount = Column(Money, default=0)
    total_amount = Column(Money, default=0)
    bill_no = Column(String(60))
    payment_mode = Column(String(20), default="Vendor Credit")
    status = Column(String(15), default="Open")  # Open / Completed / Cancelled
    schedule_id = Column(Integer)
    voucher_id = Column(Integer)
    vendor_bill_id = Column(Integer)
    remarks = Column(Text)


class Tyre(AuditMixin, Base):
    __tablename__ = "tyres"
    kind = F(String(10), "Type", options=["Tyre", "Battery"], default="Tyre", required=True)
    serial_no = F(String(60), "Serial no.", required=True, unique=True)
    brand = F(String(60), "Brand")
    size = F(String(40), "Size / spec")
    purchase_date = F(Date, "Purchase date")
    cost = F(Money, "Cost (₹)", default=0)
    vendor_id = F(Integer, "Vendor", fk="vendors.id", ref="vendors")
    warranty_till = F(Date, "Warranty till")
    vehicle_id = F(Integer, "Fitted on vehicle", fk="vehicles.id", ref="vehicles")
    position = F(String(20), "Position", help="e.g. FL, FR, RL-O, RL-I, Stepney")
    fitted_date = F(Date, "Fitted on")
    fitted_km = F(Numeric(10, 0), "Fitted at (km)")
    status = F(String(15), "Status", options=["In Stock", "Fitted", "Removed", "Retreading", "Scrapped", "Sold"], default="In Stock")
    total_km = F(Numeric(10, 0), "Total km run", default=0, readonly=True)
    remarks = F(Text, "Remarks")


class TyreEvent(Base):
    __tablename__ = "tyre_events"
    id = Column(Integer, primary_key=True)
    tyre_id = Column(Integer, nullable=False, index=True)
    at = Column(Date, nullable=False)
    event = Column(String(15), nullable=False)  # Fitted / Removed / Retread / Scrapped / Rotated / Sold
    vehicle_id = Column(Integer)
    position = Column(String(20))
    odometer = Column(Numeric(10, 0))
    km_run = Column(Numeric(10, 0))
    cost = Column(Money, default=0)
    remarks = Column(Text)
    user_id = Column(Integer)
    created_at = Column(DateTime(timezone=True))
