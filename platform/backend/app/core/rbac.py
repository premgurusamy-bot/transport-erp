"""Permission catalogue and default role → permission mapping.

Permissions are checked on every backend request (see deps.require). Roles are stored in the
database (editable by authorised administrators, audited); these are only the seeded defaults.
"""
from __future__ import annotations

PERMISSIONS: dict[str, str] = {
    # platform
    "users.manage": "Create users, assign roles, revoke sessions",
    "settings.read": "View configuration",
    "settings.write": "Change configuration (versioned)",
    "audit.read": "View audit history",
    "integrations.admin": "Configure integration providers",
    "approvals.read": "View approval queue",
    "masters.read": "View master data",
    "masters.write": "Create/edit master data",
    "masters.approve": "Approve sensitive master changes (e.g. bank details)",
    "documents.read": "View documents",
    "documents.write": "Upload documents",
    # commercial
    "crm.read": "View enquiries/leads",
    "crm.write": "Create/edit enquiries/leads",
    "quote.read": "View quotations",
    "quote.write": "Prepare quotations",
    "quote.view_cost": "See internal cost, owner quote and margin",
    "quote.approve_discount": "Approve below-floor pricing",
    "booking.read": "View bookings",
    "booking.write": "Create/modify bookings",
    "booking.cancel": "Cancel bookings",
    "credit.read": "View credit profiles/exposure",
    "credit.write": "Propose credit changes",
    "credit.approve": "Approve credit limits/exceptions",
    # operations
    "fleet.read": "View vehicles, fuel, maintenance",
    "fleet.write": "Edit vehicles, fuel, maintenance, tyres",
    "fleet.release_defect": "Release a vehicle after a critical safety defect",
    "driver.read": "View drivers",
    "driver.write": "Edit drivers",
    "driver.view_sensitive": "View driver bank/identity details",
    "owner.read": "View vehicle owners",
    "owner.write": "Edit vehicle owners/attached vehicles",
    "dispatch.plan": "Allocate vehicles and plan dispatch",
    "dispatch.authorize": "Authorise dispatch",
    "dispatch.override": "Override non-legal allocation warnings with reason",
    "trip.read": "View trips",
    "trip.update": "Record trip events",
    "trip.close": "Close trips",
    "custody.write": "Record custody, scans, POD",
    "gps.view": "View live/last GPS",
    "camera.view": "Request live camera streams",
    "lr.write": "Generate/amend LR and e-way bills",
    "consolidation.plan": "Run PTL consolidation",
    "compliance.read": "View compliance",
    "compliance.write": "Record compliance documents/renewals",
    "compliance.approve_renewal": "Approve compliance renewal expenses (Owner/Director)",
    # supply network
    "vendor.read": "View vendors",
    "vendor.write": "Edit vendors",
    "procurement.write": "Create requests/RFQs/POs",
    "procurement.approve": "Approve procurement",
    "inventory.read": "View inventory",
    "inventory.write": "Stock movements",
    "godown.read": "View godown",
    "godown.write": "Godown operations",
    # finance
    "accounts.read": "View accounts",
    "accounts.post": "Prepare/post vouchers",
    "accounts.approve": "Approve vouchers/expenses",
    "invoice.write": "Generate invoices",
    "payment.prepare": "Prepare payments",
    "payment.approve": "Approve/execute payments",
    "bank.import": "Import bank statements",
    "bank.reconcile": "Confirm bank matches",
    "settlement.prepare": "Prepare driver/owner/vendor settlements",
    "settlement.approve": "Approve settlements",
    "collections.write": "Collections follow-up",
    "cashflow.read": "View cash flow/budget",
    "budget.write": "Prepare budgets",
    "budget.approve": "Approve budgets",
    "tax.read": "View GST/TDS registers",
    "tax.write": "Prepare GST/TDS data",
    # customer care, risk
    "complaint.read": "View complaints",
    "complaint.write": "Handle complaints",
    "incident.read": "View incidents/claims",
    "incident.write": "Record incidents/claims",
    "claim.approve": "Approve claim financial treatment",
    "insurance.read": "View insurance",
    "insurance.write": "Edit insurance",
    "legal.read": "View legal cases (privileged)",
    "legal.write": "Edit legal cases",
    # people & governance
    "hr.read": "View employees",
    "hr.write": "Edit employees/attendance/leave",
    "hr.view_salary": "View salary details",
    "payroll.prepare": "Prepare payroll",
    "payroll.approve": "Approve payroll",
    "remuneration.write": "Propose driver remuneration rules",
    "remuneration.approve": "Approve driver remuneration rules",
    "sop.read": "View SOPs/checklists",
    "sop.write": "Edit SOPs/checklists",
    "sop.approve": "Approve SOPs",
    # intelligence
    "controltower.read": "Operations control tower",
    "reports.read": "View reports",
    "reports.export": "Export reports",
    "ai.use": "Use AI assistants",
    "ai.admin": "Configure AI providers/budgets",
    "marketing.read": "View marketing",
    "marketing.write": "Draft marketing content/campaigns",
    "marketing.approve": "Approve campaigns/content",
    "ca.read": "CA/auditor read of authorised records",
    "sync.write": "Submit offline events",
    # external portals
    "portal.customer": "Customer portal",
    "portal.customer_admin": "Manage own customer users",
    "portal.owner": "Vehicle owner portal",
    "portal.vendor": "Vendor portal",
    "driver.app": "Driver app",
}

ALL = list(PERMISSIONS)


def _p(*prefixes: str, extra: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> list[str]:
    out = [p for p in ALL if any(p.startswith(x) for x in prefixes)]
    out += list(extra)
    return sorted(set(out) - set(exclude))


_READ_ALL = tuple(p for p in ALL if p.endswith(".read"))

DEFAULT_ROLES: dict[str, tuple[str, list[str]]] = {
    "owner_director": ("Owner / Director", [p for p in ALL if not p.startswith(("portal.", "driver.app", "ca."))]),
    "operations_manager": (
        "Operations Manager",
        _p("crm.", "quote.", "booking.", "dispatch.", "trip.", "custody.", "gps.", "camera.", "lr.", "consolidation.",
           "fleet.", "driver.read", "driver.write", "owner.", "compliance.read", "compliance.write", "godown.",
           "vendor.read", "procurement.write", "inventory.", "complaint.", "incident.", "controltower.", "reports.",
           "ai.use", "approvals.read", "masters.", "documents.", "credit.read", "sop.read", "sync.write",
           exclude=("quote.approve_discount", "masters.approve")),
    ),
    "dispatcher": (
        "Dispatcher",
        _p("booking.read", "dispatch.plan", "trip.", "custody.", "gps.view", "lr.write", "consolidation.",
           "fleet.read", "driver.read", "owner.read", "compliance.read", "godown.read", "controltower.",
           "masters.read", "documents.", "ai.use", "quote.read", "crm.read", "sync.write"),
    ),
    "accounts": (
        "Accounts",
        _p("accounts.", "invoice.", "payment.prepare", "bank.", "settlement.prepare", "collections.", "cashflow.",
           "budget.write", "tax.", "credit.read", "credit.write", "masters.read", "documents.", "reports.", "ai.use",
           "approvals.read", "booking.read", "trip.read", "vendor.read", "owner.read", "driver.read", "quote.read",
           "quote.view_cost", "incident.read", "controltower.read", "complaint.read"),
    ),
    "hr": ("HR", _p("hr.", "payroll.prepare", "remuneration.write", "driver.read", "driver.write", "sop.read",
                    "documents.", "masters.read", "reports.read", "ai.use")),
    "customer_support": (
        "Customer Support",
        _p("crm.", "booking.read", "trip.read", "gps.view", "complaint.", "documents.read", "masters.read",
           "quote.read", "ai.use", "controltower.read"),
    ),
    "sales_marketing": (
        "Sales / Marketing",
        _p("crm.", "quote.read", "quote.write", "marketing.read", "marketing.write", "masters.read",
           "booking.read", "reports.read", "ai.use"),
    ),
    "fleet_maintenance": (
        "Fleet / Maintenance",
        _p("fleet.", "driver.read", "compliance.", "vendor.read", "procurement.write", "inventory.",
           "documents.", "masters.read", "trip.read", "ai.use", "reports.read",
           exclude=("compliance.approve_renewal",)),
    ),
    "compliance_coordinator": (
        "Compliance Coordinator",
        _p("compliance.read", "compliance.write", "fleet.read", "driver.read", "owner.read", "insurance.",
           "documents.", "masters.read", "ai.use", "sop.read", "legal.read"),
    ),
    "store_custodian": (
        "Store / Godown Custodian",
        _p("godown.", "inventory.", "custody.write", "trip.read", "booking.read", "documents.", "masters.read"),
    ),
    "system_admin": (
        "System Administrator",
        _p("users.", "settings.", "audit.", "integrations.", "masters.read", "ai.admin", "approvals.read"),
    ),
    "driver": ("Driver", ["driver.app", "sync.write", "ai.use"]),
    "attached_driver": ("Attached Vehicle Driver", ["driver.app", "sync.write"]),
    "customer_admin": ("Customer Admin", ["portal.customer", "portal.customer_admin", "ai.use"]),
    "customer_user": ("Customer User", ["portal.customer", "ai.use"]),
    "vehicle_owner": ("Attached Vehicle Owner", ["portal.owner"]),
    "vendor_user": ("Vendor User", ["portal.vendor"]),
    "ca_auditor": ("CA / External Auditor", ["ca.read"]),
}

# Roles whose users are external (scoped to a single customer / owner / vendor / driver record).
EXTERNAL_ROLES = {"customer_admin", "customer_user", "vehicle_owner", "vendor_user", "attached_driver", "ca_auditor"}
