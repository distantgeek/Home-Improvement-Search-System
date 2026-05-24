// @ts-check
const { test, expect } = require('@playwright/test');
const fixtures = require('../fixtures/meili-results.json');

// Phase 1 target behavior — these tests describe the Meilisearch-backed UI.
// They FAIL against the current Serper-based index.html and pass after Phase 1.

const MEILI_SEARCH = '**/meili/indexes/events/search';
const MEILI_STATS = '**/meili/indexes/events/stats';

async function mockMeilisearch(page) {
  await page.route(MEILI_SEARCH, route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixtures.searchResponse),
    })
  );
  await page.route(MEILI_STATS, route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixtures.statsResponse),
    })
  );
}

test.describe('Phase 1: Meilisearch search flow', () => {
  test('topbar has no Serper API key field', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#apiKeyInput')).toBeHidden();
  });

  test('topbar shows last-indexed timestamp from Meilisearch stats', async ({ page }) => {
    await mockMeilisearch(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Should show a "last updated" date sourced from /indexes/events/stats
    await expect(page.locator('#lastUpdated')).toBeVisible();
    await expect(page.locator('#lastUpdated')).not.toBeEmpty();
  });

  test('run search calls Meilisearch search endpoint', async ({ page }) => {
    let searchCalled = false;
    await page.route(MEILI_SEARCH, route => {
      searchCalled = true;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixtures.searchResponse),
      });
    });
    await page.route(MEILI_STATS, route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.statsResponse) })
    );

    await page.goto('/');
    await page.click('#runSearchBtn');
    await page.waitForLoadState('networkidle');
    expect(searchCalled).toBe(true);
  });

  test('results render with correct columns after search', async ({ page }) => {
    await mockMeilisearch(page);
    await page.goto('/');
    await page.click('#runSearchBtn');

    await expect(page.locator('#resultsTable')).toBeVisible();
    await expect(page.locator('#resultsBody tr')).toHaveCount(
      fixtures.searchResponse.hits.length
    );

    // Spot-check first row content
    const firstRow = page.locator('#resultsBody tr').first();
    await expect(firstRow).toContainText('Frederick County Home Show');
    await expect(firstRow).toContainText('Frederick');
    await expect(firstRow).toContainText('21702');
    await expect(firstRow).toContainText('MD');
  });

  test('result count updates after search', async ({ page }) => {
    await mockMeilisearch(page);
    await page.goto('/');
    await page.click('#runSearchBtn');
    await expect(page.locator('#resultCount')).not.toContainText('Run a search');
    await expect(page.locator('#resultCount')).toContainText('3');
  });

  test('export button enables after results load', async ({ page }) => {
    await mockMeilisearch(page);
    await page.goto('/');
    await page.click('#runSearchBtn');
    await expect(page.locator('#exportBtn')).toBeEnabled();
  });

  test('table is hidden and placeholder shown when no results returned', async ({ page }) => {
    await page.route(MEILI_SEARCH, route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hits: [], query: '', processingTimeMs: 1, estimatedTotalHits: 0 }),
      })
    );
    await page.route(MEILI_STATS, route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtures.statsResponse) })
    );

    await page.goto('/');
    await page.click('#runSearchBtn');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#resultsTable')).toBeHidden();
    await expect(page.locator('#tablePlaceholder')).toBeVisible();
  });

  test('error banner shows when Meilisearch is unreachable', async ({ page }) => {
    await page.route(MEILI_SEARCH, route => route.abort('failed'));
    await page.route(MEILI_STATS, route => route.abort('failed'));

    await page.goto('/');
    await page.click('#runSearchBtn');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#errorBanner')).toBeVisible();
  });
});

test.describe('Phase 1: event type filtering', () => {
  test.beforeEach(async ({ page }) => {
    await mockMeilisearch(page);
    await page.goto('/');
    await page.click('#runSearchBtn');
    await expect(page.locator('#resultsBody tr')).toHaveCount(3);
  });

  test('Meilisearch query includes event type filter when type is selected', async ({ page }) => {
    // The search request body should include a filter for checked event types
    let requestBody = null;
    await page.route(MEILI_SEARCH, async route => {
      requestBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixtures.searchResponse),
      });
    });

    await page.click('#runSearchBtn');
    await page.waitForLoadState('networkidle');
    // Filter expression should be present when event types are checked
    expect(requestBody).not.toBeNull();
    expect(requestBody).toHaveProperty('filter');
  });
});
