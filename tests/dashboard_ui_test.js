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
  assert((await page.locator('#adminNotice').innerText()).startsWith('运行时：'),'active operation notice was overwritten');

  await cfg({reset:true,admin_delay_ms:180}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80');
  await page.evaluate(()=>{kvApplyNow.click();kvSaveRestart.click()}); await wait(500);
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply','apply+save was not serialized');
  assert(!(await page.locator('#adminNotice').innerText()).includes('下次启动'),'blocked save overwrote apply notice');

  await cfg({reset:true,status_delay_ms:1200}); await page.reload(); await wait(3500);
  s=await fixture(); assert(s.status_max===1,'status polling overlapped');

  await cfg({reset:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetUnit').selectOption('MB'); await page.locator('#kvBudgetInput').fill('255'); await page.locator('#kvApplyNow').click(); await wait(50);
  assert((await page.locator('#adminNotice').innerText()).includes('最小 256 MB'),'small MB validation missing'); s=await fixture(); assert(s.admin.length===0,'invalid MB reached server');
  await page.locator('#kvBudgetInput').fill('256.5'); await page.locator('#kvApplyNow').click(); await wait(50); s=await fixture(); assert(s.admin.length===0,'fractional MB reached server');

  await cfg({reset:true,malformed:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await wait(100); assert((await page.locator('#adminNotice').innerText()).includes('操作失败'),'malformed response not reported');
  await cfg({reset:true,forbidden:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvSaveRestart').click(); await wait(100); assert(await page.locator('#kvApplyNow').isDisabled(),'403 did not disable controls');

  await cfg({reset:true,admin_delay_ms:100,mismatch_once:true,mismatch_makes_eviction:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await wait(700);
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply,dry-run,apply','revision mismatch did not retry transaction');
  assert(s.admin[1].revision==='1'&&s.admin[3].revision==='2','apply did not echo dry-run revisions');
  const confirms=await page.evaluate(()=>window.__confirms); assert(confirms.length===1&&confirms[0].includes('90.0 GB'),'retry did not reconfirm changed eviction pressure');
  await cfg({reset:true,mismatch_remaining:2}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await wait(300);
  assert(/KV 状态持续变化|操作失败/.test(await page.locator('#adminNotice').innerText()),'revision retry cap was not actionable');
  await cfg({reset:true,eviction_fail:true}); await page.reload(); await wait(100); await page.locator('#kvBudgetInput').fill('32'); await page.locator('#kvApplyNow').click(); await wait(250);
  assert((await page.locator('#adminNotice').innerText()).includes('操作失败'),'eviction failure notice was not actionable');
  assert(!(await page.locator('#kvBudgetInput').isDisabled())&&!(await page.locator('#kvBudgetUnit').isDisabled())&&!(await page.locator('#kvApplyNow').isDisabled())&&!(await page.locator('#kvSaveRestart').isDisabled()),'500 eviction failure disabled controls');
  s=await fixture(); assert(s.kv.entries===100&&s.kv.used_bytes===(40*2**30)&&s.kv.revision==='2','eviction failure fixture did not publish truthful partial state');
  await wait(1100); assert((await page.locator('#kvUsed').innerText())==='40.0 GB'&&(await page.locator('#kvEntries').innerText())==='100','next status poll did not paint partial-eviction stats');
  await cfg({reset:true}); await page.reload(); await wait(150);
  for (const theme of ['paper','terminal','calm']) { await page.locator(`[data-theme-choice="${theme}"]`).click(); assert(await page.locator('#dashboard').getAttribute('data-theme')===theme,'theme did not apply '+theme); }
  await page.reload(); assert(await page.locator('#dashboard').getAttribute('data-theme')==='calm','theme did not persist');
  const forbidden=['Counters reset when','Token hit rate','Request hit rate','Outcomes','Used','Budget','Entries / utilization','Disk KV capacity','Current request','tokens per second'];
  const desktop=await page.evaluate(()=>({w:document.documentElement.scrollWidth,v:innerWidth,text:document.body.innerText})); assert(desktop.w<=desktop.v&&desktop.text.includes('纸面运行报告')&&desktop.text.includes('上下文窗口')&&desktop.text.includes('计数器会在此服务器进程重启时清零。')&&forbidden.every(s=>!desktop.text.includes(s)),'desktop layout or Chinese labels missing');
  await page.setViewportSize({width:390,height:844}); await wait(50); const mobile=await page.evaluate(()=>({w:document.documentElement.scrollWidth,v:innerWidth,text:document.body.innerText})); assert(mobile.w<=mobile.v&&forbidden.every(s=>!mobile.text.includes(s)),'mobile dashboard overflows or exposes English labels'); await page.setViewportSize({width:1440,height:900});
  await page.locator('#contextNextInput').fill('131072'); await page.locator('#contextSaveRestart').click(); await wait(1100); s=await fixture(); assert(s.context_admin[0].header==='1'&&s.context_admin[0].value===131072,'context admin header or payload missing'); assert((await page.locator('#contextNotice').innerText()).includes('下次启动生效，需要重启'),'context restart copy missing'); assert((await page.locator('#contextNextInput').inputValue())==='131072','polling replaced saved next-start context limit with live limit');
  await cfg({reset:true,context_forbidden:true}); await page.reload(); await wait(100); await page.locator('#contextSaveRestart').click(); await wait(50); assert(await page.locator('#contextSaveRestart').isDisabled()&&!await page.locator('#kvApplyNow').isDisabled(),'context 403 did not isolate controls');
  await cfg({reset:true,context_durable:false}); await page.reload(); await wait(100); await page.locator('#contextSaveRestart').click(); await wait(50); assert((await page.locator('#contextNotice').innerText()).includes('已提交，但尚未确认已持久化'),'context durable failure was not truthful');
  await cfg({reset:true}); await page.reload(); await wait(100); await page.locator('#callFilterCaller').fill('direct'); await page.locator('#callFilterApi').selectOption('responses'); await page.locator('#callFilterStatus').selectOption('active'); assert((await page.locator('#callsRecords').innerText()).includes('direct')&&(await page.locator('#callsRecords').innerText()).includes('进行中'),'call filters did not localize direct result'); await page.locator('#callFilterCaller').fill('恶意'); await page.locator('#callFilterApi').selectOption('chat'); await page.locator('#callFilterStatus').selectOption('failed'); assert(await page.locator('#callsRecords').locator('img,script').count()===0&&(await page.locator('#callsRecords').innerText()).includes('<script>坏</script>')&&(await page.locator('#callsRecords').innerText()).includes('失败'),'malicious calls text was parsed as markup or result was not localized');
  await cfg({reset:true,host_available:false}); await page.reload(); await wait(100); assert((await page.locator('#hostPhysical').innerText())==='不可用','unknown host was not explicit'); await cfg({offline:true}); await wait(1150); assert((await page.locator('#health').innerText())==='数据已过期','offline snapshot was not marked stale');
  await page.screenshot({path:'output/playwright/dashboard-desktop.png',fullPage:true});
  return {ok:true,double_apply:'one transaction',apply_save:'one transaction',poll_max_active:1,revision_sequence:s.admin.map(x=>x.mode),confirm_count:confirms.length};
}
