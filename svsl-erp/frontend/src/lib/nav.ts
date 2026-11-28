// Main menu: groups, screens, permissions and icons.
export type NavItem = { to: string; label: string; perm?: string; icon: string };
export const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Operations", items: [
    { to: "/", label: "Dashboard", perm: "dashboard:read", icon: "dashboard" },
    { to: "/bookings", label: "Bookings", perm: "bookings:read", icon: "calendar" },
    { to: "/trips", label: "Trips", perm: "trips:read", icon: "route" },
    { to: "/lr", label: "LR / Consignments", perm: "lr:read", icon: "file" },
    { to: "/fleet-board", label: "Fleet board", perm: "trips:read", icon: "truck" },
    { to: "/eway-bills", label: "E-way bills", perm: "lr:read", icon: "barcode" },
    { to: "/complaints", label: "Complaints", perm: "customers:read", icon: "message" },
  ] },
  { group: "Masters", items: [
    { to: "/customers", label: "Customers", perm: "customers:read", icon: "users" },
    { to: "/vehicles", label: "Vehicles", perm: "vehicles:read", icon: "truck" },
    { to: "/drivers", label: "Drivers", perm: "drivers:read", icon: "user" },
    { to: "/vendors", label: "Vendors", perm: "vendors:read", icon: "briefcase" },
    { to: "/routes", label: "Routes", perm: "routes:read", icon: "pin" },
    { to: "/rates", label: "Rate contracts", perm: "rates:read", icon: "rupee" },
  ] },
  { group: "Billing", items: [
    { to: "/invoices", label: "Invoices & notes", perm: "invoices:read", icon: "file" },
  ] },
  { group: "Accounts", items: [
    { to: "/accounts", label: "Accounts home", perm: "accounts:read", icon: "wallet" },
    { to: "/receipts", label: "Receipts", perm: "accounts:write", icon: "rupee" },
    { to: "/vendor-payments", label: "Payments", perm: "accounts:write", icon: "bank" },
    { to: "/vouchers", label: "Vouchers", perm: "accounts:read", icon: "book" },
    { to: "/ledgers", label: "Groups & ledgers", perm: "accounts:read", icon: "book" },
    { to: "/bank", label: "Bank reconciliation", perm: "accounts:read", icon: "bank" },
    { to: "/reports?r=trial_balance", label: "Financial statements", perm: "accounts:read", icon: "chart" },
    { to: "/reports?r=customer_outstanding", label: "Outstanding & ageing", perm: "accounts:read", icon: "clock" },
    { to: "/reports?r=gst_summary", label: "GST reports", perm: "invoices:read", icon: "pie" },
    { to: "/tally", label: "Tally export / import", perm: "accounts:read", icon: "upload" },
  ] },
  { group: "Fleet", items: [
    { to: "/fuel", label: "Diesel & fuel", perm: "fuel:read", icon: "fuel" },
    { to: "/maintenance", label: "Maintenance", perm: "maintenance:read", icon: "wrench" },
    { to: "/tyres", label: "Tyres", perm: "maintenance:read", icon: "tyre" },
    { to: "/tolls", label: "Tolls & FASTag", perm: "routes:read", icon: "toll" },
    { to: "/driver-ops", label: "Driver advances & settlement", perm: "drivers:read", icon: "wallet" },
  ] },
  { group: "Warehouse", items: [
    { to: "/warehouse", label: "Stock", perm: "warehouse:read", icon: "warehouse" },
    { to: "/warehouse-masters", label: "Godowns & items", perm: "warehouse:read", icon: "box" },
  ] },
  { group: "Purchase", items: [
    { to: "/purchase", label: "Vendor bills", perm: "purchase:read", icon: "cart" },
  ] },
  { group: "HR", items: [
    { to: "/employees", label: "Employees", perm: "hr:read", icon: "users" },
    { to: "/attendance", label: "Attendance", perm: "hr:read", icon: "calendar" },
    { to: "/payroll", label: "Payroll", perm: "payroll:read", icon: "rupee" },
  ] },
  { group: "Compliance", items: [
    { to: "/compliance", label: "Compliance", perm: "compliance:read", icon: "shield" },
    { to: "/documents", label: "Documents", perm: "documents:read", icon: "file" },
  ] },
  { group: "Reports", items: [{ to: "/reports", label: "Reports", perm: "reports:read", icon: "chart" }] },
  { group: "Admin", items: [
    { to: "/company", label: "Company", perm: "company:read", icon: "building" },
    { to: "/settings", label: "Settings", perm: "settings:read", icon: "settings" },
    { to: "/users", label: "Users", perm: "users:read", icon: "user" },
    { to: "/import", label: "Import from Excel", icon: "upload" },
    { to: "/audit", label: "Audit trail", perm: "audit:read", icon: "history" },
    { to: "/backup", label: "Backup", perm: "backup:read", icon: "save" },
    { to: "/licence", label: "Licence", perm: "settings:read", icon: "key" },
  ] },
];

/** Menu group of the current screen (for the breadcrumb above page titles). */
export function groupOf(path: string, search = ""): string | null {
  for (const g of NAV) for (const i of g.items) {
    const [p, q] = i.to.split("?");
    if (p === path && (!q || search.includes(q))) return g.group;
  }
  for (const g of NAV) for (const i of g.items) if (i.to.split("?")[0] === path) return g.group;
  return null;
}

/** Menu icon of the current screen. */
export function iconOf(path: string): string | null {
  for (const g of NAV) for (const i of g.items) if (i.to.split("?")[0] === path) return i.icon;
  return null;
}
