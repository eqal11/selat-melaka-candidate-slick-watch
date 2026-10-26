import {test,expect} from '@playwright/test';

// These checks use committed real SAR; unrelated live/context requests must not delay them.
test.beforeEach(async({context})=>{
 await context.route('**/api/v1/live/conditions?**',route=>route.abort('internetdisconnected'));
 await context.route('https://tile.openstreetmap.org/**',route=>route.abort('internetdisconnected'));
 await context.route('https://tiles.openseamap.org/**',route=>route.abort('internetdisconnected'));
});

test('shows the sourced validation register and honest processing status',async({page})=>{
 test.setTimeout(60000);
 const response=await page.request.get('/api/v1/validation/cases');
 expect(response.ok()).toBeTruthy();
 const register=await response.json();
 expect(register.cases.length).toBeGreaterThanOrEqual(8);
 await page.goto('/');
 await page.getByRole('button',{name:'Validation cases',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Validation cases',exact:true})).toBeVisible();
 await expect(page.locator('.validation-case')).toHaveCount(register.cases.length);
 for(const item of register.cases){
  const card=page.locator('.validation-case').filter({has:page.locator('b').filter({hasText:item.id})}).first();
  await expect(card).toBeVisible();
  for(const source of item.sources){
   await expect(card.locator(`a[href="${source.url}"]`)).toBeVisible();
  }
  const processed=(item.processing_results??[]).filter((row:{status:string})=>row.status==='processed');
  await expect(card.locator('.case-scene')).toHaveCount(processed.length);
  if(!(item.processing_results??[]).length){
   await expect(card.getByText('Not run; no detection outcome is claimed.')).toBeVisible();
  }
 }
});
