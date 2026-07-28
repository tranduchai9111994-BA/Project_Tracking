const { JSDOM } = require('./_tmp_node/node_modules/jsdom');
const fs = require('fs');
const http = require('http');

function httpGet(path) {
    return new Promise((resolve, reject) => {
        http.get('http://127.0.0.1:5555' + path, (res) => {
            let d = ''; res.on('data', c => d += c);
            res.on('end', () => resolve(d)); res.on('error', reject);
        }).on('error', reject);
    });
}

(async () => {
    const html = await httpGet('/');
    const dom = new JSDOM(html, {
        runScripts: 'outside-only',
        pretendToBeVisual: true,
        url: 'http://127.0.0.1:5555/',
        storageQuota: 10_000_000,
    });
    const win = dom.window;

    // Wait for DOMContentLoaded
    await new Promise(r => setTimeout(r, 100));

    win.fetch = async (url, opts) => {
        const path = url.startsWith('http') ? new URL(url).pathname + (new URL(url).search) : url;
        const body = await httpGet(path);
        return { ok: true, status: 200, json: async () => JSON.parse(body), text: async () => body };
    };
    win.Chart = function() { return { destroy: () => {}, resize: () => {}, update: () => {} }; };
    win.Chart.register = () => {};
    win.Chart.defaults = {
        color: '', font: {}, borderColor: '',
        plugins: {
            legend: { labels: {} },
            tooltip: { titleFont: {}, bodyFont: {} },
            datalabels: {},
        },
        datasets: { bar: {} },
    };
    win.MutationObserver = class { constructor(fn) { this.fn = fn; } observe() {} disconnect() {} };

    const jsData = fs.readFileSync('static/js/dashboard.js', 'utf-8');
    try {
        win.eval(jsData);
    } catch (e) {
        console.log('EVAL ERROR:', e.message);
    }

    // Manually construct metricsData like backend would return
    const dashboardResp = JSON.parse(await httpGet('/api/projects/default/dashboard?module=PR&process=' + encodeURIComponent('PRM.BP.03 – Quy trình tính lương sản phẩm') + ',' + encodeURIComponent('PRM.BP.04 – Quy trình tính năng suất theo công đoạn')));

    console.log('=== Response check ===');
    console.log('metrics.summary.total_overdue:', dashboardResp.metrics.summary.total_overdue);
    console.log('metrics.summary.unassigned_count:', dashboardResp.metrics.summary.unassigned_count);
    console.log('metrics.summary.high_risk_count:', dashboardResp.metrics.summary.high_risk_count);
    console.log('metrics.module_overview[0]:', JSON.stringify(dashboardResp.metrics.module_overview[0]));

    // Call applyDashboardResponse from within the eval scope
    win.__resp = dashboardResp;
    console.log();
    console.log('=== Calling applyDashboardResponse ===');
    try {
        win.eval('applyDashboardResponse(__resp)');
        console.log('OK');
    } catch (e) {
        console.log('THROW:', e.message);
        console.log(e.stack);
    }
    console.log();
    console.log('=== DOM state after renderSummaryCards ===');
    console.log('cardTotal:', win.document.getElementById('cardTotal').textContent);
    console.log('cardProgress:', win.document.getElementById('cardProgress').textContent);
    console.log('cardOverdue:', win.document.getElementById('cardOverdue').textContent);
    console.log('cardOverdueRecords:', win.document.getElementById('cardOverdueRecords').textContent);
    console.log('cardUnassigned:', win.document.getElementById('cardUnassigned').textContent);
    console.log('cardHighRisk:', win.document.getElementById('cardHighRisk').textContent);
    console.log('cardModules:', win.document.getElementById('cardModules').textContent);

    console.log();
    // module table already rendered from applyDashboardResponse
    const tbody = win.document.getElementById('moduleTable');
    if (tbody) {
        const firstRow = tbody.querySelector('tr');
        if (firstRow) {
            const cells = firstRow.querySelectorAll('td');
            console.log('firstRow cells:', Array.from(cells).map(c => c.textContent.trim()));
        }
    }

    process.exit(0);
})().catch(err => {
    console.error('FATAL:', err);
    process.exit(1);
});
