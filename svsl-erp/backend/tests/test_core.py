from datetime import date
from decimal import Decimal

from app.core.money import amount_in_words, inr
from app.core.numbering import financial_year, fy_bounds, next_number
from app.core.validators import gstin_check_digit, validate, validate_gstin
from app.db import SessionLocal
from app.services import gst


def test_gstin_checksum():
    body = "33ABCDE1234F1Z"
    good = body + gstin_check_digit(body)
    assert validate_gstin(good) is None
    bad = body + ("0" if good[-1] != "0" else "1")
    assert "check digit" in validate_gstin(bad)
    assert validate_gstin("99XXXXX") is not None
    assert "state code" in validate_gstin("00ABCDE1234F1Z" + gstin_check_digit("00ABCDE1234F1Z"))


def test_other_validators():
    assert validate("pan", "ABCDE1234F") is None
    assert validate("pan", "ABCD1234F") is not None
    assert validate("ifsc", "SBIN0001234") is None
    assert validate("mobile", "9876543210") is None
    assert validate("mobile", "1234567890") is not None
    assert validate("vehicle_no", "TN38BX1234") is None
    assert validate("vehicle_no", "22BH1234AA") is None
    assert validate("ewb", "123456789012") is None


def test_indian_formats():
    assert inr(Decimal("1234567.5")) == "₹ 12,34,567.50"
    assert inr(999, symbol=False) == "999.00"
    assert amount_in_words(Decimal("12500.50")) == "Rupees Twelve Thousand Five Hundred and Fifty Paise Only"
    assert amount_in_words(10000000) == "Rupees One Crore Only"


def test_financial_year():
    assert financial_year(date(2026, 3, 31)) == "2025-26"
    assert financial_year(date(2026, 4, 1)) == "2026-27"
    assert fy_bounds("2026-27") == (date(2026, 4, 1), date(2027, 3, 31))


def test_numbering_sequential_and_unique():
    db = SessionLocal()
    nums = [next_number(db, "TESTDOC", date(2026, 5, 1)) for _ in range(5)]
    db.commit()
    assert len(set(nums)) == 5
    assert nums[0].endswith("00001") and nums[-1].endswith("00005")
    assert next_number(db, "TESTDOC", date(2027, 5, 1)).endswith("2027-28/00001")  # new FY restarts
    db.rollback()
    db.close()


def test_gst_compute_intra_inter_rcm():
    intra = gst.compute(10000, 5, "FCM", "33", "33")
    assert intra["cgst"] == Decimal("250.00") and intra["sgst"] == Decimal("250.00") and intra["igst"] == 0
    inter = gst.compute(10000, 18, "FCM", "33", "29")
    assert inter["igst"] == Decimal("1800.00") and inter["cgst"] == 0
    rcm = gst.compute(10000, 5, "RCM", "33", "33")
    assert rcm["rcm_tax"] == Decimal("500.00") and rcm["cgst"] == 0 and rcm["igst"] == 0
    ex = gst.compute(10000, 0, "EXEMPT", "33", "29")
    assert ex["igst"] == 0
    assert gst.place_of_supply("29ABCDE1234F1Z5", "33", "33") == "29"
    assert gst.place_of_supply(None, "29", "33") == "33"
