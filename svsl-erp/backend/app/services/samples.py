"""Sample documents for layout previews: the latest real document when one exists, otherwise an unsaved,
clearly marked SAMPLE built in memory (never written to the database)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import BankAccount, Consignment, ConsignmentItem, Customer, DeliveryPoint, GstTreatment, Invoice, InvoiceLine


def sample_invoice(db: Session):
    inv = db.query(Invoice).filter(Invoice.doc_type == "tax_invoice").order_by(Invoice.id.desc()).first()
    bank = db.query(BankAccount).filter_by(is_active=True, print_on_invoice=True).first()
    if inv:
        return inv, db.get(Customer, inv.customer_id), db.query(InvoiceLine).filter_by(invoice_id=inv.id).order_by(InvoiceLine.line_no).all(), bank, db.get(GstTreatment, inv.gst_treatment_id) if inv.gst_treatment_id else None
    today = date.today()
    inv = Invoice(invoice_no="SAMPLE/0001", doc_type="tax_invoice", invoice_date=today, due_date=today + timedelta(days=30), billing_name="SAMPLE CUSTOMER PVT LTD",
                  billing_address="Sample address, Coimbatore", customer_gstin=None, place_of_supply="33", supplier_state_code="33", sac="996791", charge_mechanism="FCM",
                  gst_rate=Decimal("5"), is_interstate=False, taxable_value=Decimal("25000"), cgst=Decimal("625"), sgst=Decimal("625"), igst=Decimal("0"), rcm_tax=Decimal("0"),
                  round_off=Decimal("0"), total=Decimal("26250"), amount_received=Decimal("0"), status="Issued", einvoice_status="Not Applicable", po_number="PO-SAMPLE", verify_token="sample")
    cust = Customer(name="SAMPLE CUSTOMER PVT LTD", billing_state_code="33")
    lines = [InvoiceLine(line_no=1, description="Freight – LR SAMPLE/LR/0001, Coimbatore → Chennai, Vehicle TN00XX0000", sac="996791", quantity=Decimal("1"), rate=Decimal("13000"), amount=Decimal("13000")),
             InvoiceLine(line_no=2, description="Freight – LR SAMPLE/LR/0002, Coimbatore → Hosur, Vehicle TN00XX0000", sac="996791", quantity=Decimal("1"), rate=Decimal("12000"), amount=Decimal("12000"))]
    return inv, cust, lines, bank, None


def sample_lr(db: Session):
    lr = db.query(Consignment).filter(Consignment.status != "Cancelled").order_by(Consignment.id.desc()).first()
    if lr:
        return lr, db.get(Customer, lr.customer_id), db.query(ConsignmentItem).filter_by(consignment_id=lr.id).all(), db.query(DeliveryPoint).filter_by(consignment_id=lr.id).all()
    lr = Consignment(lr_no="SAMPLE/LR/0001", lr_date=date.today(), customer_id=0, consignor_name="SAMPLE CONSIGNOR", consignor_address="Coimbatore", consignee_name="SAMPLE CONSIGNEE",
                     consignee_address="Chennai", from_place="Coimbatore", to_place="Chennai", distance_km=Decimal("505"), vehicle_no="TN00XX0000", driver_name="Sample Driver",
                     load_type="FTL", is_return=False, packages=20, quantity=Decimal("200"), weight_kg=Decimal("4000"), charged_weight_kg=Decimal("4000"), goods_value=Decimal("35000"),
                     basic_freight=Decimal("12000"), loading_charges=Decimal("500"), unloading_charges=Decimal("500"), waiting_charges=0, detention_charges=0, extra_stop_charges=0,
                     other_charges=0, total_freight=Decimal("13000"), advance_freight=Decimal("0"), balance_freight=Decimal("13000"), payment_terms="To Be Billed", gst_paid_by="Consignor",
                     risk="Owner's Risk", status="Booked", revision=0, verify_token="sample", freight_breakdown={"lines": [{"label": "Per trip: 1 trip × ₹12000.00", "amount": "12000"}]})
    items = [ConsignmentItem(description="SAMPLE auto components", hsn="8708", packages=20, package_type="Box", quantity=Decimal("200"), uom="NOS", weight_kg=Decimal("4000"), value=Decimal("35000"))]
    return lr, None, items, []
