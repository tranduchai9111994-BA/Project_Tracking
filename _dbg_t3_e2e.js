// Task 3 E2E: verify Function Diff section renders + tabs work
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));

  await page.goto('http://localhost:5000/');
  await page.waitForTimeout(1500);
  await page.evaluate(async () => {
    const r = await fetch('/api/projects/default/dashboard');
    applyDashboardResponse(await r.json());
  });
  await page.waitForTimeout(3000);   // wait for diff async load

  // 1) Section visible + summary cards + tabs
  const state = await page.evaluate(() => {
    const s = document.getElementById('section-function-diff');
    const cards = document.getElementById('fdiffSummaryCards').children;
    const tabs = document.getElementById('fdiffTabsWrap').children;
    const emptyHidden = document.getElementById('fdiffEmptyState').classList.contains('hidden');
    return {
      sectionHidden: s.classList.contains('hidden'),
      emptyHidden,
      cardCount: cards.length,
      cards: Array.from(cards).map(c => c.innerText.trim()),
      tabCount: tabs.length,
      tabLabels: Array.from(tabs).map(t => t.innerText.trim()),
      headerTs: document.getElementById('fdiffHeaderTs').innerText,
      subtitle: document.getElementById('fdiffSubtitle').innerText,
    };
  });
  console.log('1) Section state:');
  console.log(JSON.stringify(state, null, 2));

  // 2) First tab "Mới thêm" data
  const addedTable = await page.evaluate(() => {
    const rows = document.querySelectorAll('#fdiffTableBody tr');
    return {
      rowCount: rows.length,
      first: rows.length ? rows[0].innerText.slice(0, 200) : null,
    };
  });
  console.log('2) Added tab:', addedTable);

  // 3) Switch to "PIC changed" tab
  await page.evaluate(() => _fdiffSetActiveTab('pic_changed'));
  await page.waitForTimeout(300);
  const picTab = await page.evaluate(() => ({
    rowCount: document.querySelectorAll('#fdiffTableBody tr').length,
    first: document.querySelector('#fdiffTableBody tr')?.innerText.slice(0, 200),
  }));
  console.log('3) PIC changed tab:', picTab);

  // 4) Switch to "Status changed" tab
  await page.evaluate(() => _fdiffSetActiveTab('phase_status_changed'));
  await page.waitForTimeout(300);
  const statusTab = await page.evaluate(() => ({
    rowCount: document.querySelectorAll('#fdiffTableBody tr').length,
    first: document.querySelector('#fdiffTableBody tr')?.innerText.slice(0, 200),
  }));
  console.log('4) Status changed tab:', statusTab);

  // 5) Click row → open function detail
  await page.evaluate(() => {
    const tr = document.querySelector('#fdiffTableBody tr');
    if (tr) tr.click();
  });
  await page.waitForTimeout(700);
  const modalState = await page.evaluate(() => ({
    modalHidden: document.getElementById('functionDetailModal').classList.contains('hidden'),
    ma_cn: document.getElementById('fnDetailMaCn').textContent,
  }));
  console.log('5) Row click → modal:', modalState);
  await page.keyboard.press('Escape');

  await page.locator('#section-function-diff').scrollIntoViewIfNeeded();
  await page.screenshot({ path: '_dbg_t3_diff.png' });
  console.log('Saved _dbg_t3_diff.png');

  console.log('\nPage errors:', errors);
  await browser.close();
})();
