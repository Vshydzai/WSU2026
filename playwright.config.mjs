import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './web/browser',
  timeout: 30000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['junit', { outputFile: 'test-results/browser.xml' }], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:8787', trace: 'retain-on-failure', screenshot: 'only-on-failure',
    launchOptions: process.env.DASHBOARD_CHROMIUM_PATH ? {
      executablePath: process.env.DASHBOARD_CHROMIUM_PATH,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    } : {},
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: `${process.env.DASHBOARD_PYTHON || '.venv/bin/python'} vshydzai/scripts/serve_dashboard.py --demo --port 8787`,
    url: 'http://127.0.0.1:8787/config.json',
    reuseExistingServer: false,
    timeout: 20000,
  },
});
