"""Permission catalogue and default roles.

Permission strings are `<module>:<action>`; `*` grants everything.
"""
from __future__ import annotations

MODULES = {
    "dashboard": "Dashboard",
    "company": "Company master",
    "branches": "Branches & locations",
    "customers": "Customers",
    "vehicles": "Vehicles",
    "drivers": "Drivers",
    "vendors": "Vendors",
    "routes": "Routes & tolls",
    "rates": "Freight rate contracts",
    "bookings": "Bookings",
    "lr": "LR / consignments",
    "trips": "Trips",
    "invoices": "Invoices & GST",
    "accounts": "Accounts",
    "fuel": "Diesel & fuel",
    "maintenance": "Maintenance & tyres",
    "warehouse": "Godown / warehouse",
    "purchase": "Purchase & vendor bills",
    "documents": "Documents",
    "hr": "Employees & attendance",
    "payroll": "Payroll",
    "compliance": "Statutory compliance",
    "reports": "Reports",
    "notifications": "Notifications",
    "settings": "System settings",
    "users": "Users & roles",
    "audit": "Audit trail",
    "backup": "Backup",
}

SPECIAL = {
    "lr:cancel": "Cancel LR",
    "lr:amend": "Amend LR after creation",
    "invoices:cancel": "Cancel invoices / issue credit notes",
    "accounts:cancel": "Cancel (reverse) vouchers",
    "rates:approve": "Activate / revise rate contracts",
    "drivers:aadhaar": "View driver Aadhaar & bank numbers",
    "hr:salary": "View salaries & bank numbers of employees",
    "backup:restore": "Restore database from backup",
    "portal:access": "Customer portal",
    "driver_app:access": "Driver mobile app",
}


def all_permissions() -> dict[str, str]:
    perms: dict[str, str] = {}
    for key, label in MODULES.items():
        perms[f"{key}:read"] = f"{label} – view"
        perms[f"{key}:write"] = f"{label} – create / edit"
    perms.update(SPECIAL)
    return perms


def _rw(*mods: str) -> list[str]:
    out = []
    for m in mods:
        out += [f"{m}:read", f"{m}:write"]
    return out


def _r(*mods: str) -> list[str]:
    return [f"{m}:read" for m in mods]


DEFAULT_ROLES: dict[str, tuple[str, list[str]]] = {
    "Super Admin": ("Full system access including users, settings and restore", ["*"]),
    "Owner": ("Business owner – full access", ["*"]),
    "General Manager": (
        "All operations and finance; no user administration or restore",
        _rw(*[m for m in MODULES if m not in ("users", "backup", "settings")])
        + _r("users", "settings", "backup")
        + ["lr:cancel", "lr:amend", "invoices:cancel", "accounts:cancel", "rates:approve", "hr:salary"],
    ),
    "Accountant": (
        "Billing, accounts, purchase, compliance and payroll",
        _rw("invoices", "accounts", "purchase", "vendors", "compliance", "payroll", "documents")
        + _r("dashboard", "customers", "lr", "trips", "vehicles", "drivers", "reports", "rates", "fuel", "maintenance", "warehouse", "company", "branches")
        + ["invoices:cancel", "accounts:cancel", "reports:write", "customers:write", "hr:salary"],
    ),
    "Transport Manager": (
        "Bookings, LR, trips, fleet allocation and rates",
        _rw("bookings", "lr", "trips", "vehicles", "drivers", "routes", "fuel", "documents", "customers")
        + _r("dashboard", "rates", "reports", "maintenance", "invoices", "branches", "company", "vendors")
        + ["lr:cancel", "lr:amend", "rates:write"],
    ),
    "Dispatch Operator": (
        "Day-to-day bookings, LR and trip updates",
        _rw("bookings", "lr", "trips", "fuel")
        + _r("dashboard", "vehicles", "drivers", "routes", "customers", "documents", "rates", "branches", "company"),
    ),
    "Warehouse Manager": (
        "Godown inward/outward, stock and warehouse billing",
        _rw("warehouse", "documents") + _r("dashboard", "customers", "reports", "lr", "branches", "company"),
    ),
    "Fleet Manager": (
        "Vehicles, maintenance, tyres, fuel and tolls",
        _rw("vehicles", "maintenance", "fuel", "routes", "documents", "drivers")
        + _r("dashboard", "vendors", "trips", "reports", "purchase", "branches", "company")
        + ["purchase:write"],
    ),
    "HR Manager": (
        "Employees, drivers, attendance, leave and payroll",
        _rw("hr", "payroll", "drivers", "documents") + _r("dashboard", "compliance", "branches", "company")
        + ["hr:salary", "drivers:aadhaar"],
    ),
    "Driver": ("Driver mobile app only", ["driver_app:access"]),
    "Customer": ("Customer portal only – sees own data", ["portal:access"]),
}


def has_permission(perms: list[str] | None, needed: str) -> bool:
    if not perms:
        return False
    if "*" in perms or needed in perms:
        return True
    # write implies read
    if needed.endswith(":read") and needed.replace(":read", ":write") in perms:
        return True
    return False
