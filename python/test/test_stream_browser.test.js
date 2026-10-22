'use strict';
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {setTimeout:delay}=require('node:timers/promises');
const {chromium}=require('playwright');

const port=Number(process.env.STREAM_BROWSER_TEST_PORT||41982);
const baseURL='http://127.0.0.1:'+port;
const python=process.env.PYTHON||'python';

async function waitForServer(child){
  let lastError=null;
  for(let attempt=0;attempt<120;attempt++){
    if(child.exitCode!==null)throw new Error('Stream fixture server exited early.');
    try{
      const response=await fetch(baseURL,{signal:AbortSignal.timeout(1000)});
      if(response.ok)return;
      lastError=new Error('HTTP '+response.status);
    }catch(error){lastError=error;}
    await delay(150);
  }
  throw new Error('Stream fixture server did not become ready: '+String(lastError));
}

(async()=>{
  const server=spawn(python,['python/test/stream_browser_fixture_server.py'],{
    cwd:process.cwd(),
    env:{...process.env,STREAM_BROWSER_TEST_PORT:String(port),PYTHONPATH:'python'}
  });
  let serverOutput='';
  server.stdout.on('data',chunk=>{serverOutput+=chunk.toString();});
  server.stderr.on('data',chunk=>{serverOutput+=chunk.toString();});
  let browser=null;
  try{
    await waitForServer(server);
    browser=await chromium.launch({headless:true,args:['--no-sandbox']});
    const page=await browser.newPage({viewport:{width:1365,height:900}});
    const pageErrors=[];
    page.on('pageerror',error=>pageErrors.push(error.message));
    await page.addInitScript(()=>{
      localStorage.setItem('self-driving-robot:arduino-command-history:city',JSON.stringify(['servo 90','servo 95']));
    });
    const workspaceLoaded=page.waitForResponse(response=>response.url().includes('/api/workspace')&&response.request().method()==='GET'&&response.ok(),{timeout:15000});
    const response=await page.goto(baseURL,{waitUntil:'domcontentloaded',timeout:20000});
    await workspaceLoaded;
    assert.equal(response.status(),200,'Stream dashboard should render');

    // History entries fill the input only; selecting one does not submit a command.
    await page.locator('#console_toggle_btn').click();
    await page.locator('[data-console-tab="arduino-commands"]').click();
    await page.locator('#arduino_command_history_panel > summary').click();
    const historyButtons=page.locator('#arduino_command_history_list .arduino-history-entry');
    assert.equal(await historyButtons.count(),2,'Saved commands should appear in the visible history');
    await historyButtons.first().click();
    assert.equal(await page.locator('#arduino_custom_command').inputValue(),'servo 95','Newest command should fill the input');
    assert.equal(await page.locator('#arduino_command_feedback').textContent(),'Loaded from history; press Enter or Send to transmit.');
    await page.locator('#arduino_command_history_clear').click();
    assert.equal(await page.locator('#arduino_command_history_count').textContent(),'0');
    assert.equal(await page.evaluate(()=>localStorage.getItem('self-driving-robot:arduino-command-history:city')),'[]');
    await page.locator('#console_toggle_btn').click();
    await page.waitForFunction(()=>window.StreamState&&document.querySelector('#video_canvas'),null,{timeout:10000});
    const checkbox=page.locator('#ext_crosshair');
    await page.evaluate(()=>{
      document.querySelectorAll('.right-panel details.dock-panel').forEach(panel=>{panel.open=true;});
    });
    await checkbox.check({timeout:5000});
    assert.equal(await checkbox.isChecked(),true);
    assert.equal(await page.locator('#video_canvas').evaluate(canvas=>canvas.classList.contains('crosshair-active')),true);

    await page.keyboard.press('Escape');
    await page.waitForFunction(()=>{
      const checkbox=document.querySelector('#ext_crosshair');
      const canvas=document.querySelector('#video_canvas');
      return checkbox&&!checkbox.checked&&canvas&&!canvas.classList.contains('crosshair-active');
    },null,{timeout:5000});
    await page.waitForFunction(()=>{
      const status=document.querySelector('#ext_workspace_save_status');
      return status&&status.dataset.state==='saved';
    },null,{timeout:8000});

    // Exercise actual zoom, grid and pan interaction handlers in the live dashboard.
    const zoom=page.locator('#workspace_zoom_percent');
    await zoom.fill('150%');
    await zoom.press('Enter');
    assert.equal(await zoom.inputValue(),'150%','Zoom percentage entry should apply');
    assert.ok(Math.abs((await page.evaluate(()=>window.collectStreamWorkspace().view.zoom))-1.5)<0.001);

    await page.locator('#ext_grid').check();
    await page.waitForFunction(()=>window.collectStreamWorkspace().view.grid===true,null,{timeout:5000});
    await page.waitForFunction(()=>document.querySelector('#ext_precision_overlay').childElementCount>0,null,{timeout:5000});

    const beforePan=await page.evaluate(()=>window.collectStreamWorkspace().view);
    await page.locator('[data-tool="pan"]').click();
    const canvasBox=await page.locator('#video_canvas').boundingBox();
    assert.ok(canvasBox&&canvasBox.width>100&&canvasBox.height>100,'Camera canvas should have a measurable viewport');
    await page.mouse.move(canvasBox.x+canvasBox.width*0.30,canvasBox.y+canvasBox.height*0.35);
    await page.mouse.down();
    await page.mouse.move(canvasBox.x+canvasBox.width*0.38,canvasBox.y+canvasBox.height*0.42,{steps:5});
    await page.mouse.up();
    await page.waitForFunction(prior=>{
      const view=window.collectStreamWorkspace().view;
      return Math.abs(view.panX-prior.panX)>1||Math.abs(view.panY-prior.panY)>1;
    },beforePan,{timeout:5000});

    await page.locator('[data-tool="select"]').click();
    await page.locator('#ext_ruler').check();
    const rulerBox=await page.locator('#video_canvas').boundingBox();
    await page.mouse.click(rulerBox.x+rulerBox.width*0.30,rulerBox.y+rulerBox.height*0.55);
    await page.mouse.move(rulerBox.x+rulerBox.width*0.50,rulerBox.y+rulerBox.height*0.65,{steps:3});
    await page.mouse.click(rulerBox.x+rulerBox.width*0.50,rulerBox.y+rulerBox.height*0.65);
    await page.waitForFunction(()=>window.collectStreamWorkspace().annotations.some(item=>item.kind==='ruler'),null,{timeout:5000});
    await page.keyboard.press('Escape');
    await page.waitForFunction(()=>!document.querySelector('#ext_ruler').checked,null,{timeout:5000});

    // Inject one save failure, then verify Retry reaches a successful save.
    await delay(600);
    await page.waitForFunction(()=>{
      const status=document.querySelector('#ext_workspace_save_status');
      return status&&status.dataset.state==='saved';
    },null,{timeout:5000});
    let failNextWorkspacePost=true;
    await page.route('**/api/workspace',async route=>{
      if(route.request().method()==='POST'&&failNextWorkspacePost){
        failNextWorkspacePost=false;
        await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'Injected workspace failure for retry test'})});
      }else await route.continue();
    });
    await page.locator('#ext_save_workspace').click();
    await page.waitForFunction(()=>{
      const status=document.querySelector('#ext_workspace_save_status');
      return status&&status.dataset.state==='error';
    },null,{timeout:5000});
    assert.equal(await page.locator('#ext_workspace_save_retry').isVisible(),true,'Failed save should expose Retry');
    await page.locator('#ext_workspace_save_retry').click();
    await page.waitForFunction(()=>{
      const status=document.querySelector('#ext_workspace_save_status');
      return status&&status.dataset.state==='saved';
    },null,{timeout:8000});
    await page.unroute('**/api/workspace');

    const persisted=await page.evaluate(async()=>{
      const response=await fetch('/api/workspace',{cache:'no-store'});
      return {ok:response.ok,data:await response.json()};
    });
    assert.equal(persisted.ok,true,'Workspace API should remain available');
    assert.equal(persisted.data.workspace.view.crosshair,false,'Esc should persist Crosshair disabled');
    assert.equal(persisted.data.workspace.view.crosshairPoint,null,'Esc should clear its pinned point');
    assert.ok(Math.abs(Number(persisted.data.workspace.view.zoom)-1.5)<0.001,'Zoom should persist');
    assert.equal(persisted.data.workspace.view.grid,true,'Grid visibility should persist');
    assert.ok(Math.abs(Number(persisted.data.workspace.view.panX)-Number(beforePan.panX))>1||
      Math.abs(Number(persisted.data.workspace.view.panY)-Number(beforePan.panY))>1,'Pan should persist');
    assert.ok(persisted.data.workspace.annotations.some(item=>item.kind==='ruler'),'Ruler measurement should persist');

    const workspaceLoadedAfterReload=page.waitForResponse(response=>response.url().includes('/api/workspace')&&response.request().method()==='GET'&&response.ok(),{timeout:15000});
    await page.reload({waitUntil:'domcontentloaded',timeout:20000});
    await workspaceLoadedAfterReload;
    await page.waitForFunction(()=>window.StreamState&&typeof window.collectStreamWorkspace==='function',null,{timeout:10000});
    await page.waitForFunction(()=>{
      const workspace=window.collectStreamWorkspace();
      return workspace&&workspace.view&&Math.abs(Number(workspace.view.zoom)-1.5)<0.001&&
        workspace.view.grid===true&&workspace.annotations.some(item=>item.kind==='ruler');
    },null,{timeout:10000});
    assert.equal(await page.locator('#ext_crosshair').isChecked(),false,'Crosshair must stay off after reload');
    assert.equal(await page.locator('#ext_grid').isChecked(),true,'Grid should restore after reload');
    assert.equal(await page.locator('#workspace_zoom_percent').inputValue(),'150%','Zoom should restore after reload');
    assert.equal(await page.locator('#video_canvas').evaluate(canvas=>canvas.classList.contains('crosshair-active')),false);
    assert.deepEqual(pageErrors,[],'Stream UI must not throw uncaught browser exceptions');
    console.log('Stream browser smoke test passed: startup, tools, Escape, zoom/grid/pan/ruler, failed-save retry, reload, and no uncaught page errors.');
  }catch(error){
    error.message+='\nFixture server output:\n'+serverOutput;
    throw error;
  }finally{
    if(browser)await browser.close().catch(()=>{});
    server.kill('SIGTERM');
    await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(3000)]);
    if(server.exitCode===null)server.kill('SIGKILL');
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
