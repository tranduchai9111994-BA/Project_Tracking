// Task 2 E2E: verify FIT/GAP section renders + charts drawn + table populates
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push('[console] ' + msg.text());
  });

  await page.goto('http://localhost:5000/');
  await page.waitForTimeout(1500);
  await page.evaluate(async () => {
    const r = await fetch('/api/projects/default/dashboard');
    applyDashboardResponse(await r.json());
  });
  await page.waitForTimeout(2500);   // wait for fitgap async load

  // 1) Section visible + summary cards
  const state1 = await page.evaluate(() => {
    const s = document.getElementById('section-fitgap-dashboard');
    const cards = document.getElementById('fitgapSummaryCards').children;
    return {
      hidden: s.classList.contains('hidden'),
      cardCount: cards.length,
      cards: Array.from(cards).map(c => c.innerText.trim()),
    };
  });
  console.log('1) FIT/GAP section state:');
  console.log(JSON.stringify(state1, null, 2));

  // 2) Charts drawn
  const chartsState = await page.evaluate(() => ({
    byModule: !!Chart.getChart(document.getElementById('chartFitgapByModule')),
    byProcess: !!Chart.getChart(document.getElementById('chartFitgapByProcess')),
    byPriority: !!Chart.getChart(document.getElementById('chartFitgapByPriority')),
  }));
  console.log('2) Charts:', chartsState);

  // 3) Aging table populated
  const tableState = await page.evaluate(() => {
    const rows = document.getElementById('fitgapAgingBody').querySelectorAll('tr');
    return {
      rowCount: rows.length,
      first: rows.length ? rows[0].innerText.slice(0, 200) : null,
    };
  });
  console.log('3) Aging table:', tableState);

  // 4) Change threshold to 30 → reload
  await page.evaluate(() => {
    document.getElementById('fitgapAgingThr').value = '30';
    loadFitgapDashboard();
  });
  await page.waitForTimeout(800);
  const afterThr = await page.evaluate(() => {
    const c = document.getElementById('fitgapAgingCount').innerText;
    const lbl = document.getElementById('fitgapAgingThrLabel').innerText;
    return { count: c, threshold: lbl };
  });
  console.log('4) After threshold=30:', afterThr);

  // 5) Click aging row → opens function detail modal
  await page.evaluate(() => {
    const tr = document.querySelector('#fitgapAgingBody tr');
    if (tr && tr.onclick) tr.click();
  });
  await page.waitForTimeout(800);
  const modalState = await page.evaluate(() => ({
    modalHidden: document.getElementById('functionDetailModal').classList.contains('hidden'),
    ma_cn: document.getElementById('fnDetailMaCn').textContent,
  }));
  console.log('5) Click row → modal:', modalState);
  await page.keyboard.press('Escape');

  await page.waitForTimeout(300);
  await page.locator('#section-fitgap-dashboard').scrollIntoViewIfNeeded();
  await page.screenshot({ path: '_dbg_t2_section.png', fullPage: false });
  console.log('Saved _dbg_t2_section.png');

  console.log('\nPage errors:', errors);
  await browser.close();
})();
