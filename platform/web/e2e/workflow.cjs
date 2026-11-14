// UI click-through: enquiry → quotation → send → acceptance → booking → confirm (credit gate shown).
// Needs API + web running with the --demo seed. Usage: GRL_WEB=http://localhost:5173 node e2e/workflow.cjs
const { chromium } = require('playwright');
const BASE = process.env.GRL_WEB || 'http://localhost:5173';
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1366, height: 900 } });
  const errors = [];
  p.on('pageerror', e => errors.push(e.message));
  p.on('dialog', d => d.accept(d.type() === 'prompt' ? 'Buyer Name' : undefined));
  await p.goto(BASE + '/login');
  await p.fill('input[autocomplete=username]', 'owner@groadlines.local');
  await p.fill('input[type=password]', process.env.GRL_OWNER_PW || 'Owner@12345');
  await p.click('button:has-text("Sign in")');
  await p.waitForURL('**/erp');
  // 1. Enquiry
  await p.goto(BASE + '/erp/enquiries');
  await p.click('button:has-text("+ Enquiry")');
  const m = p.locator('.modal');
  const sel = async (field, text) => { const s = m.locator(`[data-field="${field}"] select`); const v = await s.locator('option', { hasText: text }).first().getAttribute('value'); await s.selectOption(v); };
  await sel('customer_id', 'Kovai');
  await sel('service_type', 'FTL');
  await sel('origin_id', 'Coimbatore');
  await sel('destination_id', 'Chennai');
  await m.locator('[data-field=goods_description] input').fill('Cotton yarn cartons');
  await m.locator('[data-field=weight_kg] input').fill('4000');
  await m.locator('button:has-text("Save")').click();
  await p.waitForSelector('.toaster >> text=saved');
  // 2. Quote (first row = newest)
  await p.locator('tbody tr').first().locator('button:has-text("Quote")').click();
  await p.locator('.modal button:has-text("Save")').click();
  await p.waitForSelector('.modal p:has-text("Selling price:")');
  const quoteText = await p.textContent('.modal');
  if (!/Internal \(never shown to customer\)/.test(quoteText)) errors.push('internal cost panel missing for owner');
  await p.locator('.modal button:has-text("Done")').click();
  // 3. Send + accept
  await p.goto(BASE + '/erp/quotations');
  await p.locator('tbody tr').first().locator('button:has-text("Send")').click();
  await p.waitForSelector('tbody tr >> nth=0 >> text=sent');
  await p.locator('tbody tr').first().locator('button:has-text("Record acceptance")').click();
  await p.waitForSelector('tbody tr >> nth=0 >> text=accepted');
  // 4. Booking from accepted quotation
  await p.goto(BASE + '/erp/bookings');
  await p.click('button:has-text("+ Booking")');
  const q = p.locator('.modal [data-field=quotation_id] select');
  await q.selectOption({ index: 1 });
  await p.locator('.modal [data-field=consignor_name] input').fill('Kovai Mills');
  await p.locator('.modal [data-field=consignee_name] input').fill('Chennai Traders');
  await p.locator('.modal [data-field=goods_description] input').fill('Cotton yarn cartons');
  await p.locator('.modal [data-field=weight_kg] input').fill('4000');
  await p.locator('.modal button:has-text("Save")').click();
  await p.waitForURL('**/erp/bookings/*');
  // 5. Confirm → demo customer has no approved credit → on hold with reasons
  await p.click('button:has-text("Confirm")');
  await p.waitForSelector('text=on hold');
  const page = await p.textContent('main');
  if (!/full advance required|No approved credit/i.test(page)) errors.push('credit reason not shown');
  await p.screenshot({ path: (process.env.OUT || '.') + '/workflow-booking.png' });
  console.log(errors.length ? 'FAIL\n' + errors.join('\n') : 'UI WORKFLOW PASS');
  await b.close();
  process.exit(errors.length ? 1 : 0);
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
