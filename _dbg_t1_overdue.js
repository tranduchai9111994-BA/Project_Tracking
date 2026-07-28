// Verify overdue function shows red banner + red border on overdue phase
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  await page.goto('http://localhost:5000/');
  await page.waitForTimeout(1500);
  await page.evaluate(async () => {
    const r = await fetch('/api/projects/default/dashboard');
    applyDashboardResponse(await r.json());
  });
  await page.waitForTimeout(1500);

  // Open detail for row 3 (TMS.FR.02 Báo cáo tháng - UAT overdue) — fire & forget
  await page.evaluate(() => { openFunctionDetail(3); return null; });
  await page.waitForTimeout(1500);

  const state = await page.evaluate(() => {
    const bodyText = document.getElementById('fnDetailBody').innerText;
    const bodyHTML = document.getElementById('fnDetailBody').innerHTML;
    return {
      ma_cn: document.getElementById('fnDetailMaCn').textContent,
      ten_cn: document.getElementById('fnDetailTenCn').textContent,
      hasOverdueBanner: bodyHTML.includes('bg-red-50') && bodyHTML.includes('Function đang trễ deadline'),
      hasUatOverdueBadge: bodyText.includes('⚠️ TRỄ'),
      hasDaysOverdue: /quá \d+ ngày/.test(bodyText),
      bodyExcerpt: bodyText.slice(0, 400),
    };
  });
  console.log('Overdue function detail state:');
  console.log(JSON.stringify(state, null, 2));

  await page.screenshot({ path: '_dbg_t1_overdue.png' });
  console.log('Saved _dbg_t1_overdue.png');
  await browser.close();
})();
