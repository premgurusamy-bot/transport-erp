"""E-invoice (IRP) and e-way bill integrations.

These government systems are reached only through an authorised GSP / ASP / direct API access
issued by GSTN/NIC against the business's own GSTIN. Until credentials are configured the ERP:
  * builds the official JSON (for offline upload on the portal), and
  * lets users record the IRN / EWB number returned by the portal.
Nothing is ever marked "Generated" unless the external system returns success.

The HTTP client below follows the NIC API flow (auth → generate) but every GSP wraps it differently;
it must be adapted to and certified with your chosen provider before production use.
"""
from __future__ import annotations

from datetime import date

import httpx

from ..config import get_settings
from ..core.money import D, r2


class NotConfigured(Exception):
    pass


class PortalError(Exception):
    pass


def irp_configured() -> bool:
    s = get_settings()
    return bool(s.irp_base_url and s.irp_client_id and s.irp_client_secret and s.irp_username and s.irp_password)


def ewb_configured() -> bool:
    s = get_settings()
    return bool(s.ewb_base_url and s.ewb_client_id and s.ewb_client_secret and s.ewb_username and s.ewb_password)


def build_einvoice_json(inv, company, customer, lines) -> dict:
    """INV-01 schema v1.1 payload for a services invoice (SAC). Review against the current NIC schema."""
    is_service = True
    doc_type = {"tax_invoice": "INV", "debit_note": "DBN", "credit_note": "CRN"}.get(inv.doc_type, "INV")
    items = []
    for i, ln in enumerate(lines, 1):
        amt = r2(ln.amount)
        rate = D(inv.gst_rate)
        tax_factor = rate / 100 if inv.charge_mechanism == "FCM" else D(0)
        items.append({
            "SlNo": str(i), "PrdDesc": ln.description[:300], "IsServc": "Y" if is_service else "N", "HsnCd": ln.sac or inv.sac,
            "Qty": float(ln.quantity or 1), "Unit": "OTH", "UnitPrice": float(r2(ln.rate or amt)), "TotAmt": float(amt), "Discount": 0,
            "AssAmt": float(amt), "GstRt": float(rate),
            "IgstAmt": float(r2(amt * tax_factor)) if inv.is_interstate else 0,
            "CgstAmt": 0 if inv.is_interstate else float(r2(amt * tax_factor / 2)),
            "SgstAmt": 0 if inv.is_interstate else float(r2(amt * tax_factor / 2)),
            "TotItemVal": float(r2(amt * (1 + tax_factor))),
        })
    return {
        "Version": "1.1",
        "TranDtls": {"TaxSch": "GST", "SupTyp": "B2B", "RegRev": "Y" if inv.charge_mechanism == "RCM" else "N", "IgstOnIntra": "N"},
        "DocDtls": {"Typ": doc_type, "No": inv.invoice_no[:16], "Dt": inv.invoice_date.strftime("%d/%m/%Y")},
        "SellerDtls": {"Gstin": company.gstin, "LglNm": company.legal_name, "TrdNm": company.trade_name, "Addr1": (company.address or "")[:100], "Loc": company.city, "Pin": int(company.pincode) if company.pincode else None, "Stcd": company.state_code, "Ph": company.phone, "Em": company.email},
        "BuyerDtls": {"Gstin": customer.gstin, "LglNm": customer.legal_name or customer.name, "Pos": inv.place_of_supply, "Addr1": (customer.billing_address or "")[:100], "Loc": customer.billing_city, "Pin": int(customer.billing_pincode) if customer.billing_pincode else None, "Stcd": customer.billing_state_code},
        "ItemList": items,
        "ValDtls": {"AssVal": float(inv.taxable_value), "CgstVal": float(inv.cgst), "SgstVal": float(inv.sgst), "IgstVal": float(inv.igst), "RndOffAmt": float(inv.round_off), "TotInvVal": float(inv.total)},
    }


def generate_irn(payload: dict) -> dict:
    if not irp_configured():
        raise NotConfigured("E-invoice IRP/GSP credentials are not configured. Upload the JSON on the IRP portal and record the IRN, or configure IRP_* settings.")
    s = get_settings()
    try:
        with httpx.Client(base_url=s.irp_base_url, timeout=30) as c:
            auth = c.post("/eivital/v1.04/auth", headers={"client_id": s.irp_client_id, "client_secret": s.irp_client_secret}, json={"UserName": s.irp_username, "Password": s.irp_password})
            if auth.status_code >= 300:
                raise PortalError(f"IRP authentication failed: {auth.text[:300]}")
            token = auth.json().get("Data", {}).get("AuthToken")
            r = c.post("/eicore/v1.03/Invoice", headers={"client_id": s.irp_client_id, "client_secret": s.irp_client_secret, "user_name": s.irp_username, "authtoken": token or "", "Gstin": payload["SellerDtls"]["Gstin"]}, json=payload)
    except httpx.HTTPError as exc:
        raise PortalError(f"Could not reach IRP: {exc}") from exc
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    data = body.get("Data") if isinstance(body, dict) else None
    if r.status_code >= 300 or not data or not data.get("Irn"):
        raise PortalError(f"IRP rejected the invoice: {r.text[:500]}")
    return {"irn": data["Irn"], "ack_no": str(data.get("AckNo")), "ack_date": data.get("AckDt"), "signed_qr": data.get("SignedQRCode")}


def cancel_irn(irn: str, reason_code: str, remark: str) -> dict:
    if not irp_configured():
        raise NotConfigured("IRP is not configured. Cancel the IRN on the IRP portal within 24 hours and then record the cancellation here.")
    raise PortalError("IRN cancellation through the API must be enabled for your GSP before use.")


def build_ewaybill_json(lr, company) -> dict:
    """EWB-01 style payload for the NIC bulk-upload tool; consignor normally generates it, the transporter may on their behalf."""
    return {
        "supplyType": "O", "subSupplyType": "1", "docType": "INV", "docNo": lr.customer_invoice_no, "docDate": lr.customer_invoice_date.strftime("%d/%m/%Y") if lr.customer_invoice_date else None,
        "fromGstin": lr.consignor_gstin or "URP", "fromTrdName": lr.consignor_name, "fromAddr1": (lr.consignor_address or "")[:120], "fromPlace": lr.from_place,
        "toGstin": lr.consignee_gstin or "URP", "toTrdName": lr.consignee_name, "toAddr1": (lr.consignee_address or "")[:120], "toPlace": lr.to_place,
        "totInvValue": float(lr.goods_value or 0), "transporterId": company.gstin, "transporterName": company.legal_name, "transDocNo": lr.lr_no,
        "transDocDate": lr.lr_date.strftime("%d/%m/%Y"), "transMode": "1", "transDistance": str(int(lr.distance_km or 0)), "vehicleNo": lr.vehicle_no, "vehicleType": "R",
    }


def ewb_validity_days(distance_km) -> int:
    """Validity for normal cargo: 1 day per 200 km or part (Rule 138(10)); ODC is 20 km/day – configure separately."""
    km = int(D(distance_km) or 0)
    return max(1, -(-km // 200))


def update_part_b(ewb_no: str, vehicle_no: str, reason: str) -> dict:
    if not ewb_configured():
        raise NotConfigured("E-way bill API is not configured. Update Part-B on the e-way bill portal and record the change here.")
    raise PortalError("Part-B API update must be enabled with your GSP before use.")


def today() -> date:
    return date.today()
