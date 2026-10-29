'use strict';
// @ts-check
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 45000,
  fullyParallel: false, // sequential: these drive one real local server, not isolated fixtures
  retries: 0,
  reporter: [['list']],
  use: {
    actionTimeout: 10000,
    ignoreHTTPSErrors: true,
  },
});
