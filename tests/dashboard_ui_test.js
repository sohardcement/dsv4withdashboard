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
  await cfg({reset:true}); await page.evaluate(()=>localStorage.setItem('ds4-dashboard-mode','not-a-mode')); await page.reload(); await wait(150);
  assert(await page.locator('#dashboard').getAttribute('data-mode')==='management','management must be the default mode');
  assert(await page.locator('#managementLayout').isVisible(),'management layout must be visible by default');
  assert(await page.locator('#monitorLayout').getAttribute('hidden')===''&&await page.locator('#monitorLayout').getAttribute('aria-hidden')==='true','monitor layout must be hidden by default');
  assert(await page.locator('[data-mode-choice="management"]').getAttribute('aria-pressed')==='true','management mode button must be pressed by default');
  assert(await page.locator('#paperLayout,#terminalLayout,#calmLayout').count()===0,'legacy theme roots must be absent');
  const tokens=await page.evaluate(()=>{const s=getComputedStyle(document.documentElement);return ['paper','surface','ink','muted','line','accent','success','danger'].map(name=>s.getPropertyValue('--'+name).trim())});
  assert(tokens.join(',')==='#f3f0e7,#f8f5ed,#171a1d,#706d65,#c4bfb4,#df4932,#28734b,#a52a1c','precision instrument tokens do not match the approved palette');
  const headings=page.locator('h1'); assert(await headings.count()===1&&(await headings.innerText()).includes('DS4'),'dashboard must have one DS4 page heading');
  const brand=page.locator('h1 a[href="#managementSummary"]');
  assert(await brand.count()===1&&await brand.locator('[aria-hidden="true"]').count()===1,'brand anchor or status glyph is missing');
  assert(await page.getByRole('navigation',{name:'Dashboard 模式'}).locator('[data-mode-choice]').count()===2,'labeled mode navigation is missing');
  assert(await page.locator('#connectionState>[aria-hidden="true"]').count()===1&&await page.locator('#connectionState>#health').count()===1&&await page.locator('#connectionState>#updatedAt').count()===1,'connection scaffold is incomplete');
  assert(await page.locator('#managementSummary').count()===1,'management summary anchor target is missing');
  await page.evaluate(()=>document.activeElement.blur());
  for (const expected of ['brand','management','monitor']) {
    await page.keyboard.press('Tab');
    const focused=await page.evaluate(()=>{const e=document.activeElement,s=getComputedStyle(e);return {brand:e.matches('h1 a[href="#managementSummary"]'),choice:e.dataset.modeChoice||'',style:s.outlineStyle,width:parseFloat(s.outlineWidth)}});
    assert((expected==='brand'?focused.brand:focused.choice===expected)&&focused.style!=='none'&&focused.width>0,'keyboard focus order or visible outline failed at '+expected);
  }
  await page.locator('#kvBudgetUnit').selectOption('MB'); await page.locator('#kvBudgetInput').fill('255'); await page.locator('#callFilterCaller').fill('direct'); await page.locator('#kvApplyNow').click(); await wait(50);
  const preserved=await page.evaluate(()=>({kv:document.getElementById('kvBudgetInput').value,filter:document.getElementById('callFilterCaller').value,notice:document.getElementById('adminNotice').textContent}));
  await page.locator('[data-mode-choice="monitor"]').click();
  assert(await page.locator('#dashboard').getAttribute('data-mode')==='monitor','monitor mode did not apply');
  assert(await page.locator('#managementLayout').getAttribute('hidden')===''&&await page.locator('#managementLayout').getAttribute('aria-hidden')==='true'&&await page.locator('#monitorLayout').getAttribute('hidden')===null&&await page.locator('#monitorLayout').getAttribute('aria-hidden')==='false','mode roots did not switch to monitor');
  await page.locator('[data-mode-choice="management"]').click();
  const restored=await page.evaluate(()=>({kv:document.getElementById('kvBudgetInput').value,filter:document.getElementById('callFilterCaller').value,notice:document.getElementById('adminNotice').textContent}));
  assert(JSON.stringify(restored)===JSON.stringify(preserved)&&preserved.notice.includes('最小 256 MB'),'mode switching reset unsaved management state');
  await page.locator('[data-mode-choice="monitor"]').click();
  await page.reload(); await wait(150);
  assert(await page.locator('#dashboard').getAttribute('data-mode')==='monitor','monitor mode did not persist');
  assert(await page.locator('#monitorLayout').getAttribute('hidden')===null&&await page.locator('#monitorLayout').getAttribute('aria-hidden')==='false','persisted monitor root state is wrong');
  await page.locator('[data-mode-choice="management"]').click();
  assert(await page.locator('#dashboard').getAttribute('data-mode')==='management','management mode did not reapply');
  assert(await page.locator('#managementLayout').isVisible()&&await page.locator('#monitorLayout').getAttribute('hidden')===''&&await page.locator('#monitorLayout').getAttribute('aria-hidden')==='true','mode roots did not switch back to management');
  assert(await page.locator('#dashboard').locator('#contextSaveRestart,#kvApplyNow,#kvSaveRestart').count()===3,'shared administration controls disappeared');
  const forbidden=['Counters reset when','Token hit rate','Request hit rate','Outcomes','Used','Budget','Entries / utilization','Disk KV capacity','Current request','tokens per second'];
  const desktop=await page.evaluate(()=>({w:document.documentElement.scrollWidth,v:innerWidth,text:document.body.innerText})); assert(desktop.w<=desktop.v&&desktop.text.includes('管理模式')&&desktop.text.includes('上下文窗口')&&desktop.text.includes('计数器会在此服务器进程重启时清零。')&&forbidden.every(s=>!desktop.text.includes(s)),'desktop layout or Chinese labels missing');
  await page.setViewportSize({width:390,height:844}); await wait(50); const mobile=await page.evaluate(()=>({w:document.documentElement.scrollWidth,v:innerWidth,text:document.body.innerText})); assert(mobile.w<=mobile.v&&forbidden.every(s=>!mobile.text.includes(s)),'mobile dashboard overflows or exposes English labels'); await page.setViewportSize({width:1440,height:900});
  assert((await page.locator('#contextNextInput').getAttribute('min'))==='4096','context input minimum does not match server');
  await page.locator('#contextNextInput').fill('4095'); await page.locator('#contextSaveRestart').click(); await wait(50); s=await fixture(); assert(s.context_admin.length===0,'below-minimum context reached server'); assert((await page.locator('#contextNotice').innerText()).includes('4,096 到 2,147,483,647')&&await page.locator('#contextNotice').evaluate(e=>e.className==='notice bad'),'invalid context did not show actionable Chinese error');
  await page.locator('#contextNextInput').fill('2147483648'); await page.locator('#contextSaveRestart').click(); await wait(50); s=await fixture(); assert(s.context_admin.length===0,'above-maximum context reached server');
  await page.locator('#contextNextInput').fill('131072'); await page.locator('#contextSaveRestart').click(); await wait(1100); s=await fixture(); assert(s.context_admin[0].header==='1'&&s.context_admin[0].value===131072,'context admin header or payload missing'); assert((await page.locator('#contextNotice').innerText()).includes('下次启动生效，需要重启'),'context restart copy missing'); assert((await page.locator('#contextNextInput').inputValue())==='131072','polling replaced saved next-start context limit with live limit');
  await cfg({reset:true,context_fail_once:true}); await page.reload(); await wait(100); await page.locator('#contextNextInput').fill('131072'); await page.locator('#contextSaveRestart').click(); await wait(50); assert((await page.locator('#contextNotice').innerText()).includes('上下文设置失败，请检查数值后重试。')&&await page.locator('#contextNotice').evaluate(e=>e.className==='notice bad'),'context failure was not localized or marked bad'); await page.locator('#contextSaveRestart').click(); await wait(50); s=await fixture(); assert(s.context_admin.length===2&&(await page.locator('#contextNotice').innerText()).includes('下次启动生效，需要重启。')&&await page.locator('#contextNotice').evaluate(e=>e.className==='notice'),'context success retry did not clear error notice');
  await cfg({reset:true,context_forbidden:true}); await page.reload(); await wait(100); await page.locator('#contextSaveRestart').click(); await wait(50); assert(await page.locator('#contextSaveRestart').isDisabled()&&!await page.locator('#kvApplyNow').isDisabled(),'context 403 did not isolate controls');
  await cfg({reset:true,context_durable:false}); await page.reload(); await wait(100); await page.locator('#contextSaveRestart').click(); await wait(50); assert((await page.locator('#contextNotice').innerText()).includes('已提交，但尚未确认已持久化'),'context durable failure was not truthful');
  await cfg({reset:true}); await page.reload(); await wait(100); assert(await page.locator('#callFilterClient').count()===1,'service filter missing'); assert((await page.locator('#callsRecords').innerText()).includes('hanako-agent'),'service column missing'); assert((await page.locator('#callsCallers').innerText()).includes('hermes-agent'),'service/IP aggregate missing'); await page.locator('#callFilterClient').selectOption('hanako-agent'); assert((await page.locator('#callsRecords').innerText()).includes('hanako-agent')&&!(await page.locator('#callsRecords').innerText()).includes('hermes-agent'),'service filter did not narrow records'); await page.locator('#callFilterClient').selectOption('<img src=x onerror=alert(1)>'); assert(await page.locator('#callsRecords').locator('img,script').count()===0&&(await page.locator('#callsRecords').innerText()).includes('<script>坏</script>')&&(await page.locator('#callsRecords').innerText()).includes('失败'),'malicious service or calls text was parsed as markup or result was not localized'); await page.locator('#callFilterClient').selectOption(''); await page.locator('#callFilterCaller').fill('direct'); await page.locator('#callFilterApi').selectOption('responses'); await page.locator('#callFilterStatus').selectOption('active'); assert((await page.locator('#callsRecords').innerText()).includes('direct')&&(await page.locator('#callsRecords').innerText()).includes('进行中'),'existing call filters did not localize direct result');
  await cfg({reset:true,host_available:false}); await page.reload(); await wait(100); assert((await page.locator('#hostPhysical').innerText())==='不可用','unknown host was not explicit'); await cfg({offline:true}); await wait(1150); assert((await page.locator('#health').innerText())==='数据已过期','offline snapshot was not marked stale');
  await page.screenshot({path:'output/playwright/dashboard-management-desktop.png',fullPage:true});
  return {ok:true,double_apply:'one transaction',apply_save:'one transaction',poll_max_active:1,revision_sequence:s.admin.map(x=>x.mode),confirm_count:confirms.length};
}
