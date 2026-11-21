"""Customisable document layouts (Settings → Document layouts)."""
import shutil
import subprocess

import pytest

from .conftest import lr_payload, make_contract, make_customer

needs_pdftotext = pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext not installed")


def text_of(pdf_bytes: bytes) -> str:
    return subprocess.run(["pdftotext", "-raw", "-", "-"], input=pdf_bytes, capture_output=True, check=True).stdout.decode()


def test_defaults_and_validation(api):
    d = api.get("/api/layouts")
    assert set(d["documents"]) == {"invoice", "lr", "thermal", "report"}
    assert d["layouts"]["invoice"]["copies"] == ["ORIGINAL FOR RECIPIENT"]
    assert "Invalid" in api.put("/api/layouts/invoice", {"orientation": "sideways"}, expect=400).json()["detail"]
    assert "colour" in api.put("/api/layouts/invoice", {"accent_color": "blue"}, expect=400).json()["detail"]
    assert "between" in api.put("/api/layouts/invoice", {"margin_mm": 99}, expect=400).json()["detail"]
    cols = [{"key": "description", "label": "x", "show": False}]
    assert "description" in api.put("/api/layouts/invoice", {"columns": cols}, expect=400).json()["detail"]
    assert api.put("/api/layouts/invoice", {"copies": []}, expect=400)


@needs_pdftotext
def test_custom_invoice_and_lr_layout_is_printed(api):
    cust = make_customer(api)
    make_contract(api, cust["id"])
    lr = api.post("/api/lr", lr_payload(cust["id"]))["lr"]
    inv = api.post("/api/invoices", {"customer_id": cust["id"], "lr_ids": [lr["id"]]})
    saved = api.put("/api/layouts/invoice", {
        "paper": "A5", "accent_color": "#aa0000", "copies": ["ORIGINAL FOR RECIPIENT", "DUPLICATE FOR SUPPLIER"],
        "titles": {"tax_invoice": "FREIGHT BILL"}, "show_bank": False, "show_tax_summary": False, "footer_text": "Thank you for your business",
        "columns": [{"key": "line_no", "label": "Sl", "show": True, "width": 5}, {"key": "description", "label": "Particulars of service", "show": True, "width": 60},
                    {"key": "sac", "label": "SAC", "show": False, "width": 8}, {"key": "amount", "label": "Amount (Rs)", "show": True, "width": 20}],
    })
    assert saved["paper"] == "A5" and len(saved["columns"]) == 6  # hidden/omitted columns are kept, not lost
    out = api.c.get(f"/api/invoices/{inv['id']}/pdf", headers=api.h).content
    txt = text_of(out)
    flat = " ".join(txt.split())
    assert "Qty" not in flat and "Rate" not in flat  # omitted columns stay hidden
    assert "FREIGHT" in flat and "BILL" in flat and "Particulars of service" in flat and "DUPLICATE FOR SUPPLIER" in flat and "Thank you for your business" in flat
    assert "Page 2" in txt  # one page per copy
    assert "SAC" not in txt.split("Particulars of service")[1].split("\n")[0]
    api.put("/api/layouts/lr", {"copies": ["Consignor Copy", "Consignee Copy"], "hide_freight_on_copies": ["Consignee Copy"], "title": "GOODS CONSIGNMENT NOTE"})
    txt = " ".join(text_of(api.c.get(f"/api/lr/{lr['id']}/pdf", headers=api.h).content).split())
    consignor, consignee = txt.split("CONSIGNEE COPY")[0], txt.split("CONSIGNEE COPY")[1]
    assert "GOODS CONSIGNMENT NOTE" in txt and "Total freight" in consignor and "Total freight" not in consignee
    assert "CONSIGNOR COPY" in text_of(api.c.get(f"/api/lr/{lr['id']}/pdf?copy=first", headers=api.h).content)
    # reset restores defaults
    assert api.post("/api/layouts/invoice/reset")["paper"] == "A4"
    api.post("/api/layouts/lr/reset")


def test_preview_and_signature_image(client, api):
    for doc in ("invoice", "lr", "thermal", "report"):
        r = api.c.post(f"/api/layouts/{doc}/preview", headers=api.h, json={"font_size": 9})
        assert r.status_code == 200 and r.content[:4] == b"%PDF", doc
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGBA", (300, 100), (0, 0, 120, 255)).save(buf, "PNG")
    r = client.post("/api/layouts/assets/signature", headers=api.h, files={"file": ("sig.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    assert api.c.get("/api/layouts/assets/signature", headers=api.h).status_code == 200
    assert api.c.post("/api/layouts/invoice/preview", headers=api.h, json={}).content[:4] == b"%PDF"
    assert client.post("/api/layouts/assets/signature", headers=api.h, files={"file": ("x.pdf", b"%PDF-1", "application/pdf")}).status_code == 400
    api.c.delete("/api/layouts/assets/signature", headers=api.h)
    assert api.c.get("/api/layouts/assets/signature", headers=api.h).status_code == 404
