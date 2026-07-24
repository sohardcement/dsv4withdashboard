async page => {
  const assert=(ok,msg)=>{if(!ok)throw new Error(msg)};
  const dashboardUrl=page.url(),dashboardBase=dashboardUrl.replace(/\/$/,''),fixtureUrl=dashboardBase+'/fixture/state',configUrl=dashboardBase+'/fixture/config';
  const cfg=body=>page.evaluate(body=>fetch('/fixture/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json()),body);
  const cfgApi=body=>page.request.post(configUrl,{data:body}).then(r=>r.json());
  const fixture=()=>page.evaluate(()=>fetch('/fixture/state').then(r=>r.json()));
  const fixtureApi=()=>page.request.get(fixtureUrl).then(r=>r.json());
  const wait=ms=>page.waitForTimeout(ms);
  const waitKvState=state=>page.waitForFunction(state=>document.getElementById('dashboard').dataset.kvState===state,state);
  const waitAdmin=modes=>page.waitForFunction(async modes=>(await fetch('/fixture/state').then(r=>r.json())).admin.map(x=>x.mode).join(',')===modes,modes);
  const waitStatusIdle=async()=>{const deadline=Date.now()+8000;while(Date.now()<deadline){if((await fixtureApi()).status_active===0)return;await wait(100)}throw new Error('timed out waiting for delayed status handlers to drain')};
  const reloadReady=async()=>{await page.reload();await page.waitForFunction(()=>online===true&&lastUpdatedAt>0&&!['等待中','不可用'].includes(document.getElementById('health').textContent)&&document.getElementById('dashboard').dataset.kvState==='idle'&&['kvBudgetInput','kvBudgetUnit','kvApplyNow','kvSaveRestart','contextNextInput','contextSaveRestart'].every(id=>!document.getElementById(id).disabled))};
  await cfg({reset:true,status_delay_ms:800}); await page.reload(); await page.setViewportSize({width:1200,height:900});
  assert(await page.evaluate(()=>['kvBudgetInput','kvBudgetUnit','kvApplyNow','kvSaveRestart','kvConfirmApply','kvCancelApply','contextNextInput','contextSaveRestart'].every(id=>document.getElementById(id).disabled)),'administration controls were enabled before the first good snapshot');
  await page.evaluate(async()=>{kvBudgetInput.value='80';contextNextInput.value='131072';await Promise.all([checkKvImpact(),persistKvBudget(),confirmKvApply(),saveContext()]);kvApplyNow.click();kvSaveRestart.click();contextSaveRestart.click()});
  let s=await fixture(); assert(s.admin.length===0&&s.context_admin.length===0,'pre-snapshot handlers reached an administration endpoint');
  await page.waitForFunction(()=>online===true&&lastUpdatedAt>0&&!kvApplyNow.disabled&&!contextSaveRestart.disabled); await page.locator('[data-mode-choice="management"]').click();
  await cfg({reset:true,admin_delay_ms:180}); await reloadReady();
  await page.locator('#kvBudgetInput').fill('80');
  await page.evaluate(()=>{kvApplyNow.click();kvApplyNow.click()});
  assert(await page.locator('#kvBudgetInput').isDisabled()&&await page.locator('#kvBudgetUnit').isDisabled()&&await page.locator('#kvApplyNow').isDisabled()&&await page.locator('#kvSaveRestart').isDisabled(),'checking did not disable all controls');
  await waitAdmin('dry-run'); await waitKvState('review');
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run','review performed more than one dry-run or applied immediately');
  assert(s.admin.every(x=>x.header==='1'),'admin header missing');
  const review=page.locator('#kvReview'); assert(await review.count()===1&&await review.isVisible(),'KV impact review did not open exactly once');
  assert(await review.getAttribute('tabindex')==='-1'&&await review.getAttribute('aria-labelledby')==='kvReviewTitle'&&await page.locator('#dashboard').getAttribute('data-kv-state')==='review','KV review semantics or state marker are missing');
  assert((await review.innerText()).includes('64.0 GB → 80.0 GB')&&(await review.innerText()).includes('需要清理\n否'),'review did not show the budget change and explicit cleanup decision');
  assert(await page.evaluate(()=>document.activeElement===document.getElementById('kvReview')),'review did not receive focus');
  assert(await page.locator('#kvConfirmApply').isVisible()&&await page.locator('#kvCancelApply').isVisible(),'review actions are missing');
  assert(await page.locator('#kvBudgetInput').isDisabled()&&await page.locator('#kvBudgetUnit').isDisabled()&&await page.locator('#kvApplyNow').isDisabled()&&await page.locator('#kvSaveRestart').isDisabled(),'review did not keep all KV controls locked');
  await page.locator('#kvCancelApply').click();
  assert(!(await review.isVisible())&&(await page.locator('#kvBudgetInput').inputValue())==='80','cancel did not hide review or retain target');
  assert(await page.evaluate(()=>document.activeElement===kvApplyNow),'cancel did not restore focus to apply trigger');
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run','cancel contacted the server');
  await page.locator('#kvApplyNow').click(); await waitKvState('review'); await page.locator('#kvConfirmApply').click();
  assert(await page.locator('#kvBudgetInput').isDisabled()&&await page.locator('#kvBudgetUnit').isDisabled()&&await page.locator('#kvApplyNow').isDisabled()&&await page.locator('#kvSaveRestart').isDisabled(),'applying did not keep all KV controls locked');
  await waitAdmin('dry-run,dry-run,apply'); await waitKvState('success'); s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,dry-run,apply','explicit confirmation did not apply the reviewed revision');
  assert((await page.locator('#adminNotice').innerText()).startsWith('运行时：'),'runtime success notice was overwritten');
  assert(!(await page.locator('#kvApplyNow').isDisabled()),'successful apply did not restore controls');

  await cfg({reset:true}); await reloadReady(); await page.locator('#kvBudgetInput').fill('32'); await page.locator('#kvApplyNow').click(); await waitAdmin('dry-run'); await waitKvState('review');
  assert((await review.innerText()).includes('需要清理\n是')&&(await review.innerText()).includes('预计清理\n28 条')&&(await review.innerText()).includes('预计释放\n14.0 GB'),'real shrink review did not show projected positive cleanup and released bytes');
  await page.locator('#kvConfirmApply').click(); await waitAdmin('dry-run,apply'); await waitKvState('success'); s=await fixture();
  assert(s.kv.budget_bytes===32*2**30&&s.kv.used_bytes===32*2**30&&s.kv.entries===88,'confirmed real shrink did not apply the reviewed projection');

  await cfg({reset:true,admin_delay_ms:180}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80');
  await page.evaluate(()=>{kvApplyNow.click();kvSaveRestart.click()}); await waitAdmin('dry-run'); await waitKvState('review');
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run','apply+save was not serialized');
  assert(!(await page.locator('#adminNotice').innerText()).includes('下次启动'),'blocked save overwrote apply notice');
  await cfg({reset:true,admin_delay_ms:180}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80');
  await page.evaluate(()=>{kvSaveRestart.click();kvSaveRestart.click();kvApplyNow.click()});
  assert(await page.locator('#dashboard').getAttribute('data-kv-state')==='saving'&&await page.locator('#kvBudgetInput').isDisabled()&&await page.locator('#kvBudgetUnit').isDisabled()&&await page.locator('#kvApplyNow').isDisabled()&&await page.locator('#kvSaveRestart').isDisabled(),'saving did not lock all KV controls');
  await waitAdmin('persist'); await waitKvState('success'); s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='persist','save double-click or apply interleaved with persistence'); assert(await page.evaluate(()=>document.activeElement===kvSaveRestart),'save success did not restore focus to its trigger');

  await cfg({reset:true}); await reloadReady(); const independentNotice=await page.locator('#adminNotice').innerText();
  await page.locator('#kvBudgetInput').fill('80'); await page.waitForFunction(()=>kvTargetState.textContent.includes('尚未应用到当前运行时'));
  assert((await page.locator('#adminNotice').innerText())===independentNotice,'dirty target state overwrote the operation result notice');
  await page.locator('#kvBudgetInput').fill('64'); await page.waitForFunction(()=>kvTargetState.textContent.includes('与当前运行时一致'));
  await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvSaveRestart').click(); await waitAdmin('persist'); await waitKvState('success');
  assert((await page.locator('#kvTargetState').innerText()).includes('尚未应用到当前运行时')&&(await page.locator('#adminNotice').innerText()).includes('下次启动'),'persist-only save falsely marked the runtime target aligned or lost its operation result');
  await page.locator('#kvApplyNow').click(); await waitKvState('review'); await page.locator('#kvConfirmApply').click(); await waitAdmin('persist,dry-run,apply'); await waitKvState('success');
  await page.waitForFunction(()=>kvTargetState.textContent.includes('与当前运行时一致'));
  assert((await page.locator('#adminNotice').innerText()).startsWith('运行时：'),'runtime alignment overwrote the apply result');

  await cfg({reset:true,status_delay_ms:1200}); await page.reload(); await wait(3500);
  s=await fixture(); assert(s.status_max===1,'status polling overlapped');

  await cfg({reset:true}); await reloadReady(); const delayedKv=await page.locator('#kvUsed').innerText(); await cfg({status_delay_ms:5000});
  await page.waitForFunction(()=>document.getElementById('dashboard').classList.contains('stale')&&document.getElementById('health').textContent==='数据已过期',null,{timeout:4500});
  const delayedAge=await page.locator('#updatedAt').innerText(); await page.waitForFunction(previous=>document.getElementById('updatedAt').textContent!==previous,delayedAge,{timeout:2500});
  assert((await page.locator('#updatedAt').innerText()).includes('秒前更新')&&(await page.locator('#kvUsed').innerText())===delayedKv&&await page.locator('#kvApplyNow').isDisabled()&&await page.locator('#contextSaveRestart').isDisabled(),'timed-out status did not age independently, retain data, or disable administration');
  await page.goto('about:blank'); await cfgApi({status_delay_ms:0}); await waitStatusIdle(); s=await fixtureApi(); assert(s.status_active===0,'delayed status handlers did not drain before fixture reset');
  await cfgApi({reset:true}); await page.goto(dashboardUrl); await page.waitForFunction(()=>online===true&&lastUpdatedAt>0&&document.getElementById('dashboard').dataset.kvState==='idle'&&!document.getElementById('kvApplyNow').disabled); const malformedKv=await page.locator('#kvUsed').innerText(),malformedUpdatedAt=await page.evaluate(()=>lastUpdatedAt); await cfg({status_patch:{calls:{records:null}}});
  await page.waitForFunction(()=>document.getElementById('dashboard').classList.contains('stale'),null,{timeout:3500});
  assert((await page.locator('#kvUsed').innerText())===malformedKv&&(await page.locator('#managementRecentCalls').innerText()).includes('hanako-agent')&&await page.evaluate(previous=>lastUpdatedAt===previous,malformedUpdatedAt),'malformed structural snapshot replaced the last good snapshot or reset freshness');
  await cfg({reset:true}); await page.waitForFunction(()=>!document.getElementById('dashboard').classList.contains('stale')&&!document.getElementById('kvApplyNow').disabled,null,{timeout:3500});
  await cfg({status_patch:{prefill:{avg_tps:1900.4}}}); await page.waitForFunction(()=>document.getElementById('monitorPrefill').dataset.motionDirection==='increase'); await wait(500);
  await cfg({status_patch:{calls:{records:null}}}); await page.waitForFunction(()=>document.getElementById('dashboard').classList.contains('stale'),null,{timeout:3500});
  await cfg({reset:true}); await page.waitForFunction(()=>!document.getElementById('dashboard').classList.contains('stale')&&document.getElementById('monitorPrefill').dataset.motionDirection==='none',null,{timeout:3500}); assert(await page.locator('#monitorPrefill .metric-value-layer-in-increase').count()===0&&await page.locator('#monitorPrefill .metric-value-layer').count()===1,'stale recovery reused the pre-outage metric baseline');
  for(const [patch,label] of [[{queue_depth:null},'queue depth'],[{context:{remaining:null}},'context remaining'],[{kv_cache:{used_bytes:'bad'}},'KV used bytes']]){
    const before=await page.evaluate(()=>({updated:lastUpdatedAt,queue:managementQueue.textContent,context:managementContext.textContent,kv:kvUsed.textContent}));
    await cfg({status_patch:patch}); await page.waitForFunction(()=>document.getElementById('dashboard').classList.contains('stale'),null,{timeout:3500});
    const after=await page.evaluate(()=>({updated:lastUpdatedAt,queue:managementQueue.textContent,context:managementContext.textContent,kv:kvUsed.textContent}));
    assert(JSON.stringify(after)===JSON.stringify(before),label+' invalid snapshot partially painted or changed lastUpdatedAt');
    await cfg({reset:true}); await page.waitForFunction(previous=>!document.getElementById('dashboard').classList.contains('stale')&&lastUpdatedAt>previous,before.updated,{timeout:3500});
  }

  await cfg({reset:true}); await reloadReady(); await page.locator('#kvBudgetUnit').selectOption('MB'); await page.locator('#kvBudgetInput').fill('255'); await page.locator('#kvApplyNow').click(); await waitKvState('error');
  assert((await page.locator('#adminNotice').innerText()).includes('最小 256 MB')&&await page.locator('#kvBudgetInput').getAttribute('aria-invalid')==='true'&&await page.locator('#kvBudgetUnit').getAttribute('aria-invalid')==='true','small MB validation or invalid semantics missing'); s=await fixture(); assert(s.admin.length===0,'invalid MB reached server');
  await page.locator('#kvBudgetInput').fill('256'); assert(await page.locator('#kvBudgetInput').getAttribute('aria-invalid')==='false'&&await page.locator('#kvBudgetUnit').getAttribute('aria-invalid')==='false','KV edit did not clear invalid semantics');
  await page.locator('#kvBudgetInput').fill('256.5'); await page.locator('#kvApplyNow').click(); s=await fixture(); assert(s.admin.length===0,'fractional MB reached server');

  await cfg({reset:true,malformed:true}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await waitKvState('error'); assert((await page.locator('#adminNotice').innerText()).includes('操作失败'),'malformed response not reported');
  await cfg({reset:true,forbidden:true}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvSaveRestart').click(); await waitKvState('error'); assert(await page.locator('#kvApplyNow').isDisabled(),'403 did not disable controls');
  await cfg({reset:true}); await reloadReady(); await page.route('**/ds4/admin/kv-cache',route=>route.fulfill({status:403,contentType:'text/plain',body:'forbidden'})); await page.locator('#kvSaveRestart').click(); await waitKvState('error'); assert(await page.locator('#kvApplyNow').isDisabled()&&!await page.locator('#contextSaveRestart').isDisabled()&&(await page.locator('#adminNotice').innerText()).includes('仅可从本机管理'),'non-JSON 403 did not isolate only KV controls'); await page.unroute('**/ds4/admin/kv-cache');

  const rejectRuntime=async(patch,label)=>{await cfg({reset:true,runtime_patch:patch});await reloadReady();await page.locator('#kvBudgetInput').fill('80');await page.locator('#kvApplyNow').click();await waitKvState('error');assert((await page.locator('#adminNotice').innerText()).includes('运行时结果无法读取')&&!(await review.isVisible()),label+' runtime contract was accepted')};
  await rejectRuntime({after_bytes:null},'missing field');
  await rejectRuntime({before_entries:'116'},'wrong numeric type');
  await rejectRuntime({after_bytes:50465865729},'inconsistent after value');
  await rejectRuntime({attempted:false},'unattempted dry-run');
  await rejectRuntime({applied:true},'applied dry-run');
  await rejectRuntime({revision:'bogus'},'unusable revision');
  await rejectRuntime({new_budget_bytes:79*2**30},'mismatched requested target');
  await rejectRuntime({eviction_required:true},'inconsistent eviction decision');
  await rejectRuntime({after_bytes:48318382080},'release without eviction');
  await cfg({reset:true,runtime_patch:{after_bytes:42949672960}}); await reloadReady(); await page.locator('#kvBudgetInput').fill('32'); await page.locator('#kvApplyNow').click(); await waitKvState('error'); assert(!(await review.isVisible()),'runtime bytes above the requested target reached review');
  await cfg({reset:true,runtime_patch:{after_entries:116}}); await reloadReady(); await page.locator('#kvBudgetInput').fill('32'); await page.locator('#kvApplyNow').click(); await waitKvState('error'); s=await fixture(); assert(!(await review.isVisible())&&s.kv.entries===116&&s.kv.used_bytes===46*2**30,'dry-run bytes release without entry removal was accepted or mutated fixture state');
  await cfg({reset:true,apply_runtime_patch:{after_entries:116}}); await reloadReady(); await page.locator('#kvBudgetInput').fill('32'); await page.locator('#kvApplyNow').click(); await waitKvState('review'); await page.locator('#kvConfirmApply').click(); await waitAdmin('dry-run,apply'); await waitKvState('error'); s=await fixture(); assert(s.kv.entries===88&&s.kv.used_bytes===32*2**30,'apply response patch mutated source state instead of only corrupting the response');
  await cfg({reset:true,apply_runtime_patch:{after_entries:'116'}}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await waitKvState('review'); await page.locator('#kvConfirmApply').click(); await waitAdmin('dry-run,apply'); await waitKvState('error'); assert((await page.locator('#adminNotice').innerText()).includes('运行时结果无法读取'),'malformed successful apply runtime was accepted');
  await cfg({reset:true,apply_runtime_patch:{new_budget_bytes:79*2**30}}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await waitKvState('review'); await page.locator('#kvConfirmApply').click(); await waitAdmin('dry-run,apply'); await waitKvState('error'); assert((await page.locator('#adminNotice').innerText()).includes('运行时结果无法读取'),'mismatched successful apply target was accepted');

  await cfg({reset:true}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await waitKvState('review'); await cfg({offline:true}); await page.waitForFunction(()=>document.getElementById('kvConfirmApply').disabled&&!document.getElementById('kvCancelApply').disabled);
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run','offline review changed transaction before confirmation'); await page.evaluate(()=>confirmKvApply()); s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run','stale offline review applied'); await page.locator('#kvCancelApply').click(); assert(!(await review.isVisible())&&await page.evaluate(()=>document.activeElement===document.getElementById('kvCapacity')),'offline review cancel did not close and move focus to a safe fallback');
  await cfg({reset:true}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await waitKvState('review'); await cfg({kv:{enabled:false,budget_bytes:68719476736,used_bytes:49392123904,entries:116,revision:'1'}}); await page.waitForFunction(()=>document.getElementById('kvConfirmApply').disabled&&!document.getElementById('kvCancelApply').disabled);
  await page.evaluate(()=>confirmKvApply()); s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run','disabled-cache review applied'); await page.locator('#kvCancelApply').click(); assert(!(await review.isVisible())&&await page.evaluate(()=>document.activeElement===document.getElementById('kvCapacity')),'disabled-cache review cancel did not close and move focus to a safe fallback');

  await cfg({reset:true,mismatch_once:true,mismatch_runtime_patch:{before_bytes:90*2**30,after_bytes:80*2**30,before_entries:150,after_entries:140,eviction_required:true}}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await waitKvState('review'); await page.locator('#kvConfirmApply').click(); await waitAdmin('dry-run,apply,dry-run'); await waitKvState('review');
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply,dry-run'&&(await review.innerText()).includes('需要清理\n是'),'changed eviction flag was auto-applied instead of reviewed');

  await cfg({reset:true,admin_delay_ms:100,mismatch_once:true,mismatch_makes_eviction:true}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await waitKvState('review'); await page.locator('#kvConfirmApply').click(); await waitAdmin('dry-run,apply,dry-run'); await waitKvState('review');
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply,dry-run','changed impact was silently applied');
  assert(s.admin[1].revision==='1','first apply did not echo reviewed revision');
  assert(await review.isVisible()&&(await review.innerText()).includes('90.0 GB')&&(await review.innerText()).includes('需要清理\n是')&&(await review.innerText()).includes('预计清理'),'changed eviction impact was not returned for review');
  assert(await page.evaluate(()=>document.activeElement===document.getElementById('kvReview')),'changed impact review did not receive focus');
  await page.locator('#kvConfirmApply').click(); await waitAdmin('dry-run,apply,dry-run,apply'); await waitKvState('success'); s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply,dry-run,apply'&&s.admin[3].revision==='2','second confirmation did not apply revised impact');
  await cfg({reset:true,mismatch_remaining:2}); await reloadReady(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#kvApplyNow').click(); await waitKvState('review'); await page.locator('#kvConfirmApply').click(); await waitAdmin('dry-run,apply,dry-run,apply'); await waitKvState('error');
  assert(/KV 状态持续变化|操作失败/.test(await page.locator('#adminNotice').innerText()),'revision retry cap was not actionable');
  assert(!(await page.locator('#kvApplyNow').isDisabled())&&await page.evaluate(()=>document.activeElement===kvApplyNow),'revision retry cap did not restore controls and focus');
  s=await fixture(); assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply,dry-run,apply'&&s.admin[1].revision==='1'&&s.admin[3].revision==='2','identical impact did not retry exactly once with the refreshed revision');
  await cfg({reset:true,eviction_fail:true}); await reloadReady(); await page.locator('#kvBudgetInput').fill('32'); await page.locator('#kvApplyNow').click(); await waitKvState('review'); await page.locator('#kvConfirmApply').click(); await waitAdmin('dry-run,apply'); await waitKvState('error');
  assert((await page.locator('#adminNotice').innerText()).includes('操作失败'),'eviction failure notice was not actionable');
  assert(!(await page.locator('#kvBudgetInput').isDisabled())&&!(await page.locator('#kvBudgetUnit').isDisabled())&&!(await page.locator('#kvApplyNow').isDisabled())&&!(await page.locator('#kvSaveRestart').isDisabled()),'500 eviction failure disabled controls');
  s=await fixture(); assert(s.kv.entries===100&&s.kv.used_bytes===(40*2**30)&&s.kv.revision==='2','eviction failure fixture did not publish truthful partial state');
  await page.waitForFunction(()=>document.getElementById('kvUsed').textContent==='40.0 GB'&&document.getElementById('kvEntries').textContent==='100'); assert((await page.locator('#kvUsed').innerText())==='40.0 GB'&&(await page.locator('#kvEntries').innerText())==='100','next status poll did not paint partial-eviction stats');
  await cfg({reset:true}); await page.evaluate(()=>{localStorage.setItem('ds4-dashboard-mode','not-a-mode');localStorage.setItem('ds4-dashboard-theme','not-a-theme')}); await reloadReady();
  assert(await page.locator('#dashboard').getAttribute('data-mode')==='monitor','monitor must be the default mode');
  assert(await page.locator('#monitorLayout').isVisible(),'monitor layout must be visible by default');
  assert(await page.locator('#managementLayout').getAttribute('hidden')===''&&await page.locator('#managementLayout').getAttribute('aria-hidden')==='true','management layout must be hidden by default');
  assert(await page.locator('[data-mode-choice="monitor"]').getAttribute('aria-pressed')==='true','monitor mode button must be pressed by default');
  assert((await page.getByRole('navigation',{name:'Dashboard 模式'}).locator('[data-mode-choice]').allInnerTexts()).join('/')==='管理/监控','mode choices must place management before monitor');
  await cfg({reset:true});
  await page.evaluate(()=>{
    localStorage.removeItem('ds4-dashboard-mode');
    localStorage.setItem('ds4-dashboard-theme','terminal');
  });
  await reloadReady();
  assert(await page.locator('#dashboard').getAttribute('data-mode')==='monitor','fresh dashboard must default to monitor');
  assert(await page.locator('#monitorLayout').isVisible()&&await page.locator('#managementLayout').getAttribute('hidden')==='','fresh dashboard did not expose monitor only');
  assert(await page.locator('[data-theme-choice]').count()===3&&await page.locator('.theme-switch').count()===1,'system, dark, and light-gray theme controls are incomplete');
  const lumenContract=await page.evaluate(()=>{
    const root=getComputedStyle(document.documentElement);
    const wall=document.body;
    const light=document.querySelector('.light-field');
    const shadow=document.querySelector('.light-shadow');
    const glass=document.querySelector('.glass-column');
    const optical=document.querySelector('.optical-panel');
    return {
      htmlTheme:document.documentElement.dataset.theme||'',
      themePreference:document.getElementById('dashboard').dataset.themePreference||'',
      ink:root.getPropertyValue('--ink').trim(),
      success:root.getPropertyValue('--success').trim(),
      danger:root.getPropertyValue('--danger').trim(),
      wallBackground:wall?getComputedStyle(wall).backgroundImage:'',
      lightDuration:light?getComputedStyle(light).animationDuration:'',
      lightName:light?getComputedStyle(light).animationName:'',
      shadowDuration:shadow?getComputedStyle(shadow).animationDuration:'',
      shadowName:shadow?getComputedStyle(shadow).animationName:'',
      glassBlur:glass?getComputedStyle(glass).backdropFilter:'',
      opticalBackground:optical?getComputedStyle(optical).backgroundImage:'',
      opticalTop:optical?getComputedStyle(optical).borderTopColor:'',
      opticalBottom:optical?getComputedStyle(optical).borderBottomColor:'',
      opticalCount:document.querySelectorAll('.optical-panel').length
    };
  });
  assert(['light','dark'].includes(lumenContract.htmlTheme)&&lumenContract.themePreference==='system','invalid or missing preference must fall back to the system theme');
  assert(lumenContract.success&&lumenContract.danger&&lumenContract.ink,'semantic theme tokens are missing');
  assert(lumenContract.wallBackground.includes('gradient')&&lumenContract.lightDuration==='18s'&&lumenContract.lightName==='signal-drift'&&lumenContract.shadowDuration==='26s'&&lumenContract.shadowName==='signal-shadow'&&lumenContract.glassBlur.includes('blur(30px)')&&lumenContract.opticalBackground.includes('gradient')&&lumenContract.opticalTop!==lumenContract.opticalBottom&&lumenContract.opticalCount>=4,'layered optical material, environmental light, or workbench surfaces are missing');
  await page.locator('[data-theme-choice="dark"]').click();
  assert(await page.evaluate(()=>document.documentElement.dataset.theme==='dark'&&document.getElementById('dashboard').dataset.themePreference==='dark'&&localStorage.getItem('ds4-dashboard-theme')==='dark'),'dark theme did not apply or persist');
  const darkSurface=await page.evaluate(()=>{const style=getComputedStyle(document.documentElement);return {wall:style.getPropertyValue('--wall').trim(),ink:style.getPropertyValue('--ink').trim()}});
  assert(darkSurface.wall==='#081018'&&darkSurface.ink==='#e8eef2','dark theme is not using the charcoal/blue-gray material system');
  await page.locator('[data-theme-choice="light"]').click();
  assert(await page.evaluate(()=>document.documentElement.dataset.theme==='light'&&document.getElementById('dashboard').dataset.themePreference==='light'&&localStorage.getItem('ds4-dashboard-theme')==='light'),'light-gray theme did not apply or persist');
  const lightSurface=await page.evaluate(()=>{const style=getComputedStyle(document.documentElement);return {wall:style.getPropertyValue('--wall').trim(),ink:style.getPropertyValue('--ink').trim()}});
  assert(lightSurface.wall==='#cfd3d4'&&lightSurface.ink==='#151a20','light theme is not using the neutral mist-gray material system');
  await page.locator('[data-theme-choice="system"]').click();
  assert(await page.locator('.glass-column:visible').count()===1,'the active mode must expose exactly one primary glass column');
  await page.locator('[data-mode-choice="management"]').click();
  assert(await page.locator('.glass-column:visible').count()===1,'management mode must expose exactly one primary glass column');
  const legacyLayoutSelector=['paper','terminal','calm'].map(name=>'#'+name+'Layout').join(','); assert(await page.locator(legacyLayoutSelector).count()===0,'legacy theme roots must be absent');
  const headings=page.locator('h1'); assert(await headings.count()===2&&await page.locator('h1:visible').count()===1&&(await page.locator('h1:visible').innerText())==='运行与容量','management mode must expose exactly one visible page heading');
  const brand=page.locator('.brand a[href="#managementSummary"]');
  assert(await brand.count()===1&&await brand.locator('[aria-hidden="true"]').count()===1,'brand anchor or status glyph is missing');
  assert(await page.getByRole('navigation',{name:'Dashboard 模式'}).locator('[data-mode-choice]').count()===2,'labeled mode navigation is missing');
  assert(await page.locator('#connectionState>#connectionPulse[aria-hidden="true"]').count()===1&&await page.locator('#connectionState>#health').count()===1&&await page.locator('#connectionState>#updatedAt').count()===1,'connection signal scaffold is incomplete');
  assert(await page.locator('label[for="kvBudgetUnit"]').isVisible()&&await page.locator('label[for="callFilterCaller"],label[for="callFilterClient"],label[for="callFilterApi"],label[for="callFilterStatus"]').count()===4,'compact visible unit or monitor filter labels are missing');
  assert((await page.locator('#kvBudgetInput').getAttribute('aria-describedby'))==='budgetHelp kvTargetState adminNotice'&&(await page.locator('#kvBudgetUnit').getAttribute('aria-describedby'))==='budgetHelp kvTargetState adminNotice'&&(await page.locator('#contextNextInput').getAttribute('aria-describedby'))==='contextEffect contextNotice','administration controls are not associated with help and result text');
  const legacyLabels=['纸面运行报告','深色控制台','从容解释型','Token hit rate','Request hit rate','Disk KV capacity','Current request','tokens per second'];
  const visibleText=await page.locator('body').innerText(); assert(legacyLabels.every(label=>!visibleText.includes(label)),'legacy theme names or former English product labels remain visible');
  await page.setViewportSize({width:1200,height:900}); const shortControls=await page.locator('a:visible,button:visible,input:visible,select:visible').evaluateAll(nodes=>nodes.filter(node=>node.getBoundingClientRect().height<43.5).map(node=>node.id||node.textContent));
  assert(shortControls.length===0,'management mode has controls shorter than 44px: '+shortControls.join(','));
  assert(await page.locator('#managementSummary').count()===1,'management summary anchor target is missing');
  await page.locator('[data-mode-choice="management"]').click(); await page.evaluate(()=>document.activeElement.blur());
  for (const expected of ['brand','management','monitor']) {
    const focusTarget=expected==='brand'?'.brand a':`[data-mode-choice="${expected}"]`; await page.locator(focusTarget).focus();
    const focused=await page.evaluate(()=>{const e=document.activeElement,s=getComputedStyle(e);return {brand:e.matches('.brand a[href="#managementSummary"]'),choice:e.dataset.modeChoice||'',style:s.outlineStyle,width:parseFloat(s.outlineWidth)}});
    assert((expected==='brand'?focused.brand:focused.choice===expected),'focus target is not reachable at '+expected);
  }
  await page.locator('#kvBudgetUnit').selectOption('MB'); await page.locator('#kvBudgetInput').fill('255'); await page.locator('#contextNextInput').fill('131071'); await page.locator('#kvApplyNow').click(); await waitKvState('error');
  await page.locator('[data-mode-choice="monitor"]').click();
  assert(await page.locator('#dashboard').getAttribute('data-mode')==='monitor','monitor mode did not apply');
  assert(await page.locator('#managementLayout').getAttribute('hidden')===''&&await page.locator('#managementLayout').getAttribute('aria-hidden')==='true'&&await page.locator('#monitorLayout').getAttribute('hidden')===null&&await page.locator('#monitorLayout').getAttribute('aria-hidden')==='false','mode roots did not switch to monitor');
  assert(await page.locator('h1:visible').count()===1&&(await page.locator('h1:visible').innerText())==='实时推理工作台','monitor mode must expose exactly one visible page heading');
  assert(await page.locator('[data-call-filter]').count()===4&&await page.locator('#callFilterCaller').count()===1,'monitor must own the single four-filter set');
  await page.setViewportSize({width:1200,height:900}); const shortMonitorControls=await page.locator('a:visible,button:visible,input:visible,select:visible').evaluateAll(nodes=>nodes.filter(node=>node.getBoundingClientRect().height<43.5).map(node=>({label:node.id||node.textContent,height:node.getBoundingClientRect().height,minHeight:getComputedStyle(node).minHeight,display:getComputedStyle(node).display})));
  assert(shortMonitorControls.length===0,'monitor mode has controls shorter than 44px: '+JSON.stringify(shortMonitorControls));
  await page.locator('#callFilterCaller').fill('direct');
  const preserved=await page.evaluate(()=>({kv:document.getElementById('kvBudgetInput').value,unit:document.getElementById('kvBudgetUnit').value,context:document.getElementById('contextNextInput').value,filter:document.getElementById('callFilterCaller').value,notice:document.getElementById('adminNotice').textContent}));
  await wait(1200);
  await page.locator('[data-mode-choice="management"]').click();
  const restored=await page.evaluate(()=>({kv:document.getElementById('kvBudgetInput').value,unit:document.getElementById('kvBudgetUnit').value,context:document.getElementById('contextNextInput').value,filter:document.getElementById('callFilterCaller').value,notice:document.getElementById('adminNotice').textContent}));
  assert(JSON.stringify(restored)===JSON.stringify(preserved)&&preserved.notice.includes('最小 256 MB'),'polling or mode switching reset dirty management targets');
  await page.locator('[data-mode-choice="monitor"]').click();
  await reloadReady();
  assert(await page.locator('#dashboard').getAttribute('data-mode')==='monitor','monitor mode did not persist');
  assert(await page.locator('#monitorLayout').getAttribute('hidden')===null&&await page.locator('#monitorLayout').getAttribute('aria-hidden')==='false','persisted monitor root state is wrong');
  const monitorMetricsText=await page.locator('#monitorMetrics').innerText(); assert(monitorMetricsText.includes('52.7 t/s')&&monitorMetricsText.includes('75.0%')&&monitorMetricsText.includes('解码中 · 运行中')&&monitorMetricsText.includes('hanako-agent'),'monitor metrics are missing decode speed, request KV hit, activity, or service');
  assert(await page.locator('.wall-mirror').count()===0&&await page.locator('[data-mirror]').count()===0,'wall mirror wallpaper must be removed from the monitor metrics');
  const colorContract=await page.evaluate(()=>{
    const primaries=[...document.querySelectorAll('button.primary')];
    const active=document.querySelector('[data-request-id="99"] .result');
    const failed=document.querySelector('[data-request-id="98"] .result');
    return {
      theme:document.documentElement.dataset.theme,
      complete:primaries.length>0&&!!active&&!!failed,
      primaries:primaries.map(node=>getComputedStyle(node).backgroundColor),
      active:active?getComputedStyle(active).color:'',
      failed:failed?getComputedStyle(failed).color:''
    };
  });
  const expectedColors=colorContract.theme==='dark'?{primary:'rgb(232, 238, 242)',active:'rgb(114, 213, 162)',failed:'rgb(255, 137, 147)'}:{primary:'rgb(21, 26, 32)',active:'rgb(22, 120, 74)',failed:'rgb(189, 60, 73)'};
  assert(colorContract.complete&&colorContract.primaries.every(value=>value===expectedColors.primary)&&colorContract.active===expectedColors.active&&colorContract.failed===expectedColors.failed,'theme action or status color discipline is broken');
  const motion=await page.evaluate(()=>({prefillWindow:!!document.querySelector('#monitorPrefill .metric-value-window'),decodeWindow:!!document.querySelector('#monitorDecode .metric-value-window'),prefillDirection:document.getElementById('monitorPrefill').dataset.motionDirection,decodeDirection:document.getElementById('monitorDecode').dataset.motionDirection,prefillBar:!!document.getElementById('monitorPrefillBar'),decodeBar:!!document.getElementById('monitorDecodeBar')})); assert(motion.prefillWindow&&motion.decodeWindow&&motion.prefillDirection==='none'&&motion.decodeDirection==='none'&&motion.prefillBar&&motion.decodeBar,'monitor metrics are missing stable value windows or initial motion state');
  const motionIds=['monitorPrefill','monitorDecode','monitorCacheHit','monitorContext','monitorQueue'];
  const patchMonitor=async patch=>{await cfg({status_patch:patch});await page.waitForFunction(ids=>ids.every(id=>document.getElementById(id).dataset.motionDirection),motionIds)};
  const waitMetricMotion=async(direction,id)=>page.waitForFunction(({id,direction})=>{const node=document.getElementById(id);return node&&node.dataset.motionDirection===direction&&node.querySelector('.metric-value-layer-in-'+direction)&&node.querySelector('.metric-value-layer-out-'+direction)},{id,direction});
  await patchMonitor({queue_depth:3,prefill:{avg_tps:1900.4},decode:{avg_tps:60.7},request:{cached_tokens:28672},context:{utilization:.40}});
  await waitMetricMotion('increase','monitorPrefill');
  const increaseFrames=await page.evaluate(()=>document.querySelector('#monitorPrefill .metric-value-layer-in-increase')?.getAnimations()[0]?.effect?.getKeyframes().map(frame=>String(frame.transform))||[]); assert(increaseFrames.some(transform=>transform.includes('0.96'))&&increaseFrames.some(transform=>transform.includes('scale(1)')),'increase motion scale trajectory is not a subtle scale-up');
  for(const id of motionIds){if(id!=='monitorPrefill')await waitMetricMotion('increase',id);assert(await page.locator('#'+id+' .metric-value-layer').count()<=2,id+' accumulated increase layers')}
  await patchMonitor({queue_depth:1,prefill:{avg_tps:1700.4},decode:{avg_tps:44.7},request:{cached_tokens:16384},context:{utilization:.20}});
  await waitMetricMotion('decrease','monitorPrefill');
  const decreaseFrames=await page.evaluate(()=>document.querySelector('#monitorPrefill .metric-value-layer-in-decrease')?.getAnimations()[0]?.effect?.getKeyframes().map(frame=>String(frame.transform))||[]); assert(decreaseFrames.some(transform=>transform.includes('1.04'))&&decreaseFrames.some(transform=>transform.includes('scale(1)')),'decrease motion scale trajectory is not a subtle scale-down');
  for(const id of motionIds){if(id!=='monitorPrefill')await waitMetricMotion('decrease',id);assert(await page.locator('#'+id+' .metric-value-layer').count()<=2,id+' accumulated decrease layers')}
  await page.waitForTimeout(500); await patchMonitor({queue_depth:1,prefill:{avg_tps:1700.4},decode:{avg_tps:44.7},request:{cached_tokens:16384},context:{utilization:.20}}); for(const id of motionIds){await page.waitForFunction(id=>document.getElementById(id).dataset.motionDirection==='none',id);assert(await page.locator('#'+id+' .metric-value-layer').count()===1,id+' equal value unexpectedly animated')}
  await cfg({status_patch:{active:false}}); await page.waitForFunction(()=>['monitorPrefill','monitorDecode','monitorCacheHit'].every(id=>document.getElementById(id).dataset.motionDirection==='none'));
  await cfg({status_patch:{active:true,phase:'decode',queue_depth:2,prefill:{avg_tps:1850.4},decode:{avg_tps:52.7},request:{cached_tokens:24576},context:{utilization:.2937}}}); for(const id of ['monitorPrefill','monitorDecode','monitorCacheHit']){await page.waitForFunction(id=>document.getElementById(id).dataset.motionDirection==='none',id);assert(await page.locator('#'+id+' .metric-value-layer').count()===1,id+' unavailable recovery invented motion direction')}
  await page.emulateMedia({reducedMotion:'reduce'}); await patchMonitor({queue_depth:3,prefill:{avg_tps:1900.4},decode:{avg_tps:60.7},request:{cached_tokens:28672},context:{utilization:.40}}); await page.waitForFunction(()=>document.getElementById('monitorPrefill').dataset.motionDirection==='increase'); assert(await page.evaluate(()=>document.querySelector('#monitorPrefill .metric-value-window').getAnimations().length===0&&document.querySelectorAll('#monitorPrefill .metric-value-layer').length===1),'reduced motion still started metric animation'); await page.emulateMedia({reducedMotion:'no-preference'});
  assert(await page.locator('#monitorPhase').getAttribute('data-motion-direction')===null,'phase text must not use numeric motion');
  await cfg({reset:true}); await reloadReady();
  assert(await page.evaluate(()=>!!document.getElementById('monitorPrefillBar')&&!!document.getElementById('monitorDecodeBar')),'monitor prefill or decode bar is missing');
  const signalBefore=await page.evaluate(()=>{const pulse=document.getElementById('connectionPulse'),stamp=document.getElementById('updatedAt');return {updated:lastUpdatedAt,pulse:Number(pulse&&pulse.dataset.signalRevision||0),stamp:Number(stamp&&stamp.dataset.signalRevision||0)}});
  await page.waitForFunction(before=>{const pulse=document.getElementById('connectionPulse'),stamp=document.getElementById('updatedAt');return !!pulse&&lastUpdatedAt>before.updated&&Number(pulse.dataset.signalRevision||0)>before.pulse&&Number(stamp.dataset.signalRevision||0)>before.stamp},signalBefore);
  const pollSignal=await page.evaluate(()=>{const pulse=document.getElementById('connectionPulse'),stamp=document.getElementById('updatedAt'),prefill=document.getElementById('monitorPrefillBar'),decode=document.getElementById('monitorDecodeBar');return {pulseRevision:Number(pulse.dataset.signalRevision||0),stampRevision:Number(stamp.dataset.signalRevision||0),pulseAnimations:pulse.getAnimations().map(animation=>({duration:animation.effect.getTiming().duration,playState:animation.playState})),stampAnimations:stamp.getAnimations().map(animation=>({duration:animation.effect.getTiming().duration,playState:animation.playState})),prefillProperty:getComputedStyle(prefill).transitionProperty,decodeDuration:getComputedStyle(decode).transitionDuration}});
  assert(pollSignal.pulseRevision>0&&pollSignal.stampRevision>0&&pollSignal.pulseAnimations.some(animation=>animation.duration===620&&animation.playState==='running')&&pollSignal.stampAnimations.some(animation=>animation.duration===420&&animation.playState==='running')&&pollSignal.prefillProperty.includes('width')&&parseFloat(pollSignal.decodeDuration)>0,'successful polling does not cue the real-time signal layer or progress transition');
  assert(await page.locator('#monitorHost').count()===1,'monitor host section is missing its stable ID');
  assert((await page.locator('#callFilterApi option').evaluateAll(options=>options.map(o=>o.value).filter(Boolean).sort().join('/')))==='anthropic/openai/responses','fixture API filters do not use emitted protocol values');
  assert(await page.locator('#monitorCalls tr[data-request-id]').count()===5,'monitor must show exactly five fixture calls');
  assert((await page.locator('[data-request-id="98"]').innerText()).includes('42.1s')&&(await page.locator('[data-request-id="99"]').innerText()).includes('18.4s'),'finished or active row duration is missing');
  await page.locator('[data-request-id="98"] .request-select').click();
  assert(await page.locator('[data-request-id="98"]').getAttribute('aria-selected')==='true','clicked request was not selected');
  let inspectorText=await page.locator('#requestInspector').innerText(); assert(inspectorText.includes('hermes-agent')&&inspectorText.includes('42.1s')&&inspectorText.includes('61.9%'),'request inspector is missing service, duration, or cache hit');
  await page.evaluate(()=>window.__selectedRequestRow=document.querySelector('[data-request-id="98"]')); const inspectorRecords=(await fixture()).calls.records.map(record=>String(record.request_id)==='98'?{...record,prompt_tokens:40000,cached_tokens:20000,cache_write_tokens:3000,output_tokens:777,cache_source:'review-refresh',finish:'length',kind:'completion',stream:true,tools:true}:record); await cfg({call_records:inspectorRecords}); await page.waitForFunction(()=>document.getElementById('requestInspector').textContent.includes('review-refresh'));
  inspectorText=await page.locator('#requestInspector').innerText(); assert(['openai / completion','STREAM','工具调用\n是','PROMPT\n40,000','CACHED\n20,000','OUTPUT\n777','写入缓存\n3,000 token','缓存来源\nreview-refresh','结束原因\nlength','50.0%'].every(value=>inspectorText.includes(value)),'inspector-only record changes did not refresh the token visualization and request profile'); assert(await page.evaluate(()=>window.__selectedRequestRow===document.querySelector('[data-request-id="98"]')),'inspector-only record changes needlessly rebuilt the selected table row');
  await page.locator('[data-request-id="97"] .request-select').focus(); await page.keyboard.press('Enter');
  assert((await page.locator('#requestInspector').innerText()).includes('openclaw')&&await page.evaluate(()=>document.activeElement.closest('[data-request-id]')?.dataset.requestId)==='97','keyboard request selection did not update inspector or preserve row focus');
  await page.locator('#callFilterClient').selectOption('hanako-agent');
  assert((await page.locator('#requestInspector').innerText()).includes('从 Request Trace 选择请求以查看剖面'),'filtering out selection did not reset inspector');
  await page.locator('#callFilterClient').selectOption('<img src=x onerror=alert(1)>');
  const hostileMonitor=page.locator('#monitorCalls'); assert(await hostileMonitor.locator('img,script').count()===0&&!(await hostileMonitor.innerText()).includes('<script>坏</script>')&&(await hostileMonitor.innerText()).includes('失败'),'malicious monitor row was parsed as markup, leaked a long error, or result was not localized');
  await hostileMonitor.locator('.request-select').click(); inspectorText=await page.locator('#requestInspector').innerText(); assert(await page.locator('#requestInspector').locator('img,script').count()===0&&inspectorText.includes('<img src=x onerror=alert(1)>')&&inspectorText.includes('<script>坏</script>'),'malicious inspector values were parsed as markup');
  await page.locator('#callFilterClient').selectOption(''); await page.locator('#callFilterCaller').fill('direct'); await page.locator('#callFilterApi').selectOption('responses'); await page.locator('#callFilterStatus').selectOption('active'); assert((await page.locator('#monitorCalls').innerText()).includes('direct')&&(await page.locator('#monitorCalls').innerText()).includes('进行中'),'monitor caller/API/result filters did not localize active result');
  assert(await page.locator('#requestInspector').getAttribute('tabindex')==='-1','request inspector is not a programmatic focus target');
  for(const width of [1024,390]){await page.setViewportSize({width,height:900});const overflow=await page.evaluate(()=>{const wrap=document.querySelector('.call-table-wrap'),rect=node=>node?{client:node.clientWidth,scroll:node.scrollWidth,width:node.getBoundingClientRect().width}:null;return {page:document.documentElement.scrollWidth<=innerWidth,wrap:!!wrap&&wrap.scrollWidth>wrap.clientWidth&&['auto','scroll'].includes(getComputedStyle(wrap).overflowX),outside:[...document.body.querySelectorAll('*')].filter(e=>e!==wrap&&!e.matches('.timeline-panel')&&e.scrollWidth>e.clientWidth+1&&['auto','scroll'].includes(getComputedStyle(e).overflowX)).map(e=>e.className),console:rect(document.querySelector('.monitor-console')),wrapBox:rect(wrap),table:rect(document.querySelector('.monitor-table'))}});assert(overflow.page&&overflow.wrap&&overflow.outside.length===0,width+'px must confine intentional horizontal scrolling to the timeline and call table: '+JSON.stringify(overflow))}
  await page.setViewportSize({width:1200,height:900}); let monitorResponsive=await page.evaluate(()=>({columns:getComputedStyle(document.querySelector('.monitor-grid')).gridTemplateColumns.trim().split(/\s+/).length,metrics:getComputedStyle(document.getElementById('monitorMetrics')).gridTemplateColumns.trim().split(/\s+/).length,decode:document.querySelector('.vital-decode').getBoundingClientRect().width,prefill:document.querySelector('.vital-prefill').getBoundingClientRect().width,metricsOverflow:getComputedStyle(document.getElementById('monitorMetrics')).overflowX,tableMax:getComputedStyle(document.querySelector('.monitor-table-wrap')).maxHeight,timelineStages:document.querySelectorAll('.timeline-stage').length,axis:document.querySelectorAll('.timeline-axis span').length})); assert(monitorResponsive.columns===2&&monitorResponsive.metrics===4&&monitorResponsive.decode>monitorResponsive.prefill+20&&monitorResponsive.metricsOverflow==='hidden'&&monitorResponsive.tableMax!=='none'&&monitorResponsive.timelineStages===6&&monitorResponsive.axis===5,'workbench hierarchy, four-column signal field, bounded trace, or structured timeline is missing');
  await page.setViewportSize({width:800,height:900}); monitorResponsive=await page.evaluate(()=>({columns:getComputedStyle(document.querySelector('.monitor-grid')).gridTemplateColumns.trim().split(/\s+/).length,host:getComputedStyle(document.querySelector('.monitor-host .host-ruler')).gridTemplateColumns.trim().split(/\s+/).length})); assert(monitorResponsive.columns===1&&monitorResponsive.host===3,'compact monitor did not stack its main panels or preserve adaptive host metrics');
  await page.setViewportSize({width:700,height:900}); const metricDividers=await page.evaluate(()=>[...document.querySelectorAll('#monitorMetrics>.vital')].map(e=>getComputedStyle(e).borderLeftStyle)); assert(metricDividers.every(style=>style==='none'),'monitor vitals should not draw internal left borders');
  await page.setViewportSize({width:390,height:844}); monitorResponsive=await page.evaluate(()=>({w:document.documentElement.scrollWidth,v:innerWidth,metrics:getComputedStyle(document.getElementById('monitorMetrics')).gridTemplateColumns.trim().split(/\s+/).length,host:getComputedStyle(document.querySelector('.monitor-host .host-ruler')).gridTemplateColumns.trim().split(/\s+/).length,button:document.querySelector('.request-select').getBoundingClientRect().height,timelineScroll:document.querySelector('.timeline-panel').scrollWidth>document.querySelector('.timeline-panel').clientWidth})); assert(monitorResponsive.w<=monitorResponsive.v&&monitorResponsive.metrics===2&&monitorResponsive.host===2&&monitorResponsive.button>=44&&monitorResponsive.timelineScroll,'390px monitor overflows or loses adaptive signals, bounded timeline, host layout, or touch target sizing'); await page.setViewportSize({width:1200,height:900});
  await page.locator('#callFilterCaller').fill(''); await page.locator('#callFilterApi').selectOption(''); await page.locator('#callFilterStatus').selectOption('');
  const errorProbe={request_id:'error-width',client:'probe-service',caller:'probe-caller',api:'openai',kind:'chat',status:'failed',stream:false,tools:false,started_at:1,finished_at:2,prompt_tokens:0,cached_tokens:0,cache_write_tokens:0,output_tokens:0,cache_source:'',finish:'error',error:'long failure: '+'x'.repeat(240)};
  await cfg({call_records:[errorProbe],status_patch:{active:false,phase:'idle',calls:{active_request_id:''}}}); await page.waitForFunction(()=>document.querySelector('[data-request-id="error-width"]'));
  await page.setViewportSize({width:400,height:844}); assert(await page.locator('[data-request-id="error-width"] td:nth-child(7)').isHidden(),'request trace should keep long errors in the inspector instead of expanding compact rows'); await page.locator('[data-request-id="error-width"] .request-select').click(); assert((await page.locator('#requestInspector').innerText()).includes('long failure:'),'long request error was not preserved in the inspector'); await page.setViewportSize({width:1200,height:900});
  await cfg({reset:true}); await page.waitForFunction(()=>document.querySelectorAll('#monitorCalls tr[data-request-id]').length===5);
  await cfg({status_patch:{active:false,phase:'idle',calls:{active_request_id:'0'}}}); await page.waitForFunction(()=>document.getElementById('monitorPhase').textContent.includes('空闲 · 就绪'));
  const idleMonitor=await page.evaluate(()=>({phase:monitorPhase.textContent,service:monitorPhaseMeta.textContent,prefill:monitorPrefill.textContent,decode:monitorDecode.textContent,cache:monitorCacheHit.textContent,managementActive:managementCallsActive.textContent,monitorActive:monitorCallsActive.textContent,duration:document.querySelector('[data-request-id="99"] td:nth-child(6)').textContent})); assert(idleMonitor.phase==='空闲 · 就绪'&&idleMonitor.service==='服务 · —'&&idleMonitor.prefill==='不可用'&&idleMonitor.decode==='不可用'&&idleMonitor.cache==='不可用'&&idleMonitor.managementActive.endsWith('—')&&idleMonitor.monitorActive.endsWith('—')&&idleMonitor.duration==='—','idle snapshot exposed retained current-request metrics, identity, or elapsed time');
  await cfg({status_patch:{active:true,phase:'decode',calls:{active_request_id:''}}}); await page.waitForFunction(()=>monitorPhase.textContent.includes('解码中 · 运行中')); assert((await page.locator('#monitorPhase').innerText())==='解码中 · 运行中'&&(await page.locator('#monitorPhaseMeta').innerText())==='服务 · —'&&(await page.locator('#monitorDecode').innerText())==='不可用'&&(await page.locator('#monitorCallsActive').innerText()).endsWith('—')&&(await page.locator('#topTokens').innerText())==='—'&&!await page.locator('#dashboard').evaluate(node=>node.classList.contains('is-active')),'blank active request ID was treated as a live header identity');
  await cfg({status_patch:{active:true,phase:'prefill',calls:{active_request_id:'99'}}}); await page.waitForFunction(()=>monitorPhase.textContent.includes('预填充中')); assert((await page.locator('#monitorPrefill').innerText()).includes('1850.4 t/s')&&(await page.locator('#monitorPrefillMeta').innerText()).includes('8,192 / 8,192 token')&&(await page.locator('#monitorDecode').innerText())==='不可用','prefill phase hid same-request prefill or exposed retained decode metrics');
  const matrixBase={caller:'matrix',client:'matrix-client',api:'openai',kind:'chat',stream:false,tools:false,prompt_tokens:8,cached_tokens:0,cache_write_tokens:0,output_tokens:0,cache_source:'',finish:'stop',error:''};
  const matrix=[{...matrixBase,request_id:'missing-start',status:'completed',finished_at:2},{...matrixBase,request_id:'missing-finish',status:'completed',started_at:1},{...matrixBase,request_id:'negative',status:'completed',started_at:-1,finished_at:2},{...matrixBase,request_id:'reversed',status:'completed',started_at:10,finished_at:9},{...matrixBase,request_id:'valid',status:'completed',started_at:2000,finished_at:2042.1},{...matrixBase,request_id:'99',status:'active',started_at:1000,finished_at:0},{...matrixBase,request_id:'100',status:'active',started_at:1000,finished_at:0}];
  await cfg({reset:true,call_records:matrix,status_patch:{calls:{active_request_id:'99'}}}); await page.waitForFunction(()=>document.querySelectorAll('#monitorCalls tr[data-request-id]').length===7); const durationFor=id=>page.locator(`[data-request-id="${id}"] td:nth-child(6)`).innerText(); assert(await durationFor('missing-start')==='—'&&await durationFor('missing-finish')==='—'&&await durationFor('negative')==='—'&&await durationFor('reversed')==='—'&&await durationFor('valid')==='42.1s'&&await durationFor('99')==='18.4s'&&await durationFor('100')==='—','timestamp matrix accepted invalid terminal times or mismatched active elapsed');
  await cfg({reset:true,status_patch:{host:{available:true,memory_used_bytes:null,memory_total_bytes:'',swap_used_bytes:null,process_rss_bytes:''}}}); await page.waitForFunction(()=>document.getElementById('managementHostPhysical').textContent==='不可用'); assert((await page.locator('#managementHostPhysical').innerText())==='不可用'&&(await page.locator('#managementHostPressure').innerText())==='不可用'&&(await page.locator('#managementHostRss').innerText())==='不可用','partial host sample coerced null or empty fields to 0 B');
  await cfg({reset:true}); await page.waitForFunction(()=>[...document.querySelectorAll('#callFilterClient option')].some(o=>o.value==='hanako-agent')); await page.locator('#callFilterClient').selectOption('hanako-agent'); await page.evaluate(()=>window.__keptClientOption=[...callFilterClient.options].find(o=>o.value==='hanako-agent')); await wait(1100); assert(await page.evaluate(()=>window.__keptClientOption===[...callFilterClient.options].find(o=>o.value==='hanako-agent')),'unchanged option list was needlessly rebuilt during polling');
  const retainedRecord={...matrixBase,request_id:'99',client:'hanako-agent',api:'responses',status:'active',started_at:1,finished_at:0},changedRecord={...matrixBase,request_id:'101',client:'new-service',status:'completed',started_at:1,finished_at:2}; await cfg({call_records:[retainedRecord,changedRecord]}); await page.waitForFunction(()=>[...callFilterClient.options].some(o=>o.value==='new-service')); assert((await page.locator('#callFilterClient').inputValue())==='hanako-agent','record option update lost the still-valid selected filter');
  await page.locator('#callFilterClient').selectOption(''); const stableRecords=[{...matrixBase,request_id:'stable-known',caller:'same-caller',client:'hanako-agent',status:'completed',started_at:1,finished_at:2},{...matrixBase,request_id:'stable-missing',caller:'same-caller',client:'未标识服务',status:'active',started_at:2,finished_at:0}]; await cfg({call_records:stableRecords,status_patch:{active:true,phase:'decode',calls:{active_request_id:'stable-missing'}}}); await page.waitForFunction(()=>document.querySelectorAll('#monitorCalls tr[data-request-id]').length===2&&document.getElementById('timelineSummary').textContent.includes('hanako-agent')); assert((await page.locator('[data-request-id="stable-missing"]').innerText()).includes('hanako-agent'),'unknown service did not inherit the unique known service for its caller'); await page.locator('[data-request-id="stable-missing"] .request-select').click(); assert((await page.locator('#requestInspector').innerText()).includes('hanako-agent')&&(await page.locator('#timelineSummary').innerText()).includes('hanako-agent'),'inspector or timeline did not keep the service identity stable');
  const historicalBase={...matrixBase,caller:'historical-proxy',status:'completed',started_at:1,finished_at:2};
  await cfg({call_records:[{...historicalBase,request_id:'historical-a',client:'service-a'}],status_patch:{active:false,phase:'idle',calls:{active_request_id:''}}}); await page.waitForFunction(()=>document.querySelector('[data-request-id="historical-a"]')?.textContent.includes('service-a'));
  await cfg({call_records:[{...historicalBase,request_id:'historical-b',client:'service-b'}]}); await page.waitForFunction(()=>document.querySelector('[data-request-id="historical-b"]')?.textContent.includes('service-b'));
  await cfg({call_records:[{...historicalBase,request_id:'historical-unknown',client:'未标识服务'}]}); await page.waitForFunction(()=>document.querySelector('[data-request-id="historical-unknown"]'));
  const historicalText=await page.locator('[data-request-id="historical-unknown"]').innerText(),historicalMemory=await page.evaluate(()=>({map:JSON.parse(localStorage.getItem('ds4-dashboard-client-map')||'{}'),ambiguous:JSON.parse(localStorage.getItem('ds4-dashboard-client-ambiguous')||'[]')}));
  assert(historicalText.includes('未标识服务')&&!historicalText.includes('service-b')&&!Object.prototype.hasOwnProperty.call(historicalMemory.map,'historical-proxy')&&historicalMemory.ambiguous.includes('historical-proxy'),'historically ambiguous caller inherited the most recently seen client');
  assert(await page.locator('#monitorCalls .request-select').first().getAttribute('aria-controls')==='requestInspector','request selection button does not expose its inspector relationship'); await cfg({reset:true}); await page.waitForFunction(()=>[...callFilterClient.options].some(o=>o.value==='batch-evaluator')); await page.locator('#callFilterClient').selectOption(''); await page.waitForFunction(()=>document.querySelectorAll('#monitorCalls tr[data-request-id]').length===5);
  await page.locator('[data-mode-choice="management"]').click();
  assert(await page.locator('#dashboard').getAttribute('data-mode')==='management','management mode did not reapply');
  assert(await page.locator('#managementLayout').isVisible()&&await page.locator('#monitorLayout').getAttribute('hidden')===''&&await page.locator('#monitorLayout').getAttribute('aria-hidden')==='true','mode roots did not switch back to management');
  assert(await page.locator('h1:visible').count()===1&&(await page.locator('h1:visible').innerText())==='运行与容量','management mode did not restore its sole visible page heading');
  assert(await page.locator('#managementTitle').count()===1&&(await page.locator('#managementTitle').innerText())==='运行与容量','management title is missing');
  assert((await page.locator('#managementPhase').innerText()).includes('解码'),'management phase was not localized');
  assert((await page.locator('#managementContext').innerText()).includes('115,720'),'management context remaining is missing');
  assert((await page.locator('#managementKv').innerText()).includes('46.0 / 64.0 GB'),'management KV summary is missing');
  assert((await page.locator('#kvEffect').innerText()).includes('立即影响运行'),'KV runtime effect is unclear');
  assert((await page.locator('#contextEffect').innerText()).includes('重启后生效'),'context restart effect is unclear');
  assert(await page.locator('#managementRecent table').count()===1&&await page.locator('#managementRecentCalls').getAttribute('aria-live')===null,'management recent calls are not a quiet semantic table');
  assert((await page.locator('#managementRecent thead th').allInnerTexts()).join('/')==='请求/服务/API/结果/时长','management recent call headers are incomplete');
  const managementRecentText=await page.locator('#managementRecentCalls').innerText(); assert(await page.locator('#managementRecentCalls tr[data-call-id]').count()===3&&managementRecentText.includes('hanako-agent')&&managementRecentText.includes('responses'),'management recent calls are incomplete');
  assert((await page.locator('#managementRecentCalls tr[data-call-id] td:nth-child(5)').allInnerTexts()).join('/')==='18.4s/42.1s/12.5s','management recent calls do not show truthful active and completed durations');
  const recentDurationRecords=[{...matrixBase,request_id:'99',status:'active',started_at:1000,finished_at:0},{...matrixBase,request_id:'done',status:'completed',started_at:5,finished_at:7.5},{...matrixBase,request_id:'invalid',status:'completed',started_at:9,finished_at:8}];
  await cfg({call_records:recentDurationRecords,status_patch:{active:true,calls:{active_request_id:'99'}}}); await page.waitForFunction(()=>[...document.querySelectorAll('#managementRecentCalls tr[data-call-id]')].map(row=>row.dataset.callId).join('/')==='99/done/invalid');
  const recentDurationValues=(await page.locator('#managementRecentCalls tr[data-call-id] td:nth-child(5)').allInnerTexts()).join('/'); assert(recentDurationValues==='18.4s/2.5s/—','management recent duration accepted an invalid terminal record: '+recentDurationValues);
  await cfg({reset:true}); await page.waitForFunction(()=>document.querySelectorAll('#managementRecentCalls tr[data-call-id]').length===3);
  await cfg({call_records:[]}); await wait(1100); assert((await page.locator('#managementRecentCalls').innerText()).includes('暂无调用记录')&&await page.locator('#managementRecentCalls tr').count()===1,'empty management recent calls are not explicit');
  await cfg({call_records:[{request_id:'<img src=x>',client:'<script>坏</script>',api:'<img src=x onerror=alert(1)>',status:'failed',error:''},{request_id:'98',client:'hermes-agent',api:'chat',status:'completed',error:''},{request_id:'97',client:'openclaw',api:'chat',status:'active',error:''}]}); await wait(1100); const hostileRecent=page.locator('#managementRecentCalls'); assert(await hostileRecent.locator('img,script').count()===0&&(await hostileRecent.innerText()).includes('<script>坏</script>')&&(await hostileRecent.innerText()).includes('<img src=x>'),'hostile management recent call text was parsed as markup'); await cfg({reset:true}); await wait(1100);
  assert((await page.locator('#managementHost').innerText()).includes('内存压力'),'management host pressure is missing');
  assert(await page.locator('#dashboard').locator('#contextSaveRestart,#kvApplyNow,#kvSaveRestart').count()===3,'shared administration controls disappeared');
  const forbidden=['Counters reset when','Token hit rate','Request hit rate','Outcomes','Used','Budget','Entries / utilization','Disk KV capacity','Current request','tokens per second'];
  const fontStacks=await page.evaluate(()=>({body:getComputedStyle(document.body).fontFamily,instrument:getComputedStyle(document.querySelector('.mono')).fontFamily}));
  assert(fontStacks.body.includes('Hiragino Sans GB')&&fontStacks.instrument.includes('Hiragino Sans GB'),'dashboard font stacks do not provide a locally available Chinese fallback');
  const desktop=await page.evaluate(()=>({w:document.documentElement.scrollWidth,v:innerWidth,text:document.body.innerText})); assert(desktop.w<=desktop.v&&desktop.text.includes('管理')&&desktop.text.includes('上下文窗口')&&desktop.text.includes('运行与容量')&&forbidden.every(s=>!desktop.text.includes(s)),'desktop layout or Chinese labels missing');
  await page.setViewportSize({width:800,height:900}); await page.waitForFunction(()=>innerWidth===800); const compact=await page.evaluate(()=>({nav:getComputedStyle(document.querySelector('.management-nav')).display,management:getComputedStyle(document.querySelector('.management-grid')).gridTemplateColumns,settings:getComputedStyle(document.querySelector('.settings-grid')).gridTemplateColumns})); assert(compact.nav==='none'&&!compact.management.includes('180px')&&compact.settings.trim().split(/\s+/).length===2,'compact management breakpoint did not hide the sidebar while preserving two setting columns');
  await page.setViewportSize({width:390,height:844}); await page.waitForFunction(()=>innerWidth===390); const mobile=await page.evaluate(()=>({w:document.documentElement.scrollWidth,v:innerWidth,text:document.body.innerText,settings:getComputedStyle(document.querySelector('.settings-grid')).gridTemplateColumns})); assert(mobile.w<=mobile.v&&mobile.settings.trim().split(/\s+/).length===1&&forbidden.every(s=>!mobile.text.includes(s)),'mobile dashboard overflows, keeps two setting columns, or exposes English labels'); await page.setViewportSize({width:1440,height:900});
  assert((await page.locator('#contextNextInput').getAttribute('min'))==='4096','context input minimum does not match server');
  await page.locator('#contextNextInput').fill('4095'); await page.locator('#contextSaveRestart').click(); await page.waitForFunction(()=>contextNextInput.getAttribute('aria-invalid')==='true'&&document.getElementById('contextNotice').textContent.includes('4,096 到 2,147,483,647')); s=await fixture(); assert(s.context_admin.length===0,'below-minimum context reached server'); assert(await page.locator('#contextNotice').evaluate(e=>e.className==='notice bad'),'invalid context did not show actionable Chinese error'); await page.evaluate(()=>document.activeElement.blur()); const dirtyContextUpdate=await page.evaluate(()=>lastUpdatedAt); await page.waitForFunction(previous=>lastUpdatedAt>previous,dirtyContextUpdate); assert((await page.locator('#contextNextInput').inputValue())==='4095','polling replaced a dirty context target after validation failure');
  assert(await page.locator('#contextNextInput').getAttribute('aria-invalid')==='true','invalid context did not expose aria-invalid'); await page.locator('#contextNextInput').fill('4096'); assert(await page.locator('#contextNextInput').getAttribute('aria-invalid')==='false','context edit did not clear aria-invalid');
  await page.locator('#contextNextInput').fill('2147483648'); await page.locator('#contextSaveRestart').click(); await page.waitForFunction(()=>contextNextInput.getAttribute('aria-invalid')==='true'); s=await fixture(); assert(s.context_admin.length===0,'above-maximum context reached server');
  await page.locator('#contextNextInput').fill('131072'); await page.locator('#contextSaveRestart').click(); await wait(1100); s=await fixture(); assert(s.context_admin[0].header==='1'&&s.context_admin[0].value===131072,'context admin header or payload missing'); const contextSaved=await page.locator('#contextNotice').innerText(); assert(contextSaved.includes('需要重启')&&contextSaved.includes('当前运行值未改变'),'context restart copy missing'); assert((await page.locator('#contextNextInput').inputValue())==='131072','polling replaced saved next-start context limit with live limit');
  await cfg({reset:true,context_fail_once:true}); await reloadReady(); await page.locator('#contextNextInput').fill('131072'); await page.locator('#contextSaveRestart').click(); await page.waitForFunction(()=>document.getElementById('contextNotice').textContent.includes('上下文设置失败，请检查数值后重试。')); assert(await page.locator('#contextNotice').evaluate(e=>e.className==='notice bad'),'context failure was not localized or marked bad'); await page.locator('#contextSaveRestart').click(); await page.waitForFunction(async()=>{const state=await fetch('/fixture/state').then(r=>r.json()),notice=document.getElementById('contextNotice').textContent;return state.context_admin.length===2&&notice.includes('需要重启')&&notice.includes('当前运行值未改变')}); s=await fixture(); assert(s.context_admin.length===2&&await page.locator('#contextNotice').evaluate(e=>e.className==='notice'),'context success retry did not clear error notice');
  await cfg({reset:true,context_forbidden:true}); await reloadReady(); await page.locator('#contextSaveRestart').click(); await page.waitForFunction(()=>contextSaveRestart.disabled&&document.getElementById('contextNotice').textContent.includes('仅可从本机管理')); assert(!await page.locator('#kvApplyNow').isDisabled(),'context 403 did not isolate controls');
  await cfg({reset:true,context_durable:false}); await reloadReady(); await page.locator('#contextSaveRestart').click(); await page.waitForFunction(()=>document.getElementById('contextNotice').textContent.includes('已提交，但尚未确认已持久化'));
  await cfg({reset:true,host_available:false}); await page.reload(); await page.waitForFunction(()=>document.getElementById('health').textContent!=='等待中'&&document.getElementById('managementHostPhysical').textContent==='不可用'); assert((await page.locator('#managementHostPhysical').innerText())==='不可用'&&(await page.locator('#managementHostPressure').innerText())==='不可用'&&(await page.locator('#managementHostRss').innerText())==='不可用'&&(await page.locator('#monitorHostPhysical').innerText())==='不可用'&&(await page.locator('#monitorHostPressure').innerText())==='不可用'&&(await page.locator('#monitorHostRss').innerText())==='不可用','unknown host was not explicit in both modes');
  const lastVisibleKv=await page.locator('#kvUsed').innerText(); await page.locator('#kvBudgetInput').fill('80'); await page.locator('#contextNextInput').fill('131072'); await cfg({offline:true}); await page.waitForFunction(()=>document.getElementById('dashboard').classList.contains('stale')&&document.getElementById('updatedAt').textContent.includes('更新'));
  const staleUpdated=await page.locator('#updatedAt').innerText(); assert((await page.locator('#connectionState').innerText()).includes('数据已过期')&&/更新/.test(staleUpdated)&&staleUpdated!=='尚未更新','offline snapshot did not expose a meaningful stale update age');
  assert((await page.locator('#kvUsed').innerText())===lastVisibleKv&&(await page.locator('#kvBudgetInput').inputValue())==='80'&&(await page.locator('#contextNextInput').inputValue())==='131072','offline polling cleared the last snapshot or touched targets');
  assert(await page.locator('#kvBudgetInput').isDisabled()&&await page.locator('#kvBudgetUnit').isDisabled()&&await page.locator('#kvApplyNow').isDisabled()&&await page.locator('#kvSaveRestart').isDisabled()&&await page.locator('#contextNextInput').isDisabled()&&await page.locator('#contextSaveRestart').isDisabled(),'offline state did not disable both administration groups');
  await cfg({offline:false}); await page.waitForFunction(()=>document.getElementById('health').textContent!=='数据已过期'&&!document.getElementById('kvApplyNow').disabled&&!document.getElementById('contextSaveRestart').disabled); assert(!await page.locator('#dashboard').evaluate(e=>e.classList.contains('stale'))&&(await page.locator('#updatedAt').innerText()).includes('更新')&&(await page.locator('#kvBudgetInput').inputValue())==='80'&&(await page.locator('#contextNextInput').inputValue())==='131072','successful recovery did not clear stale state, restore controls, or preserve touched targets');
  await cfg({reset:true,offline:true}); await page.reload(); await page.waitForFunction(()=>document.getElementById('health').textContent==='不可用'); assert((await page.locator('#updatedAt').innerText())==='尚未更新'&&!(await page.locator('#connectionState').innerText()).includes('数据已过期'),'first-load unavailable state was confused with a stale snapshot');

  const acceptanceState=await cfg({reset:true});
  await cfg({call_records:acceptanceState.calls.records.map((record,index)=>({...record,caller:index===3?'198.51.100.8':record.caller,client:index===3?'safety-probe':record.client,error:''}))});
  await page.evaluate(()=>localStorage.setItem('ds4-dashboard-mode','management')); await reloadReady();
  await page.setViewportSize({width:1440,height:900});
  await page.waitForFunction(()=>document.getElementById('dashboard').dataset.mode==='management'&&!document.getElementById('dashboard').classList.contains('stale')&&document.getElementById('health').textContent!=='等待中'&&document.querySelectorAll('#managementRecentCalls tr[data-call-id]').length===3&&!document.getElementById('kvApplyNow').disabled);
  const uniqueControlIds=['callFilterCaller','callFilterClient','callFilterApi','callFilterStatus','kvApplyNow','kvSaveRestart','contextSaveRestart'];
  assert(await page.evaluate(ids=>ids.every(id=>document.querySelectorAll('#'+id).length===1),uniqueControlIds),'filter or administration control IDs are duplicated');
  const contextSummaryBox=await page.locator('#managementContext').boundingBox(); assert(contextSummaryBox&&contextSummaryBox.height<50,'context summary value split into an unreadable multi-line fragment');
  await wait(300);
  assert(await page.locator('.mode-layout:not([hidden])').evaluate(node=>getComputedStyle(node).opacity==='1'),'management screenshot was captured before the mode transition settled');
  await page.evaluate(()=>scrollTo(0,0)); await wait(16);
  await page.screenshot({path:'output/playwright/dashboard-management-desktop.png'});
  await page.locator('[data-mode-choice="monitor"]').click();
  await page.locator('[data-request-id="98"] .request-select').click();
  await page.waitForFunction(()=>document.getElementById('dashboard').dataset.mode==='monitor'&&document.querySelectorAll('#monitorCalls tr[data-request-id]').length===5&&document.getElementById('requestInspector').textContent.includes('hermes-agent'));
  await wait(300);
  assert(await page.locator('.mode-layout:not([hidden])').evaluate(node=>getComputedStyle(node).opacity==='1'),'monitor screenshot was captured before the mode transition settled');
  const monitorHierarchy=await page.evaluate(()=>{const decode=document.querySelector('.vital-decode strong'),secondary=[...document.querySelectorAll('.vital-prefill strong,.vital-cache strong,.vital-context strong,.vital-queue strong')],track=[...document.querySelectorAll('.timeline-stage')];return {decodeSize:parseFloat(getComputedStyle(decode).fontSize),secondaryMax:Math.max(...secondary.map(node=>parseFloat(getComputedStyle(node).fontSize))),stageWidths:track.map(node=>Math.round(node.getBoundingClientRect().width)),axis:document.querySelectorAll('.timeline-axis span').length,orbit:document.querySelectorAll('.token-orbit').length,runtimeScales:document.querySelectorAll('.runtime-scale').length,expertBars:document.querySelectorAll('.expert-signal i').length}});
  assert(monitorHierarchy.decodeSize>=48&&monitorHierarchy.decodeSize>=monitorHierarchy.secondaryMax*2.5&&new Set(monitorHierarchy.stageWidths).size>=3&&monitorHierarchy.axis===5&&monitorHierarchy.orbit===1&&monitorHierarchy.runtimeScales===2&&monitorHierarchy.expertBars===12,'decode anchor, proportional timeline, request visualization, or runtime instruments are missing');
  const fifthRowBox=await page.locator('[data-request-id="95"]').boundingBox();
  const fifthRowBottom=fifthRowBox&&fifthRowBox.y+fifthRowBox.height; assert(fifthRowBottom&&fifthRowBottom<=901,'fifth monitor call must fit within the 1440x900 acceptance viewport');
  const lastInspectorFactBox=await page.locator('#requestInspector dd').last().boundingBox();
  const lastInspectorFactBottom=lastInspectorFactBox&&lastInspectorFactBox.y+lastInspectorFactBox.height; assert(lastInspectorFactBottom&&lastInspectorFactBottom<=901,'last inspector fact must fit within the 1440x900 acceptance viewport');
  assert(await page.locator('#monitorMetrics').isVisible()&&await page.locator('#requestInspector').isVisible(),'monitor metrics or selected request inspector are not visible in the acceptance view');
  const informationFirst = await page.evaluate(() => {
    const grid = document.querySelector('.monitor-grid').getBoundingClientRect();
    const metrics = document.getElementById('monitorMetrics').getBoundingClientRect();
    const console = document.querySelector('.monitor-console').getBoundingClientRect();
    const timeline = document.getElementById('inferenceTimeline').getBoundingClientRect();
    const trace = document.querySelector('[aria-labelledby="monitorCallsTitle"]').getBoundingClientRect();
    const host = document.querySelector('.monitor-host').getBoundingClientRect();
    const body = getComputedStyle(document.body);
    return {
      mirrors: document.querySelectorAll('.wall-mirror').length,
      gridWidth: grid.width,
      metricsBottom: metrics.bottom,
      gridTop: grid.top,
      timelineTop: timeline.top,
      timelineBottom: timeline.bottom,
      timelineRight: timeline.right,
      traceTop: trace.top,
      traceBottom: trace.bottom,
      consoleLeft: console.left,
      consoleRight: console.right,
      consoleWidth: console.width,
      hostGap: host.top - trace.bottom,
      pageWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth,
      outerBackground: body.backgroundColor
    };
  });
  assert(
    informationFirst.mirrors === 0 &&
    informationFirst.consoleWidth >= 330 &&
    informationFirst.timelineTop - informationFirst.metricsBottom >= 12 &&
    informationFirst.consoleLeft - informationFirst.timelineRight >= 15 &&
    informationFirst.traceTop - informationFirst.timelineBottom >= 12 &&
    informationFirst.hostGap >= 14 && informationFirst.hostGap <= 20 &&
    informationFirst.consoleLeft >= 0 &&
    informationFirst.consoleRight <= informationFirst.viewportWidth &&
    informationFirst.pageWidth <= informationFirst.viewportWidth,
    'instrument desktop layout has wallpaper, overlap, a detached section, clipped inspector, or page overflow'
  );
  await page.setViewportSize({width:1300,height:900});
  const boundaryDesktop=await page.evaluate(()=>{const timeline=document.getElementById('inferenceTimeline').getBoundingClientRect(),console=document.querySelector('.monitor-console').getBoundingClientRect();return {gap:console.left-timeline.right,cols:getComputedStyle(document.getElementById('monitorMetrics')).gridTemplateColumns.trim().split(/\s+/).length,sw:document.documentElement.scrollWidth,vw:innerWidth}});
  assert(boundaryDesktop.gap>=15&&boundaryDesktop.cols===4&&boundaryDesktop.sw<=boundaryDesktop.vw,'1300px monitor must keep the four-column signal field without leaking into the inspector');
  await page.setViewportSize({width:1440,height:900});
  const motionBudget=await page.evaluate(()=>{const ms=value=>value.trim().endsWith('ms')?Number.parseFloat(value):Number.parseFloat(value)*1000;const mode=getComputedStyle(document.querySelector('.mode-layout:not([hidden])')),row=getComputedStyle(document.querySelector('#monitorCalls tr[aria-selected="true"]'));return {mode:ms(mode.animationDuration),row:row.transitionDuration.split(',').map(ms)}});
  assert(motionBudget.mode>0&&motionBudget.mode<=280&&motionBudget.row.every(value=>value>=0&&value<=200),'dashboard mode or row feedback exceeds the real-time signal motion budget');
  await page.evaluate(()=>scrollTo(0,0)); await wait(16);
  await page.screenshot({path:'output/playwright/dashboard-monitor-desktop.png'});
  await page.locator('[data-theme-choice="light"]').click(); await wait(250);
  await page.screenshot({path:'output/playwright/dashboard-monitor-light.png'});
  await page.locator('[data-theme-choice="dark"]').click(); await wait(250);
  await page.screenshot({path:'output/playwright/dashboard-monitor-dark.png'});
  await page.locator('[data-theme-choice="system"]').click();
  const longService='x'.repeat(160),longMetric=1e20,longMetricText=longMetric.toFixed(1)+' t/s';
  const longCalls=(await fixture()).calls.records.map(record=>record.request_id==='99'?{...record,client:longService}:record);
  await cfg({call_records:longCalls,status_patch:{active:true,phase:'decode',prefill:{avg_tps:longMetric},calls:{active_request_id:'99'}}});
  await page.waitForFunction(([service,value])=>document.getElementById('monitorPhaseMeta').textContent.includes(service)&&document.getElementById('monitorPrefill').getAttribute('title')===value,[longService,longMetricText]);
  const longMetricContract=await page.evaluate(()=>{const value=document.getElementById('monitorPrefill'),windowNode=value.querySelector('.metric-value-window'),layer=windowNode.querySelector('.metric-value-layer'),phase=document.getElementById('monitorPhaseMeta'),phaseCell=document.querySelector('.vital-phase');return {truncated:value.classList.contains('metric-value-truncated'),title:value.getAttribute('title'),visible:layer.textContent,ellipsis:getComputedStyle(layer).textOverflow,layerWidth:layer.getBoundingClientRect().width,windowWidth:windowNode.getBoundingClientRect().width,phaseWrap:getComputedStyle(phase).overflowWrap,phaseRight:phase.getBoundingClientRect().right,phaseCellRight:phaseCell.getBoundingClientRect().right}});
  assert(longMetricContract.truncated&&longMetricContract.title===longMetricText&&longMetricContract.visible===longMetricText&&longMetricContract.ellipsis==='ellipsis'&&longMetricContract.layerWidth<=longMetricContract.windowWidth+1&&longMetricContract.phaseWrap==='anywhere'&&longMetricContract.phaseRight<=longMetricContract.phaseCellRight+1,'long metric or 160-character service name was silently clipped, overlapped, or lacked the full-value affordance');
  await page.setViewportSize({width:1308,height:900});
  const resizeTruncation=await page.evaluate(()=>{refreshMetricTruncation();const node=document.getElementById('monitorPrefill'),windowNode=node.querySelector('.metric-value-window'),layer=windowNode.querySelector('.metric-value-layer');return {title:node.getAttribute('title'),ellipsis:getComputedStyle(layer).textOverflow,width:layer.getBoundingClientRect().width,window:windowNode.getBoundingClientRect().width,sw:document.documentElement.scrollWidth,vw:innerWidth}});
  assert(resizeTruncation.title===longMetricText&&resizeTruncation.ellipsis==='ellipsis'&&resizeTruncation.width<=resizeTruncation.window+1&&resizeTruncation.sw<=resizeTruncation.vw,'long metric lost its full-value affordance or caused page overflow after resize');
  await page.setViewportSize({width:1440,height:900});
  await cfg({reset:true}); await page.waitForFunction(()=>!document.getElementById('dashboard').classList.contains('stale')&&document.getElementById('monitorPrefill').textContent.includes('1850.4 t/s'));
  await page.emulateMedia({reducedMotion:'reduce'});
  await wait(20);
  const reduced=await page.evaluate(()=>({
    light:getComputedStyle(document.querySelector('.light-field')).animationName,
    shadow:getComputedStyle(document.querySelector('.light-shadow')).animationName,
    mode:getComputedStyle(document.querySelector('.mode-layout:not([hidden])')).animationName,
    pulse:document.getElementById('connectionPulse').getAnimations().filter(animation=>animation.playState==='running').length,
    stamp:document.getElementById('updatedAt').getAnimations().filter(animation=>animation.playState==='running').length
  }));
  assert(reduced.light==='none'&&reduced.shadow==='none'&&reduced.mode==='none'&&reduced.pulse===0&&reduced.stamp===0,'reduced motion still animates the signal field, polling receipt, or mode');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.setViewportSize({width:390,height:844});
  const mobileLumen=await page.evaluate(()=>({
    overflow:document.documentElement.scrollWidth>innerWidth,
    light:getComputedStyle(document.querySelector('.light-field')).animationName,
    shadow:getComputedStyle(document.querySelector('.light-shadow')).animationName,
    blur:getComputedStyle(document.querySelector('.glass-column')).backdropFilter
  }));
  assert(!mobileLumen.overflow&&mobileLumen.light==='none'&&mobileLumen.shadow==='none','mobile wall overflows or keeps a continuous signal animation');
  const mobileBlur=parseFloat((mobileLumen.blur.match(/blur\(([^p]+)px\)/)||[])[1]||'0');
  assert(mobileBlur<=12,'mobile glass blur exceeds 12px');
  await page.setViewportSize({width:390,height:844}); await page.locator('[data-mode-choice="management"]').click();
  await page.waitForFunction(()=>document.getElementById('dashboard').dataset.mode==='management'&&!document.getElementById('managementLayout').hidden&&document.documentElement.scrollWidth<=innerWidth&&document.querySelectorAll('#managementRecentCalls tr[data-call-id]').length===3);
  await page.screenshot({path:'output/playwright/dashboard-management-mobile.png',fullPage:true});
  const ambiguousRecords=[{...matrixBase,request_id:'ambiguous-known-a',caller:'shared-caller',client:'service-a',status:'completed',started_at:1,finished_at:2},{...matrixBase,request_id:'ambiguous-known-b',caller:'shared-caller',client:'service-b',status:'completed',started_at:2,finished_at:4},{...matrixBase,request_id:'ambiguous-unknown',caller:'shared-caller',client:'未标识服务',status:'completed',started_at:3,finished_at:5}];
  await cfg({call_records:ambiguousRecords,status_patch:{active:false,phase:'idle',calls:{active_request_id:''}}}); await page.evaluate(()=>{localStorage.setItem('ds4-dashboard-mode','monitor');localStorage.setItem('ds4-dashboard-client-map',JSON.stringify({'shared-caller':'stale-service'}))}); await reloadReady(); await page.waitForFunction(()=>document.querySelectorAll('#monitorCalls tr[data-request-id]').length===3);
  const ambiguousText=await page.locator('[data-request-id="ambiguous-unknown"]').innerText(); assert(ambiguousText.includes('未标识服务')&&!ambiguousText.includes('service-a')&&!ambiguousText.includes('service-b'),'ambiguous caller was mapped to one of multiple clients');
  assert(await page.evaluate(()=>{const map=JSON.parse(localStorage.getItem('ds4-dashboard-client-map')||'{}');return !Object.prototype.hasOwnProperty.call(map,'shared-caller')}),'ambiguous caller kept a stale persisted client mapping');
  await cfg({reset:true}); await page.evaluate(()=>localStorage.setItem('ds4-dashboard-mode','management')); await page.setViewportSize({width:1024,height:900}); await reloadReady();
  assert(await page.evaluate(()=>{const col=document.querySelector('.management-console').getBoundingClientRect().width;return col>=360&&document.documentElement.scrollWidth<=innerWidth&&getComputedStyle(document.querySelector('.settings-grid')).gridTemplateColumns.trim().split(/\s+/).length===1}),'1024px management glass column must stay >=360px with no page overflow and vertical settings');
  await page.setViewportSize({width:1024,height:900});
  await page.locator('[data-mode-choice="monitor"]').click();
  const compactDesktop = await page.evaluate(() => {
    const metrics = document.getElementById('monitorMetrics');
    const timeline = document.getElementById('inferenceTimeline').getBoundingClientRect();
    const console = document.querySelector('.monitor-console').getBoundingClientRect();
    return { gap: console.left - timeline.right, width: console.width, sw: document.documentElement.scrollWidth, vw: innerWidth, cols: getComputedStyle(metrics).gridTemplateColumns.trim().split(/\s+/).length, decode: document.querySelector('.vital-decode').getBoundingClientRect().width, prefill: document.querySelector('.vital-prefill').getBoundingClientRect().width };
  });
  assert(compactDesktop.gap >= 15 && compactDesktop.width >= 320 && compactDesktop.sw <= compactDesktop.vw && compactDesktop.cols === 4 && compactDesktop.decode > compactDesktop.prefill + 20, '1024px monitor inspector overlaps, shrinks below 320px, overflows, or signals lose their decode-first hierarchy');
  await page.setViewportSize({width:390,height:844});
  const mobileInformationFirst = await page.evaluate(() => ({
    mirrors: document.querySelectorAll('.wall-mirror').length,
    sw: document.documentElement.scrollWidth,
    vw: innerWidth,
    consoleWidth: document.querySelector('.monitor-console').getBoundingClientRect().width,
    metricsBottom: document.getElementById('monitorMetrics').getBoundingClientRect().bottom,
    timelineTop: document.getElementById('inferenceTimeline').getBoundingClientRect().top,
    traceBottom: document.querySelector('[aria-labelledby="monitorCallsTitle"]').getBoundingClientRect().bottom,
    hostTop: document.querySelector('.monitor-host').getBoundingClientRect().top,
    hostBottom: document.querySelector('.monitor-host').getBoundingClientRect().bottom,
    consoleTop: document.querySelector('.monitor-console').getBoundingClientRect().top
  }));
  assert(mobileInformationFirst.mirrors === 0 && mobileInformationFirst.sw <= mobileInformationFirst.vw && mobileInformationFirst.consoleWidth > 0 && mobileInformationFirst.metricsBottom <= mobileInformationFirst.timelineTop + 1 && mobileInformationFirst.traceBottom <= mobileInformationFirst.hostTop + 1 && mobileInformationFirst.hostBottom <= mobileInformationFirst.consoleTop + 1, 'mobile instrument layout has wallpaper, page overflow, missing inspector, or loses the metrics-to-timeline-to-trace-to-host-to-inspector order');
  await wait(300);
  assert(await page.locator('.mode-layout:not([hidden])').evaluate(node=>getComputedStyle(node).opacity==='1'),'mobile monitor screenshot was captured before the mode transition settled');
  await page.screenshot({path:'output/playwright/dashboard-monitor-mobile.png',fullPage:true});
  await cfg({offline:true}); await page.waitForFunction(()=>document.getElementById('dashboard').classList.contains('stale'));
  assert(await page.evaluate(()=>document.body.classList.contains('dashboard-stale')&&getComputedStyle(document.querySelector('.light-field')).animationName==='none'),'stale dashboard did not apply the static light-field state');
  await page.locator('[data-mode-choice="management"]').click();
  await page.locator('[data-mode-choice="monitor"]').click();
  const staleMotion=await page.evaluate(()=>({layout:getComputedStyle(document.querySelector('.mode-layout:not([hidden])')).animationName,running:document.getAnimations().filter(a=>a.animationName&&a.playState==='running').map(a=>a.animationName),pulse:document.getElementById('connectionPulse').getAnimations().filter(animation=>animation.playState==='running').length,stamp:document.getElementById('updatedAt').getAnimations().filter(animation=>animation.playState==='running').length}));
  assert(staleMotion.layout==='none'&&staleMotion.running.length===0&&staleMotion.pulse===0&&staleMotion.stamp===0,'stale dashboard started mode, metric, ambient, or polling animations: '+staleMotion.layout+'/'+staleMotion.running.join(','));
  await page.setViewportSize({width:1024,height:900});
  await cfg({offline:false}); await page.waitForFunction(()=>!document.getElementById('dashboard').classList.contains('stale')&&!document.getElementById('kvApplyNow').disabled);
  assert(await page.evaluate(()=>{const light=getComputedStyle(document.querySelector('.light-field')),shadow=getComputedStyle(document.querySelector('.light-shadow'));return !document.body.classList.contains('dashboard-stale')&&light.animationName==='signal-drift'&&light.animationPlayState==='running'&&shadow.animationName==='signal-shadow'&&shadow.animationPlayState==='running'}),'recovered desktop dashboard did not clear static state and resume both signal fields');
  await page.locator('[data-mode-choice="monitor"]').click(); await cfg({reset:true,status_patch:{active:false,phase:'idle',calls:{active_request_id:'0'}}}); await page.waitForFunction(()=>document.getElementById('monitorPhase').textContent.includes('空闲 · 就绪'));
  assert(await page.evaluate(()=>['monitorPrefill','monitorDecode','monitorCacheHit'].every(id=>document.getElementById(id).dataset.motionDirection==='none'&&document.getElementById(id).querySelectorAll('.metric-value-layer').length===1)),'unavailable metrics must keep direction=none and a single layer');
  return {ok:true,double_apply:'one transaction',apply_save:'one transaction',poll_max_active:1,revision_sequence:s.admin.map(x=>x.mode),fifth_row_bottom:fifthRowBottom,last_inspector_fact_bottom:lastInspectorFactBottom};
}
