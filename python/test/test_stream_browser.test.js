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
    const response=await page.goto(baseURL,{waitUntil:'networkidle',timeout:20000});
    assert.equal(response.status(),200,'Stream dashboard should render');

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

    const persisted=await page.evaluate(async()=>{
      const response=await fetch('/api/workspace',{cache:'no-store'});
      return {ok:response.ok,data:await response.json()};
    });
    assert.equal(persisted.ok,true,'Workspace API should remain available');
    assert.equal(persisted.data.workspace.view.crosshair,false,'Esc should persist Crosshair disabled');
    assert.equal(persisted.data.workspace.view.crosshairPoint,null,'Esc should clear its pinned point');

    await page.reload({waitUntil:'networkidle',timeout:20000});
    await page.waitForFunction(()=>window.StreamState&&document.querySelector('#ext_crosshair'),null,{timeout:10000});
    await delay(150);
    assert.equal(await page.locator('#ext_crosshair').isChecked(),false,'Crosshair must stay off after reload');
    assert.equal(await page.locator('#video_canvas').evaluate(canvas=>canvas.classList.contains('crosshair-active')),false);
    assert.deepEqual(pageErrors,[],'Stream UI must not throw uncaught browser exceptions');
    console.log('Stream browser smoke test passed: startup, Crosshair toggle/Escape, workspace persistence, reload, no uncaught page errors.');
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
