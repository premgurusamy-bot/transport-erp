import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Btn } from "../components/ui";
import { setLang, t, useLang } from "../i18n";
import Admin from "./Admin";
import AiPage from "./AiPage";
import Approvals from "./Approvals";
import { Bookings, Enquiries, Quotations } from "./Commercial";
import ControlTower from "./ControlTower";
import Finance from "./Finance";
import Fleet from "./Fleet";
import Marketing from "./Marketing";
import { DispatchBoard, TripDetail, Trips } from "./Operations";
import People from "./People";
import Risk from "./Risk";
import Supply from "./Supply";

const NAV: { to: string; key: string; any: string[] }[] = [
  { to: "", key: "nav.controlTower", any: ["controltower.read"] },
  { to: "approvals", key: "nav.approvals", any: ["approvals.read", "quote.approve_discount", "payment.approve", "credit.approve", "settlement.approve", "accounts.approve"] },
  { to: "enquiries", key: "nav.enquiries", any: ["crm.read"] },
  { to: "quotations", key: "nav.quotations", any: ["quote.read"] },
  { to: "bookings", key: "nav.bookings", any: ["booking.read"] },
  { to: "dispatch", key: "nav.dispatch", any: ["dispatch.plan"] },
  { to: "trips", key: "nav.trips", any: ["trip.read"] },
  { to: "fleet", key: "nav.fleet", any: ["fleet.read", "driver.read", "compliance.read", "owner.read"] },
  { to: "supply", key: "nav.supply", any: ["vendor.read", "inventory.read", "godown.read", "procurement.write"] },
  { to: "finance", key: "nav.finance", any: ["accounts.read", "ca.read", "cashflow.read", "reports.read"] },
  { to: "risk", key: "nav.risk", any: ["complaint.read", "incident.read", "insurance.read", "legal.read"] },
  { to: "people", key: "nav.people", any: ["hr.read", "sop.read", "payroll.prepare"] },
  { to: "marketing", key: "nav.marketing", any: ["marketing.read"] },
  { to: "ai", key: "nav.ai", any: ["ai.use", "ai.admin"] },
  { to: "admin", key: "nav.admin", any: ["users.manage", "settings.read", "audit.read", "masters.read"] },
];

export default function ErpApp() {
  useLang();
  const { me, can, logout } = useAuth();
  const nav = useNavigate();
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">{t("app.name")}</div>
        <nav>
          {NAV.filter((n) => n.any.some(can)).map((n) => (
            <NavLink key={n.to} to={`/erp/${n.to}`} end={n.to === ""}>{t(n.key)}</NavLink>
          ))}
        </nav>
        <div className="side-foot">
          <div className="small">{me?.name}</div>
          <div className="small muted">{me?.roles.join(", ")}</div>
          <div className="row gap small"><a onClick={() => setLang("en")}>EN</a><a onClick={() => setLang("ta")}>தமிழ்</a></div>
          <Btn kind="ghost" onClick={() => { logout(); nav("/login"); }}>{t("action.signOut")}</Btn>
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route index element={<ControlTower />} />
          <Route path="approvals" element={<Approvals />} />
          <Route path="enquiries" element={<Enquiries />} />
          <Route path="quotations" element={<Quotations />} />
          <Route path="bookings/*" element={<Bookings />} />
          <Route path="dispatch" element={<DispatchBoard />} />
          <Route path="trips" element={<Trips />} />
          <Route path="trips/:id" element={<TripDetail />} />
          <Route path="fleet/*" element={<Fleet />} />
          <Route path="supply/*" element={<Supply />} />
          <Route path="finance/*" element={<Finance />} />
          <Route path="risk/*" element={<Risk />} />
          <Route path="people/*" element={<People />} />
          <Route path="marketing/*" element={<Marketing />} />
          <Route path="ai" element={<AiPage />} />
          <Route path="admin/*" element={<Admin />} />
        </Routes>
      </main>
    </div>
  );
}

export function SubNav({ items }: { items: { to: string; label: string; show?: boolean }[] }) {
  return (
    <div className="subnav">
      {items.filter((i) => i.show !== false).map((i) => <NavLink key={i.to} to={i.to} end>{i.label}</NavLink>)}
    </div>
  );
}
