"""Documents, HR & payroll, statutory compliance."""
from __future__ import annotations

from sqlalchemy import UniqueConstraint

from .base import JSON, ActiveMixin, AuditMixin, Base, Boolean, Column, Date, DateTime, F, Integer, Money, Numeric, String, Text

DOC_TYPES = [
    "GST Certificate", "PAN", "RC Book", "Insurance", "Fitness Certificate", "National Permit", "State Permit",
    "Pollution Certificate", "Road Tax", "Driving Licence", "Aadhaar", "Customer Agreement", "Vendor Agreement",
    "LR", "POD", "Invoice", "E-way Bill", "Purchase Bill", "Receipt", "Photo", "Employee Document", "Statutory Return",
    "Other",
]


class Document(AuditMixin, Base):
    __tablename__ = "documents"
    title = F(String(200), "Title", required=True)
    doc_type = F(String(40), "Document type", options=DOC_TYPES, required=True)
    entity_type = F(String(30), "Linked to", options=["company", "vehicle", "driver", "customer", "vendor", "employee", "consignment", "trip", "invoice", "vendor_bill", "compliance", "other"])
    entity_id = F(Integer, "Linked record id")
    doc_number = F(String(80), "Document number")
    issue_date = F(Date, "Issue date")
    expiry_date = F(Date, "Expiry date")
    tags = F(String(200), "Tags")
    access_roles = Column(JSON, default=list, info={"label": "Restricted to roles (blank = all with document access)"})
    current_version = Column(Integer, default=0, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, nullable=False, index=True)
    version = Column(Integer, nullable=False)
    file_name = Column(String(260), nullable=False)
    stored_name = Column(String(120), nullable=False)
    mime = Column(String(100))
    size_bytes = Column(Integer)
    sha256 = Column(String(64))
    uploaded_by = Column(Integer)
    uploaded_at = Column(DateTime(timezone=True))
    note = Column(String(200))


class Department(AuditMixin, ActiveMixin, Base):
    __tablename__ = "departments"
    name = F(String(80), "Department", required=True, unique=True)


class Employee(AuditMixin, ActiveMixin, Base):
    __tablename__ = "employees"
    code = F(String(20), "Employee code", required=True, unique=True, group="Basic")
    name = F(String(120), "Name", required=True, group="Basic")
    department_id = F(Integer, "Department", fk="departments.id", ref="departments", group="Basic")
    designation = F(String(80), "Designation", group="Basic")
    branch_id = F(Integer, "Branch", fk="branches.id", ref="branches", group="Basic")
    mobile = F(String(15), "Mobile", validator="mobile", group="Basic")
    email = F(String(120), "Email", validator="email", group="Basic")
    address = F(Text, "Address", group="Basic")
    dob = F(Date, "Date of birth", group="Basic")
    gender = F(String(10), "Gender", options=["", "Male", "Female", "Other"], group="Basic")
    joining_date = F(Date, "Joining date", required=True, group="Employment")
    status = F(String(15), "Status", options=["Active", "Notice Period", "Resigned", "Terminated", "Retired"], default="Active", group="Employment")
    basic = F(Money, "Basic + DA per month (₹)", default=0, group="Salary")
    hra = F(Money, "HRA (₹)", default=0, group="Salary")
    other_allowances = F(Money, "Other allowances (₹)", default=0, group="Salary")
    pf_applicable = F(Boolean, "EPF applicable", default=False, group="Statutory")
    esi_applicable = F(Boolean, "ESI applicable", default=False, group="Statutory")
    pt_applicable = F(Boolean, "Professional tax applicable", default=True, group="Statutory")
    uan = F(String(12), "UAN", group="Statutory")
    esic_no = F(String(17), "ESIC IP no.", group="Statutory")
    pan = F(String(10), "PAN", validator="pan", group="Statutory")
    monthly_tds = F(Money, "Monthly TDS (₹)", default=0, group="Statutory")
    bank_name = F(String(120), "Bank", group="Salary")
    bank_account_enc = F(Text, "Bank account no.", secret=True, group="Salary")
    ifsc = F(String(11), "IFSC", validator="ifsc", group="Salary")
    resignation_date = F(Date, "Resignation date", group="Exit")
    last_working_day = F(Date, "Last working day", group="Exit")
    exit_reason = F(Text, "Exit reason", group="Exit")
    exit_settlement_amount = F(Money, "Full & final settlement (₹)", group="Exit")
    exit_settled_on = F(Date, "F&F settled on", group="Exit")


class Attendance(AuditMixin, Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("person_type", "person_id", "att_date", name="uq_attendance_person_date"),)
    person_type = Column(String(10), nullable=False)  # employee / driver
    person_id = Column(Integer, nullable=False, index=True)
    att_date = Column(Date, nullable=False, index=True)
    status = Column(String(12), nullable=False)  # Present / Absent / Half Day / Leave / On Trip / Week Off / Holiday
    in_time = Column(String(5))
    out_time = Column(String(5))
    overtime_hours = Column(Numeric(5, 2), default=0)
    remarks = Column(String(200))


class LeaveType(AuditMixin, ActiveMixin, Base):
    __tablename__ = "leave_types"
    name = F(String(40), "Leave type", required=True, unique=True)
    days_per_year = F(Numeric(5, 1), "Days per year", default=0)
    paid = F(Boolean, "Paid leave", default=True)


class LeaveRequest(AuditMixin, Base):
    __tablename__ = "leave_requests"
    person_type = F(String(10), "Person type", options=["employee", "driver"], required=True)
    person_id = F(Integer, "Person id", required=True)
    leave_type_id = F(Integer, "Leave type", fk="leave_types.id", ref="leave_types", required=True)
    from_date = F(Date, "From", required=True)
    to_date = F(Date, "To", required=True)
    days = F(Numeric(5, 1), "Days", required=True)
    reason = F(Text, "Reason")
    status = F(String(12), "Status", options=["Pending", "Approved", "Rejected", "Cancelled"], default="Pending")
    decided_by = F(Integer, "Decided by", readonly=True)


class SalaryAdvance(AuditMixin, Base):
    __tablename__ = "salary_advances"
    employee_id = F(Integer, "Employee", fk="employees.id", ref="employees", required=True)
    advance_date = F(Date, "Date", required=True)
    amount = F(Money, "Amount (₹)", required=True)
    monthly_recovery = F(Money, "Recover per month (₹)", required=True)
    recovered = F(Money, "Recovered so far (₹)", default=0, readonly=True)
    mode = F(String(10), "Paid by", options=["Cash", "Bank"], default="Cash")
    voucher_id = F(Integer, "Voucher", readonly=True)


class PayrollRun(AuditMixin, Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (UniqueConstraint("month", name="uq_payroll_month"),)
    month = Column(String(7), nullable=False)  # YYYY-MM
    status = Column(String(12), default="Draft", nullable=False)  # Draft / Posted
    total_gross = Column(Money, default=0)
    total_deductions = Column(Money, default=0)
    total_net = Column(Money, default=0)
    employer_pf = Column(Money, default=0)
    employer_esi = Column(Money, default=0)
    voucher_id = Column(Integer)
    config_snapshot = Column(JSON)


class Payslip(Base):
    __tablename__ = "payslips"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, nullable=False, index=True)
    person_type = Column(String(10), nullable=False)
    person_id = Column(Integer, nullable=False)
    name = Column(String(120))
    days_in_month = Column(Numeric(4, 1))
    paid_days = Column(Numeric(4, 1))
    basic = Column(Money, default=0)
    hra = Column(Money, default=0)
    allowances = Column(Money, default=0)
    gross = Column(Money, default=0)
    pf_employee = Column(Money, default=0)
    esi_employee = Column(Money, default=0)
    professional_tax = Column(Money, default=0)
    tds = Column(Money, default=0)
    advance_recovery = Column(Money, default=0)
    other_deductions = Column(Money, default=0)
    net_pay = Column(Money, default=0)
    pf_employer = Column(Money, default=0)
    esi_employer = Column(Money, default=0)
    details = Column(JSON)


class ComplianceRule(AuditMixin, ActiveMixin, Base):
    __tablename__ = "compliance_rules"
    code = F(String(30), "Code", required=True, unique=True)
    name = F(String(160), "Requirement", required=True)
    category = F(String(30), "Category", options=["GST", "TDS", "Income Tax", "EPF", "ESI", "Professional Tax", "Labour", "Transport", "Company Law", "Other"], required=True)
    frequency = F(String(12), "Frequency", options=["Monthly", "Quarterly", "Half-Yearly", "Annual"], required=True)
    due_day = F(Integer, "Due day", required=True)
    due_month_offset = F(Integer, "Months after period end", default=1, help="0 = same month as period end")
    applicable = F(Boolean, "Applicable to this business", default=True)
    authority = F(String(120), "Authority / portal")
    description = F(Text, "Notes")
    verify_note = F(Text, "Verification note")


class ComplianceTask(AuditMixin, Base):
    __tablename__ = "compliance_tasks"
    __table_args__ = (UniqueConstraint("rule_id", "period", name="uq_compliance_rule_period"),)
    rule_id = Column(Integer, nullable=False)
    period = Column(String(10), nullable=False)  # 2026-04 / 2026-Q1 / 2026-H1 / FY2026-27
    due_date = Column(Date, nullable=False, index=True)
    status = Column(String(20), default="Pending", nullable=False)  # Pending / In Preparation / Filed - Awaiting Ack / Acknowledged / Not Applicable
    arn = Column(String(60))
    filed_on = Column(Date)
    confirmed_by = Column(Integer)
    confirmed_at = Column(DateTime(timezone=True))
    amount_paid = Column(Money)
    challan_no = Column(String(60))
    document_id = Column(Integer)
    remarks = Column(Text)


class StatutoryRegister(AuditMixin, ActiveMixin, Base):
    __tablename__ = "statutory_registers"
    name = F(String(160), "Register", required=True, unique=True)
    act = F(String(160), "Act / rule")
    description = F(Text, "Description")
    columns = Column(JSON, default=list, info={"label": "Columns"})


class RegisterEntry(AuditMixin, Base):
    __tablename__ = "register_entries"
    register_id = Column(Integer, nullable=False, index=True)
    entry_date = Column(Date, nullable=False)
    data = Column(JSON, default=dict)
