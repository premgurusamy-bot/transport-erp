import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ImportPage from "./pages/Import";
import Setup from "./pages/Setup";
import LicencePage from "./pages/Licence";
import { Toasts } from "./components/ui";
import { auth } from "./lib/api";
import { Accounts, Admin, Auth, Billing, Business, Dashboard, Fleet, LR, Masters, Portal, Reports, Trips } from "./pages";

function Protected({ children }: { children: React.ReactElement }) {
  if (!auth.token) return <Navigate to="/login" replace />;
  const u = auth.user;
  if (u?.must_change_password && !location.pathname.startsWith("/profile")) return <Navigate to="/profile?first=1" replace />;
  return children;
}

function StaffOnly({ children }: { children: React.ReactElement }) {
  const u = auth.user;
  if (u?.customer_id && u.permissions.includes("portal:access")) return <Navigate to="/portal" replace />;
  if (u?.driver_id && u.permissions.includes("driver_app:access")) return <Navigate to="/driver" replace />;
  return children;
}

export default function App() {
  return <>
    <Routes>
      <Route path="/login" element={<Auth.Login />} />
      <Route path="/setup" element={<Setup />} />
      <Route path="/portal" element={<Protected><Portal.CustomerPortal /></Protected>} />
      <Route path="/driver" element={<Protected><Portal.DriverApp /></Protected>} />
      <Route element={<Protected><StaffOnly><Layout /></StaffOnly></Protected>}>
        <Route path="/" element={<Dashboard.default />} />
        <Route path="/bookings" element={<Masters.Bookings />} />
        <Route path="/trips" element={<Trips.default />} />
        <Route path="/fleet-board" element={<Trips.FleetBoard />} />
        <Route path="/lr" element={<LR.default />} />
        <Route path="/eway-bills" element={<Masters.EwayBills />} />
        <Route path="/complaints" element={<Masters.Complaints />} />
        <Route path="/customers" element={<Masters.Customers />} />
        <Route path="/vehicles" element={<Masters.Vehicles />} />
        <Route path="/drivers" element={<Masters.Drivers />} />
        <Route path="/vendors" element={<Masters.Vendors />} />
        <Route path="/routes" element={<Masters.RoutesPage />} />
        <Route path="/rates" element={<Masters.Rates />} />
        <Route path="/invoices" element={<Billing.default />} />
        <Route path="/receipts" element={<Billing.Receipts />} />
        <Route path="/vouchers" element={<Accounts.Vouchers />} />
        <Route path="/ledgers" element={<Accounts.Ledgers />} />
        <Route path="/bank" element={<Accounts.BankReco />} />
        <Route path="/tally" element={<Accounts.Tally />} />
        <Route path="/accounts" element={<Accounts.AccountsHome />} />
        <Route path="/vendor-payments" element={<Accounts.VendorPayments />} />
        <Route path="/import" element={<ImportPage />} />
        <Route path="/fuel" element={<Fleet.Fuel />} />
        <Route path="/maintenance" element={<Fleet.Maintenance />} />
        <Route path="/tyres" element={<Fleet.Tyres />} />
        <Route path="/tolls" element={<Fleet.Tolls />} />
        <Route path="/driver-ops" element={<Fleet.DriverOps />} />
        <Route path="/warehouse" element={<Business.Warehouse />} />
        <Route path="/warehouse-masters" element={<Business.WarehouseMasters />} />
        <Route path="/purchase" element={<Business.Purchase />} />
        <Route path="/employees" element={<Business.Employees />} />
        <Route path="/attendance" element={<Business.Attendance />} />
        <Route path="/payroll" element={<Business.Payroll />} />
        <Route path="/compliance" element={<Business.Compliance />} />
        <Route path="/documents" element={<Business.Documents />} />
        <Route path="/reports" element={<Reports.default />} />
        <Route path="/company" element={<Admin.Company />} />
        <Route path="/settings" element={<Admin.Settings />} />
        <Route path="/users" element={<Admin.Users />} />
        <Route path="/audit" element={<Admin.Audit />} />
        <Route path="/backup" element={<Admin.Backup />} />
        <Route path="/licence" element={<LicencePage />} />
      </Route>
      <Route path="/profile" element={<Protected><div className="solo"><Auth.Profile /></div></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    <Toasts />
  </>;
}
