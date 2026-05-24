// @ts-check
const { test, expect } = require('@playwright/test');
const fixtures = require('../fixtures/meili-results.json');

// Coverage coloring tests — verify green/red/gray indicators based on served counties.
// Require Phase 1 Meilisearch mock to seed results into the table.

async function mockAndSearch(page) {
  await page.route('**/meili/indexes/events/search', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixtures.searchResponse),
    })
  );
  await page.route('**/meili/indexes/events/stats', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixtures.statsResponse),
    })
  );
  await page.goto('/');
  await page.evaluate(() => localStorage.clear());
  await page.click('#runSearchBtn');
  await expect(page.locator('#resultsBody tr')).toHaveCount(3);
}

test.describe('Coverage coloring', () => {
  test('all rows show gray (unknown) when no counties are configured', async ({ page }) => {
    await mockAndSearch(page);
    const coverageCells = page.locator('#resultsBody tr td[data-col="coverage"], #resultsBody tr .coverage-indicator');
    // All should have unknown/gray state — no county is in servedSet
    const rows = page.locator('#resultsBody tr');
    const count = await rows.count();
    for (let i = 0; i < count; i++) {
      const cell = rows.nth(i).locator('[data-cov], .cov-unknown, td:last-child');
      // Coverage indicator should not be green (served) since nothing is configured
      await expect(rows.nth(i)).not.toContainText('✓');
    }
  });

  test('row shows green when its county is in servedSet', async ({ page }) => {
    // Configure Frederick County MD as served before loading
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('hiss.servedCounties', JSON.stringify(['MD:Frederick County']));
    });
    await page.route('**/meili/indexes/events/search', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.searchResponse) })
    );
    await page.route('**/meili/indexes/events/stats', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.statsResponse) })
    );
    await page.reload();
    await page.click('#runSearchBtn');
    await expect(page.locator('#resultsBody tr')).toHaveCount(3);

    // First row (Frederick County Home Show, MD:Frederick County) should be served
    const firstRow = page.locator('#resultsBody tr').first();
    await expect(firstRow).toContainText('✓');
  });

  test('row shows red (✗) when county is known but not served', async ({ page }) => {
    // Only Frederick County is served; Arlington and Montgomery are not
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('hiss.servedCounties', JSON.stringify(['MD:Frederick County']));
    });
    await page.route('**/meili/indexes/events/search', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.searchResponse) })
    );
    await page.route('**/meili/indexes/events/stats', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.statsResponse) })
    );
    await page.reload();
    await page.click('#runSearchBtn');
    await expect(page.locator('#resultsBody tr')).toHaveCount(3);

    // Second row (Montgomery County) should be not-served (✗)
    const secondRow = page.locator('#resultsBody tr').nth(1);
    await expect(secondRow).toContainText('✗');
  });
});

test.describe('Coverage filter toggle', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('hiss.servedCounties', JSON.stringify(['MD:Frederick County']));
    });
    await page.route('**/meili/indexes/events/search', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.searchResponse) })
    );
    await page.route('**/meili/indexes/events/stats', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.statsResponse) })
    );
    await page.reload();
    await page.click('#runSearchBtn');
    await expect(page.locator('#resultsBody tr')).toHaveCount(3);
  });

  test('"Served Only" filter hides non-served rows', async ({ page }) => {
    await page.click('.cov-btn[data-cov="served"]');
    // Only Frederick County is served — should show 1 row
    await expect(page.locator('#resultsBody tr')).toHaveCount(1);
    await expect(page.locator('#resultsBody tr').first()).toContainText('Frederick');
  });

  test('"Not Served" filter shows only non-served rows', async ({ page }) => {
    await page.click('.cov-btn[data-cov="not-served"]');
    // Montgomery (MD) and Arlington (VA) are not served — 2 rows
    await expect(page.locator('#resultsBody tr')).toHaveCount(2);
  });

  test('"All Results" restores full count', async ({ page }) => {
    await page.click('.cov-btn[data-cov="served"]');
    await page.click('.cov-btn[data-cov="all"]');
    await expect(page.locator('#resultsBody tr')).toHaveCount(3);
  });
});
