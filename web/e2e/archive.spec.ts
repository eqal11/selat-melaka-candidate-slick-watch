import {test,expect} from '@playwright/test';

// These checks use committed real SAR; unrelated live/context requests must not delay them.
test.beforeEach(async({context})=>{
 await context.route('**/api/v1/live/conditions?**',route=>route.abort('internetdisconnected'));
 await context.route('https://tile.openstreetmap.org/**',route=>route.abort('internetdisconnected'));
 await context.route('https://tiles.openseamap.org/**',route=>route.abort('internetdisconnected'));
});

test('replays a committed real Sentinel-1 SAR image with its own archived polygons',async({page})=>{
 test.setTimeout(60000);
 const response=await page.request.get('/api/v1/history');
 expect(response.ok()).toBeTruthy();
 const archive=await response.json();
 const entry=archive.entries.find((row:{scene_id:string,count:number,preview_raw?:string,preview_filtered?:string})=>row.scene_id.includes('20261002T113320')&&row.count>0&&row.preview_raw&&row.preview_filtered);
 expect(entry,'The checked-in real scene and its imagery must remain available').toBeTruthy();
 const polygonsResponse=await page.request.get(`/api/v1/history/${entry.id}/candidates.geojson`);
 expect(polygonsResponse.ok()).toBeTruthy();
 const polygons=await polygonsResponse.json();
 expect(polygons.features.length).toBe(entry.count);
 await page.goto('/');
 await page.getByRole('button',{name:'History',exact:true}).click();
 const raw=page.waitForResponse(r=>new URL(r.url()).pathname===`/api/v1/history/${entry.id}/raw.webp`&&r.status()===200);
 const filtered=page.waitForResponse(r=>new URL(r.url()).pathname===`/api/v1/history/${entry.id}/filtered.webp`&&r.status()===200);
 await page.locator('.history-entry').filter({hasText:entry.scene_id}).click();
 for(const image of await Promise.all([raw,filtered])){
  expect(image.headers()['content-type']).toContain('image/webp');
  expect((await image.body()).byteLength).toBeGreaterThan(0);
  expect((await image.body()).byteLength).toBeLessThan(3*1024*1024);
 }
 await expect(page.getByText('REAL Sentinel‑1 archive replay',{exact:true})).toBeVisible();
 await expect(page.locator('.map-pane canvas.maplibregl-canvas')).toHaveCount(2);
 await expect.poll(async()=>Number(await page.locator('.map-pane').last().getAttribute('data-rendered-candidate-count')),{timeout:30000}).toBeGreaterThan(0);
 await page.screenshot({path:'test-results/real-archive-sar-and-polygons.png',fullPage:true});
});
