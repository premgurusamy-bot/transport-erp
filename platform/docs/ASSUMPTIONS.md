# Assumptions

Each assumption is either configurable in **Admin › Settings** (versioned, audited) or listed for verification.

| # | Assumption | Why | How to change / verify |
|---|---|---|---|
| A-01 | Initial own fleet: two 7-ton 22-ft and one 12-ton 20-ft open-body vehicles; legal payload 7,000 / 12,000 kg; body width 7.5 ft | From the brief; dimensions approximate | Edit each vehicle with RC/registered payload and measured body size before use |
| A-02 | Vehicle classes MGV (7 t) and HGV (12 t) for licence matching | Typical classification | Confirm against RC/licence categories |
| A-03 | Registrations TN00GR0001-0003 are placeholders | Real numbers not provided | Replace in Fleet › Vehicles |
| A-04 | Office location Coimbatore; verified service cities: Coimbatore, Tiruppur, Erode, Salem, Chennai, Madurai, Tiruchirappalli, Pollachi; Bengaluru/Kochi/Hyderabad NOT verified | Tamil Nadu focus with Coimbatore priority | Admin › Masters › Locations › "Service verified" |
| A-05 | Lane distances/tolls are manual estimates | No maps provider yet | Update lane master or connect maps adapter |
| A-06 | Cost rates (₹/km fuel 22, maintenance 4.5, toll 2.2; driver ₹900/day; fixed ₹1,800/day; 350 km/day; deadhead 30%) | Conservative placeholders | `pricing.cost_rates` – calibrate in pilot |
| A-07 | GST: GTA under RCM by default; FCM 12% (5% option) | Common practice; must be confirmed | `tax.gst_rates`; CA review |
| A-08 | TDS 194C 1% individual / 2% others | Current common rates; verify | `tax.tds_rates`; CA review |
| A-09 | E-way threshold ₹50,000 | Common threshold; exemptions vary | `eway.value_threshold`; CA review |
| A-10 | PF 12% up to ₹15,000; ESI 0.75% up to ₹21,000; PT 0 | Placeholders | `payroll.statutory`; consultant review |
| A-11 | Financial year April–March; numbering resets each FY | Indian practice | — |
| A-12 | Driver duty limit 10 h/day driving, 8 h rest | Conservative default | `driver.duty` |
| A-13 | Approval thresholds: expense ₹5,000; procurement ₹10,000; repair ₹15,000; payments/settlements/refunds/write-offs always | Conservative | `approval.thresholds` (Owner only) |
| A-14 | Retention: GPS pings 365 days; notifications 730 days; camera clips 90 days; legal hold overrides | Data minimisation | `retention.days`; confirm legal retention needs |
| A-15 | AI budget ₹300/day, ₹5,000/month; alerts 50/75/90/100% | Modest default | `ai.budget` (Owner only) |
| A-16 | Marketing auto-publish cap: 2 routine posts/day | Conservative | `marketing.daily_autopublish_cap` |
| A-17 | Notification cap 10 per recipient per day (OTPs exempt) | Avoid spam | `notification.daily_cap_per_recipient` |
| A-18 | Customer credit default 30 days when approved; none until approved | Conservative | Credit profiles (approval) |
| A-19 | Indian mobile numbers, 10–13 digits | Local practice | — |
| A-20 | DVR: 2 channels per own vehicle (1 road, 2 cargo) | From brief | Verify actual DVR SDK during procurement |
