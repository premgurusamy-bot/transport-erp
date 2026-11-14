const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1366, height: 860 } });
  const errors = [];
  p.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  p.on('pageerror', e => errors.push('pageerror: ' + e.message));
  p.on('response', r => { if (r.url().includes('/api/') && r.status() >= 400 && r.status() !== 401) errors.push(`${r.status()} ${r.url()}`); });
  await p.goto((process.env.GRL_WEB || 'http://localhost:5173') + '/');
  await p.screenshot({ path: (process.env.OUT || '.') + '/website.png' });
  await p.goto((process.env.GRL_WEB || 'http://localhost:5173') + '/login');
  await p.fill('input[autocomplete=username]', 'owner@groadlines.local');
  await p.fill('input[type=password]', 'Owner@12345');
  await p.click('button:has-text("Sign in")');
  await p.waitForURL('**/erp');
  const pages = ['', 'approvals', 'enquiries', 'quotations', 'bookings', 'dispatch', 'trips', 'fleet', 'fleet/compliance', 'fleet/defects', 'fleet/fuel',
    'fleet/maintenance', 'fleet/tyres', 'fleet/drivers', 'fleet/owners', 'supply', 'supply/procurement', 'supply/inventory', 'supply/godown', 'finance',
    'finance/receipts', 'finance/expenses', 'finance/settlements', 'finance/bank', 'finance/collections', 'finance/reports', 'finance/cash', 'finance/tally',
    'risk', 'risk/incidents', 'risk/insurance', 'risk/legal', 'people', 'people/sops', 'people/employees', 'people/payroll', 'marketing', 'marketing/campaigns',
    'marketing/opportunities', 'marketing/funnel', 'ai', 'admin', 'admin/masters', 'admin/users', 'admin/settings', 'admin/audit', 'admin/integrations', 'admin/notifications'];
  for (const pg of pages) {
    await p.goto((process.env.GRL_WEB || 'http://localhost:5173') + '/erp/' + pg);
    await p.waitForTimeout(500);
    const txt = await p.textContent('main');
    if (!txt || txt.length < 20) errors.push('empty page ' + pg);
  }
  await p.goto((process.env.GRL_WEB || 'http://localhost:5173') + '/erp/');
  await p.waitForTimeout(800);
  await p.screenshot({ path: (process.env.OUT || '.') + '/control-tower.png' });
  // customer portal
  await p.goto((process.env.GRL_WEB || 'http://localhost:5173') + '/login');
  await p.evaluate(() => sessionStorage.clear());
  await p.goto((process.env.GRL_WEB || 'http://localhost:5173') + '/login');
  await p.fill('input[autocomplete=username]', 'customer1@demo.local');
  await p.fill('input[type=password]', 'Demo@12345');
  await p.click('button:has-text("Sign in")');
  await p.waitForURL('**/portal/customer');
  for (const pg of ['', 'quotes', 'enquiry', 'invoices', 'support']) { await p.goto((process.env.GRL_WEB || 'http://localhost:5173') + '/portal/customer/' + pg); await p.waitForTimeout(400); }
  // owner and vendor
  for (const [u, path] of [['owner1@demo.local', 'owner'], ['vendor1@demo.local', 'vendor']]) {
    await p.evaluate(() => sessionStorage.clear());
    await p.goto((process.env.GRL_WEB || 'http://localhost:5173') + '/login');
    await p.fill('input[autocomplete=username]', u); await p.fill('input[type=password]', 'Demo@12345');
    await p.click('button:has-text("Sign in")'); await p.waitForURL('**/portal/' + path);
    await p.waitForTimeout(500);
  }
  // driver OTP
  await p.evaluate(() => sessionStorage.clear());
  await p.goto((process.env.GRL_WEB || 'http://localhost:5173') + '/login');
  await p.click('button:has-text("Driver (OTP)")');
  await p.fill('input[type=tel]', '9000000201');
  await p.click('button:has-text("Send OTP")');
  await p.waitForSelector('text=MOCK SMS OTP');
  const t = await p.textContent('.login');
  const otp = t.match(/OTP: (\d{6})/)[1];
  await p.fill('input[inputmode=numeric] >> nth=1', otp);
  await p.click('button:has-text("Sign in")');
  await p.waitForURL('**/driver');
  await p.setViewportSize({ width: 390, height: 844 });
  await p.waitForTimeout(600);
  await p.screenshot({ path: (process.env.OUT || '.') + '/driver.png' });
  console.log(errors.length ? errors.join('\n') : 'NO ERRORS');
  await b.close();
})();
