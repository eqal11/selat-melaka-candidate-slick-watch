import {defineConfig,devices} from '@playwright/test';

const port=Number(process.env.E2E_WEB_PORT??5173);
const origin=`http://127.0.0.1:${port}`;
export default defineConfig({
 testDir:'./e2e',
 timeout:180000,
 use:{
  baseURL:origin,
  ...devices['Desktop Chrome'],
  launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH},
 },
 webServer:process.env.E2E_EXTERNAL_SERVERS?undefined:[
  {
   command:process.env.E2E_API_COMMAND??'uv run uvicorn api.main:app --host 127.0.0.1 --port 8000',
   cwd:'..',url:'http://127.0.0.1:8000/health',reuseExistingServer:!process.env.CI,timeout:120000,
  },
  {
   command:`npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
   url:origin,reuseExistingServer:!process.env.CI,timeout:30000,
  },
 ],
});
