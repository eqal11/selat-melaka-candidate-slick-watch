import {test,expect} from '@playwright/test';
test('loads app and shows offline demo when API is unreachable',async({page})=>{
  await page.route('**/api/v1/**',route=>route.abort());
  await page.goto('/');
  await expect(page.getByRole('heading',{name:/Selat Melaka/})).toBeVisible();
  await page.getByRole('button',{name:/Analyze selected zone/}).click();
  await expect(page.getByText(/SYNTHETIC DEMO/).first()).toBeVisible({timeout:10000});
  await page.screenshot({path:'../docs/screenshots/offline-demo.png',fullPage:true});
});
