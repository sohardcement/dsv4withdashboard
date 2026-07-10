async page => {
  const assert=(ok,msg)=>{if(!ok)throw new Error(msg)};
  const cfg=body=>page.evaluate(body=>fetch('/fixture/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json()),body);
  const fixture=()=>page.evaluate(()=>fetch('/fixture/state').then(r=>r.json()));
  const wait=ms=>page.waitForTimeout(ms);
  await page.addInitScript(()=>{window.__confirms=[];window.confirm=message=>{window.__confirms.push(message);return true}});
  await cfg({reset:true,admin_delay_ms:180}); await page.reload(); await wait(100);
  await page.locator('#kvBudgetInput').fill('80');
  await page.evaluate(()=>{kvApplyNow.click();kvApplyNow.click()});
  assert(await page.locator('#kvBudgetInput').isDisabled()&&await page.locator('#kvBudgetUnit').isDisabled()&&await page.locator('#kvApplyNow').isDisabled()&&await page.locator('#kvSaveRestart').isDisabled(),'busy transaction did not disable all controls');
  await wait(500);
  let s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply','double apply started more than one transaction');
  assert(s.admin.every(x=>x.header==='1'),'admin header missing');
  assert((await page.locator('#adminNotice').innerText()).startsWith('Runtime:'),'active operation notice was overwritten');

  await cfg({reset:true,admin_delay_ms:180}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80');
  await page.evaluate(()=>{kvApplyNow.click();kvSaveRestart.click()}); await wait(500);
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply','apply+save was not serialized');
  assert(!(await page.locator('#adminNotice').innerText()).includes('restart'),'blocked save overwrote apply notice');

  await cfg({reset:true,status_delay_ms:1200}); await page.reload(); await wait(3500);
  s=await fixture(); assert(s.status_max===1,'status polling overlapped');

  await cfg({reset:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetUnit').selectOption('MB'); await page.locator('#kvBudgetInput').fill('255'); await page.locator('#kvApplyNow').click(); await wait(50);
  assert((await page.locator('#adminNotice').innerText()).includes('minimum 256 MB'),'small MB validation missing'); s=await fixture(); assert(s.admin.length===0,'invalid MB reached server');
  await page.locator('#kvBudgetInput').fill('256.5'); await page.locator('#kvApplyNow').click(); await wait(50); s=await fixture(); assert(s.admin.length===0,'fractional MB reached server');

  await cfg({reset:true,malformed:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await wait(100); assert((await page.locator('#adminNotice').innerText()).includes('unreadable'),'malformed response not reported');
  await cfg({reset:true,forbidden:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvSaveRestart').click(); await wait(100); assert(await page.locator('#kvApplyNow').isDisabled(),'403 did not disable controls');

  await cfg({reset:true,admin_delay_ms:100,mismatch_once:true,mismatch_makes_eviction:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await wait(700);
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply,dry-run,apply','revision mismatch did not retry transaction');
  assert(s.admin[1].revision==='1'&&s.admin[3].revision==='2','apply did not echo dry-run revisions');
  const confirms=await page.evaluate(()=>window.__confirms); assert(confirms.length===1&&confirms[0].includes('90.0 GB'),'retry did not reconfirm changed eviction pressure');
  await cfg({reset:true,mismatch_remaining:2}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await wait(300);
  assert((await page.locator('#adminNotice').innerText()).includes('kept changing'),'revision retry cap was not actionable');
  await cfg({reset:true,eviction_fail:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('32'); await page.locator('#kvApplyNow').click(); await wait(250);
  assert((await page.locator('#adminNotice').innerText()).includes('previous limit was restored'),'eviction failure notice was not actionable');
  assert(!(await page.locator('#kvBudgetInput').isDisabled())&&!(await page.locator('#kvBudgetUnit').isDisabled())&&!(await page.locator('#kvApplyNow').isDisabled())&&!(await page.locator('#kvSaveRestart').isDisabled()),'500 eviction failure disabled controls');
  s=await fixture(); assert(s.kv.entries===100&&s.kv.used_bytes===(40*2**30)&&s.kv.revision==='2','eviction failure fixture did not publish truthful partial state');
  await wait(1100); assert((await page.locator('#kvUsed').innerText())==='40.0 GB'&&(await page.locator('#kvEntries').innerText())==='100','next status poll did not paint partial-eviction stats');
  return {ok:true,double_apply:'one transaction',apply_save:'one transaction',poll_max_active:1,revision_sequence:s.admin.map(x=>x.mode),confirm_count:confirms.length};
}
