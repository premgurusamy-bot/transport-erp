import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, homeFor, useAuth } from "./auth";
import { Toaster } from "./components/ui";
import "./styles.css";
import ErpApp from "./pages/ErpApp";
import Login from "./pages/Login";
import Website from "./portals/Website";
import CustomerPortal from "./portals/CustomerPortal";
import OwnerPortal from "./portals/OwnerPortal";
import VendorPortal from "./portals/VendorPortal";
import DriverApp from "./portals/DriverApp";

function Guard({ children, need }: { children: React.ReactNode; need: (p: string[]) => boolean }) {
  const { me, ready } = useAuth();
  if (!ready) return <p className="center muted">Loading…</p>;
  if (!me) return <Navigate to="/login" replace />;
  if (!need(me.permissions)) return <Navigate to={homeFor(me)} replace />;
  return <>{children}</>;
}

const internal = (p: string[]) => p.some((x) => !x.startsWith("portal.") && !["driver.app", "sync.write", "ai.use", "ca.read"].includes(x)) || p.includes("ca.read");

function App() {
  return (
    <Routes>
      <Route path="/" element={<Website />} />
      <Route path="/login" element={<Login />} />
      <Route path="/erp/*" element={<Guard need={internal}><ErpApp /></Guard>} />
      <Route path="/portal/customer/*" element={<Guard need={(p) => p.includes("portal.customer")}><CustomerPortal /></Guard>} />
      <Route path="/portal/owner/*" element={<Guard need={(p) => p.includes("portal.owner")}><OwnerPortal /></Guard>} />
      <Route path="/portal/vendor/*" element={<Guard need={(p) => p.includes("portal.vendor")}><VendorPortal /></Guard>} />
      <Route path="/driver/*" element={<Guard need={(p) => p.includes("driver.app")}><DriverApp /></Guard>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("/sw.js").catch(() => {});

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
        <Toaster />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
