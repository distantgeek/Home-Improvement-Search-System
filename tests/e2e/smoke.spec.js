// @ts-check
const { test, expect } = require('@playwright/test');

// Stable UI structure tests — no network calls, pass against current index.html.
// These must stay green throughout Phase 1 migration.

test.describe('Page load', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('renders brand name', async ({ page }) => {
    await expect(page.locator('.brand')).toContainText('HISS');
  });

  test('has no uncaught JS errors on load', async ({ page }) => {
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    expect(errors).toHaveLength(0);
  });

  test('state select is present and starts empty', async ({ page }) => {
    const sel = page.locator('#stateSelect');
    await expect(sel).toBeVisible();
    await expect(sel).toHaveValue('');
  });

  test('run search button is present', async ({ page }) => {
    await expect(page.locator('#runSearchBtn')).toBeVisible();
  });

  test('results table is hidden before any search', async ({ page }) => {
    await expect(page.locator('#resultsTable')).toBeHidden();
    await expect(page.locator('#tablePlaceholder')).toBeVisible();
  });

  test('export button is disabled before any search', async ({ page }) => {
    await expect(page.locator('#exportBtn')).toBeDisabled();
  });

  test('result count shows prompt text initially', async ({ page }) => {
    await expect(page.locator('#resultCount')).toContainText('Run a search');
  });

  test('error banner is hidden initially', async ({ page }) => {
    await expect(page.locator('#errorBanner')).toBeHidden();
  });
});

test.describe('County list', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('shows placeholder before state selected', async ({ page }) => {
    await expect(page.locator('#countyList')).toContainText('Select a state first');
  });

  test('populates MD counties when Maryland is selected', async ({ page }) => {
    await page.selectOption('#stateSelect', 'MD');
    await expect(page.locator('#countyList label').first()).toBeVisible();
    // Frederick County is in MD
    await expect(page.locator('#countyList')).toContainText('Frederick');
  });

  test('county search filters the list', async ({ page }) => {
    await page.selectOption('#stateSelect', 'MD');
    await page.fill('#countySearch', 'Frederick');
    const labels = page.locator('#countyList label');
    const count = await labels.count();
    for (let i = 0; i < count; i++) {
      await expect(labels.nth(i)).toContainText(/frederick/i);
    }
  });
});

test.describe('Served counties modal', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('opens when Configure Served Counties is clicked', async ({ page }) => {
    await page.click('#openCoverageModal');
    await expect(page.locator('#coverageModal')).toBeVisible();
  });

  test('closes on Save & Close', async ({ page }) => {
    await page.click('#openCoverageModal');
    await page.click('#saveCoverageBtn');
    await expect(page.locator('#coverageModal')).toBeHidden();
  });

  test('modal body populates with county checkboxes', async ({ page }) => {
    await page.click('#openCoverageModal');
    await expect(page.locator('#coverageModalBody input[type="checkbox"]').first()).toBeVisible();
  });

  test('selected counties persist to localStorage on save', async ({ page }) => {
    await page.click('#openCoverageModal');
    // Check the first checkbox in the modal
    const first = page.locator('#coverageModalBody input[type="checkbox"]').first();
    await first.check();
    await page.click('#saveCoverageBtn');

    const stored = await page.evaluate(() => localStorage.getItem('hiss.servedCounties'));
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored);
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed.length).toBeGreaterThan(0);
  });
});

test.describe('Coverage filter buttons', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('"All Results" is active by default', async ({ page }) => {
    await expect(page.locator('.cov-btn[data-cov="all"]')).toHaveClass(/active/);
  });

  test('clicking Served Only makes it active', async ({ page }) => {
    await page.click('.cov-btn[data-cov="served"]');
    await expect(page.locator('.cov-btn[data-cov="served"]')).toHaveClass(/active/);
    await expect(page.locator('.cov-btn[data-cov="all"]')).not.toHaveClass(/active/);
  });
});
