'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
require('../stream/static/stream-state.js');
const {createCommandHistory,normalizeEditorTool,normalizeWorkspaceToolState}=globalThis.StreamState;
function fakeStorage(seed){const values=new Map(Object.entries(seed||{}));return {getItem:key=>values.has(key)?values.get(key):null,setItem:(key,value)=>values.set(key,String(value)),get:key=>values.get(key)};}
test('history recalls backward/forward and restores the pre-navigation draft',()=>{
  const history=createCommandHistory({storage:fakeStorage(),key:'history'});
  history.remember('servo 90');history.remember('servo 95');
  assert.deepEqual(history.move(-1,'new draft'),{handled:true,value:'servo 95',index:1});
  assert.deepEqual(history.move(-1,'servo 95'),{handled:true,value:'servo 90',index:0});
  assert.deepEqual(history.move(1,''),{handled:true,value:'servo 95',index:1});
  assert.deepEqual(history.move(1,''),{handled:true,value:'new draft',index:2});
  assert.equal(history.move(1,'new draft').handled,false);
});
test('editing a recalled command detaches history navigation',()=>{
  const history=createCommandHistory({storage:fakeStorage(),key:'history'});history.remember('servo 90');history.remember('servo 95');
  history.move(-1,'');history.edit('servo 96');assert.equal(history.move(1,'servo 96').handled,false);
  assert.deepEqual(history.snapshot(),['servo 90','servo 95']);
});
test('history caps entries, trims commands, suppresses adjacent duplicates, and persists',()=>{
  const storage=fakeStorage(),history=createCommandHistory({storage,key:'history',limit:2});
  history.remember(' servo 90 ');history.remember('servo 90');history.remember('servo 95');history.remember('stop');
  assert.deepEqual(history.snapshot(),['servo 95','stop']);assert.deepEqual(JSON.parse(storage.get('history')),['servo 95','stop']);
});
test('malformed or unavailable storage does not break command entry',()=>{
  const malformed=fakeStorage({history:'{bad json'});assert.deepEqual(createCommandHistory({storage:malformed,key:'history'}).snapshot(),[]);
  const failing={getItem(){throw Error('blocked');},setItem(){throw Error('blocked');}};
  const history=createCommandHistory({storage:failing,key:'history'});assert.equal(history.remember('stop'),'stop');assert.deepEqual(history.snapshot(),['stop']);
});
test('clearing history removes persisted values and resets navigation state',()=>{
  const storage=fakeStorage();
  const history=createCommandHistory({storage,key:'history'});
  history.remember('servo 90');history.remember('servo 95');
  assert.equal(history.move(-1,'draft').value,'servo 95');
  history.clear();
  assert.deepEqual(history.snapshot(),[]);
  assert.deepEqual(JSON.parse(storage.get('history')),[]);
  assert.equal(history.length,0);
  assert.equal(history.move(-1,'new draft').handled,false);
  history.remember('stop');
  assert.deepEqual(history.snapshot(),['stop']);
});
test('favorites are labeled, case-insensitive, bounded, validated, and persisted',()=>{
  const storage=fakeStorage();
  const favorites=globalThis.StreamState.createCommandFavorites({storage,key:'favorites',limit:2});
  assert.deepEqual(favorites.add('Park position','servo 95'),{label:'Park position',command:'servo 95'});
  favorites.add('park POSITION','servo 100');
  assert.equal(favorites.length,1,'A label is unique ignoring case and updates the existing entry');
  favorites.add('Safety stop','stop');
  favorites.add('Lights','led 1');
  assert.deepEqual(favorites.snapshot(),[
    {label:'Safety stop',command:'stop'},
    {label:'Lights',command:'led 1'}
  ]);
  assert.deepEqual(JSON.parse(storage.get('favorites')),favorites.snapshot());
  assert.equal(favorites.add('Bad command','servo 95\\nsecond'),null);
  assert.equal(favorites.add('Unicode','停'),null);
  assert.equal(favorites.remove('safety STOP'),true);
  assert.equal(favorites.remove('missing'),false);
  favorites.clear();
  assert.deepEqual(JSON.parse(storage.get('favorites')),[]);
});
test('disabled crosshair cannot restore a pinned workspace point',()=>{
  const state=normalizeWorkspaceToolState({tool:'ruler',crosshair:false,crosshairPoint:{space:'image',u:.4,v:.7}});
  assert.equal(state.editorTool,'ruler');assert.equal(state.crosshairEnabled,false);assert.equal(state.crosshairPoint,null);assert.equal(state.crosshairPinned,false);
});
test('workspace state rejects null, empty, non-finite, and out-of-range coordinates',()=>{
  for(const point of [
    {space:'image',u:null,v:0.2},
    {space:'image',u:'',v:0.2},
    {space:'image',u:'NaN',v:0.2},
    {space:'canvas',u:1.1,v:0.2},
    {space:'canvas',u:0.2,v:-0.1},
    {space:'image',u:1000001,v:0.2}
  ]){
    const state=normalizeWorkspaceToolState({crosshair:true,crosshairPoint:point});
    assert.equal(state.crosshairPoint,null,JSON.stringify(point));
    assert.equal(state.crosshairPinned,false,JSON.stringify(point));
  }
});
test('workspace crosshair and tool values are normalized',()=>{
  const state=normalizeWorkspaceToolState({tool:'unknown',crosshair:true,crosshairPoint:{space:'image',u:'0.4',v:.7}});
  assert.equal(state.editorTool,'select');assert.deepEqual(state.crosshairPoint,{space:'image',u:.4,v:.7});assert.equal(state.crosshairPinned,true);
  assert.equal(normalizeEditorTool('pan'),'pan');assert.equal(normalizeEditorTool(null),'select');
  assert.equal(normalizeWorkspaceToolState({crosshair:true,crosshairPoint:{space:'other',u:0,v:0}}).crosshairPoint,null);
});
