import {test,expect} from '@playwright/test';
let sceneId=process.env.REAL_SCENE_ID;
test('loads a real Sentinel-1 analysis and renders its SAR image and candidate overlay',async({page})=>{
 await page.goto('/');
 await expect(page.getByRole('heading',{name:/Selat Melaka/})).toBeVisible();
 if(!sceneId){
  await page.getByRole('button',{name:/Find real Sentinel/}).click();
  await expect.poll(async()=>page.getByLabel('Scene picker').locator('option').count(),{timeout:90000}).toBeGreaterThan(1);
  sceneId=await page.getByLabel('Scene picker').locator('option').nth(1).getAttribute('value')??undefined;
  if(!sceneId) throw new Error('STAC returned no real scene option; no alternate result substituted.');
 }
 const dateToken=sceneId!.match(/_(20\d{6})T/)![1]!; const day=dateToken.slice(0,4)+'-'+dateToken.slice(4,6)+'-'+dateToken.slice(6,8);
 await page.getByLabel('Start UTC').fill(day); await page.getByLabel('End UTC').fill(day);
 await page.getByRole('button',{name:/Find real Sentinel/}).click();
 await expect(page.getByLabel('Scene picker')).toContainText(sceneId!,{timeout:90000});
 await page.getByLabel('Scene picker').selectOption(sceneId!);
 const rawLayer=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/preview-raw-fixed.webp')&&r.status()===200,{timeout:90000}); const filteredLayer=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/preview-filtered-fixed.webp')&&r.status()===200,{timeout:90000});
 const resultPromise=page.waitForResponse(response=>{const path=new URL(response.url()).pathname;return /\/api\/v1\/results\/[0-9a-f]{24}$/.test(path)&&response.status()===200},{timeout:240000});
 await page.getByRole('button',{name:/Analyze real scene/}).click();
 await expect(page.getByText(/REAL Sentinel-1/).first()).toBeVisible({timeout:240000});
 await expect(page.locator('.result').getByText(sceneId!,{exact:false}).first()).toBeVisible();
 await expect(page.locator('.map-pane')).toHaveCount(2);
 await expect(page.locator('.map-pane canvas.maplibregl-canvas').first()).toBeVisible();
 await Promise.all([rawLayer,filteredLayer]); await page.waitForTimeout(1500);
 await expect(page.getByRole('button',{name:'Analyze real scene'})).toBeEnabled({timeout:90000});
 await expect.poll(async()=>Number(await page.locator('.map-pane').last().getAttribute('data-rendered-candidate-count')),{timeout:30000}).toBeGreaterThan(0);
 await page.getByLabel('Minimum heuristic score').fill('0'); await expect.poll(async()=>page.locator('.candidate-row').count(),{timeout:30000}).toBeGreaterThan(0);

 await page.getByText('Independent verification layers').click(); await page.getByLabel('Polygon outline only').check();
 const resultResponse=await resultPromise;const found=new URL(resultResponse.url()).pathname.split('/').pop()!;
 const sar=await page.request.get(`/api/v1/results/${found}/preview-filtered-fixed.webp`);
 expect(sar.ok()).toBeTruthy();expect(sar.headers()['content-type']).toContain('image/webp');expect((await sar.body()).byteLength).toBeLessThan(3*1024*1024);
 await page.getByLabel('SAR variant').selectOption('raw'); await page.waitForTimeout(1200);
 await page.screenshot({path:'../docs/screenshots/real-scene-raw.png',fullPage:true});
 await page.getByLabel('SAR variant').selectOption('filtered'); await page.waitForTimeout(1200);
 await page.locator('.map-tools select').first().selectOption('side'); await page.waitForTimeout(1500);
 await page.screenshot({path:'../docs/screenshots/real-scene-with-candidates.png',fullPage:true});
 await page.locator('.map-tools select').first().selectOption('swipe'); await page.waitForTimeout(1500);
 await expect(page.getByLabel('Swipe curtain')).toBeVisible();
 await page.screenshot({path:'../docs/screenshots/real-scene-swipe.png',fullPage:true});
 await page.locator('.candidate-row').first().click(); await expect(page.locator('.crop-grid canvas')).toHaveCount(3);
});