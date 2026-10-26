import {test,expect} from '@playwright/test';

test('shows source-verified validation register without fabricating scene outcomes',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'Validation cases'}).click();
 await expect(page.getByRole('heading',{name:'Validation cases'})).toBeVisible();
 await expect(page.locator('.validation-case')).toHaveCount(9);
 await expect(page.getByText('princess-empress-philippines-2023')).toBeVisible();
 await expect(page.getByText('gc600-gulf-of-mexico-natural-seep')).toBeVisible();
 await expect(page.getByText('Not run; no candidate count, wind, funnel, distance or IoU is claimed.').first()).toBeVisible();
 await expect(page.locator('.validation-case a[href^="https://"]')).toHaveCount(23);
});

