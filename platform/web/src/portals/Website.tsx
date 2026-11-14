import { useState } from "react";
import { Link } from "react-router-dom";
import { post } from "../api";
import { Btn, ErrorBox, useData } from "../components/ui";
import { get } from "../api";
import { setLang, t, useLang } from "../i18n";

export default function Website() {
  useLang();
  const cov = useData(() => get("/public/coverage"), []);
  const [sent, setSent] = useState<string | null>(null);
  const [err, setErr] = useState<any>(null);
  const [f, setF] = useState<any>({ service_type: "FTL", consent: false });
  const set = (k: string, v: any) => setF((o: any) => ({ ...o, [k]: v }));
  return (
    <div className="site">
      <header className="site-h">
        <div className="brand">{t("app.name")}</div>
        <nav className="row gap"><a href="#services">Services</a><a href="#coverage">Coverage</a><a href="#enquiry">{t("website.enquire")}</a>
          <Link to="/login">Customer login</Link><a onClick={() => setLang("en")}>EN</a><a onClick={() => setLang("ta")}>தமிழ்</a></nav>
      </header>
      <section className="hero">
        <h1>{t("website.hero")}</h1>
        <p>Full Truck Load and shared Part Truck Load transport, with goods custody tracked from pickup to proof of delivery.</p>
        <a href="#enquiry" className="btn btn-primary">{t("website.enquire")}</a>
      </section>
      <section id="services" className="site-sec grid2">
        <div className="card"><h3>FTL - Full Truck Load</h3><p>An exclusive vehicle for your load. No other customer's goods are added. Dedicated LR, trip and proof of delivery.</p></div>
        <div className="card"><h3>PTL - Part Truck Load</h3><p>Pay for the space you use. Your goods share the vehicle with other customers' consignments; each consignment has its own LR, package labels and POD, and your details stay confidential.</p></div>
      </section>
      <section id="coverage" className="site-sec">
        <h2>Verified service coverage</h2>
        <p className="muted small">We list only routes we have verified. Ask us about other destinations.</p>
        <div className="chips">{(cov.data || []).map((c: any) => <span key={c.city} className="chip">{c.city}</span>)}</div>
      </section>
      <section id="enquiry" className="site-sec">
        <h2>{t("website.enquire")}</h2>
        {sent ? <div className="alert alert-green">{sent}</div> : (
          <form className="form card" onSubmit={async (e) => { e.preventDefault(); setErr(null); try { const r = await post("/public/enquiries", f); setSent(`${r.message} Reference: ${r.reference}`); } catch (x) { setErr(x); } }}>
            <ErrorBox error={err} />
            <div className="grid-form">
              <label><span>Your name *</span><input required onChange={(e) => set("name", e.target.value)} /></label>
              <label><span>Company</span><input onChange={(e) => set("company", e.target.value)} /></label>
              <label><span>Mobile *</span><input required type="tel" onChange={(e) => set("phone", e.target.value)} /></label>
              <label><span>Email</span><input type="email" onChange={(e) => set("email", e.target.value || null)} /></label>
              <label><span>Service</span><select value={f.service_type} onChange={(e) => set("service_type", e.target.value)}><option>FTL</option><option>PTL</option></select></label>
              <label><span>Pickup date</span><input type="date" onChange={(e) => set("pickup_date", e.target.value || null)} /></label>
              <label><span>From *</span><input required onChange={(e) => set("origin", e.target.value)} /></label>
              <label><span>To *</span><input required onChange={(e) => set("destination", e.target.value)} /></label>
              <label className="span2"><span>Goods *</span><input required onChange={(e) => set("goods", e.target.value)} /></label>
              <label><span>Approx. weight (kg)</span><input type="number" onChange={(e) => set("weight_kg", e.target.value ? Number(e.target.value) : null)} /></label>
              <input className="hp" tabIndex={-1} autoComplete="off" onChange={(e) => set("website", e.target.value)} aria-hidden="true" />
              <label className="span2 row gap"><input type="checkbox" checked={f.consent} onChange={(e) => set("consent", e.target.checked)} /> I agree to be contacted about this enquiry.</label>
            </div>
            <Btn>Send enquiry</Btn>
          </form>
        )}
      </section>
      <footer className="site-f small muted">© G ROAD LINES · Coimbatore, Tamil Nadu · Genuine customer testimonials will be published only with permission.</footer>
    </div>
  );
}
