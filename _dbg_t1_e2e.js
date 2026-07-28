// Task 1 E2E: verify search bar + modal in real Chrome
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  const logs = [];
  const netCalls = [];
  page.on('pageerror', err => errors.push(err.message));
  page.on('console', msg => logs.push(`[${msg.type()}] ${msg.text()}`));
  page.on('request', req => {
    if (req.url().includes('/function-search') || req.url().includes('/function-detail'))
      netCalls.push(`REQ ${req.method()} ${req.url()}`);
  });
  page.on('response', resp => {
    if (resp.url().includes('/function-search') || resp.url().includes('/function-detail'))
      netCalls.push(`RES ${resp.status()} ${resp.url()}`);
  });

  await page.goto('http://localhost:5000/');
  await page.waitForTimeout(1500);
  // Load default project data
  await page.evaluate(async () => {
    const r = await fetch('/api/projects/default/dashboard');
    applyDashboardResponse(await r.json());
  });
  await page.waitForTimeout(1500);

  // 1) Verify search bar is visible now (after dashboard loaded)
  const searchWrapVisible = await page.evaluate(() => {
    return !document.getElementById('searchWrap').classList.contains('hidden');
  });
  console.log('1) searchWrap visible after data loaded:', searchWrapVisible);

  // 2) Type "TMS" into search box → wait for dropdown → verify contents
  await page.locator('#searchBox').focus();
  // fill() replaces content atomically; use type() to simulate keystrokes triggering input event
  await page.locator('#searchBox').type('TMS', { delay: 50 });
  await page.waitForTimeout(1500);  // debounce 200ms + fetch time
  const searchResult = await page.evaluate(() => {
    const results = document.getElementById('searchResults');
    const items = results.querySelectorAll('.search-item');
    return {
      hidden: results.classList.contains('hidden'),
      itemCount: items.length,
      firstItem: items.length ? items[0].innerText.slice(0, 120) : null,
      resultsHTML: results.innerHTML.slice(0, 200),
    };
  });
  console.log('2) Search "TMS":', searchResult);
  console.log('   Network calls:', netCalls);

  // 3) Click first result → modal opens with data
  await page.evaluate(() => {
    document.querySelector('#searchResults .search-item').click();
  });
  await page.waitForTimeout(500);
  const modalState = await page.evaluate(() => {
    const m = document.getElementById('functionDetailModal');
    return {
      hidden: m.classList.contains('hidden'),
      ma_cn: document.getElementById('fnDetailMaCn').textContent.trim(),
      ten_cn: document.getElementById('fnDetailTenCn').textContent.trim(),
      badgesCount: document.getElementById('fnDetailBadges').children.length,
      bodyText: document.getElementById('fnDetailBody').innerText.slice(0, 400),
    };
  });
  console.log('3) Modal after click:');
  console.log(JSON.stringify(modalState, null, 2));

  await page.screenshot({ path: '_dbg_t1_modal.png' });
  console.log('  Saved _dbg_t1_modal.png');

  // 4) Press Escape → modal closes
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
  const closedState = await page.evaluate(() => ({
    hidden: document.getElementById('functionDetailModal').classList.contains('hidden'),
  }));
  console.log('4) After Escape - modal hidden:', closedState.hidden);

  // 5) Empty query → hides dropdown
  await page.locator('#searchBox').fill('');
  await page.waitForTimeout(300);
  const emptyState = await page.evaluate(() => ({
    hidden: document.getElementById('searchResults').classList.contains('hidden'),
  }));
  console.log('5) After clear - dropdown hidden:', emptyState.hidden);

  // 6) Search a Vietnamese term
  await page.locator('#searchBox').fill('Báo');
  await page.waitForTimeout(500);
  const vnResult = await page.evaluate(() => {
    const items = document.getElementById('searchResults').querySelectorAll('.search-item');
    return items.length;
  });
  console.log('6) Search "Báo" (Vietnamese) - hits:', vnResult);

  console.log('\nErrors:', errors);
  await browser.close();
})().catch(err => { console.error('FATAL:', err); process.exit(1); });
