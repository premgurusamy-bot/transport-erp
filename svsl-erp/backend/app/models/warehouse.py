"""Godown / warehouse management and purchase / vendor management."""
from __future__ import annotations

from sqlalchemy import UniqueConstraint

from .base import JSON, ActiveMixin, AuditMixin, Base, Boolean, Column, Date, DateTime, F, Integer, Money, Numeric, Qty, Rate, String, Text


class Warehouse(AuditMixin, ActiveMixin, Base):
    __tablename__ = "warehouses"
    code = F(String(20), "Code", required=True, unique=True)
    name = F(String(120), "Godown name", required=True)
    branch_id = F(Integer, "Branch / location", fk="branches.id", ref="branches")
    address = F(Text, "Address")
    area_sqft = F(Numeric(10, 0), "Area (sq.ft)")
    capacity_pallets = F(Integer, "Capacity (pallets)")
    incharge = F(String(120), "In-charge")
    phone = F(String(15), "Phone")


class Item(AuditMixin, ActiveMixin, Base):
    __tablename__ = "items"
    sku = F(String(40), "SKU", required=True, unique=True)
    name = F(String(200), "Item name", required=True)
    hsn = F(String(8), "HSN")
    uom = F(String(10), "Unit", options=["NOS", "BOX", "PKG", "KG", "MT", "LTR", "SET", "PALLET", "BAG"], default="NOS")
    customer_id = F(Integer, "Owner customer (customer-owned stock)", fk="customers.id", ref="customers")
    category = F(String(60), "Category")
    batch_tracked = F(Boolean, "Batch tracked", default=False)
    weight_per_unit_kg = F(Numeric(10, 3), "Weight per unit (kg)")
    reorder_level = F(Qty, "Reorder level")
    barcode = F(String(60), "Barcode", unique=True)


class StockDoc(AuditMixin, Base):
    """Inward (GRN) / outward (dispatch) / adjustment / damage / shortage / stock count document."""

    __tablename__ = "stock_docs"
    doc_no = Column(String(30), unique=True, nullable=False)
    doc_type = Column(String(12), nullable=False)  # Inward / Outward / Transfer / Adjustment / Damage / Shortage / Count
    doc_date = Column(Date, nullable=False, index=True)
    warehouse_id = Column(Integer, nullable=False, index=True)
    to_warehouse_id = Column(Integer)
    customer_id = Column(Integer, index=True)
    vehicle_no = Column(String(15))
    consignment_id = Column(Integer)
    party_doc_no = Column(String(60))
    loaded_by = Column(String(120))
    remarks = Column(Text)
    status = Column(String(12), default="Posted", nullable=False)
    handling_units = Column(Qty, default=0)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    doc_id = Column(Integer, nullable=False, index=True)
    at = Column(Date, nullable=False, index=True)
    warehouse_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, index=True)
    batch_no = Column(String(40), default="", nullable=False)
    qty_in = Column(Qty, default=0, nullable=False)
    qty_out = Column(Qty, default=0, nullable=False)
    packages = Column(Integer, default=0)
    location_bin = Column(String(30))
    reason = Column(String(20))  # Inward / Outward / Damage / Shortage / Adjustment / Transfer
    remarks = Column(String(300))
    user_id = Column(Integer)
    created_at = Column(DateTime(timezone=True))


class WarehouseRateCard(AuditMixin, ActiveMixin, Base):
    __tablename__ = "warehouse_rate_cards"
    customer_id = F(Integer, "Customer", fk="customers.id", ref="customers", required=True)
    warehouse_id = F(Integer, "Godown (blank = all)", fk="warehouses.id", ref="warehouses")
    storage_basis = F(String(20), "Storage basis", options=["fixed_monthly", "per_sqft_month", "per_unit_day", "per_pallet_day"], required=True)
    storage_rate = F(Rate, "Storage rate (₹)", required=True)
    area_sqft = F(Numeric(10, 0), "Area allotted (sq.ft)")
    handling_in_rate = F(Rate, "Handling in per unit (₹)", default=0)
    handling_out_rate = F(Rate, "Handling out per unit (₹)", default=0)
    min_monthly = F(Money, "Minimum monthly bill (₹)", default=0)
    gst_treatment_id = F(Integer, "GST treatment", fk="gst_treatments.id", ref="gst_treatments")
    effective_from = F(Date, "Effective from", required=True)
    effective_to = F(Date, "Effective to")


class PurchaseOrder(AuditMixin, Base):
    __tablename__ = "purchase_orders"
    po_no = Column(String(30), unique=True, nullable=False)
    po_date = Column(Date, nullable=False)
    vendor_id = Column(Integer, nullable=False, index=True)
    category = Column(String(30))
    vehicle_id = Column(Integer)
    expected_date = Column(Date)
    lines = Column(JSON, default=list)  # [{description, qty, uom, rate, gst_rate, amount, received_qty}]
    subtotal = Column(Money, default=0)
    gst_amount = Column(Money, default=0)
    total = Column(Money, default=0)
    status = Column(String(15), default="Open")  # Open / Partly Received / Received / Closed / Cancelled
    terms = Column(Text)
    remarks = Column(Text)


class GoodsReceipt(AuditMixin, Base):
    __tablename__ = "goods_receipts"
    grn_no = Column(String(30), unique=True, nullable=False)
    grn_date = Column(Date, nullable=False)
    po_id = Column(Integer, index=True)
    vendor_id = Column(Integer, nullable=False)
    lines = Column(JSON, default=list)  # [{po_line, description, qty}]
    challan_no = Column(String(60))
    remarks = Column(Text)


class VendorBill(AuditMixin, Base):
    __tablename__ = "vendor_bills"
    entry_no = Column(String(30), unique=True, nullable=False)
    vendor_id = Column(Integer, nullable=False, index=True)
    bill_no = Column(String(60), nullable=False)
    bill_date = Column(Date, nullable=False, index=True)
    category = Column(String(30), nullable=False)
    po_id = Column(Integer)
    vehicle_id = Column(Integer)
    lines = Column(JSON, default=list)  # [{description, expense_ledger_id, amount, gst_rate}]
    taxable_value = Column(Money, default=0)
    cgst = Column(Money, default=0)
    sgst = Column(Money, default=0)
    igst = Column(Money, default=0)
    is_rcm = Column(Boolean, default=False)
    itc_eligible = Column(Boolean, default=True)
    tds_amount = Column(Money, default=0)
    round_off = Column(Money, default=0)
    total = Column(Money, default=0)
    amount_paid = Column(Money, default=0)
    due_date = Column(Date)
    status = Column(String(15), default="Unpaid")
    voucher_id = Column(Integer)
    source_type = Column(String(30))
    source_id = Column(Integer)
    remarks = Column(Text)
    __table_args__ = (UniqueConstraint("vendor_id", "bill_no", name="uq_vendor_bill_no"),)
