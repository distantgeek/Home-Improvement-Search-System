// @ts-check
const { test, expect } = require('@playwright/test');
const fixtures = require('../fixtures/meili-results.json');

// CSV export tests — verify headers, row content, and filename.
// Require Phase 1 Meilisearch mock to seed results.

const MEILI_HOST = 'http://192.168.2.148:7700';

async function mockAndSearch(page) {
  await page.route(`${MEILI_HOST}/indexes/events/search`, route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixtures.searchResponse),
    })
  );
  await page.route(`${MEILI_HOST}/indexes/events/stats`, route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixtures.statsResponse),
    })
  );
  await page.goto('/');
  await page.click('#runSearchBtn');
  await expect(page.locator('#resultsBody tr')).toHaveCount(3);
}

test.describe('CSV export', () => {
  test('export button enables after results load', async ({ page }) => {
    await mockAndSearch(page);
    await expect(page.locator('#exportBtn')).toBeEnabled();
  });

  test('export downloads a file with correct CSV headers', async ({ page }) => {
    await mockAndSearch(page);

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.click('#exportBtn'),
    ]);

    const stream = await download.createReadStream();
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    const csv = Buffer.concat(chunks).toString('utf-8');

    const headers = csv.split('\n')[0];
    expect(headers).toContain('Event Name');
    expect(headers).toContain('County');
    expect(headers).toContain('ZIP');
    expect(headers).toContain('State');
    expect(headers).toContain('Event Type');
    expect(headers).toContain('Coverage');
  });

  test('exported CSV contains correct row data', async ({ page }) => {
    await mockAndSearch(page);

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.click('#exportBtn'),
    ]);

    const stream = await download.createReadStream();
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    const csv = Buffer.concat(chunks).toString('utf-8');

    expect(csv).toContain('Frederick County Home Show');
    expect(csv).toContain('21702');
    expect(csv).toContain('Frederick');
  });

  test('exported CSV has correct row count (header + 3 data rows)', async ({ page }) => {
    await mockAndSearch(page);

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.click('#exportBtn'),
    ]);

    const stream = await download.createReadStream();
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    const csv = Buffer.concat(chunks).toString('utf-8');

    const rows = csv.trim().split('\n').filter(r => r.trim());
    // 1 header + 3 data rows
    expect(rows).toHaveLength(4);
  });

  test('export filename contains current date', async ({ page }) => {
    await mockAndSearch(page);

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.click('#exportBtn'),
    ]);

    const year = new Date().getFullYear().toString();
    expect(download.suggestedFilename()).toContain(year);
    expect(download.suggestedFilename()).toMatch(/\.csv$/i);
  });

  test('export respects active coverage filter', async ({ page }) => {
    // Configure Frederick County as served, then filter to served-only before export
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('hiss.servedCounties', JSON.stringify(['MD:Frederick County']));
    });
    await page.route(`${MEILI_HOST}/indexes/events/search`, route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.searchResponse) })
    );
    await page.route(`${MEILI_HOST}/indexes/events/stats`, route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.statsResponse) })
    );
    await page.reload();
    await page.click('#runSearchBtn');
    await expect(page.locator('#resultsBody tr')).toHaveCount(3);

    await page.click('.cov-btn[data-cov="served"]');

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.click('#exportBtn'),
    ]);

    const stream = await download.createReadStream();
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    const csv = Buffer.concat(chunks).toString('utf-8');

    // Only Frederick County row should be exported
    const rows = csv.trim().split('\n').filter(r => r.trim());
    expect(rows).toHaveLength(2); // header + 1 data row
    expect(csv).toContain('Frederick County Home Show');
    expect(csv).not.toContain('Montgomery County');
  });
});
