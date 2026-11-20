"""Customers, vehicles, drivers, vendors, routes, toll plazas, fuel stations."""
from __future__ import annotations

from .base import ActiveMixin, AuditMixin, Base, Boolean, Date, DateTime, F, Integer, Money, Numeric, String, Text

CUSTOMER_CATEGORIES = ["Automobile OEM", "Auto Components", "Industrial", "Textile", "FMCG", "Trader", "Individual", "Other"]
VEHICLE_TYPES = [
    "Trailer (40 ft)", "Trailer (32 ft)", "Container (20 ft)", "Container (32 ft)", "Open Body Truck",
    "Closed Body Truck", "Multi-Axle Truck", "LCV / Tempo", "Car Carrier", "Tipper", "Other",
]


class Customer(AuditMixin, ActiveMixin, Base):
    __tablename__ = "customers"
    code = F(String(20), "Customer code", required=True, unique=True, group="Basic")
    name = F(String(200), "Customer name", required=True, group="Basic")
    legal_name = F(String(200), "Legal name", group="Basic")
    category = F(String(40), "Customer category", options=CUSTOMER_CATEGORIES, group="Basic")
    gstin = F(String(15), "GSTIN", validator="gstin", group="Tax")
    pan = F(String(10), "PAN", validator="pan", group="Tax")
    gst_registration = F(String(20), "GST registration", options=["Registered", "Unregistered", "SEZ", "Government"], default="Registered", group="Tax")
    default_gst_treatment_id = F(Integer, "Default GST treatment", fk="gst_treatments.id", ref="gst_treatments", group="Tax")
    billing_address = F(Text, "Billing address", group="Address")
    billing_city = F(String(80), "Billing city", group="Address")
    billing_state = F(String(60), "Billing state", group="Address")
    billing_state_code = F(String(2), "Billing state code", group="Address")
    billing_pincode = F(String(6), "Billing pincode", validator="pincode", group="Address")
    delivery_address = F(Text, "Delivery address", group="Address")
    contact_person = F(String(120), "Contact person", group="Contact")
    mobile = F(String(15), "Mobile", validator="mobile", group="Contact")
    email = F(String(120), "Email", validator="email", group="Contact")
    whatsapp = F(String(15), "WhatsApp number", validator="mobile", group="Contact")
    payment_terms = F(String(120), "Payment terms", group="Credit")
    credit_limit = F(Money, "Credit limit (₹)", default=0, group="Credit")
    credit_days = F(Integer, "Credit period (days)", default=30, group="Credit")
    contract_start = F(Date, "Contract start", group="Contract")
    contract_end = F(Date, "Contract end", group="Contract")
    rate_agreement_ref = F(String(120), "Rate agreement reference", group="Contract")
    billing_rules = F(Text, "Customer-specific billing rules", group="Contract", help="e.g. bill monthly, attach POD copy, PO number mandatory")
    billing_cycle = F(String(20), "Billing cycle", options=["Per LR", "Per Trip", "Weekly", "Fortnightly", "Monthly"], default="Per Trip", group="Contract")
    po_number = F(String(60), "Customer PO / vendor code", group="Contract")
    ledger_id = F(Integer, "Ledger", fk="ledgers.id", ref="ledgers", readonly=True, group="Basic")
    branch_id = F(Integer, "Branch", fk="branches.id", ref="branches", group="Basic")
    remarks = F(Text, "Remarks", group="Basic")


class Vehicle(AuditMixin, ActiveMixin, Base):
    __tablename__ = "vehicles"
    registration_no = F(String(15), "Registration number", required=True, unique=True, validator="vehicle_no", group="Basic")
    vehicle_type = F(String(40), "Vehicle type", options=VEHICLE_TYPES, required=True, group="Basic")
    make = F(String(60), "Make", group="Basic")
    model = F(String(60), "Model", group="Basic")
    manufacture_year = F(Integer, "Year of manufacture", group="Basic")
    chassis_no = F(String(40), "Chassis number", group="Basic")
    engine_no = F(String(40), "Engine number", group="Basic")
    gvw_kg = F(Numeric(10, 0), "GVW (kg)", group="Capacity")
    tare_kg = F(Numeric(10, 0), "Tare weight (kg)", group="Capacity")
    payload_kg = F(Numeric(10, 0), "Payload capacity (kg)", group="Capacity")
    body_length_ft = F(Numeric(5, 1), "Body length (ft)", group="Capacity")
    fuel_tank_litres = F(Numeric(6, 0), "Fuel tank (litres)", group="Capacity")
    expected_kmpl = F(Numeric(5, 2), "Expected mileage (km/l)", group="Capacity")
    ownership = F(String(20), "Ownership", options=["Owned", "Leased", "Attached"], default="Owned", required=True, group="Ownership")
    owner_name = F(String(120), "Owner name (leased/attached)", group="Ownership")
    owner_vendor_id = F(Integer, "Owner vendor (attached)", fk="vendors.id", ref="vendors", group="Ownership")
    purchase_date = F(Date, "Purchase date", group="Ownership")
    purchase_value = F(Money, "Purchase value (₹)", group="Ownership")
    loan_bank = F(String(120), "Loan financier", group="Loan")
    loan_account = F(String(40), "Loan account no.", group="Loan")
    loan_amount = F(Money, "Loan amount (₹)", group="Loan")
    emi_amount = F(Money, "EMI (₹)", group="Loan")
    emi_day = F(Integer, "EMI due day of month", group="Loan")
    loan_end_date = F(Date, "Loan end date", group="Loan")
    insurance_company = F(String(120), "Insurance company", group="Documents")
    insurance_policy_no = F(String(60), "Insurance policy no.", group="Documents")
    insurance_expiry = F(Date, "Insurance expiry", group="Documents")
    fc_expiry = F(Date, "FC (fitness) expiry", group="Documents")
    national_permit_no = F(String(40), "National permit no.", group="Documents")
    national_permit_expiry = F(Date, "National permit expiry", group="Documents")
    state_permit_no = F(String(40), "State permit no.", group="Documents")
    state_permit_expiry = F(Date, "State permit expiry", group="Documents")
    puc_expiry = F(Date, "Pollution (PUC) expiry", group="Documents")
    road_tax_expiry = F(Date, "Road tax valid till", group="Documents")
    gps_provider = F(String(80), "GPS provider", group="GPS")
    gps_device_id = F(String(60), "GPS device ID / IMEI", group="GPS")
    gps_sim = F(String(20), "GPS SIM number", group="GPS")
    fastag_id = F(String(40), "FASTag ID", group="GPS")
    status = F(String(20), "Status", options=["Available", "On Trip", "Maintenance", "Breakdown", "Inactive", "Sold"], default="Available", group="Basic")
    branch_id = F(Integer, "Home branch", fk="branches.id", ref="branches", group="Basic")
    current_odometer = F(Numeric(10, 0), "Current odometer (km)", default=0, group="Basic")
    remarks = F(Text, "Remarks", group="Basic")


class VehicleEvent(AuditMixin, Base):
    """Purchase, sale, transfer, deactivation, reactivation — permanent history."""

    __tablename__ = "vehicle_events"
    vehicle_id = F(Integer, "Vehicle", fk="vehicles.id", ref="vehicles", required=True)
    event_type = F(String(20), "Event", options=["Purchase", "Sale", "Transfer", "Deactivation", "Reactivation"], required=True)
    event_date = F(Date, "Date", required=True)
    from_branch_id = F(Integer, "From branch", fk="branches.id", ref="branches")
    to_branch_id = F(Integer, "To branch", fk="branches.id", ref="branches")
    amount = F(Money, "Amount (₹)")
    party = F(String(160), "Buyer / seller")
    odometer = F(Numeric(10, 0), "Odometer")
    remarks = F(Text, "Remarks")
    voucher_id = F(Integer, "Voucher", fk="vouchers.id", ref="vouchers", readonly=True)


class Driver(AuditMixin, ActiveMixin, Base):
    __tablename__ = "drivers"
    code = F(String(20), "Driver code", required=True, unique=True, group="Basic")
    name = F(String(120), "Name", required=True, group="Basic")
    father_name = F(String(120), "Father's name", group="Basic")
    dob = F(Date, "Date of birth", group="Basic")
    address = F(Text, "Address", group="Basic")
    mobile = F(String(15), "Mobile", validator="mobile", required=True, group="Basic")
    aadhaar_enc = F(Text, "Aadhaar number", secret=True, group="Restricted", help="Stored encrypted; visible only with 'drivers:aadhaar' permission")
    licence_no = F(String(20), "Driving licence no.", required=True, group="Licence")
    licence_class = F(String(40), "Licence class", options=["LMV", "LMV-TR", "HMV", "HGMV", "HPMV", "HTV", "MGV", "Transport"], group="Licence")
    licence_issue_date = F(Date, "Licence issue date", group="Licence")
    licence_expiry = F(Date, "Licence expiry", required=True, group="Licence")
    hazardous_endorsement = F(Boolean, "Hazardous goods endorsement", default=False, group="Licence")
    emergency_contact_name = F(String(120), "Emergency contact name", group="Basic")
    emergency_contact_phone = F(String(15), "Emergency contact phone", validator="mobile", group="Basic")
    blood_group = F(String(5), "Blood group", group="Basic")
    joining_date = F(Date, "Joining date", group="Employment")
    employment_status = F(String(20), "Employment status", options=["Active", "On Leave", "Suspended", "Resigned", "Terminated"], default="Active", group="Employment")
    employment_type = F(String(20), "Employment type", options=["Permanent", "Contract", "Attached Vehicle"], default="Permanent", group="Employment")
    monthly_salary = F(Money, "Monthly salary (₹)", default=0, group="Pay")
    daily_bata = F(Money, "Daily bata (₹)", default=0, group="Pay")
    food_allowance_per_day = F(Money, "Food allowance per day (₹)", default=0, group="Pay")
    trip_allowance = F(Money, "Trip allowance per trip (₹)", default=0, group="Pay")
    per_km_allowance = F(Numeric(8, 2), "Allowance per km (₹)", default=0, group="Pay")
    pf_applicable = F(Boolean, "EPF applicable", default=False, group="Pay")
    esi_applicable = F(Boolean, "ESI applicable", default=False, group="Pay")
    bank_name = F(String(120), "Bank", group="Pay")
    bank_account_enc = F(Text, "Bank account no.", secret=True, group="Pay")
    ifsc = F(String(11), "IFSC", validator="ifsc", group="Pay")
    status = F(String(20), "Availability", options=["Available", "On Trip", "Off Duty", "On Leave"], default="Available", group="Basic")
    gps_consent = F(Boolean, "GPS tracking consent given", default=False, group="Consent")
    gps_consent_at = F(DateTime(timezone=True), "Consent recorded at", readonly=True, group="Consent")
    branch_id = F(Integer, "Branch", fk="branches.id", ref="branches", group="Basic")
    ledger_id = F(Integer, "Advance ledger", fk="ledgers.id", ref="ledgers", readonly=True, group="Basic")
    remarks = F(Text, "Remarks", group="Basic")


class DriverIncident(AuditMixin, Base):
    __tablename__ = "driver_incidents"
    driver_id = F(Integer, "Driver", fk="drivers.id", ref="drivers", required=True)
    vehicle_id = F(Integer, "Vehicle", fk="vehicles.id", ref="vehicles")
    trip_id = F(Integer, "Trip", fk="trips.id", ref="trips")
    kind = F(String(20), "Type", options=["Accident", "Fine / Challan", "Breakdown", "Theft", "Damage", "Complaint", "Other"], required=True)
    incident_date = F(Date, "Date", required=True)
    location = F(String(200), "Location")
    description = F(Text, "Description", required=True)
    challan_no = F(String(60), "Challan / FIR no.")
    amount = F(Money, "Fine / loss amount (₹)", default=0)
    recover_from_driver = F(Boolean, "Recover from driver", default=False)
    insurance_claim_no = F(String(60), "Insurance claim no.")
    status = F(String(20), "Status", options=["Open", "Under Review", "Closed"], default="Open")
    reported_via = F(String(20), "Reported via", options=["Office", "Driver App"], default="Office")


class Vendor(AuditMixin, ActiveMixin, Base):
    __tablename__ = "vendors"
    code = F(String(20), "Vendor code", required=True, unique=True)
    name = F(String(200), "Vendor name", required=True)
    category = F(String(30), "Category", options=["Diesel / Fuel", "Spare Parts", "Tyres", "Batteries", "Workshop / Repairs", "Vehicle Dealer", "Insurance", "Office", "Vehicle Owner (Attached)", "Transporter", "Other"], required=True)
    gstin = F(String(15), "GSTIN", validator="gstin")
    pan = F(String(10), "PAN", validator="pan")
    address = F(Text, "Address")
    city = F(String(80), "City")
    state = F(String(60), "State")
    state_code = F(String(2), "State code")
    pincode = F(String(6), "Pincode", validator="pincode")
    contact_person = F(String(120), "Contact person")
    mobile = F(String(15), "Mobile", validator="mobile")
    email = F(String(120), "Email", validator="email")
    payment_terms = F(String(120), "Payment terms")
    credit_days = F(Integer, "Credit days", default=0)
    bank_name = F(String(120), "Bank name")
    bank_account_no = F(String(30), "Bank account no.")
    ifsc = F(String(11), "IFSC", validator="ifsc")
    tds_section = F(String(10), "TDS section", options=["", "194C", "194J", "194I", "194Q"])
    ledger_id = F(Integer, "Ledger", fk="ledgers.id", ref="ledgers", readonly=True)


class Route(AuditMixin, ActiveMixin, Base):
    __tablename__ = "routes"
    code = F(String(30), "Route code", required=True, unique=True)
    origin = F(String(120), "Origin", required=True)
    destination = F(String(120), "Destination", required=True)
    via = F(String(200), "Via")
    distance_km = F(Numeric(8, 1), "Estimated distance (km)", required=True)
    est_hours = F(Numeric(6, 1), "Estimated transit (hours)")
    est_toll = F(Money, "Estimated toll (₹)", default=0)
    est_diesel_litres = F(Numeric(8, 1), "Estimated diesel (litres)")
    origin_state_code = F(String(2), "Origin state code")
    destination_state_code = F(String(2), "Destination state code")
    remarks = F(Text, "Remarks")


class TollPlaza(AuditMixin, ActiveMixin, Base):
    __tablename__ = "toll_plazas"
    name = F(String(160), "Toll plaza", required=True, unique=True)
    highway = F(String(40), "Highway")
    location = F(String(160), "Location")
    state = F(String(60), "State")
    rate_lcv = F(Money, "Rate – LCV (₹)")
    rate_truck_2axle = F(Money, "Rate – 2 axle truck (₹)")
    rate_3axle = F(Money, "Rate – 3 axle (₹)")
    rate_multi_axle = F(Money, "Rate – multi-axle (₹)")
    rates_effective_from = F(Date, "Rates effective from")


class RouteToll(AuditMixin, Base):
    __tablename__ = "route_tolls"
    route_id = F(Integer, "Route", fk="routes.id", ref="routes", required=True)
    toll_plaza_id = F(Integer, "Toll plaza", fk="toll_plazas.id", ref="toll_plazas", required=True)
    sequence = F(Integer, "Order", default=1)


class FuelStation(AuditMixin, ActiveMixin, Base):
    __tablename__ = "fuel_stations"
    name = F(String(160), "Fuel station", required=True, unique=True)
    company = F(String(40), "Oil company", options=["IOCL", "BPCL", "HPCL", "Reliance", "Nayara", "Shell", "Own Pump", "Other"])
    location = F(String(160), "Location")
    vendor_id = F(Integer, "Vendor (credit account)", fk="vendors.id", ref="vendors")
    credit_account = F(Boolean, "Credit account", default=False)


class FuelCard(AuditMixin, ActiveMixin, Base):
    __tablename__ = "fuel_cards"
    card_no = F(String(40), "Card number", required=True, unique=True)
    provider = F(String(60), "Provider", required=True)
    vehicle_id = F(Integer, "Vehicle", fk="vehicles.id", ref="vehicles")
    vendor_id = F(Integer, "Vendor", fk="vendors.id", ref="vendors")
    valid_till = F(Date, "Valid till")
    opening_balance = F(Money, "Opening balance (₹)", default=0)
