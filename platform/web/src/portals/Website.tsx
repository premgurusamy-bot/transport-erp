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
        <nav className="row gap"><a href="#services">{t("website.services")}</a><a href="#coverage">{t("website.coverage")}</a><a href="#enquiry">{t("website.enquire")}</a>
          <Link to="/login">{t("website.login")}</Link><a onClick={() => setLang("en")}>EN</a><a onClick={() => setLang("ta")}>தமிழ்</a></nav>
      </header>
      <section className="hero">
        <h1>{t("website.hero")}</h1>
        <p>{t("website.sub")}</p>
        <a href="#enquiry" className="btn btn-primary">{t("website.enquire")}</a>
      </section>
      <section id="services" className="site-sec grid2">
        <div className="card"><h3>{t("website.ftlTitle")}</h3><p>{t("website.ftl")}</p></div>
        <div className="card"><h3>{t("website.ptlTitle")}</h3><p>{t("website.ptl")}</p></div>
      </section>
      <section id="coverage" className="site-sec">
        <h2>{t("website.coverageTitle")}</h2>
        <p className="muted small">{t("website.coverageNote")}</p>
        <div className="chips">{(cov.data || []).map((c: any) => <span key={c.city} className="chip">{c.city}</span>)}</div>
      </section>
      <section id="enquiry" className="site-sec">
        <h2>{t("website.enquire")}</h2>
        {sent ? <div className="alert alert-green">{sent}</div> : (
          <form className="form card" onSubmit={async (e) => { e.preventDefault(); setErr(null); try { const r = await post("/public/enquiries", f); setSent(`${r.message} Reference: ${r.reference}`); } catch (x) { setErr(x); } }}>
            <ErrorBox error={err} />
            <div className="grid-form">
              <label><span>{t("f.name")} *</span><input required onChange={(e) => set("name", e.target.value)} /></label>
              <label><span>{t("f.company")}</span><input onChange={(e) => set("company", e.target.value)} /></label>
              <label><span>{t("f.mobile")} *</span><input required type="tel" onChange={(e) => set("phone", e.target.value)} /></label>
              <label><span>{t("f.email")}</span><input type="email" onChange={(e) => set("email", e.target.value || null)} /></label>
              <label><span>{t("f.service")}</span><select value={f.service_type} onChange={(e) => set("service_type", e.target.value)}><option>FTL</option><option>PTL</option></select></label>
              <label><span>{t("f.pickupDate")}</span><input type="date" onChange={(e) => set("pickup_date", e.target.value || null)} /></label>
              <label><span>{t("f.from")} *</span><input required onChange={(e) => set("origin", e.target.value)} /></label>
              <label><span>{t("f.to")} *</span><input required onChange={(e) => set("destination", e.target.value)} /></label>
              <label className="span2"><span>{t("f.goods")} *</span><input required onChange={(e) => set("goods", e.target.value)} /></label>
              <label><span>{t("f.weight")}</span><input type="number" onChange={(e) => set("weight_kg", e.target.value ? Number(e.target.value) : null)} /></label>
              <input className="hp" tabIndex={-1} autoComplete="off" onChange={(e) => set("website", e.target.value)} aria-hidden="true" />
              <label className="span2 row gap"><input type="checkbox" checked={f.consent} onChange={(e) => set("consent", e.target.checked)} /> {t("website.consent")}</label>
            </div>
            <Btn>{t("website.send")}</Btn>
          </form>
        )}
      </section>
      <footer className="site-f small muted">© G ROAD LINES · Coimbatore, Tamil Nadu · Genuine customer testimonials will be published only with permission.</footer>
    </div>
  );
}
