// Accessibility audit with axe-core (WCAG 2.1 A/AA rules) on key screens. Fails on serious/critical violations.
const { chromium } = require('playwright');
const path = require('path');
const BASE = process.env.GRL_WEB || 'http://localhost:5173';
const AXE = path.join(__dirname, '..', 'node_modules', 'axe-core', 'axe.min.js');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 860 } });
  const results = [];
  const audit = async (name) => {
    await p.waitForTimeout(600);
    await p.addScriptTag({ path: AXE });
    const r = await p.evaluate(async () => (await window.axe.run(document, { runOnly: ['wcag2a', 'wcag2aa'] })).violations
      .map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length, help: v.help, sample: v.nodes[0]?.target?.join(' ') })));
    results.push({ name, violations: r });
  };
  await p.goto(BASE + '/'); await audit('website');
  await p.goto(BASE + '/login'); await audit('login');
  await p.fill('input[autocomplete=username]', 'owner@groadlines.local');
  await p.fill('input[type=password]', process.env.GRL_OWNER_PW || 'Owner@12345');
  await p.click('button:has-text("Sign in")'); await p.waitForURL('**/erp');
  for (const pg of ['', 'approvals', 'bookings', 'dispatch', 'trips', 'fleet', 'finance', 'finance/bank', 'admin/settings']) { await p.goto(BASE + '/erp/' + pg); await audit('erp/' + pg); }
  await p.evaluate(() => sessionStorage.clear());
  await p.goto(BASE + '/login');
  await p.fill('input[autocomplete=username]', 'customer1@demo.local'); await p.fill('input[type=password]', 'Demo@12345');
  await p.click('button:has-text("Sign in")'); await p.waitForURL('**/portal/customer'); await audit('portal/customer');
  let bad = 0;
  for (const r of results) {
    const serious = r.violations.filter(v => ['serious', 'critical'].includes(v.impact));
    bad += serious.length;
    console.log(`${r.name}: ${r.violations.length} issue type(s), ${serious.length} serious/critical`);
    for (const v of r.violations) console.log(`   [${v.impact}] ${v.id} x${v.n} - ${v.help} (${v.sample})`);
  }
  await b.close();
  console.log(bad ? 'A11Y FAIL' : 'A11Y PASS (no serious/critical)');
  process.exit(bad ? 1 : 0);
})();
