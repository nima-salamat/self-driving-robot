HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Interactive ROI & Settings</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>

:root {
  color-scheme: dark;
  --bg: #0b1119;
  --panel: #121b27;
  --panel-raised: #182332;
  --border: #2b3949;
  --accent: #22d3ee;
  --accent-soft: rgba(34, 211, 238, .12);
  --muted: #9bacbd;
  --txt: #e6edf5;
}
* { box-sizing: border-box; }
html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; }
body {
  padding: 0;
  font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif;
  color: var(--txt);
  background: var(--bg);
}
.container {
  width: 100%;
  height: 100vh;
  height: 100dvh;
  max-width: none;
  margin: 0;
  padding: 8px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  gap: 8px;
  align-items: stretch;
  overflow: hidden;
}
.container > .card {
  min-width: 0;
  min-height: 0;
  height: 100%;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, .2);
}
.header {
  flex: 0 0 auto;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 32px;
  margin-bottom: 8px;
}
.h1 { font-size: 16px; font-weight: 700; white-space: nowrap; }
.header > .small { min-width: 0; line-height: 1.35; }
.controls {
  flex: 0 0 auto;
  display: flex;
  gap: 6px;
  align-items: center;
  min-height: 34px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
select, input[type=number], input[type=color], input[type=checkbox], input[type=range] {
  background: #0b1420;
  color: var(--txt);
  border: 1px solid var(--border);
  padding: 5px 7px;
  border-radius: 5px;
}
input[type=checkbox] { accent-color: var(--accent); }
input[type=range] { accent-color: var(--accent); }
button.btn {
  background: var(--accent);
  color: #06202a;
  border: 1px solid transparent;
  padding: 7px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-weight: 700;
  transition: background .15s ease;
}
button.btn:hover { background: #67e8f9; }
button.ghost {
  background: #101925;
  border: 1px solid var(--border);
  color: var(--txt);
  padding: 6px 9px;
  border-radius: 5px;
  cursor: pointer;
}
button.ghost:hover { border-color: var(--accent); background: var(--accent-soft); }
button:disabled, input:disabled, select:disabled { opacity: .45; cursor: not-allowed; }
.canvas-stage {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 80px;
  overflow: hidden;
  padding: 5px;
  border: 1px solid #344456;
  border-radius: 6px;
  background-color: #080d14;
  background-image:
    linear-gradient(rgba(115, 145, 170, .08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(115, 145, 170, .08) 1px, transparent 1px);
  background-size: 24px 24px;
}
canvas {
  /* Keep the canvas's intrinsic dimensions aligned with the camera frame.
     max-size constraints scale it down without changing its aspect ratio. */
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: 100%;
  border-radius: 3px;
  display: block;
  background: #000;
}
.label { width: 145px; color: var(--muted); font-size: 12px; }
.small { font-size: 12px; color: var(--muted); }
.right-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 1px;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: #33475b transparent;
}
.dock-panel {
  flex: 0 0 auto;
  min-width: 0;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
}
.dock-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 38px;
  padding: 9px 11px;
  list-style: none;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .02em;
}
.dock-summary::-webkit-details-marker { display: none; }
.dock-summary:hover { background: rgba(255,255,255,.025); }
.dock-panel[open] .dock-summary {
  color: var(--accent);
  background: var(--accent-soft);
  border-bottom: 1px solid var(--border);
}
.dock-chevron { color: var(--muted); transition: transform .15s ease; }
.dock-panel[open] .dock-chevron { transform: rotate(180deg); }
.dock-content { padding: 10px; min-width: 0; }
.dock-content > .section-title { display: none; }
.inputs { max-height: 220px; overflow: auto; padding-right: 5px; }
.input-wrap { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.counter { min-width: 64px; text-align: center; }
.section-title { font-weight: 700; margin-bottom: 10px; font-size: 14px; color: var(--accent); }
.toggle-row { display: flex; gap: 7px; align-items: center; margin-bottom: 7px; flex-wrap: wrap; }
.notice {
  background: rgba(255,255,255,.025);
  padding: 8px;
  border: 1px solid rgba(255,255,255,.05);
  border-radius: 5px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.45;
}
.workspace-statusbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 25px;
  padding: 3px 2px 1px;
  color: #a6bacb;
  font: 11px ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: nowrap;
  overflow: hidden;
}
.workspace-statusbar .cad-help { overflow: hidden; text-overflow: ellipsis; }
.workspace-statusbar .cad-area { margin-left: auto; color: var(--accent); }
.status-line { margin-top: 4px; font-size: 12px; color: var(--accent); }
.small-muted { font-size: 11px; color: var(--muted); }
.form-row { display: flex; gap: 7px; align-items: center; margin: 5px 0; flex-wrap: wrap; }
.toast {
  position: fixed;
  right: 16px;
  bottom: 16px;
  max-width: min(420px, calc(100vw - 32px));
  background: #101925;
  border: 1px solid var(--border);
  padding: 10px 13px;
  border-radius: 6px;
  color: var(--txt);
  box-shadow: 0 8px 30px rgba(0,0,0,.4);
  z-index: 9999;
}
.encoder-map-link {
  margin-left: auto;
  flex: 0 0 auto;
  color: var(--accent);
  font-size: 11px;
  text-decoration: none;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 5px;
  white-space: nowrap;
}
.encoder-map-link:hover { background: var(--accent-soft); }
.container.dock-hidden { grid-template-columns: minmax(0, 1fr); }
.container.dock-hidden .right-panel { display: none; }
@media (max-width: 1050px) {
  .container { grid-template-columns: minmax(0, 1fr) 285px; }
  .h1 { font-size: 14px; }
  .header > .small { display: none; }
  .label { width: 125px; }
}
@media (max-width: 720px) {
  .container { grid-template-columns: minmax(0, 1fr); padding: 5px; }
  .container > .card { padding: 7px; }
  .right-panel {
    display: none;
    position: fixed;
    z-index: 100;
    top: 50px;
    right: 5px;
    bottom: 5px;
    width: min(330px, calc(100vw - 10px));
    height: auto;
    padding: 5px;
    background: #0b1119;
    border: 1px solid var(--border);
    border-radius: 7px;
    box-shadow: 0 14px 45px rgba(0,0,0,.6);
  }
  .container.show-dock .right-panel { display: flex; }
  .header { gap: 6px; }
  .h1 { font-size: 13px; }
  .controls { gap: 4px; }
  .controls .small { font-size: 11px; }
  #workspace_zoom { width: 58px !important; }
  .workspace-statusbar { gap: 7px; font-size: 10px; }
  .workspace-statusbar .cad-help { display: none; }
  .encoder-map-link { padding: 5px; font-size: 10px; }
}


.container { height:calc(100vh - 32px); height:calc(100dvh - 32px); grid-template-columns:minmax(0,1fr) 315px; }
.app-menubar{height:32px;min-height:32px;display:flex;align-items:center;gap:3px;padding:0 8px;background:#0a1018;border-bottom:1px solid #263444;color:var(--txt);user-select:none;position:relative;z-index:300}
.app-brand{display:flex;align-items:center;gap:7px;padding:0 10px 0 4px;font-size:11px;font-weight:800;letter-spacing:.07em;color:#dce8f3;white-space:nowrap}
.brand-mark{width:17px;height:17px;border:2px solid var(--accent);border-radius:4px;position:relative}.brand-mark:after{content:"";position:absolute;inset:3px;background:var(--accent);opacity:.65}
.menu-group{position:relative;height:100%;display:flex;align-items:center}.menu-group>summary{list-style:none;cursor:pointer;padding:6px 9px;border-radius:4px;font-size:12px;color:#c2cfdd}.menu-group>summary::-webkit-details-marker{display:none}
.menu-group[open]>summary,.menu-group>summary:hover{background:#1c2a39;color:white}
.menu-dropdown{display:flex;flex-direction:column;position:absolute;top:29px;left:0;min-width:196px;padding:5px;background:#151f2c;border:1px solid #324253;border-radius:6px;box-shadow:0 12px 28px rgba(0,0,0,.45);z-index:500}
.menu-dropdown button{text-align:left;border:0;background:transparent;color:#e0e8f1;padding:7px 9px;border-radius:4px;font:inherit;font-size:12px;cursor:pointer;white-space:nowrap}.menu-dropdown button:hover{background:#233549}.menu-dropdown .menu-separator{border-top:1px solid #2b3949;margin:4px 5px}
.menu-spacer{flex:1}.menu-live{color:#9bacbd;font:11px ui-monospace,Consolas,monospace;white-space:nowrap}
.workspace-main{flex:1 1 auto;display:grid;grid-template-columns:42px minmax(0,1fr);grid-template-rows:minmax(0,1fr) auto;min-width:0;min-height:0;gap:7px}
.left-toolbar{display:flex;flex-direction:column;align-items:stretch;gap:5px;padding:5px 3px;background:#0b131d;border:1px solid #263444;border-radius:6px;min-height:0}
.tool-button{position:relative;width:34px;height:34px;padding:0;border:1px solid transparent;border-radius:5px;background:transparent;color:#b9c7d6;cursor:pointer;font-size:17px}.tool-button:hover{background:#1b2b3b;color:#fff}.tool-button[aria-pressed="true"]{color:var(--accent);border-color:#237185;background:rgba(34,211,238,.13)}
.tool-tip{display:none;position:absolute;z-index:350;left:38px;top:4px;padding:5px 7px;border:1px solid #324253;border-radius:4px;color:var(--txt);background:#111b27;font-size:11px;white-space:nowrap;pointer-events:none}.tool-button:hover .tool-tip{display:block}.tool-separator{height:1px;margin:3px 4px;background:#2b3949}
.workspace-stage-column{display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden;gap:4px}.workspace-stage-column .canvas-stage{width:100%}.workspace-stage-column .workspace-statusbar{min-height:24px}.workspace-stage-column .workspace-actionbar{flex:0 0 auto;margin-top:0!important;min-height:30px;gap:6px!important}#video_canvas{touch-action:none}
.bottom-console{grid-column:1/-1;min-width:0;height:34px;overflow:hidden;display:flex;flex-direction:column;border:1px solid #2c3a4a;border-radius:6px;background:#0a1018;transition:height .16s ease}.bottom-console.console-open{height:178px}
.console-titlebar{flex:0 0 32px;display:flex;align-items:center;gap:8px;padding:0 9px;background:#111a25;border-bottom:1px solid #273646}.console-toggle{padding:3px 2px;border:0;background:transparent;color:#d7e2ed;cursor:pointer;font-size:11px;font-weight:700}
.console-tab{height:31px;padding:0 8px;border:0;border-bottom:2px solid transparent;background:transparent;color:#95a8ba;cursor:pointer;font-size:11px}.console-tab[aria-selected="true"]{color:#e5eef7;border-bottom-color:var(--accent)}.console-count{color:#91a6bb;font:10px ui-monospace,monospace}.console-flex{flex:1}
.console-clear{border:1px solid #324253;border-radius:4px;background:#131e2b;color:#c5d3e0;padding:4px 7px;cursor:pointer;font-size:10px}.console-body{min-height:0;flex:1;overflow:auto;padding:3px 0}.console-body[hidden]{display:none}
.console-entry{display:grid;grid-template-columns:86px 50px minmax(0,1fr);gap:8px;padding:3px 9px;color:#c4d0dc;font:11px/1.35 ui-monospace,Consolas,monospace}.console-entry:hover{background:rgba(255,255,255,.035)}.console-time{color:#8499ad}.console-level{color:#22d3ee}.console-level.warn{color:#fbbf24}.console-level.error{color:#fb7185}.console-message{overflow-wrap:anywhere;white-space:pre-wrap}.console-empty{padding:10px;color:#7e91a5;font-size:11px}
.right-panel .properties-panel{order:-1}.properties-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:7px}.property-field{min-width:0;display:flex;flex-direction:column;gap:4px;color:#9bacbd;font-size:10px}.property-field input,.property-field select{width:100%;min-width:0;font-size:12px}.property-actions{display:flex;gap:6px;margin-top:9px}.property-actions>button{flex:1}.property-hint{color:#8195a8;font-size:10px;line-height:1.4;margin-top:7px}#prop_point_fields[hidden],#prop_roi_fields[hidden]{display:none!important}
@media(max-width:1050px){.container{grid-template-columns:minmax(0,1fr) 285px}.workspace-main{grid-template-columns:38px minmax(0,1fr)}.tool-button{width:30px;height:31px}.left-toolbar{padding-left:2px;padding-right:2px}}
@media(max-width:720px){.app-brand{padding-right:3px}.menu-group>summary{padding:5px;font-size:11px}.menu-live{display:none}.workspace-main{grid-template-columns:36px minmax(0,1fr);gap:4px}.left-toolbar{gap:3px}.tool-button{width:29px;height:30px}.bottom-console.console-open{height:155px}.console-entry{grid-template-columns:72px 42px minmax(0,1fr);gap:5px;font-size:10px}.workspace-stage-column .workspace-actionbar .small{display:none}}

</style>
<style>
/* Extended CAD/workspace controls */
:root{--right-pane-width:315px}
@media(min-width:721px){.container{grid-template-columns:minmax(0,1fr) var(--right-pane-width)!important}}
@media(max-width:720px){.container{grid-template-columns:minmax(0,1fr)!important}}
.right-panel{min-width:250px;position:relative}
.right-panel:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;cursor:col-resize;z-index:6}
.ext-list{display:grid;gap:4px;margin-top:7px}.ext-list-row{display:flex;gap:6px;align-items:center;justify-content:space-between;padding:5px;border:1px solid var(--border);border-radius:5px;font-size:11px}.ext-list-row button{padding:3px 6px}
.ext-layer-row{display:grid;grid-template-columns:18px minmax(0,1fr) 28px minmax(55px,100px);align-items:center;gap:5px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:11px}.ext-layer-row input[type=color]{width:26px;height:24px;padding:1px}.ext-layer-row input[type=range]{min-width:0;width:100%}
.ext-pre{background:#07101a;color:#c5d5e5;border:1px solid var(--border);border-radius:5px;padding:8px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:180px;overflow:auto;font:10px/1.45 ui-monospace,Consolas,monospace;margin:6px 0 0}
.ext-log-pre{max-height:260px}.ext-charts{display:grid;gap:7px;margin:8px 0}.ext-charts canvas{display:block;width:100%;height:58px;background:#07101a;border:1px solid var(--border);border-radius:4px}
.ext-gallery{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px}.ext-gallery-card{border:1px solid var(--border);border-radius:5px;overflow:hidden;min-width:0}.ext-gallery-card img{display:block;width:100%;aspect-ratio:4/3;object-fit:contain;background:#050a11}.ext-gallery-card div{padding:4px;font-size:10px;color:var(--muted);overflow-wrap:anywhere}.ext-stop-btn{background:#b91c1c!important;color:white!important}.ext-mini-label{color:var(--muted);font-size:10px}.ext-feature-row{display:flex;justify-content:space-between;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);font-size:11px}
#ext_precision_overlay{position:absolute;left:0;top:0;width:1px;height:1px;pointer-events:none;z-index:2;overflow:hidden}
#ext_command_palette{position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.65);display:none;align-items:flex-start;justify-content:center;padding-top:12vh}
#ext_command_palette .palette-box{width:min(620px,92vw);max-height:70vh;overflow:auto;background:#0b1420;border:1px solid var(--accent);border-radius:9px;padding:12px;box-shadow:0 18px 60px #000}
#ext_command_palette input{width:100%;margin-bottom:8px;padding:10px}
#ext_command_list{display:grid;gap:4px}#ext_command_list button{text-align:left;background:#101925;border:1px solid var(--border);color:var(--txt);padding:8px;border-radius:5px}
#ext_command_list button:hover{border-color:var(--accent);background:var(--accent-soft)}
.ext-tool-active{border-color:var(--accent)!important;color:var(--accent)!important}
</style>
<style>
/* Stable, compact stream workspace and a real camera-only fullscreen view. */
.container { padding:6px; gap:6px; }
.container > .card { padding:7px 8px; }
.header { min-height:28px; margin-bottom:5px; gap:7px; }
.header > .small { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; line-height:1.2; }
.controls { min-height:28px; margin-bottom:5px; gap:5px; }
.controls select, .controls input { max-height:28px; }
.workspace-stage-column { min-width:0; min-height:0; }
.canvas-stage { position:relative; }
.canvas-fullscreen-btn {
  position:absolute; top:8px; right:8px; z-index:5;
  padding:5px 8px; border:1px solid #3b5268; border-radius:5px;
  color:#e6edf5; background:rgba(8,15,24,.88); font-size:11px;
  font-weight:650; line-height:1.2; cursor:pointer;
  box-shadow:0 2px 9px rgba(0,0,0,.28);
}
.canvas-fullscreen-btn:hover { border-color:var(--accent); background:#142536; }
.canvas-fullscreen-btn:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
#canvas_stage:fullscreen, #canvas_stage:-webkit-full-screen {
  position:fixed; inset:0; z-index:99980;
  display:flex !important; align-items:center; justify-content:center;
  width:100vw !important; height:100vh !important; height:100dvh !important;
  min-width:0; min-height:0; max-width:none; max-height:none;
  margin:0; padding:0; border:0; border-radius:0; background:#05090f;
}
#canvas_stage:fullscreen #video_canvas, #canvas_stage:-webkit-full-screen #video_canvas {
  max-width:none; max-height:none; flex:0 0 auto;
}
#canvas_stage:fullscreen .canvas-fullscreen-btn,
#canvas_stage:-webkit-full-screen .canvas-fullscreen-btn { top:12px; right:12px; }
.right-panel { gap:5px; }
.dock-summary { min-height:31px; padding:6px 9px; font-size:11px; }
.dock-content { padding:7px; }
.properties-mode {
  height:18px; min-height:18px; margin-bottom:5px; line-height:18px;
  overflow:hidden; white-space:nowrap; text-overflow:ellipsis; font-size:10px;
}
.properties-grid { grid-auto-rows:44px; gap:5px; }
.property-field {
  height:44px; min-height:44px; gap:3px; line-height:12px;
  overflow:hidden; white-space:nowrap;
}
.property-field input, .property-field select {
  height:26px; min-height:26px; padding:3px 5px; font-size:11px;
}
.property-actions { gap:5px; margin-top:5px; }
.property-actions > button { height:28px; min-height:28px; padding:4px 7px; font-size:11px; }
.property-hint {
  height:27px; min-height:27px; max-height:27px; margin-top:5px;
  overflow:hidden; font-size:10px; line-height:13px;
  display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2;
}
.form-row { min-height:26px; gap:5px; margin:3px 0; }
.input-wrap { min-height:28px; height:28px; gap:5px; margin-bottom:3px; }
#inputs_container { height:220px; max-height:220px; }
#inputs_container .label { flex:0 0 118px; width:118px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
#inputs_container .counter { width:58px; min-width:58px; height:25px; padding:3px 5px; }
#inputs_container .btn-inc { height:25px; padding:3px 5px; font-size:10px; white-space:nowrap; }
#bev_inputs_container { height:160px; max-height:160px; }
.ext-layer-row { padding:3px 0; }
@media (max-width:720px) {
  .header { min-height:26px; }
  .right-panel {
    position:fixed !important; z-index:450; top:42px; right:5px; bottom:5px;
    width:min(350px,calc(100vw - 10px)); min-width:0; max-width:calc(100vw - 10px);
    height:auto; padding:5px; background:#0b1119;
    border:1px solid var(--border); border-radius:7px;
    box-shadow:0 14px 45px rgba(0,0,0,.6);
  }
  .container.show-dock .right-panel { display:flex !important; position:fixed !important; }
  .container:not(.show-dock) .right-panel { display:none !important; }
  .right-panel:before { display:none; }
  .property-field { height:42px; min-height:42px; }
  .properties-grid { grid-auto-rows:42px; }
  .canvas-fullscreen-btn { top:5px; right:5px; padding:4px 6px; font-size:10px; }
}
</style>
</head>
<body>
<div class="app-menubar" role="menubar" aria-label="Workspace menu">
<div class="app-brand"><span class="brand-mark" aria-hidden="true"></span><span>ROBOY STUDIO</span></div>
<details class="menu-group"><summary>File</summary><div class="menu-dropdown" role="menu"><button type="button" data-action="export-config">Export Full Configuration JSON…</button><button type="button" data-action="refresh-config">Reload Configuration</button><div class="menu-separator"></div><button type="button" data-action="take-picture">Capture Camera Image</button></div></details>
<details class="menu-group"><summary>Edit</summary><div class="menu-dropdown" role="menu"><button type="button" data-action="clear-selection">Clear Selection</button><button type="button" data-action="apply-base">Apply Base Settings</button><div class="menu-separator"></div><button type="button" data-action="properties">Show Properties Panel</button></div></details>
<details class="menu-group"><summary>View</summary><div class="menu-dropdown" role="menu"><button type="button" data-action="zoom-in">Zoom In</button><button type="button" data-action="zoom-out">Zoom Out</button><button type="button" data-action="fit-view">Fit / Reset View</button><button type="button" data-action="toggle-fullscreen">Fullscreen Camera</button><button type="button" data-action="toggle-overlays">Toggle Overlays</button><button type="button" data-action="toggle-console">Toggle Event Console</button><button type="button" data-action="toggle-properties">Show / Hide Panels</button></div></details>
<details class="menu-group"><summary>Tools</summary><div class="menu-dropdown" role="menu"><button type="button" data-action="tool-select">Select / Edit ROI</button><button type="button" data-action="tool-pan">Hand / Pan View</button><button type="button" data-action="freeze">Freeze Camera Frame</button><button type="button" data-action="unfreeze">Return to Live Camera</button></div></details>
<details class="menu-group"><summary>Help</summary><div class="menu-dropdown" role="menu"><button type="button" data-action="help">Mouse & Keyboard Shortcuts</button></div></details>
<button type="button" class="ghost" id="ext_open_palette" title="Command Palette · Ctrl+K" style="margin-left:6px;padding:4px 8px">⌘ Commands</button><span class="menu-spacer"></span><span class="menu-live" id="menu_live_status">LIVE · {{ mode|capitalize }} MODE</span></div>
<div class="container">
  <div class="card">
    <div class="header">
      <div class="h1">Interactive ROI Editor — {{ mode|capitalize }} Mode</div>
      <div class="small">Drag to move/resize bounding boxes or BEV corners. Use sliders for Trapezoid shapes. <span id="mode_features" style="color:var(--accent);"></span></div>
      {% if encoder_map_enabled %}<a class="encoder-map-link" href="/encoder-map">Odometry Map ↗</a>{% endif %}
      <button id="toggle_dock_btn" type="button" class="ghost">Hide Panels</button>
    </div>
    <div class="controls">
      <label class="small" for="variable_select">Select Object</label>
      <select id="variable_select">
        <option value="NONE">-- NONE --</option>
        {% for var in variables %}
          <option value="{{ var }}">{{ var }}</option>
        {% endfor %}
      </select>
      <button id="clear_selection" class="ghost">Clear</button>
      <button id="center_reset" class="ghost">Center Base</button>
      <div style="flex:1"></div>
      
      <label class="small" style="color:var(--accent); font-weight:bold;">
        View Zoom <input id="workspace_zoom" type="range" min="0.3" max="4.0" step="0.1" value="1.0" style="width:70px; vertical-align:middle;">
      </label>

      <label class="small" style="color:var(--accent); font-weight:bold; margin-left: 10px;">Show Overlays <input id="show_rects" type="checkbox" checked></label>
      <div id="frame_mode" class="small status-line" style="margin-left: 10px;">Mode: Live</div>
    </div>
    <div class="workspace-main">
<aside class="left-toolbar" aria-label="Tools">
<button type="button" class="tool-button" data-tool="select" aria-pressed="true" title="Select / Edit ROI (V)">↖<span class="tool-tip">Select / Edit ROI · V</span></button>
<button type="button" class="tool-button" data-tool="pan" aria-pressed="false" title="Pan view (H); middle mouse also pans">✋<span class="tool-tip">Hand / Pan · H · Middle mouse</span></button><div class="tool-separator"></div>
<button type="button" class="tool-button" data-action="zoom-in" title="Zoom in (+)">＋<span class="tool-tip">Zoom In · +</span></button>
<button type="button" class="tool-button" data-action="zoom-out" title="Zoom out (-)">−<span class="tool-tip">Zoom Out · -</span></button>
<button type="button" class="tool-button" data-action="fit-view" title="Fit view (0)">⌗<span class="tool-tip">Fit / Reset View · 0</span></button><div class="tool-separator"></div>
<button type="button" class="tool-button" id="tool_overlays_btn" aria-pressed="true" title="Toggle overlays (O)">◉<span class="tool-tip">Show / Hide Overlays · O</span></button>
<button type="button" class="tool-button" data-action="properties" title="Properties panel">☷<span class="tool-tip">Properties Panel</span></button><div class="tool-separator"></div>
<button type="button" class="tool-button" data-action="toggle-console" title="Recent events console">▤<span class="tool-tip">Recent Events · Ctrl+Backtick</span></button></aside>
<div class="workspace-stage-column">
    <div id="canvas_stage" class="canvas-stage">
      <button id="camera_fullscreen_btn" class="canvas-fullscreen-btn" type="button" aria-label="Expand camera frame to fullscreen" aria-pressed="false" title="Expand camera frame to fullscreen">⛶ Fullscreen</button>
      <canvas id="video_canvas" width="900" height="600"></canvas>
    </div>
    <div class="workspace-statusbar" aria-live="off">
      <span id="cad_cursor_x">X: — px</span>
      <span id="cad_cursor_y">Y: — px</span>
      <span id="cad_cursor_u">U: — %</span>
      <span id="cad_cursor_v">V: — %</span>
      <span class="cad-help">Drag ROI edges/handles or BEV corner points · coordinates are shown relative to the camera image</span>
      <span id="cad_selected_area" class="cad-area">Object: NONE</span>
    </div>
    <div class="workspace-actionbar" style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button id="apply_all" class="btn">Apply Base Settings</button>
      <button id="refresh_vals" class="ghost">Refresh Feed</button>
      <button id="download_json" class="ghost">Download JSON</button>
      <div style="flex:1"></div>
      <div class="small">Tip: Freeze frame to tune angles accurately</div>
    </div>
</div>
<section class="bottom-console" id="bottom_console" aria-label="Recent workspace events">
<div class="console-titlebar"><button class="console-toggle" id="console_toggle_btn" type="button" aria-expanded="false">⌃ EVENT CONSOLE</button><button class="console-tab" type="button" data-console-tab="events" aria-selected="true">Events</button><button class="console-tab" type="button" data-console-tab="api" aria-selected="false">Requests</button><span class="console-count" id="console_count">0 events</span><input id="console_filter" type="search" placeholder="Filter console…" aria-label="Filter console" style="width:135px;min-width:80px;font-size:10px;padding:4px"><select id="console_level" aria-label="Console log level" style="font-size:10px;padding:3px"><option value="ALL">All levels</option><option value="INFO">Info</option><option value="WARN">Warn</option><option value="ERROR">Error</option></select><label class="small-muted" style="display:flex;align-items:center;gap:3px;white-space:nowrap"><input type="checkbox" id="console_pause">Pause</label><label class="small-muted" style="display:flex;align-items:center;gap:3px;white-space:nowrap"><input type="checkbox" id="console_autoscroll" checked>Auto-scroll</label><button class="console-clear" id="console_export_btn" type="button">Export</button><span class="console-flex"></span><button class="console-clear" id="console_clear_btn" type="button">Clear</button></div>
<div class="console-body" id="console_events" role="log" aria-live="off"><div class="console-empty">Waiting for workspace events…</div></div>
<div class="console-body" id="console_api" role="log" aria-live="off" hidden><div class="console-empty">Request diagnostics will appear here.</div></div>
</section>
</div>
</div>

<div class="right-panel">
<details class="dock-panel properties-panel" open><summary class="dock-summary"><span>Properties</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
<div class="properties-mode" id="properties_mode">RL · ROI bounds</div>
<label class="property-field" style="margin-bottom:8px;">Object / Point<select id="prop_target"><option value="RL">Right Lane ROI (RL)</option><option value="LL">Left Lane ROI (LL)</option><option value="CW">Crosswalk ROI (CW)</option><option value="ST">Sign / Tag ROI (ST)</option><option value="OBJ">Object ROI (OBJ)</option><option value="BEV_TL">BEV · Top Left</option><option value="BEV_TR">BEV · Top Right</option><option value="BEV_BR">BEV · Bottom Right</option><option value="BEV_BL">BEV · Bottom Left</option></select></label>
<div class="properties-grid" id="prop_roi_fields"><label class="property-field">Left (U) <input id="prop_left" type="number" min="0" max="1" step="0.001"></label><label class="property-field">Top (V) <input id="prop_top" type="number" min="0" max="1" step="0.001"></label><label class="property-field">Right (U) <input id="prop_right" type="number" min="0" max="1" step="0.001"></label><label class="property-field">Bottom (V) <input id="prop_bottom" type="number" min="0" max="1" step="0.001"></label></div>
<div class="properties-grid" id="prop_point_fields" hidden><label class="property-field">X / U <input id="prop_point_x" type="number" min="-5" max="5" step="0.001"></label><label class="property-field">Y / V <input id="prop_point_y" type="number" min="-5" max="5" step="0.001"></label></div>
<div class="property-actions"><button type="button" class="btn" id="prop_apply_btn">Apply</button><button type="button" class="ghost" id="prop_revert_btn">Reload</button></div><div class="property-hint" id="prop_hint">Normalized camera coordinates (0–1). Select a region to inspect or edit.</div>
</div></details>
    <details class="dock-panel"><summary class="dock-summary"><span>Arduino Telemetry</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div id="control_notice" class="notice" style="margin-bottom:10px;"></div>
      <div class="section-title">Arduino Telemetry</div>
      <div id="arduino_status" class="small status-line">Waiting for serial state...</div>
      <pre id="arduino_output" style="max-height:180px;overflow:auto;margin:8px 0 0;padding:8px;background:#050b15;border-radius:8px;color:var(--txt);font-size:12px;white-space:pre-wrap"></pre>
    </div></details>

  
      <details class="dock-panel" open><summary class="dock-summary"><span>Runtime Health</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
        <div class="section-title">Runtime Health</div>
        <div id="health_state" class="status-line">State: UNKNOWN</div>
        <div id="health_faults" class="small">Faults: none</div>
        <div id="health_metrics" class="small" style="margin-top:6px;"></div>
      </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Bird's Eye View (BEV) Config</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Bird's Eye View (BEV) Config</div>
      <div class="form-row" style="margin-bottom: 10px;">
        <label class="label" style="color:var(--txt); font-weight:bold;">Enable BEV System</label>
        <input type="checkbox" id="use_bev_toggle">
      </div>
      
      <div class="inputs" id="bev_inputs_container" style="max-height:160px; overflow-y:auto; font-size:12px;">
        <div class="input-wrap"><div class="label">TL_X</div><input id="BEV_SRC_TL_X" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">TL_Y</div><input id="BEV_SRC_TL_Y" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">TR_X</div><input id="BEV_SRC_TR_X" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">TR_Y</div><input id="BEV_SRC_TR_Y" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">BR_X</div><input id="BEV_SRC_BR_X" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">BR_Y</div><input id="BEV_SRC_BR_Y" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">BL_X</div><input id="BEV_SRC_BL_X" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">BL_Y</div><input id="BEV_SRC_BL_Y" type="number" step="0.01" class="counter"></div>
      </div>
      <div style="margin-top:10px">
         <button id="confirm_bev_inputs" class="btn">Apply BEV Inputs</button>
      </div>
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>ROI Shape & Factors</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">ROI Shape & Factors</div>
      <div class="form-row"><label class="label">Lane Mode</label>
        <select id="lane_roi_mode" style="width: 140px;">
          <option value="rectangle">Rectangle</option><option value="trapezoid">Trapezoid</option>
        </select>
      </div>
      <div class="form-row"><label class="label">RL Top factor</label><input id="rl_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="rl_factor_val" class="small" style="width:30px;"></span></div>
      <div class="form-row"><label class="label">LL Top factor</label><input id="ll_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="ll_factor_val" class="small" style="width:30px;"></span></div>
      <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
      <div class="form-row"><label class="label">Crosswalk Trapezoid</label><input type="checkbox" id="cw_trap_mode"></div>
      <div class="form-row"><label class="label">CW Top Factor</label><input id="cw_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="cw_factor_val" class="small" style="width:30px;"></span></div>
      <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
      <div class="form-row"><label class="label">Sign/Tag Trapezoid</label><input type="checkbox" id="st_trap_mode"></div>
      <div class="form-row"><label class="label">ST Top Factor</label><input id="st_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="st_factor_val" class="small" style="width:30px;"></span></div>
      <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
      <div class="form-row"><label class="label">Object Trapezoid</label><input type="checkbox" id="obj_trap_mode"></div>
      <div class="form-row"><label class="label">OBJ Top Factor</label><input id="obj_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="obj_factor_val" class="small" style="width:30px;"></span></div>
      <div style="margin-top:10px"><button id="confirm_shape" class="btn">Save Shapes to System</button></div>
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Bounding Box Adjustments</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Bounding Box Adjustments</div>
      <div class="inputs" id="inputs_container">
        {% for var in variables %}
        <div class="input-wrap">
          <div class="label">{{ var }}</div>
          <input name="{{ var }}" type="number" step="0.01" min="0" max="1" class="counter" value="{{ '%.2f' % values[var] }}">
          <button type="button" class="ghost btn-inc" data-var="{{ var }}" data-delta="0.05">+0.05</button>
          <button type="button" class="ghost btn-inc" data-var="{{ var }}" data-delta="-0.05">-0.05</button>
        </div>
        {% endfor %}
      </div>
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Display & Colors</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content"> <div class="section-title">Display & Colors</div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_rl" checked> Right Lane</label><input type="color" id="color_rl" value="{{ ui.colors.RL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_ll" checked> Left Lane</label><input type="color" id="color_ll" value="{{ ui.colors.LL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_cw" checked> Crosswalk</label><input type="color" id="color_cw" value="{{ ui.colors.CW }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_st" checked> Sign/Tag</label><input type="color" id="color_st" value="{{ ui.colors.ST }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_obj" checked> Object</label><input type="color" id="color_obj" value="{{ ui.colors.OBJ }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_bev" checked> BEV Area</label><input type="color" id="color_bev" value="{{ ui.colors.BEV }}"></div>
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Vision Advanced Limits</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Vision Advanced Limits</div>
      <div class="inputs" style="max-height:200px; overflow-y:auto; font-size:12px;">
        <div class="form-row"><label class="label">LANE_THRESHOLD</label><input id="lane_threshold" type="number" min="0" max="255" step="1" class="counter"></div>
        <div class="form-row"><label class="label">CW_THRESHOLD</label><input id="cross_thresh" type="number" min="0" max="255" step="1" class="counter"></div>
        <div class="form-row"><label class="label">CW_SLEEP (s)</label><input id="crosswalk_sleep" type="number" min="0" step="0.1" class="counter"></div>
        <div class="form-row"><label class="label">CW_THRESH_SPEND</label><input id="crosswalk_thresh_spend" type="number" min="0" step="0.1" class="counter"></div>
        <div class="form-row"><label class="label">READ_SIGN_THRESH</label><input id="read_sign_threshold" type="number" min="0" step="1" class="counter"></div>
        <div class="form-row"><label class="label">TURN_RIGHT Lvl</label><input id="turn_right" type="number" min="0" step="1" class="counter"></div>
        <div class="form-row"><label class="label">TURN_LEFT Lvl</label><input id="turn_left" type="number" min="0" step="1" class="counter"></div>
        <div class="form-row"><label class="label">STRAIGHT Lvl</label><input id="straight" type="number" min="0" step="1" class="counter"></div>
        <div class="form-row"><label class="label">STOP Lvl</label><input id="stop_lvl" type="number" min="0" step="1" class="counter"></div>
        
        <div class="form-row"><label class="label">RUN_LVL</label>
          <select id="run_lvl" class="counter"><option value="MOVE">MOVE</option><option value="STOP">STOP</option></select>
        </div>
        <div class="form-row"><label class="label">Use Signs Vision</label><input type="checkbox" id="with_sign"></div>
        <div class="form-row"><label class="label">Use AprilTag</label><input type="checkbox" id="with_apriltag"></div>
      </div>
      <div style="display:flex;gap:8px;margin-top:12px"><button id="confirm_advanced" class="btn">Confirm Advanced Limits</button></div>
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Stream Controls</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Stream Controls</div>
      <div class="form-row">
        <button id="take_picture_btn" class="btn">Take Picture</button>
        <button id="toggle_record_btn" class="btn">Start Recording</button>
        <div id="record_status" class="small-muted status-line" style="margin-left: 10px;">Recording: No</div>
      </div>
      <div class="form-row">
        <button id="freeze_btn" class="ghost">Freeze Frame</button>
        <button id="unfreeze_btn" class="ghost">Unfreeze Frame</button>
      </div>
      <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
      <div class="form-row">
        <button id="stop_all_btn" class="btn" style="background:#ef4444; color:white; width:100%;">Stop All Sync & Requests</button>
      </div>
    </div></details>


    <details class="dock-panel" open id="ext_layers_panel"><summary class="dock-summary"><span>Layers & Opacity</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Layer Manager</div><div class="small-muted">Visibility and color affect the live ROI overlay; opacity is saved with this mode's UI settings.</div>
      <div id="ext_layer_rows"></div>
    </div></details>

    <details class="dock-panel" open id="ext_editor_panel"><summary class="dock-summary"><span>Precision Editor & Annotations</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Precision Tools</div>
      <div class="toggle-row"><label><input type="checkbox" id="ext_grid"> Grid</label><label><input type="checkbox" id="ext_snap"> Snap to 5%</label><label><input type="checkbox" id="ext_crosshair"> Crosshair</label></div>
      <div class="toggle-row"><label><input type="checkbox" id="ext_overlays" checked> ROI overlays</label><label><input type="checkbox" id="ext_ruler"> Ruler tool</label></div>
      <div class="form-row"><button type="button" class="ghost" id="ext_annotate_btn">Place Note / Marker</button><button type="button" class="ghost" id="ext_export_annotations">Export Annotations</button><button type="button" class="ghost" id="ext_clear_annotations">Clear Annotations</button></div>
      <div class="small-muted">Custom ROI preview only: these user-defined shapes do not affect the driving pipeline. Operational controls remain the fixed RL/LL/CW/ST/OBJ regions.</div>
      <div class="form-row"><button type="button" class="ghost" id="ext_roi_rect_tool">Draw Rectangle ROI</button><button type="button" class="ghost" id="ext_roi_trapezoid_tool">Draw Trapezoid ROI</button></div>
      <div class="form-row"><label for="ext_roi_top_factor" class="small-muted">Trapezoid top width</label><input type="range" id="ext_roi_top_factor" min="0.1" max="1" step="0.05" value="0.5" style="min-width:70px;flex:1"><span id="ext_roi_top_factor_label" class="small-muted">50%</span></div>
      <div class="form-row"><button type="button" class="ghost" id="ext_save_workspace">Save Workspace</button><button type="button" class="ghost" id="ext_capture_frame">Add Frame Snapshot</button></div>
      <div class="small-muted" id="ext_editor_status">Select a tool, then click the camera frame to place a marker or measure a distance.</div>
      <div id="ext_annotations_list" class="ext-list"></div>
      <div class="section-title" style="margin-top:10px">Workspace Profiles</div>
      <div class="form-row"><input type="text" id="ext_profile_name" placeholder="Profile name" maxlength="48" style="min-width:0;width:100%"></div>
      <div class="form-row"><select id="ext_profile_select" style="width:100%"><option value="">No saved profiles</option></select></div>
      <div class="form-row"><button type="button" class="ghost" id="ext_profile_save">Save Profile</button><button type="button" class="ghost" id="ext_profile_load">Load</button><button type="button" class="ghost" id="ext_profile_delete">Delete</button></div>
    </div></details>

    <details class="dock-panel" open id="ext_config_panel"><summary class="dock-summary"><span>Config, Presets & History</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Full Configuration</div>
      <div class="form-row"><button type="button" class="ghost" id="ext_export_config">Export Full JSON</button><button type="button" class="ghost" id="ext_import_config">Import JSON</button><input type="file" id="ext_config_file" accept=".json,application/json" hidden></div>
      <div class="form-row"><button type="button" class="ghost" id="ext_undo">↶ Undo</button><button type="button" class="ghost" id="ext_redo">↷ Redo</button><span class="small-muted" id="ext_undo_status">Undo: 0 · Redo: 0</span></div>
      <div class="section-title" style="margin-top:10px">Configuration Presets</div>
      <div class="form-row"><input type="text" id="ext_preset_name" placeholder="Preset name" maxlength="48" style="min-width:0;width:100%"></div>
      <div class="form-row"><select id="ext_preset_select" style="width:100%"><option value="">No saved presets</option></select></div>
      <div class="form-row"><button type="button" class="ghost" id="ext_preset_save">Save Preset</button><button type="button" class="ghost" id="ext_preset_apply">Apply</button><button type="button" class="ghost" id="ext_preset_delete">Delete</button></div>
      <div class="section-title" style="margin-top:10px">Compare Current vs Preset</div>
      <pre id="ext_config_diff" class="ext-pre">Choose a preset and select Compare.</pre>
      <div class="form-row"><button type="button" class="ghost" id="ext_compare_preset">Compare</button><button type="button" class="ghost" id="ext_history_refresh">Refresh History</button></div>
      <div class="section-title" style="margin-top:10px">Persistent History</div>
      <div class="form-row"><select id="ext_history_select" style="width:100%"><option value="">No history entries</option></select></div>
      <div class="form-row"><button type="button" class="ghost" id="ext_history_restore">Restore Selected Snapshot</button></div>
      <div class="small-muted">History and presets are mode-specific files on the robot. Import is validated against the active mode and supported controls.</div>
    </div></details>

    <details class="dock-panel" open id="ext_runtime_panel"><summary class="dock-summary"><span>Runtime & Performance</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Runtime Health</div><div id="ext_health_summary" class="small status-line">Waiting for runtime telemetry…</div>
      <div class="ext-charts"><div><div class="small-muted">Processing FPS</div><canvas id="ext_fps_chart" width="300" height="58"></canvas></div><div><div class="small-muted">Loop latency · ms</div><canvas id="ext_latency_chart" width="300" height="58"></canvas></div><div><div class="small-muted">Perception latency · ms</div><canvas id="ext_perception_chart" width="300" height="58"></canvas></div></div>
      <pre class="ext-pre" id="ext_runtime_details">Runtime detail is loading…</pre>
      <div class="section-title" style="margin-top:10px">Sign Detector Worker</div><pre class="ext-pre" id="ext_sign_status">Waiting…</pre>
      <div class="section-title" style="margin-top:10px">Confidence / Speed Decision</div><pre class="ext-pre" id="ext_confidence_status">Inactive or unavailable</pre>
      <div class="section-title" style="margin-top:10px">Adaptive Obstacle Avoidance</div><pre class="ext-pre" id="ext_obstacle_status">Inactive or unavailable</pre>
      <div class="section-title" style="margin-top:10px">Traffic Light · City</div><pre class="ext-pre" id="ext_traffic_status">Not active in this mode / unavailable</pre>
      <div class="section-title" style="margin-top:10px">Race Lifecycle</div><pre class="ext-pre" id="ext_race_status">Not active in this mode / unavailable</pre>
      <div class="section-title" style="margin-top:10px">Encoder Odometry</div><div id="ext_encoder_status" class="small-muted">Encoder map is opt-in.</div><div id="ext_encoder_embed" hidden><iframe title="Encoder odometry map" id="ext_encoder_frame" loading="lazy" style="width:100%;height:240px;border:1px solid var(--border);border-radius:6px;background:#080d14"></iframe><button type="button" class="ghost" id="ext_encoder_reset">Reset displayed origin</button></div>
    </div></details>

    <details class="dock-panel" id="ext_camera_panel"><summary class="dock-summary"><span>Camera & Processing Rate</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Processing Rate Limit</div><div class="small-muted">Changes and saves the desired vision-processing cycle rate. This is not the physical camera sensor FPS.</div>
      <div class="form-row"><label class="label" for="ext_target_fps">Target processing FPS</label><input type="number" id="ext_target_fps" min="1" max="60" step="1" value="30" class="counter"></div><div class="form-row"><button type="button" class="btn" id="ext_apply_fps">Apply FPS Limit</button><span class="small-muted" id="ext_fps_status">Loading…</span></div>
      <div class="section-title" style="margin-top:12px">Camera Runtime Controls</div><div class="small-muted" id="ext_camera_support">Checking camera capabilities…</div>
      <div class="form-row"><label class="label" for="ext_exposure">Exposure (µs)</label><input type="number" id="ext_exposure" min="1" step="100" value="10000" class="counter"></div>
      <div class="form-row"><label class="label" for="ext_gain">Analogue gain</label><input type="number" id="ext_gain" min="0.1" step="0.1" value="6" class="counter"></div>
      <div class="toggle-row"><label><input type="checkbox" id="ext_auto_exposure"> Auto exposure</label><label><input type="checkbox" id="ext_auto_wb"> Auto white balance</label></div>
      <div class="form-row"><button type="button" class="btn" id="ext_apply_camera">Apply Camera Controls</button></div>
      <div class="small-muted">Camera controls are runtime-only and are only editable when Picamera2 exposes the requested hardware controls.</div>
    </div></details>

    <details class="dock-panel" id="ext_live_features_panel"><summary class="dock-summary"><span>Live Feature Status</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="section-title">Live Feature Controls</div><div id="ext_live_feature_rows" class="ext-list">Loading supported controls…</div>
      <div class="section-title" style="margin-top:10px">Startup-Only / Firmware-Gated Features</div><pre id="ext_feature_status" class="ext-pre">Loading capabilities…</pre>
      <div class="small-muted">Live controls use the active mode's existing code paths. Traffic lights, confidence limiting, adaptive obstacle planning and encoder telemetry remain startup/firmware gated rather than being enabled unsafely from the browser.</div>
    </div></details>

    <details class="dock-panel" id="ext_server_logs_panel"><summary class="dock-summary"><span>Python Server Logs</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="form-row"><select id="ext_log_level"><option>ALL</option><option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option><option>CRITICAL</option></select><input type="search" id="ext_log_search" placeholder="Filter logs…" style="width:100%;min-width:0"></div>
      <div class="form-row"><button type="button" class="ghost" id="ext_log_refresh">Refresh Logs</button><button type="button" class="ghost" id="ext_log_export">Export Visible Logs</button></div>
      <pre id="ext_server_logs" class="ext-pre ext-log-pre">In-memory log buffer is loading…</pre>
      <div class="small-muted">Only recent allowlisted runtime logger messages are shown; the API does not expose arbitrary log files.</div>
    </div></details>

    <details class="dock-panel" id="ext_frame_gallery_panel"><summary class="dock-summary"><span>Frame History & Comparison</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div class="small-muted">Session-only snapshots from the current dashboard frame. They are not a replacement for recorded video.</div><div id="ext_frame_gallery" class="ext-gallery"></div><button type="button" class="ghost" id="ext_clear_gallery">Clear Frame History</button>
    </div></details>

    <details class="dock-panel" id="ext_safety_panel" open><summary class="dock-summary"><span>Safety & Runtime Control</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div id="ext_safety_state" class="status-line">Reading software stop state…</div>
      <div class="form-row"><button type="button" class="btn ext-stop-btn" id="ext_software_stop">Request Software Stop</button><button type="button" class="ghost" id="ext_software_resume">Resume Motion</button></div>
      <div class="small-muted">Software stop is consumed by the active Python mode loop. This is not a hardware emergency stop and does not replace a physical cutoff. Resume requires explicit confirmation.</div>
    </div></details>

  </div>
</div>

<div id="toast" class="toast" style="display:none"></div>

<script>
/* ---------- Globals ---------- */
const canvas = document.getElementById('video_canvas');
const ctx = canvas.getContext('2d');
const select = document.getElementById('variable_select');
const inputsContainer = document.getElementById('inputs_container');
const showRectsCheckbox = document.getElementById('show_rects');
const frameModeDisplay = document.getElementById('frame_mode');

let values = {{ values|tojson }};
let ui = {{ ui|tojson }};
let advanced = {{ advanced|tojson }};
const STREAM_CONTROL_ALLOWED = {{ stream_control|default(false)|tojson }};

const controlNotice = document.getElementById('control_notice');
if (controlNotice) {
    controlNotice.textContent = STREAM_CONTROL_ALLOWED
        ? 'Dashboard control is enabled.'
        : 'Dashboard is read-only. Enable STREAM_ALLOW_CONTROL or restart without --stream-read-only to allow runtime changes.';
}

let selectedVar = 'NONE';
let markerHighlight = null;
let fetchFrameTimer = null;
let valUpdateTimer = null;
let healthUpdateTimer = null;
let arduinoUpdateTimer = null;
let dragState = null;
let debounceTimers = {};
let isFrozen = false;
let isRecording = false;
let syncActive = true;

// Poll API endpoints through a shared circuit breaker. When the Python process
// disappears, stop flooding it with requests and probe again with backoff.
let dashboardApiOnline = true;
let dashboardApiFailureCount = 0;
let dashboardApiRetryAt = 0;
let dashboardApiProbeInFlight = false;

function updateDashboardConnectionState(online) {
    const state = document.getElementById('health_state');
    const faults = document.getElementById('health_faults');
    if(!online) {
        if(state) state.textContent = 'State: SERVER UNREACHABLE — retrying';
        if(faults) faults.textContent = 'Faults: waiting for the Python server to respond';
    }
}

function noteDashboardApiFailure(err) {
    const wasOnline = dashboardApiOnline;
    if(wasOnline){noteWorkspaceEvent('error','Robot dashboard connection lost: '+(err&&err.message?err.message:err));recordApiEvent('error','Dashboard request failed: '+(err&&err.message?err.message:err));}
    dashboardApiOnline = false;
    dashboardApiFailureCount += 1;
    const delayMs = Math.min(
        30000,
        1000 * Math.pow(2, Math.min(dashboardApiFailureCount - 1, 5))
    );
    dashboardApiRetryAt = Date.now() + delayMs;
    updateDashboardConnectionState(false);
    if(wasOnline) {
        console.warn('Robot server is unreachable; polling paused with retry backoff:', err && err.message ? err.message : err);
    }
}

function noteDashboardApiSuccess() {
    const wasOffline = !dashboardApiOnline;
    if(wasOffline){noteWorkspaceEvent('info','Robot dashboard connection restored');recordApiEvent('info','Dashboard requests responding again');}
    dashboardApiOnline = true;
    dashboardApiFailureCount = 0;
    dashboardApiRetryAt = 0;
    if(wasOffline) {
        const state = document.getElementById('health_state');
        if(state) state.textContent = 'State: Connected; refreshing runtime status...';
        const faults = document.getElementById('health_faults');
        if(faults) faults.textContent = 'Faults: refreshing...';
        showToast('Connection to robot server restored');
    }
}

async function fetchDashboardJson(url, options = {}) {
    if(Date.now() < dashboardApiRetryAt) return null;

    const isRecoveryProbe = !dashboardApiOnline;
    if(isRecoveryProbe && dashboardApiProbeInFlight) return null;
    if(isRecoveryProbe) dashboardApiProbeInFlight = true;

    try {
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if(!response.ok) {
            throw new Error(data.message || ('HTTP ' + response.status));
        }
        noteDashboardApiSuccess();
        return data;
    } catch(err) {
        noteDashboardApiFailure(err);
        return null;
    } finally {
        if(isRecoveryProbe) dashboardApiProbeInFlight = false;
    }
}

// Workspace Zoom Variable
let workspaceZoom=1,viewPanX=0,viewPanY=0,viewPanState=null,lastFrameImage=null,workspaceTool='select';
const WORKSPACE_EVENT_LIMIT=250;let workspaceEvents=[],workspaceApiEvents=[];
let lastLoggedHealthState=null,lastLoggedFaultSignature=null,lastLoggedArduinoState=null,lastLoggedModeSignature=null;
function noteWorkspaceEvent(level,message,channel='events'){const entry={time:new Date(),level:String(level||'info').toLowerCase(),message:String(message||'')};const store=channel==='api'?workspaceApiEvents:workspaceEvents;store.push(entry);if(store.length>WORKSPACE_EVENT_LIMIT)store.splice(0,store.length-WORKSPACE_EVENT_LIMIT);renderWorkspaceEventLog(channel);}
let workspaceConsolePaused=false,workspaceConsoleAutoScroll=true,workspaceConsoleQuery='',workspaceConsoleLevel='ALL';
function renderWorkspaceEventLog(channel='events'){
  if(workspaceConsolePaused)return;
  const store=channel==='api'?workspaceApiEvents:workspaceEvents;
  const root=document.getElementById(channel==='api'?'console_api':'console_events');if(!root)return;
  root.replaceChildren();
  const query=workspaceConsoleQuery.trim().toLowerCase();
  const selected=store.slice().reverse().filter(function(entry){
    const level=String(entry.level||'info').toUpperCase();
    return (workspaceConsoleLevel==='ALL'||level===workspaceConsoleLevel)&&(!query||(String(entry.message||'')+' '+level).toLowerCase().includes(query));
  });
  if(!selected.length){const e=document.createElement('div');e.className='console-empty';e.textContent=store.length?'No matching console entries.':channel==='api'?'No request diagnostics yet.':'No events yet.';root.appendChild(e);}
  else for(const entry of selected){
    const row=document.createElement('div');row.className='console-entry';
    const stamp=document.createElement('span');stamp.className='console-time';
    const time=entry.time instanceof Date?entry.time:new Date(entry.time||Date.now());
    stamp.textContent=time.toLocaleTimeString([],{hour12:false})+'.'+String(time.getMilliseconds()).padStart(3,'0');
    const levelName=String(entry.level||'info').toUpperCase();
    const level=document.createElement('span');level.className='console-level '+(levelName==='ERROR'?'error':levelName==='WARN'?'warn':'');level.textContent=levelName;
    const msg=document.createElement('span');msg.className='console-message';msg.textContent=entry.message;
    row.append(stamp,level,msg);root.appendChild(row);
  }
  if(workspaceConsoleAutoScroll)root.scrollTop=0;
  const c=document.getElementById('console_count');if(c)c.textContent=workspaceEvents.length+' events · '+workspaceApiEvents.length+' requests';
}
function recordApiEvent(level,message){noteWorkspaceEvent(level,message,'api');}
function setWorkspaceZoom(next,ax=canvas.width/2,ay=canvas.height/2,log=true){const z=Math.max(.3,Math.min(4,Number(next)||1));if(Math.abs(z-workspaceZoom)<.0001)return;const b=getImgBounds(),u=(ax-b.ix)/b.iw,v=(ay-b.iy)/b.ih;workspaceZoom=z;const nw=canvas.width*z,nh=canvas.height*z;viewPanX=ax-u*nw-(canvas.width-nw)/2;viewPanY=ay-v*nh-(canvas.height-nh)/2;document.getElementById('workspace_zoom').value=String(z);renderWorkspaceCanvas();updateZoomStatus();if(log)noteWorkspaceEvent('info','View zoom: '+Math.round(z*100)+'%');}
function fitWorkspaceView(log=true){workspaceZoom=1;viewPanX=0;viewPanY=0;document.getElementById('workspace_zoom').value='1';renderWorkspaceCanvas();updateZoomStatus();if(log)noteWorkspaceEvent('info','View reset to fit camera frame');}
function updateZoomStatus(){const el=document.getElementById('menu_live_status');if(el)el.textContent=(isFrozen?'FROZEN':'LIVE')+' · '+String('{{ mode|capitalize }}').toUpperCase()+' · '+Math.round(workspaceZoom*100)+'%';}
document.getElementById('workspace_zoom').addEventListener('input',e=>setWorkspaceZoom(parseFloat(e.target.value),canvas.width/2,canvas.height/2));

/* Camera frame fullscreen: scale the canvas bitmap to the viewport while
   preserving the source frame aspect ratio and native coordinate system. */
function isCameraStageFullscreen(){
  const stage=document.getElementById('canvas_stage');
  return !!stage && (document.fullscreenElement===stage || document.webkitFullscreenElement===stage);
}
function syncCameraCanvasSize(){
  const stage=document.getElementById('canvas_stage');
  const button=document.getElementById('camera_fullscreen_btn');
  if(!stage || !canvas)return;
  const active=isCameraStageFullscreen();
  if(button){
    button.textContent=active?'⤢ Exit Fullscreen':'⛶ Fullscreen';
    button.setAttribute('aria-pressed',String(active));
    button.setAttribute('aria-label',active?'Exit camera fullscreen':'Expand camera frame to fullscreen');
    button.title=active?'Exit camera fullscreen (Esc)':'Expand camera frame to fullscreen';
  }
  /* Fit in the available stage in normal and fullscreen modes.
     max-width/max-height alone only shrink oversized frames; they never
     enlarge a low-resolution frame to use the available preview space. */
  const bounds=stage.getBoundingClientRect();
  const style=window.getComputedStyle(stage);
  const paddingX=(parseFloat(style.paddingLeft)||0)+(parseFloat(style.paddingRight)||0);
  const paddingY=(parseFloat(style.paddingTop)||0)+(parseFloat(style.paddingBottom)||0);
  const availableWidth=Math.max(1,stage.clientWidth-paddingX);
  const availableHeight=Math.max(1,stage.clientHeight-paddingY);
  const frameWidth=Math.max(1,canvas.width),frameHeight=Math.max(1,canvas.height);
  const scale=Math.min(availableWidth/frameWidth,availableHeight/frameHeight);
  if(!Number.isFinite(scale)||scale<=0||!bounds.width||!bounds.height)return;
  canvas.style.width=Math.max(1,Math.floor(frameWidth*scale))+'px';
  canvas.style.height=Math.max(1,Math.floor(frameHeight*scale))+'px';
}
async function toggleCameraFullscreen(){
  const stage=document.getElementById('canvas_stage');
  if(!stage)return;
  try{
    if(isCameraStageFullscreen()){
      if(document.exitFullscreen)await document.exitFullscreen();
      else if(document.webkitExitFullscreen)document.webkitExitFullscreen();
      return;
    }
    if(stage.requestFullscreen)await stage.requestFullscreen();
    else if(stage.webkitRequestFullscreen)stage.webkitRequestFullscreen();
    else {showToast('Fullscreen is not supported by this browser.');return;}
  }catch(error){
    showToast('Could not change camera fullscreen: '+(error&&error.message?error.message:'request denied'));
  }
}
function handleCameraFullscreenChange(){
  window.requestAnimationFrame(function(){
    syncCameraCanvasSize();
    renderWorkspaceCanvas();
  });
}
document.addEventListener('fullscreenchange',handleCameraFullscreenChange);
document.addEventListener('webkitfullscreenchange',handleCameraFullscreenChange);
window.addEventListener('resize',function(){
  syncCameraCanvasSize();
});
/* Refit if the settings dock or event console changes the stage dimensions. */
const cameraStage=document.getElementById('canvas_stage');
if(cameraStage&&typeof ResizeObserver!=='undefined'){
  const cameraStageObserver=new ResizeObserver(function(){
    window.requestAnimationFrame(syncCameraCanvasSize);
  });
  cameraStageObserver.observe(cameraStage);
}

/* ---------- Utilities & Math ---------- */
function clamp01(v){ return Math.max(0, Math.min(1, v)); }
function round01(v){ return Math.round(v*1000)/1000; } 
function showToast(text, timeout=2500){
    const t = document.getElementById('toast');
    t.textContent = text;
    t.style.display = 'block';
    if(typeof noteWorkspaceEvent==='function')noteWorkspaceEvent('info',text);
    setTimeout(()=> t.style.display='none', timeout);
}
function varColorByKey(key){
  let hex = key==='RL' ? ui.colors.RL : key==='LL' ? ui.colors.LL : key==='CW' ? ui.colors.CW :
    key==='ST' ? (ui.colors.ST || '#bf7bff') : key==='OBJ' ? (ui.colors.OBJ || '#ff5757') :
    key==='BEV' ? (ui.colors.BEV || '#d946ef') : '#9ad0ff';
  const opacity = Number((ui.opacity || {})[key] == null ? 1 : (ui.opacity || {})[key]);
  if(!hex || opacity >= 0.999) return hex || '#9ad0ff';
  const parts = String(hex).match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  if(!parts) return hex;
  return 'rgba(' + parseInt(parts[1],16) + ',' + parseInt(parts[2],16) + ',' + parseInt(parts[3],16) + ',' + Math.max(0,Math.min(1,opacity)) + ')';
}
function updateFrameModeText(){
    frameModeDisplay.textContent = !syncActive ? 'Mode: STOPPED' : (isFrozen ? 'Mode: Frozen (for precise tuning)' : 'Mode: Live');
}
function sendAdvanced(payload) {
    if(!syncActive) return showToast('Requests are stopped!');
    recordApiEvent('info','Saving advanced properties: '+Object.keys(payload).join(', '));
    fetch('/set_advanced',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
        .then(async r => {
            const data = await r.json().catch(() => ({}));
            if(!r.ok) throw new Error(data.message || 'HTTP ' + r.status);
            return data;
        })
        .then(j=>{
            if(j && j.success){
                advanced = j.advanced;
                updateShapeUIFromData();
                showToast('Advanced settings saved');
            } else {
                showToast((j && j.message) || 'Could not save advanced settings');
            }
        })
        .catch(err => {
            recordApiEvent('error', 'Failed to save advanced settings: ' + err.message);
            console.error('Failed to save advanced settings:', err);
            showToast('Advanced settings failed: ' + err.message);
        });
}

// Convert image norm coords (0-1) to physical canvas coords, honoring workspace zoom
function getImgBounds(){const w=canvas.width,h=canvas.height,iw=w*workspaceZoom,ih=h*workspaceZoom;return{ix:(w-iw)/2+viewPanX,iy:(h-ih)/2+viewPanY,iw,ih};}
function canvasPointFromEvent(e){const r=canvas.getBoundingClientRect();if(!r.width||!r.height)return{x:0,y:0};return{x:(e.clientX-r.left)*canvas.width/r.width,y:(e.clientY-r.top)*canvas.height/r.height};}
function renderWorkspaceCanvas(){ctx.clearRect(0,0,canvas.width,canvas.height);if(lastFrameImage){const b=getImgBounds();ctx.drawImage(lastFrameImage,b.ix,b.iy,b.iw,b.ih);}drawOverlays();if(typeof drawPrecisionOverlay==='function')drawPrecisionOverlay();}

function toCanvas(nx, ny) {
    const b = getImgBounds();
    return { x: b.ix + nx * b.iw, y: b.iy + ny * b.ih };
}

/* ---------- Canvas frame loop ---------- */
function rectFromVars(topVar, bottomVar, leftVar, rightVar){
    const t = parseFloat(values[topVar]); const b = parseFloat(values[bottomVar]);
    const l = parseFloat(values[leftVar]); const r = parseFloat(values[rightVar]);
    if (isNaN(t)||isNaN(b)||isNaN(l)||isNaN(r)) return null;
    
    // Calculate physical canvas points using zoom
    const tl = toCanvas(l, t);
    const br = toCanvas(r, b);
    
    return {
        x: tl.x, y: tl.y, 
        w: Math.max(2, br.x - tl.x), h: Math.max(2, br.y - tl.y), 
        t, b, l, r
    };
}

function computeRects(){
    return {
        RL: rectFromVars('RL_TOP_ROI','RL_BOTTOM_ROI','RL_LEFT_ROI','RL_RIGHT_ROI'),
        LL: rectFromVars('LL_TOP_ROI','LL_BOTTOM_ROI','LL_LEFT_ROI','LL_RIGHT_ROI'),
        CW: rectFromVars('CW_TOP_ROI','CW_BOTTOM_ROI','CW_LEFT_ROI','CW_RIGHT_ROI'),
        ST: rectFromVars('ST_TOP_ROI','ST_BOTTOM_ROI','ST_LEFT_ROI','ST_RIGHT_ROI'),
        OBJ: rectFromVars('OBJ_TOP_ROI','OBJ_BOTTOM_ROI','OBJ_LEFT_ROI','OBJ_RIGHT_ROI')
    };
}

function startFrameLoop(){
    if(fetchFrameTimer) clearInterval(fetchFrameTimer);
    fetchFrameTimer = setInterval(fetchFrameOnce, 120);
    fetchFrameOnce();
}

let frameRequestInFlight = false;
let hasRenderedFrame = false;
let frameRequestFailures = 0;
let frameRetryAt = 0;

function showCameraConnectionState(message){
    if(hasRenderedFrame) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.fillStyle = '#94a3b8';
    ctx.font = '16px Segoe UI, Arial, sans-serif';
    ctx.textBaseline = 'top';
    ctx.fillText(message, 16, 16);
    ctx.restore();
    drawOverlays();
}

function fetchFrameOnce(){
    if(!syncActive || frameRequestInFlight || !dashboardApiOnline) return;
    if(Date.now() < frameRetryAt) return;

    frameRequestInFlight = true;
    const img = new Image();
    img.decoding = 'async';

    img.onload = () => {
        try {
            if(!syncActive) return;

            // Match the canvas backing dimensions to the source frame so
            // non-3:2 cameras (for example 4:3) are never stretched.
            const frameWidth = img.naturalWidth || img.width;
            const frameHeight = img.naturalHeight || img.height;
            if(frameWidth <= 0 || frameHeight <= 0) return;

            if(canvas.width !== frameWidth) canvas.width = frameWidth;
            if(canvas.height !== frameHeight) canvas.height = frameHeight;

            const rect = canvas.getBoundingClientRect();
            if(rect.width <= 0 || rect.height <= 0) return;

            lastFrameImage=img;
            renderWorkspaceCanvas();
            syncCameraCanvasSize();

            hasRenderedFrame = true;
            frameRequestFailures = 0;
            frameRetryAt = 0;
        } catch(err) {
            console.error('Failed to render camera frame:', err);
            showCameraConnectionState('Camera frame received, but display failed.');
        } finally {
            frameRequestInFlight = false;
        }
    };

    img.onerror = () => {
        frameRequestFailures += 1;
        frameRetryAt = Date.now() + Math.min(
            5000,
            250 * Math.pow(2, Math.min(frameRequestFailures - 1, 5))
        );

        try {
            // Keep the last good image. A transient 204/no-frame response must not
            // blank a working preview; keep retrying until a valid frame arrives.
            if(!hasRenderedFrame) {
                showCameraConnectionState(
                    frameRequestFailures > 3
                        ? 'Waiting for camera frames...'
                        : 'Connecting to camera...'
                );
            }
        } catch(err) {
            console.error('Failed to update camera connection state:', err);
        } finally {
            frameRequestInFlight = false;
        }
    };

    // Register callbacks before setting src so fast local responses cannot
    // complete before the browser has installed the handlers.
    img.src = '/video_feed_frame?t=' + Date.now();
}

/* ---------- Overlays (Shapes & Rects) ---------- */
function drawHandle(cx, cy, size, fill, stroke){
    ctx.beginPath();
    ctx.fillStyle = fill;
    ctx.strokeStyle = stroke || '#000';
    ctx.lineWidth = 1;
    ctx.rect(cx - size/2, cy - size/2, size, size);
    ctx.fill(); ctx.stroke();
}

function drawPolygon(points, color, isHighlight, labelText, r, fillAlpha=0.35) {
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for(let i=1; i<points.length; i++) ctx.lineTo(points[i].x, points[i].y);
    ctx.closePath();
    
    ctx.fillStyle = color;
    ctx.globalAlpha = fillAlpha;
    ctx.fill();
    
    ctx.globalAlpha = 1;
    ctx.strokeStyle = isHighlight ? '#ffffff' : color;
    ctx.lineWidth = isHighlight ? 3 : 2;
    ctx.stroke();

    if (r && labelText) {
        ctx.fillStyle = color;
        ctx.fillRect(r.x + 6, r.y + 6, 120, 18);
        ctx.fillStyle = '#012';
        ctx.font = 'bold 12px Arial';
        ctx.fillText(labelText, r.x + 10, r.y + 19);
    }
}

function drawOverlays(){
    const showRects = showRectsCheckbox.checked;
    const rects = computeRects();
    ctx.save();
    
    if(showRects){
        const laneMode = advanced.LANE_ROI_MODE || 'rectangle';
        const cwMode = advanced.CW_TRAPEZOID_MODE !== false; 
        const stMode = advanced.ST_TRAPEZOID_MODE !== false; 
        const objMode = advanced.OBJ_TRAPEZOID_MODE !== false;
        
        // 1. Draw BEV
        if(ui.visible['BEV'] && advanced.USE_BEV !== false) {
            const bevColor = varColorByKey('BEV');
            const isBevHL = (markerHighlight === 'BEV');
            const pts = [
                toCanvas(advanced.BEV_SRC_TL_X, advanced.BEV_SRC_TL_Y),
                toCanvas(advanced.BEV_SRC_TR_X, advanced.BEV_SRC_TR_Y),
                toCanvas(advanced.BEV_SRC_BR_X, advanced.BEV_SRC_BR_Y),
                toCanvas(advanced.BEV_SRC_BL_X, advanced.BEV_SRC_BL_Y)
            ];
            
            drawPolygon(pts, bevColor, isBevHL, null, null, 0.15); 
            
            ctx.fillStyle = bevColor;
            ctx.fillRect(pts[0].x, pts[0].y - 20, 90, 18);
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 12px Arial';
            ctx.fillText("BEV Region", pts[0].x + 5, pts[0].y - 7);

            const size = 12;
            for(let p of pts) drawHandle(p.x, p.y, size, '#fff', bevColor);
        }

        // 2. Draw ROIs
        for(const key of ['RL','LL','CW','ST','OBJ']){
            if(!ui.visible[key]) continue;
            const r = rects[key];
            if(!r) continue;
            
            const color = varColorByKey(key);
            const isHL = (markerHighlight === key);
            
            if(key === 'RL') {
                if(laneMode === 'trapezoid'){
                    let factor = advanced.RL_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x, y:r.y}, {x:r.x+(r.w*factor), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "RL (Trapezoid)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "RL (Rectangle)", r);
                }
            } 
            else if(key === 'LL') {
                if(laneMode === 'trapezoid'){
                    let factor = advanced.LL_TOP_WIDTH_FACTOR;
                    let pts = [{x:(r.x+r.w)-(r.w*factor), y:r.y}, {x:r.x+r.w, y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "LL (Trapezoid)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "LL (Rectangle)", r);
                }
            }
            else if(key === 'CW') {
                if(cwMode){
                    let factor = advanced.CW_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x+(r.w*(1-factor)/2), y:r.y}, {x:r.x+(r.w*(1+factor)/2), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "CW (Isosceles)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "CW (Rectangle)", r);
                }
            }
            else if(key === 'ST') {
                if(stMode){
                    let factor = advanced.ST_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x+(r.w*(1-factor)/2), y:r.y}, {x:r.x+(r.w*(1+factor)/2), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "ST (Isosceles)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "ST (Rectangle)", r);
                }
            }
            else if(key === 'OBJ') {
                if(objMode){
                    let factor = advanced.OBJ_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x+(r.w*(1-factor)/2), y:r.y}, {x:r.x+(r.w*(1+factor)/2), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "OBJ (Isosceles)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "OBJ (Rectangle)", r);
                }
            }
            
            ctx.globalAlpha = 1.0;
            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.strokeRect(r.x, r.y, r.w, r.h);
            ctx.setLineDash([]);
            
            const size = 10;
            drawHandle(r.x, r.y, size, '#fff', color);
            drawHandle(r.x + r.w, r.y, size, '#fff', color);
            drawHandle(r.x, r.y + r.h, size, '#fff', color);
            drawHandle(r.x + r.w, r.y + r.h, size, '#fff', color);
        }
    }
    ctx.restore();
}

/* ---------- Hit testing & Drag Bounding Box ---------- */
function hitTest(px, py){
    const size = 12;
    
    if(ui.visible['BEV'] && advanced.USE_BEV !== false) {
        const bevCorners = {
            TL: toCanvas(advanced.BEV_SRC_TL_X, advanced.BEV_SRC_TL_Y),
            TR: toCanvas(advanced.BEV_SRC_TR_X, advanced.BEV_SRC_TR_Y),
            BR: toCanvas(advanced.BEV_SRC_BR_X, advanced.BEV_SRC_BR_Y),
            BL: toCanvas(advanced.BEV_SRC_BL_X, advanced.BEV_SRC_BL_Y)
        };
        for(const c of Object.keys(bevCorners)){
            const {x:cx, y:cy} = bevCorners[c];
            if(px >= cx-size && px <= cx+size && py >= cy-size && py <= cy+size){
                return {type:'handle', group:'BEV', corner:c};
            }
        }
    }

    const rects = computeRects();
    for(const key of ['RL','LL','CW','ST','OBJ']){
        if(!ui.visible[key]) continue;
        const r = rects[key];
        if(!r) continue;
        
        const corners = {nw:{x:r.x,y:r.y}, ne:{x:r.x+r.w,y:r.y}, sw:{x:r.x,y:r.y+r.h}, se:{x:r.x+r.w,y:r.y+r.h}};
        for(const c of Object.keys(corners)){
            const {x:cx,y:cy} = corners[c];
            if(px >= cx-size && px <= cx+size && py >= cy-size && py <= cy+size){
                return {type:'handle', group:key, corner:c, rect:r};
            }
        }
        if(px >= r.x && px <= r.x+r.w && py >= r.y && py <= r.y+r.h){
            return {type:'inside', group:key, rect:r};
        }
    }
    return {type:'none'};
}

canvas.addEventListener('auxclick',e=>{if(e.button===1)e.preventDefault();});canvas.addEventListener('contextmenu',e=>e.preventDefault());
canvas.addEventListener('wheel',e=>{e.preventDefault();const p=canvasPointFromEvent(e);setWorkspaceZoom(workspaceZoom*(e.deltaY<0?1.12:1/1.12),p.x,p.y);},{passive:false});
canvas.addEventListener('mousedown',e=>{
    if(e.button===1||(e.button===0&&workspaceTool==='pan')){e.preventDefault();const p=canvasPointFromEvent(e);viewPanState={startX:p.x,startY:p.y,originalX:viewPanX,originalY:viewPanY};dragState=null;canvas.style.cursor='grabbing';noteWorkspaceEvent('info','Pan started (middle mouse / hand tool)');return;}
    if(e.button!==0||!syncActive||workspaceTool!=='select')return;
    const p=canvasPointFromEvent(e),px=p.x,py=p.y;
    const hit = hitTest(px, py);
    
    if(hit.group === 'BEV') {
        dragState = {type:'resize', group:'BEV', corner:hit.corner, start:{x:px,y:py}, orig: {...advanced}};
        markerHighlight = 'BEV';
        window.syncPropertiesSelection('BEV_' + hit.corner);
    } 
    else if(hit.type==='handle'){
        dragState = {type:'resize', group:hit.group, corner:hit.corner, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = mapGroupToDefaultVar(hit.group);
        select.value = selectedVar;
        window.syncPropertiesSelection(hit.group);
    } 
    else if(hit.type==='inside'){
        dragState = {type:'move', group:hit.group, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = mapGroupToDefaultVar(hit.group);
        select.value = selectedVar;
        window.syncPropertiesSelection(hit.group);
    } 
    else {
        dragState = null;
        markerHighlight = null;
    }
});

canvas.addEventListener('mousemove',e=>{
    const p=canvasPointFromEvent(e),px=p.x,py=p.y;
    if(viewPanState){viewPanX=viewPanState.originalX+(px-viewPanState.startX);viewPanY=viewPanState.originalY+(py-viewPanState.startY);canvas.style.cursor='grabbing';renderWorkspaceCanvas();return;}
    const hover = hitTest(px, py);
    
    if(dragState){
        canvas.style.cursor = dragState.type==='move' ? 'grabbing' : 'nwse-resize';
    } else if(hover.type==='handle'){
        canvas.style.cursor = 'nwse-resize';
    } else if(hover.type==='inside'){
        canvas.style.cursor = 'move';
    } else {
        canvas.style.cursor = 'default';
    }
    
    if(!dragState || !syncActive) return;
    const dx = px - dragState.start.x;
    const dy = py - dragState.start.y;
    
    const b = getImgBounds();
    const dnx = dx / b.iw; // Scale delta accurately by workspace zoom
    const dny = dy / b.ih;
    
    if(dragState.group === 'BEV'){
        const c = dragState.corner; 
        
        // Removed 0-1 restriction. Allowing bounds from -5 to 5.
        let nx = Math.max(-5.0, Math.min(5.0, dragState.orig['BEV_SRC_'+c+'_X'] + dnx));
        let ny = Math.max(-5.0, Math.min(5.0, dragState.orig['BEV_SRC_'+c+'_Y'] + dny));
        
        advanced['BEV_SRC_'+c+'_X'] = round01(nx);
        advanced['BEV_SRC_'+c+'_Y'] = round01(ny);
        
        updateShapeUIFromData(); 
        drawOverlays();
        window.syncPropertiesSelection('BEV_' + c);
        
        if(debounceTimers['BEV']) clearTimeout(debounceTimers['BEV']);
        debounceTimers['BEV'] = setTimeout(()=>{
            sendAdvanced({
                ['BEV_SRC_'+c+'_X']: advanced['BEV_SRC_'+c+'_X'],
                ['BEV_SRC_'+c+'_Y']: advanced['BEV_SRC_'+c+'_Y']
            });
        }, 220);
        return; 
    }
    
    const group = dragState.group;
    let topVar, bottomVar, leftVar, rightVar;
    if(group==='RL'){ topVar='RL_TOP_ROI'; bottomVar='RL_BOTTOM_ROI'; leftVar='RL_LEFT_ROI'; rightVar='RL_RIGHT_ROI'; }
    else if(group==='LL'){ topVar='LL_TOP_ROI'; bottomVar='LL_BOTTOM_ROI'; leftVar='LL_LEFT_ROI'; rightVar='LL_RIGHT_ROI'; }
    else if(group==='CW'){ topVar='CW_TOP_ROI'; bottomVar='CW_BOTTOM_ROI'; leftVar='CW_LEFT_ROI'; rightVar='CW_RIGHT_ROI'; }
    else if(group==='ST'){ topVar='ST_TOP_ROI'; bottomVar='ST_BOTTOM_ROI'; leftVar='ST_LEFT_ROI'; rightVar='ST_RIGHT_ROI'; }
    else { topVar='OBJ_TOP_ROI'; bottomVar='OBJ_BOTTOM_ROI'; leftVar='OBJ_LEFT_ROI'; rightVar='OBJ_RIGHT_ROI'; }
    
    const orig = dragState.origRect;
    let nx_t = orig.t, nx_b = orig.b, nx_l = orig.l, nx_r = orig.r;
    
    if(dragState.type==='move'){
        nx_t = clamp01(orig.t + dny); nx_b = clamp01(orig.b + dny);
        nx_l = clamp01(orig.l + dnx); nx_r = clamp01(orig.r + dnx);
        if(nx_r - nx_l < 0.02){ const mid = (nx_l + nx_r)/2; nx_l = mid - 0.01; nx_r = mid + 0.01; }
        if(nx_b - nx_t < 0.02){ const mid = (nx_t + nx_b)/2; nx_t = mid - 0.01; nx_b = mid + 0.01; }
    } else {
        if(dragState.corner==='nw'){ nx_t = clamp01(orig.t + dny); nx_l = clamp01(orig.l + dnx); }
        if(dragState.corner==='ne'){ nx_t = clamp01(orig.t + dny); nx_r = clamp01(orig.r + dnx); }
        if(dragState.corner==='sw'){ nx_b = clamp01(orig.b + dny); nx_l = clamp01(orig.l + dnx); }
        if(dragState.corner==='se'){ nx_b = clamp01(orig.b + dny); nx_r = clamp01(orig.r + dnx); }
        if(nx_b <= nx_t) nx_b = nx_t + 0.01;
        if(nx_r <= nx_l) nx_r = nx_l + 0.01;
    }
    values[topVar] = round01(nx_t); values[bottomVar] = round01(nx_b);
    values[leftVar] = round01(nx_l); values[rightVar] = round01(nx_r);
    updateInputsFromValues(); 
    drawOverlays();
    window.syncPropertiesSelection(group);
    
    if(debounceTimers[group]) clearTimeout(debounceTimers[group]);
    debounceTimers[group] = setTimeout(()=>{
        sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]});
    }, 220);
});

window.addEventListener('mouseup',()=>{
    if(viewPanState){viewPanState=null;canvas.style.cursor=workspaceTool==='pan'?'grab':'default';noteWorkspaceEvent('info','Pan finished');return;}
    if(!dragState || !syncActive) {
        dragState = null;
        canvas.style.cursor = 'default';
        return;
    }
    
    if(dragState.group === 'BEV') {
        const c = dragState.corner;
        sendAdvanced({
            ['BEV_SRC_'+c+'_X']: advanced['BEV_SRC_'+c+'_X'],
            ['BEV_SRC_'+c+'_Y']: advanced['BEV_SRC_'+c+'_Y']
        });
    } else {
        const group = dragState.group;
        let topVar, bottomVar, leftVar, rightVar;
        if(group==='RL'){ topVar='RL_TOP_ROI'; bottomVar='RL_BOTTOM_ROI'; leftVar='RL_LEFT_ROI'; rightVar='RL_RIGHT_ROI'; }
        else if(group==='LL'){ topVar='LL_TOP_ROI'; bottomVar='LL_BOTTOM_ROI'; leftVar='LL_LEFT_ROI'; rightVar='LL_RIGHT_ROI'; }
        else if(group==='CW'){ topVar='CW_TOP_ROI'; bottomVar='CW_BOTTOM_ROI'; leftVar='CW_LEFT_ROI'; rightVar='CW_RIGHT_ROI'; }
        else if(group==='ST'){ topVar='ST_TOP_ROI'; bottomVar='ST_BOTTOM_ROI'; leftVar='ST_LEFT_ROI'; rightVar='ST_RIGHT_ROI'; }
        else { topVar='OBJ_TOP_ROI'; bottomVar='OBJ_BOTTOM_ROI'; leftVar='OBJ_LEFT_ROI'; rightVar='OBJ_RIGHT_ROI'; }
        sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]});
    }
    
    dragState = null;
    canvas.style.cursor = 'default';
});

/* ---------- Advanced & BEV Settings logic ---------- */
const shapeInputs = {
    lane_mode: document.getElementById('lane_roi_mode'),
    rl_factor: document.getElementById('rl_factor'),
    ll_factor: document.getElementById('ll_factor'),
    cw_trap_mode: document.getElementById('cw_trap_mode'),
    cw_factor: document.getElementById('cw_factor'),
    st_trap_mode: document.getElementById('st_trap_mode'),
    st_factor: document.getElementById('st_factor'),
    obj_trap_mode: document.getElementById('obj_trap_mode'),
    obj_factor: document.getElementById('obj_factor'),
    rl_val: document.getElementById('rl_factor_val'),
    ll_val: document.getElementById('ll_factor_val'),
    cw_val: document.getElementById('cw_factor_val'),
    st_val: document.getElementById('st_factor_val'),
    obj_val: document.getElementById('obj_factor_val'),
    use_bev: document.getElementById('use_bev_toggle'),
    bev_tl_x: document.getElementById('BEV_SRC_TL_X'),
    bev_tl_y: document.getElementById('BEV_SRC_TL_Y'),
    bev_tr_x: document.getElementById('BEV_SRC_TR_X'),
    bev_tr_y: document.getElementById('BEV_SRC_TR_Y'),
    bev_br_x: document.getElementById('BEV_SRC_BR_X'),
    bev_br_y: document.getElementById('BEV_SRC_BR_Y'),
    bev_bl_x: document.getElementById('BEV_SRC_BL_X'),
    bev_bl_y: document.getElementById('BEV_SRC_BL_Y')
};

function updateShapeUIFromData() {
    shapeInputs.lane_mode.value = advanced.LANE_ROI_MODE || 'rectangle';
    shapeInputs.rl_factor.value = advanced.RL_TOP_WIDTH_FACTOR;
    shapeInputs.ll_factor.value = advanced.LL_TOP_WIDTH_FACTOR;
    shapeInputs.cw_trap_mode.checked = advanced.CW_TRAPEZOID_MODE;
    shapeInputs.cw_factor.value = advanced.CW_TOP_WIDTH_FACTOR;
    shapeInputs.st_trap_mode.checked = advanced.ST_TRAPEZOID_MODE;
    shapeInputs.st_factor.value = advanced.ST_TOP_WIDTH_FACTOR;
    shapeInputs.obj_trap_mode.checked = advanced.OBJ_TRAPEZOID_MODE;
    shapeInputs.obj_factor.value = advanced.OBJ_TOP_WIDTH_FACTOR;
    
    shapeInputs.rl_val.textContent = parseFloat(advanced.RL_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.ll_val.textContent = parseFloat(advanced.LL_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.cw_val.textContent = parseFloat(advanced.CW_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.st_val.textContent = parseFloat(advanced.ST_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.obj_val.textContent = parseFloat(advanced.OBJ_TOP_WIDTH_FACTOR).toFixed(2);
    
    shapeInputs.use_bev.checked = advanced.USE_BEV;
    shapeInputs.bev_tl_x.value = advanced.BEV_SRC_TL_X.toFixed(3);
    shapeInputs.bev_tl_y.value = advanced.BEV_SRC_TL_Y.toFixed(3);
    shapeInputs.bev_tr_x.value = advanced.BEV_SRC_TR_X.toFixed(3);
    shapeInputs.bev_tr_y.value = advanced.BEV_SRC_TR_Y.toFixed(3);
    shapeInputs.bev_br_x.value = advanced.BEV_SRC_BR_X.toFixed(3);
    shapeInputs.bev_br_y.value = advanced.BEV_SRC_BR_Y.toFixed(3);
    shapeInputs.bev_bl_x.value = advanced.BEV_SRC_BL_X.toFixed(3);
    shapeInputs.bev_bl_y.value = advanced.BEV_SRC_BL_Y.toFixed(3);

    drawOverlays();
}

function handleShapeSlider() {
    advanced.LANE_ROI_MODE = shapeInputs.lane_mode.value;
    advanced.RL_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.rl_factor.value);
    advanced.LL_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.ll_factor.value);
    advanced.CW_TRAPEZOID_MODE = shapeInputs.cw_trap_mode.checked;
    advanced.CW_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.cw_factor.value);
    advanced.ST_TRAPEZOID_MODE = shapeInputs.st_trap_mode.checked;
    advanced.ST_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.st_factor.value);
    advanced.OBJ_TRAPEZOID_MODE = shapeInputs.obj_trap_mode.checked;
    advanced.OBJ_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.obj_factor.value);
    
    shapeInputs.rl_val.textContent = advanced.RL_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.ll_val.textContent = advanced.LL_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.cw_val.textContent = advanced.CW_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.st_val.textContent = advanced.ST_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.obj_val.textContent = advanced.OBJ_TOP_WIDTH_FACTOR.toFixed(2);
    drawOverlays();
}

['input', 'change'].forEach(evt => {
    shapeInputs.lane_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.rl_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.ll_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.cw_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.cw_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.st_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.st_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.obj_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.obj_factor.addEventListener(evt, handleShapeSlider);
});

shapeInputs.use_bev.addEventListener('change', (e) => {
    sendAdvanced({ USE_BEV: e.target.checked });
    showToast('BEV System ' + (e.target.checked ? 'Enabled' : 'Disabled'));
});

document.getElementById('confirm_bev_inputs').addEventListener('click', () => {
    sendAdvanced({
        BEV_SRC_TL_X: parseFloat(shapeInputs.bev_tl_x.value) || 0,
        BEV_SRC_TL_Y: parseFloat(shapeInputs.bev_tl_y.value) || 0,
        BEV_SRC_TR_X: parseFloat(shapeInputs.bev_tr_x.value) || 0,
        BEV_SRC_TR_Y: parseFloat(shapeInputs.bev_tr_y.value) || 0,
        BEV_SRC_BR_X: parseFloat(shapeInputs.bev_br_x.value) || 0,
        BEV_SRC_BR_Y: parseFloat(shapeInputs.bev_br_y.value) || 0,
        BEV_SRC_BL_X: parseFloat(shapeInputs.bev_bl_x.value) || 0,
        BEV_SRC_BL_Y: parseFloat(shapeInputs.bev_bl_y.value) || 0
    });
    showToast('BEV Points Saved');
});

document.getElementById('confirm_shape').addEventListener('click', ()=>{
    sendAdvanced({
        LANE_ROI_MODE: advanced.LANE_ROI_MODE,
        RL_TOP_WIDTH_FACTOR: advanced.RL_TOP_WIDTH_FACTOR,
        LL_TOP_WIDTH_FACTOR: advanced.LL_TOP_WIDTH_FACTOR,
        CW_TRAPEZOID_MODE: advanced.CW_TRAPEZOID_MODE,
        CW_TOP_WIDTH_FACTOR: advanced.CW_TOP_WIDTH_FACTOR,
        ST_TRAPEZOID_MODE: advanced.ST_TRAPEZOID_MODE,
        ST_TOP_WIDTH_FACTOR: advanced.ST_TOP_WIDTH_FACTOR,
        OBJ_TRAPEZOID_MODE: advanced.OBJ_TRAPEZOID_MODE,
        OBJ_TOP_WIDTH_FACTOR: advanced.OBJ_TOP_WIDTH_FACTOR
    });
    showToast('Shape Config Saved');
});

/* ---------- Manual Box inputs ---------- */
function updateInputsFromValues(){
    inputsContainer.querySelectorAll('input').forEach(input=>{
        const name = input.name;
        if(values[name]!==undefined) input.value = round01(values[name]).toFixed(2);
    });
}
document.querySelectorAll('.btn-inc').forEach(btn=>{
    btn.addEventListener('click', ()=>{
        if(!syncActive) return showToast('Requests are stopped!');
        const v = btn.dataset.var;
        const d = parseFloat(btn.dataset.delta);
        const input = inputsContainer.querySelector(`input[name="${v}"]`);
        let val = parseFloat(input.value)||0;
        val = clamp01(round01(val + d));
        input.value = val.toFixed(2);
        debounceSendSingle(v, val);
    });
});
function debounceSendSingle(name, val){
    if(debounceTimers[name]) clearTimeout(debounceTimers[name]);
    debounceTimers[name] = setTimeout(()=>{ sendUpdate({[name]:val}); }, 250);
}
inputsContainer.querySelectorAll('input').forEach(input=>{
    input.addEventListener('input', e=>{
        if(!syncActive) return;
        const name = e.target.name;
        let v = parseFloat(e.target.value);
        if(isNaN(v)) return;
        v = clamp01(round01(v));
        values[name]=v;
        debounceSendSingle(name, v);
        drawOverlays();
    });
});
document.getElementById('apply_all').addEventListener('click', ()=>{
    if(!syncActive) return showToast('Requests are stopped!');
    const data = {};
    inputsContainer.querySelectorAll('input').forEach(input=>{
        const name = input.name;
        let val = parseFloat(input.value);
        if(!isNaN(val)) data[name] = clamp01(round01(val));
    });
    sendUpdate(data);
});
function sendUpdate(data){
    if(!syncActive) return;
    recordApiEvent('info','Saving ROI/config fields: '+Object.keys(data).join(', '));
    fetch('/update_conf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
        .then(async r => {
            const result = await r.json().catch(() => ({}));
            if(!r.ok) throw new Error(result.message || 'HTTP ' + r.status);
            return result;
        })
        .then(j=>{
            if(j && j.values){
                values = j.values;
                updateInputsFromValues(); drawOverlays();
                if(window.syncPropertiesSelection)window.syncPropertiesSelection(document.getElementById('prop_target').value);
                showToast('Base Updated');
            } else {
                showToast((j && j.message) || 'Could not update base settings');
            }
        })
        .catch(err => {
            recordApiEvent('error', 'Failed to update base settings: ' + err.message);
            console.error('Failed to update base settings:', err);
            showToast('Settings update failed: ' + err.message);
        });
}

/* ---------- Stream API Actions ---------- */
document.getElementById('refresh_vals').addEventListener('click', ()=>{
    if(!syncActive) return showToast('Requests are stopped!');
    fetchDashboardJson('/get_values').then(j=>{ if(j && j.values){ values=j.values; updateInputsFromValues(); drawOverlays(); }});
    loadAdvanced();
});
document.getElementById('clear_selection').addEventListener('click', ()=>{ select.value='NONE'; selectedVar='NONE'; markerHighlight=null; drawOverlays(); });
document.getElementById('download_json').addEventListener('click', ()=>{
    fetchDashboardJson('/get_values').then(j=>{
        if(!j || !j.values) return;
        const blob = new Blob([JSON.stringify(j.values, null, 2)], {type:'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href=url; a.download='config.json'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    });
});

/* ---------- Stop All Sync Button Logic ---------- */
const stopAllBtn = document.getElementById('stop_all_btn');
stopAllBtn.addEventListener('click', () => {
    syncActive = !syncActive;
    if(!syncActive) {
        stopAllBtn.textContent = 'Resume All Sync & Requests';
        stopAllBtn.style.background = '#22c55e'; // Green when resuming
        clearInterval(fetchFrameTimer);
        fetchFrameTimer = null;
        clearInterval(valUpdateTimer);
        valUpdateTimer = null;
        clearInterval(healthUpdateTimer);
        healthUpdateTimer = null;
        clearInterval(arduinoUpdateTimer);
        arduinoUpdateTimer = null;
        updateFrameModeText();
        showToast('All Sync Stopped');
    } else {
        stopAllBtn.textContent = 'Stop All Sync & Requests';
        stopAllBtn.style.background = '#ef4444'; // Red for stop
        startFrameLoop();
        if(!valUpdateTimer) valUpdateTimer = setInterval(fetchValuesLoop, 4000);
        if(!healthUpdateTimer) healthUpdateTimer = setInterval(updateHealth, 1000);
        if(!arduinoUpdateTimer) arduinoUpdateTimer = setInterval(updateArduinoOutput, 1000);
        fetchValuesLoop();
        updateHealth();
        updateArduinoOutput();
        updateFrameModeText();
        showToast('Sync Resumed');
    }
});

/* ---------- Advanced API Sync ---------- */
const advInputs = {
    lane_threshold: document.getElementById('lane_threshold'),
    cross_thresh: document.getElementById('cross_thresh'),
    cross_sleep: document.getElementById('crosswalk_sleep'),
    cross_thresh_spend: document.getElementById('crosswalk_thresh_spend'),
    read_sign_thresh: document.getElementById('read_sign_threshold'),
    turn_right: document.getElementById('turn_right'),
    turn_left: document.getElementById('turn_left'),
    straight: document.getElementById('straight'),
    stop_lvl: document.getElementById('stop_lvl'),
    run_lvl: document.getElementById('run_lvl'),
    with_sign: document.getElementById('with_sign'),
    with_apriltag: document.getElementById('with_apriltag')
};

function loadAdvanced(){
    if(!syncActive) return;
    fetchDashboardJson('/get_advanced').then(j=>{
        if(j && j.advanced){
            advanced = j.advanced;
            advInputs.lane_threshold.value = advanced.LANE_THRESHOLD;
            advInputs.cross_thresh.value = advanced.CROSSWALK_THRESHOLD;
            advInputs.cross_sleep.value = advanced.CROSSWALK_SLEEP;
            advInputs.cross_thresh_spend.value = advanced.CROSSWALK_THRESH_SPEND;
            advInputs.read_sign_thresh.value = advanced.READ_SIGN_THRESHOLD;
            advInputs.turn_right.value = advanced.TURN_RIGHT;
            advInputs.turn_left.value = advanced.TURN_LEFT;
            advInputs.straight.value = advanced.STRAIGHT;
            advInputs.stop_lvl.value = advanced.STOP;
            advInputs.run_lvl.value = advanced.RUN_LVL;
            advInputs.with_sign.checked = advanced.WITH_SIGN;
            advInputs.with_apriltag.checked = advanced.WITH_APRILTAG;
            updateShapeUIFromData();
        }
    });
}

document.getElementById('confirm_advanced').addEventListener('click', ()=>{
    sendAdvanced({
        LANE_THRESHOLD: parseInt(advInputs.lane_threshold.value)||0,
        CROSSWALK_THRESHOLD: parseInt(advInputs.cross_thresh.value)||0,
        CROSSWALK_SLEEP: parseFloat(advInputs.cross_sleep.value)||0,
        CROSSWALK_THRESH_SPEND: parseFloat(advInputs.cross_thresh_spend.value)||0,
        READ_SIGN_THRESHOLD: parseInt(advInputs.read_sign_thresh.value)||0,
        TURN_RIGHT: parseInt(advInputs.turn_right.value)||0,
        TURN_LEFT: parseInt(advInputs.turn_left.value)||0,
        STRAIGHT: parseInt(advInputs.straight.value)||0,
        STOP: parseInt(advInputs.stop_lvl.value)||0,
        RUN_LVL: advInputs.run_lvl.value,
        WITH_SIGN: advInputs.with_sign.checked,
        WITH_APRILTAG: advInputs.with_apriltag.checked
    });
    showToast('Advanced Limits Saved');
});

/* ---------- Color & Vis Listeners ---------- */
['vis_rl','vis_ll','vis_cw','vis_st','vis_obj','vis_bev'].forEach(id => {
    document.getElementById(id).addEventListener('change', (e) => {
        let key = id.replace('vis_', '').toUpperCase();
        ui.visible[key] = e.target.checked;
        if(syncActive) {
            fetch('/set_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({visible: ui.visible})});
        }
        drawOverlays();
    });
});
['color_rl','color_ll','color_cw','color_st','color_obj','color_bev'].forEach(id => {
    document.getElementById(id).addEventListener('change', (e) => {
        let key = id.replace('color_', '').toUpperCase();
        ui.colors[key] = e.target.value;
        if(syncActive) {
            fetch('/set_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({colors: ui.colors})});
        }
        drawOverlays();
    });
});

/* ---------- Buttons setup ---------- */
document.getElementById('freeze_btn').addEventListener('click', ()=> {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/freeze_frame', {method:'POST'}).then(()=> {isFrozen=true; updateFrameModeText(); updateZoomStatus(); showToast('Frame frozen'); noteWorkspaceEvent('info','Camera frame frozen');})
});
document.getElementById('unfreeze_btn').addEventListener('click', ()=> {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/unfreeze_frame', {method:'POST'}).then(()=> {isFrozen=false; updateFrameModeText(); updateZoomStatus(); showToast('Back to live'); noteWorkspaceEvent('info','Live camera resumed');})
});

document.getElementById('take_picture_btn').addEventListener('click', () => {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/take_picture', {method: 'POST'}).then(r => r.json()).then(j => { if (j && j.success) showToast('Picture Taken!'); });
});

document.getElementById('toggle_record_btn').addEventListener('click', () => {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/toggle_record', {method: 'POST'}).then(r => r.json()).then(j => {
        if (j && j.success) {
            isRecording = j.recording;
            const statusDiv = document.getElementById('record_status');
            const btn = document.getElementById('toggle_record_btn');
            statusDiv.textContent = 'Recording: ' + (isRecording ? 'Yes' : 'No');
            statusDiv.style.color = isRecording ? '#ef4444' : 'var(--accent)';
            btn.textContent = isRecording ? 'Stop Recording' : 'Start Recording';
            showToast(isRecording ? 'Recording Started' : 'Recording Stopped');
            noteWorkspaceEvent('info',isRecording?'Video recording started':'Video recording stopped');
        }
    });
});

/* ---------- Init ---------- */
function updateHealth(){
    if(!syncActive) return;
    fetchDashboardJson('/api/health')
        .then(j=>{
            if(!j) return;
            const h = j.health || {};
            const m = j.metrics || {};
            const t = m.timing || {};
            const state = document.getElementById('health_state');
            const faults = document.getElementById('health_faults');
            const metrics = document.getElementById('health_metrics');
            const healthStateName = String(h.state || 'UNKNOWN');
            state.textContent = 'State: ' + healthStateName;
            if(lastLoggedHealthState !== healthStateName) {
                noteWorkspaceEvent(healthStateName === 'HEALTHY' || healthStateName === 'OK' ? 'info' : 'warn', 'Runtime health state: ' + (lastLoggedHealthState || 'initial') + ' → ' + healthStateName);
                lastLoggedHealthState = healthStateName;
            }
            const names = Object.keys(h.faults || {});
            const details = names.map(name => {
                const fault = h.faults[name] || {};
                return name + (fault.message ? ': ' + fault.message : '');
            });
            const faultSignature = details.join(' | ');
            faults.textContent = 'Faults: ' + (details.length ? faultSignature : 'none');
            if(lastLoggedFaultSignature !== faultSignature) {
                if(faultSignature) noteWorkspaceEvent('error', 'Runtime faults: ' + faultSignature);
                else if(lastLoggedFaultSignature) noteWorkspaceEvent('info', 'Runtime faults cleared');
                lastLoggedFaultSignature = faultSignature;
            }
            const loop = t.loop || {};
            const camera = t.camera || {};
            const perception = t.perception || {};
            const serial = t.serial || {};
            metrics.textContent =
                'FPS avg ' + (m.avg_fps || 0).toFixed(1) +
                ' | loop p95 ' + (loop.p95_ms || 0).toFixed(1) + ' ms' +
                ' | loop max ' + (loop.max_ms || 0).toFixed(1) + ' ms' +
                ' | camera p95 ' + (camera.p95_ms || 0).toFixed(1) + ' ms' +
                ' | perception p95 ' + (perception.p95_ms || 0).toFixed(1) + ' ms' +
                ' | serial p95 ' + (serial.p95_ms || 0).toFixed(1) + ' ms' +
                (j.perception_confidence ? ' | Confidence ' + j.perception_confidence.score.toFixed(2) + ' (' + (j.perception_confidence.valid?'valid':'invalid') + ')' : '') +
                (j.speed_decision ? ' | Speed: ' + j.speed_decision.target + ' ' + j.speed_decision.reason : '') +
                (j.obstacle_diagnostics ? ' | Obstacle: ' + j.obstacle_diagnostics.state + ' — ' + j.obstacle_diagnostics.reason : '');
        })
        .catch(()=>{});
}

function updateArduinoOutput(){
    if(!syncActive) return;
    fetchDashboardJson('/api/arduino-output')
        .then(j=>{
            if(!j) return;
            const status = document.getElementById('arduino_status');
            const output = document.getElementById('arduino_output');
            const arduinoStateText = 'State: ' + (j.state || 'UNKNOWN') + ' | Connected: ' + (j.connected ? 'yes' : 'no');
            status.textContent = arduinoStateText;
            if(lastLoggedArduinoState !== arduinoStateText) {
                noteWorkspaceEvent(j.connected ? 'info' : 'warn', 'Arduino telemetry: ' + arduinoStateText);
                lastLoggedArduinoState = arduinoStateText;
            }
            output.textContent = (j.lines || []).join('\\n');
            output.scrollTop = output.scrollHeight;
        })
        .catch(()=>{});
}

function fetchValuesLoop() {
    if(!syncActive) return;
    fetchDashboardJson('/get_values').then(j=>{ if(j && j.values){ values=j.values; updateInputsFromValues(); }});
}

function loadModeFeatures(){
    fetchDashboardJson('/api/mode').then(j=>{
        if(!j) return;
        const f=j.features || {};
        const c=j.capabilities || {};
        const lane = f.lane_detector || 'default';
        const modeSignature = String(lane) + ' | BEV: ' + (f.bev ? 'on' : 'off') + ' | ML: ' + (f.ml_lane_detector ? 'on' : 'off') + ' | Marker: ' + (f.marker_mode || 'none');
        document.getElementById('mode_features').textContent = 'Lane: ' + lane + ' | BEV: ' + (f.bev ? 'on' : 'off') + ' | ML: ' + (f.ml_lane_detector ? 'on' : 'off') + ' | Marker: ' + (f.marker_mode || 'none');
        if(lastLoggedModeSignature !== modeSignature) { noteWorkspaceEvent('info', 'Runtime mode features: ' + modeSignature); lastLoggedModeSignature = modeSignature; }

        const disable = (el, condition, reason) => {
            if(!el) return;
            el.disabled = condition;
            if(condition) el.title = reason;
        };
        const controls = [
            [document.getElementById('use_bev_toggle'), !c.supports_bev, 'BEV is not supported by the active mode.'],
            [document.getElementById('confirm_bev_inputs'), !c.supports_bev, 'BEV is not supported by the active mode.'],
            [document.getElementById('lane_roi_mode'), !c.supports_lane_roi, 'Lane ROI controls are not used by the active lane detector.'],
            [document.getElementById('confirm_shape'), !c.supports_lane_roi, 'Lane ROI controls are not used by the active lane detector.'],
            [document.getElementById('rl_factor'), !c.supports_lane_roi, 'Lane ROI controls are not used by the active lane detector.'],
            [document.getElementById('ll_factor'), !c.supports_lane_roi, 'Lane ROI controls are not used by the active lane detector.'],
            [document.getElementById('cross_thresh'), !c.supports_crosswalk, 'Crosswalk processing is not supported by the active mode.'],
            [document.getElementById('crosswalk_sleep'), !c.supports_crosswalk, 'Crosswalk processing is not supported by the active mode.'],
            [document.getElementById('crosswalk_thresh_spend'), !c.supports_crosswalk, 'Crosswalk processing is not supported by the active mode.'],
            [document.getElementById('cw_trap_mode'), !c.supports_crosswalk_trapezoid, 'Crosswalk trapezoid processing is not supported by the active mode.'],
            [document.getElementById('cw_factor'), !c.supports_crosswalk_trapezoid, 'Crosswalk trapezoid processing is not supported by the active mode.'],
            [document.getElementById('obj_trap_mode'), !c.supports_object_detection, 'Object detection is not supported by the active mode.'],
            [document.getElementById('obj_factor'), !c.supports_object_detection, 'Object detection is not supported by the active mode.'],
            [document.getElementById('with_sign'), !c.supports_sign, 'Traffic-sign processing is not supported by the active mode.'],
            [document.getElementById('with_apriltag'), !c.supports_apriltag, 'AprilTag processing is not supported by the active mode.']
        ];
        controls.forEach(item=>disable(item[0], item[1], item[2]));
        if(!STREAM_CONTROL_ALLOWED){
            document.querySelectorAll('button,input,select').forEach(el=>{
                if(!['download_json','toggle_dock_btn','camera_fullscreen_btn','workspace_zoom','variable_select','clear_selection','center_reset','prop_target','prop_revert_btn','tool_overlays_btn','console_toggle_btn','console_clear_btn'].includes(el.id)&&!el.hasAttribute('data-tool')&&!el.hasAttribute('data-action')&&!el.hasAttribute('data-console-tab'))el.disabled=true;
            });
        }
        document.querySelectorAll('input[name^="CW_"]').forEach(el=>disable(el, !c.supports_crosswalk, 'Crosswalk ROI is not consumed by the active mode.'));
        document.querySelectorAll('input[name^="OBJ_"]').forEach(el=>disable(el, !c.supports_object_detection, 'Object detection ROI is not used by the active mode.'));
    }).catch(()=>{});
}


function setupCadWorkspace(){
const workspace=document.querySelector('.container'),dockToggle=document.getElementById('toggle_dock_btn'),consoleDock=document.getElementById('bottom_console'),consoleToggle=document.getElementById('console_toggle_btn'),consoleClear=document.getElementById('console_clear_btn'),propTarget=document.getElementById('prop_target');let consoleTab='events';
const narrow=()=>window.matchMedia('(max-width:720px)').matches;
let dockIsOpen=!narrow();
const dockVisible=()=>dockIsOpen;
function setDock(open){
  dockIsOpen=Boolean(open);
  const isNarrow=narrow();
  workspace.classList.toggle('show-dock',isNarrow&&dockIsOpen);
  workspace.classList.toggle('dock-hidden',!isNarrow&&!dockIsOpen);
  dockToggle.textContent=dockIsOpen?'Hide Panels':'Show Panels';
  dockToggle.setAttribute('aria-expanded',String(dockIsOpen));
  dockToggle.setAttribute('aria-label',dockIsOpen?'Hide settings panels':'Show settings panels');
  const menuDockToggle=document.querySelector('[data-action="toggle-properties"]');
  if(menuDockToggle)menuDockToggle.textContent=dockIsOpen?'Hide Panels':'Show Panels';
}
dockToggle.addEventListener('click',()=>{
  const open=!dockIsOpen;
  setDock(open);
  noteWorkspaceEvent('info','Settings dock '+(open?'shown':'hidden'));
});
window.addEventListener('resize',()=>setDock(dockIsOpen));
setDock(dockIsOpen);
function setConsoleOpen(open){consoleDock.classList.toggle('console-open',open);consoleToggle.setAttribute('aria-expanded',String(open));consoleToggle.textContent=(open?'⌄':'⌃')+' EVENT CONSOLE';}
consoleToggle.addEventListener('click',()=>setConsoleOpen(!consoleDock.classList.contains('console-open')));
consoleClear.addEventListener('click',()=>{if(consoleTab==='api')workspaceApiEvents=[];else workspaceEvents=[];renderWorkspaceEventLog(consoleTab);noteWorkspaceEvent('info','Event log cleared',consoleTab);});
document.querySelectorAll('[data-console-tab]').forEach(b=>b.addEventListener('click',()=>{consoleTab=b.dataset.consoleTab;document.querySelectorAll('[data-console-tab]').forEach(t=>t.setAttribute('aria-selected',String(t===b)));document.getElementById('console_events').hidden=consoleTab!=='events';document.getElementById('console_api').hidden=consoleTab!=='api';renderWorkspaceEventLog(consoleTab);}));
document.querySelectorAll('.menu-group').forEach(m=>m.addEventListener('toggle',()=>{if(m.open)document.querySelectorAll('.menu-group').forEach(o=>{if(o!==m)o.open=false;});}));document.addEventListener('click',e=>{if(!e.target.closest('.menu-group'))document.querySelectorAll('.menu-group').forEach(m=>m.open=false);});
function setTool(tool){workspaceTool=tool==='pan'?'pan':'select';document.querySelectorAll('[data-tool]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tool===workspaceTool)));canvas.style.cursor=workspaceTool==='pan'?'grab':'default';noteWorkspaceEvent('info',workspaceTool==='pan'?'Hand / Pan tool selected':'Select / Edit ROI tool selected');}
function zoomBy(f){setWorkspaceZoom(workspaceZoom*f,canvas.width/2,canvas.height/2);}
function toggleOverlays(){showRectsCheckbox.checked=!showRectsCheckbox.checked;document.getElementById('tool_overlays_btn').setAttribute('aria-pressed',String(showRectsCheckbox.checked));renderWorkspaceCanvas();noteWorkspaceEvent('info','Overlays '+(showRectsCheckbox.checked?'shown':'hidden'));}
function toggleProperties(){const p=document.querySelector('.properties-panel');if(!dockVisible()){setDock(true);if(p)p.open=true;noteWorkspaceEvent('info','Properties panel shown');return;}if(p){p.open=!p.open;noteWorkspaceEvent('info','Properties panel '+(p.open?'opened':'closed'));}}
document.querySelectorAll('[data-tool]').forEach(b=>b.addEventListener('click',()=>setTool(b.dataset.tool)));
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>{switch(b.dataset.action){
case 'export-config':if(window.exportFullConfig)window.exportFullConfig().catch(err=>showToast('Export failed: '+err.message));else document.getElementById('download_json').click();break;case 'refresh-config':if(window.reloadFullConfig)window.reloadFullConfig().catch(err=>showToast('Reload failed: '+err.message));else document.getElementById('refresh_vals').click();noteWorkspaceEvent('info','Full configuration refresh requested');break;
case 'take-picture':document.getElementById('take_picture_btn').click();break;case 'clear-selection':document.getElementById('clear_selection').click();break;case 'apply-base':document.getElementById('apply_all').click();break;case 'properties':toggleProperties();break;case 'toggle-properties':document.getElementById('toggle_dock_btn').click();break;
case 'zoom-in':zoomBy(1.2);break;case 'zoom-out':zoomBy(1/1.2);break;case 'fit-view':fitWorkspaceView();break;case 'toggle-fullscreen':toggleCameraFullscreen();break;case 'toggle-overlays':toggleOverlays();break;case 'toggle-console':setConsoleOpen(!consoleDock.classList.contains('console-open'));break;
case 'tool-select':setTool('select');break;case 'tool-pan':setTool('pan');break;case 'freeze':document.getElementById('freeze_btn').click();break;case 'unfreeze':document.getElementById('unfreeze_btn').click();break;
case 'help':showToast('Wheel: zoom at cursor · Middle mouse: pan · H: hand · V: select · F: fullscreen · 0: fit · O: overlays · Ctrl+Backtick: console',6500);break;}if(b.closest('.menu-group'))b.closest('.menu-group').open=false;}));
document.getElementById('center_reset').addEventListener('click',()=>fitWorkspaceView());document.getElementById('camera_fullscreen_btn').addEventListener('click',toggleCameraFullscreen);document.getElementById('tool_overlays_btn').addEventListener('click',toggleOverlays);
document.addEventListener('keydown',e=>{const tag=e.target&&e.target.tagName?e.target.tagName.toLowerCase():'';if((e.ctrlKey||e.metaKey)&&e.code==='Backquote'){e.preventDefault();setConsoleOpen(!consoleDock.classList.contains('console-open'));return;}if(['input','textarea','select'].includes(tag)||e.target?.isContentEditable||e.ctrlKey||e.metaKey||e.altKey)return;const k=e.key.toLowerCase();if(k==='h')setTool('pan');else if(k==='v')setTool('select');else if(k==='0')fitWorkspaceView();else if(k==='o')toggleOverlays();else if(k==='f')toggleCameraFullscreen();else if(k==='+'||k==='=')zoomBy(1.2);else if(k==='-')zoomBy(1/1.2);else if(k==='escape')document.querySelectorAll('.menu-group').forEach(m=>m.open=false);});
function names(g){const p=g+'_';return{top:p+'TOP_ROI',bottom:p+'BOTTOM_ROI',left:p+'LEFT_ROI',right:p+'RIGHT_ROI'};}
function info(){return propTarget.value.startsWith('BEV_')?{kind:'point',corner:propTarget.value.slice(4)}:{kind:'roi',group:propTarget.value};}
function syncPropertiesSelection(target){if(!target)return;if(target.startsWith('BEV_'))propTarget.value=target;else if(['RL','LL','CW','ST','OBJ'].includes(target))propTarget.value=target;const s=info();document.getElementById('prop_roi_fields').hidden=s.kind!=='roi';document.getElementById('prop_point_fields').hidden=s.kind!=='point';
if(s.kind==='roi'){const n=names(s.group);document.getElementById('properties_mode').textContent=s.group+' · ROI bounds';document.getElementById('prop_left').value=values[n.left]??'';document.getElementById('prop_top').value=values[n.top]??'';document.getElementById('prop_right').value=values[n.right]??'';document.getElementById('prop_bottom').value=values[n.bottom]??'';document.getElementById('prop_hint').textContent='Normalized camera coordinates (0–1). Drag this ROI or edit fields, then Apply.';document.getElementById('cad_selected_area').textContent='Object: '+s.group;}
else{const c=s.corner;document.getElementById('properties_mode').textContent='BEV · '+c+' control point';document.getElementById('prop_point_x').value=advanced['BEV_SRC_'+c+'_X']??'';document.getElementById('prop_point_y').value=advanced['BEV_SRC_'+c+'_Y']??'';document.getElementById('prop_hint').textContent='BEV point coordinates range from -5 to 5. Drag the corner or edit X/Y, then Apply.';document.getElementById('cad_selected_area').textContent='Object: BEV '+c;}}
window.syncPropertiesSelection=syncPropertiesSelection;
propTarget.addEventListener('change',()=>{const s=info();markerHighlight=s.kind==='point'?'BEV':s.group;if(s.kind==='roi'){selectedVar=mapGroupToDefaultVar(s.group);select.value=selectedVar;}syncPropertiesSelection(propTarget.value);renderWorkspaceCanvas();noteWorkspaceEvent('info','Properties target selected: '+propTarget.value);});
document.getElementById('prop_apply_btn').addEventListener('click',()=>{if(!syncActive)return showToast('Requests are stopped!');const s=info();if(s.kind==='roi'){const n=names(s.group);let l=Number(document.getElementById('prop_left').value),t=Number(document.getElementById('prop_top').value),r=Number(document.getElementById('prop_right').value),b=Number(document.getElementById('prop_bottom').value);if(![l,t,r,b].every(Number.isFinite))return showToast('Enter valid numeric ROI coordinates');l=clamp01(l);t=clamp01(t);r=clamp01(r);b=clamp01(b);if(r-l<.01||b-t<.01)return showToast('ROI requires right > left and bottom > top');values[n.left]=round01(l);values[n.top]=round01(t);values[n.right]=round01(r);values[n.bottom]=round01(b);updateInputsFromValues();renderWorkspaceCanvas();sendUpdate({[n.top]:values[n.top],[n.bottom]:values[n.bottom],[n.left]:values[n.left],[n.right]:values[n.right]});syncPropertiesSelection(s.group);noteWorkspaceEvent('info',s.group+' ROI properties applied');}
else{const c=s.corner,x=Number(document.getElementById('prop_point_x').value),y=Number(document.getElementById('prop_point_y').value);if(!Number.isFinite(x)||!Number.isFinite(y))return showToast('Enter valid BEV point coordinates');advanced['BEV_SRC_'+c+'_X']=Math.max(-5,Math.min(5,round01(x)));advanced['BEV_SRC_'+c+'_Y']=Math.max(-5,Math.min(5,round01(y)));updateShapeUIFromData();renderWorkspaceCanvas();sendAdvanced({['BEV_SRC_'+c+'_X']:advanced['BEV_SRC_'+c+'_X'],['BEV_SRC_'+c+'_Y']:advanced['BEV_SRC_'+c+'_Y']});syncPropertiesSelection('BEV_'+c);noteWorkspaceEvent('info','BEV '+c+' point properties applied');}});
document.getElementById('prop_revert_btn').addEventListener('click',()=>syncPropertiesSelection(propTarget.value));
const readout={x:document.getElementById('cad_cursor_x'),y:document.getElementById('cad_cursor_y'),u:document.getElementById('cad_cursor_u'),v:document.getElementById('cad_cursor_v'),area:document.getElementById('cad_selected_area')};
function updateCadReadout(e){const r=canvas.getBoundingClientRect();if(!r.width||!r.height)return;const p=canvasPointFromEvent(e),b=getImgBounds(),u=(p.x-b.ix)/b.iw,v=(p.y-b.iy)/b.ih;readout.x.textContent='X: '+Math.round(u*canvas.width)+' px';readout.y.textContent='Y: '+Math.round(v*canvas.height)+' px';readout.u.textContent='U: '+(u*100).toFixed(1)+' %';readout.v.textContent='V: '+(v*100).toFixed(1)+' %';}
canvas.addEventListener('mousemove',updateCadReadout,{passive:true});canvas.addEventListener('mouseleave',()=>{if(!viewPanState){readout.x.textContent='X: — px';readout.y.textContent='Y: — px';readout.u.textContent='U: — %';readout.v.textContent='V: — %';}},{passive:true});
select.addEventListener('change',()=>{selectedVar=select.value;readout.area.textContent='Object: '+(select.value||'NONE');if(selectedVar.endsWith('_TOP_ROI'))window.syncPropertiesSelection(selectedVar.split('_')[0]);});
noteWorkspaceEvent('info','Workspace initialized; middle mouse pans and wheel zooms at cursor');renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');window.syncPropertiesSelection('RL');updateZoomStatus();
}

function initApp(){
    setupCadWorkspace();
    updateInputsFromValues();
    loadModeFeatures(); 
    document.getElementById('vis_rl').checked = ui.visible.RL;
    document.getElementById('vis_ll').checked = ui.visible.LL;
    document.getElementById('vis_cw').checked = ui.visible.CW;
    document.getElementById('vis_st').checked = ui.visible.ST !== false;
    document.getElementById('vis_obj').checked = ui.visible.OBJ !== false;
    document.getElementById('vis_bev').checked = ui.visible.BEV !== false; 
    loadAdvanced();
    updateFrameModeText();
    startFrameLoop();

    // Start each poller once at page load; immediate requests avoid stale
    // "UNKNOWN"/"Waiting" status until the user toggles sync controls.
    fetchValuesLoop();
    updateHealth();
    updateArduinoOutput();
    valUpdateTimer = setInterval(fetchValuesLoop, 4000);
    healthUpdateTimer = setInterval(updateHealth, 1000);
    arduinoUpdateTimer = setInterval(updateArduinoOutput, 1000);
}
initApp();

function mapGroupToDefaultVar(g){ 
    if(g==='RL') return 'RL_TOP_ROI'; 
    if(g==='LL') return 'LL_TOP_ROI'; 
    if(g==='CW') return 'CW_TOP_ROI'; 
    if(g==='ST') return 'ST_TOP_ROI'; 
    if(g==='OBJ') return 'OBJ_TOP_ROI'; 
    return 'RL_TOP_ROI'; 
}
</script>

<script>
(function(){
'use strict';
const $ = function(id){return document.getElementById(id)};
const jsonClone = function(value){return JSON.parse(JSON.stringify(value));};
const EXT_LAYERS = ['RL','LL','CW','ST','OBJ','BEV'];
let extGrid=false, extSnap=false, extCrosshair=false, extAnnotationsVisible=true, extCrosshairPoint=null;
let editorTool='select', rulerStart=null, extAnnotations=[], extFrameGallery=[], extRuntimeSample=[];
let undoStack=[], redoStack=[], currentConfig=null, internalConfigWrite=0, extSaveTimer=null, extHealthTimer=null;
let serverLogsVisible=[], workspaceProfileNames=[], presetNames=[], historyItems=[];
let frameCompareImage=null, cameraSupportedControlNames=[], cameraSettingsEditable=false;
const nativeFetch = window.fetch.bind(window);

function normalizedConfig(snapshot){
  if(!snapshot || typeof snapshot!=='object') return null;
  const copy=jsonClone(snapshot);
  delete copy.exported_at; delete copy.controls_enabled; delete copy.success;
  return copy.config && copy.config.schema_version ? normalizedConfig(copy.config) : copy;
}
function sameConfig(a,b){try{return JSON.stringify(normalizedConfig(a))===JSON.stringify(normalizedConfig(b));}catch(_){return false;}}
async function readConfig(){
  const response=await nativeFetch('/api/config/full',{cache:'no-store'});
  if(!response.ok) throw new Error('Config API returned HTTP '+response.status);
  return normalizedConfig(await response.json());
}
function updateUndoButtons(){
  if($('ext_undo')) $('ext_undo').disabled=!STREAM_CONTROL_ALLOWED||undoStack.length===0;
  if($('ext_redo')) $('ext_redo').disabled=!STREAM_CONTROL_ALLOWED||redoStack.length===0;
  if($('ext_undo_status')) $('ext_undo_status').textContent='Undo: '+undoStack.length+' · Redo: '+redoStack.length;
}
function rememberUndo(before,after){
  if(before&&!sameConfig(before,after)){
    undoStack.push(jsonClone(before));undoStack=undoStack.slice(-40);redoStack=[];updateUndoButtons();
  }
}
function restoreTrackingStack(){
  undoStack=undoStack.slice(-40);redoStack=redoStack.slice(-40);updateUndoButtons();
}
function isTrackedMutation(url,method){
  if(method!=='POST')return false;
  return ['/update_conf','/set_advanced','/set_ui','/api/config/full','/api/processing-rate','/api/camera/settings','/api/safety','/api/features','/toggle_record'].some(function(path){return url.split('?')[0].endsWith(path);});
}
window.fetch=async function(input,init){
  const url=typeof input==='string'?input:(input&&input.url)||'';
  const method=String((init&&init.method)||(input&&input.method)||'GET').toUpperCase();
  const track=isTrackedMutation(url,method)&&internalConfigWrite===0;
  const before=currentConfig?jsonClone(currentConfig):null;
  let response;
  try{response=await nativeFetch(input,init);}catch(err){throw err;}
  if(track&&response&&response.ok){
    try{
      const next=await readConfig();
      rememberUndo(before,next);
      currentConfig=next;updateUndoButtons();
    }catch(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Configuration tracker refresh failed: '+err.message);}
  }
  return response;
};

function addSVG(name,attrs,parent){
  const node=document.createElementNS('http://www.w3.org/2000/svg',name);
  Object.keys(attrs||{}).forEach(function(key){node.setAttribute(key,String(attrs[key]));});
  (parent||$('ext_precision_overlay')).appendChild(node);return node;
}
function extImageBounds(){
  try{return getImgBounds();}catch(_){return {ix:0,iy:0,iw:canvas.width,ih:canvas.height};}
}
function drawPrecisionOverlay(){
  const svg=$('ext_precision_overlay'),stage=$('canvas_stage');if(!svg||!canvas||!stage)return;
  const canvasRect=canvas.getBoundingClientRect(),stageRect=stage.getBoundingClientRect();
  const contentLeft=stageRect.left+stage.clientLeft,contentTop=stageRect.top+stage.clientTop;
  svg.style.left=(canvasRect.left-contentLeft)+'px';
  svg.style.top=(canvasRect.top-contentTop)+'px';
  svg.style.width=Math.max(1,canvasRect.width)+'px';
  svg.style.height=Math.max(1,canvasRect.height)+'px';
  svg.setAttribute('viewBox','0 0 '+canvas.width+' '+canvas.height);
  svg.replaceChildren();
  const b=extImageBounds();
  const gridOn=extGrid&&(!currentConfig||!currentConfig.ui||currentConfig.ui.visible.GRID!==false);
  if(gridOn){
    for(let i=1;i<20;i++){
      const x=b.ix+b.iw*i/20, y=b.iy+b.ih*i/20;
      addSVG('line',{x1:x,y1:b.iy,x2:x,y2:b.iy+b.ih,stroke:'rgba(105,190,210,.25)','stroke-width':1,'stroke-dasharray':i%2===0?'3 4':'1 5'});
      addSVG('line',{x1:b.ix,y1:y,x2:b.ix+b.iw,y2:y,stroke:'rgba(105,190,210,.25)','stroke-width':1,'stroke-dasharray':i%2===0?'3 4':'1 5'});
    }
    addSVG('rect',{x:b.ix,y:b.iy,width:b.iw,height:b.ih,fill:'none',stroke:'rgba(105,190,210,.5)','stroke-width':1});
  }
  if(extCrosshair&&extCrosshairPoint){
    addSVG('line',{x1:b.ix,y1:extCrosshairPoint.y,x2:b.ix+b.iw,y2:extCrosshairPoint.y,stroke:'#f8fafc','stroke-width':1,'stroke-dasharray':'6 4'});
    addSVG('line',{x1:extCrosshairPoint.x,y1:b.iy,x2:extCrosshairPoint.x,y2:b.iy+b.ih,stroke:'#f8fafc','stroke-width':1,'stroke-dasharray':'6 4'});
    const label=addSVG('text',{x:extCrosshairPoint.x+8,y:extCrosshairPoint.y-8,fill:'#fff','font-size':11,'paint-order':'stroke','stroke':'#07101a','stroke-width':3});
    label.textContent='U '+(((extCrosshairPoint.x-b.ix)/b.iw)*100).toFixed(1)+'% · V '+(((extCrosshairPoint.y-b.iy)/b.ih)*100).toFixed(1)+'%';
  }
  if(!extAnnotationsVisible)return;
  extAnnotations.forEach(function(item,index){
    const color=item.color||'#fbbf24';
    if(item.kind==='roi_rect'||item.kind==='roi_trapezoid'){
      const x=b.ix+Number(item.x||0)*b.iw,y=b.iy+Number(item.y||0)*b.ih,w=Number(item.w||0)*b.iw,h=Number(item.h||0)*b.ih;
      if(item.kind==='roi_rect'){
        addSVG('rect',{x:x,y:y,width:w,height:h,fill:'rgba(34,211,238,.10)',stroke:color,'stroke-width':2,'stroke-dasharray':'5 3'});
      }else{
        const top=Math.max(0,Math.min(1,Number(item.topFactor==null?0.5:item.topFactor))),inset=(w*(1-top))/2;
        addSVG('polygon',{points:(x+inset)+','+y+' '+(x+w-inset)+','+y+' '+(x+w)+','+(y+h)+' '+x+','+(y+h),fill:'rgba(34,211,238,.10)',stroke:color,'stroke-width':2,'stroke-dasharray':'5 3'});
      }
      const label=addSVG('text',{x:x+4,y:y+13,fill:color,'font-size':12,'paint-order':'stroke',stroke:'#07101a','stroke-width':3});
      label.textContent=item.label||('Preview ROI '+(index+1));
      return;
    }
    const x=b.ix+Number(item.u||0)*b.iw,y=b.iy+Number(item.v||0)*b.ih;
    if(item.kind==='ruler'&&item.u2!=null&&item.v2!=null){
      const x2=b.ix+item.u2*b.iw,y2=b.iy+item.v2*b.ih;
      addSVG('line',{x1:x,y1:y,x2:x2,y2:y2,stroke:color,'stroke-width':2});
      addSVG('circle',{cx:x,cy:y,r:3,fill:color});addSVG('circle',{cx:x2,cy:y2,r:3,fill:color});
      const t=addSVG('text',{x:(x+x2)/2+5,y:(y+y2)/2-5,fill:color,'font-size':12,'paint-order':'stroke',stroke:'#07101a','stroke-width':3});
      t.textContent=item.label||Math.hypot((item.u2-item.u)*b.iw,(item.v2-item.v)*b.ih).toFixed(1)+' px';
    }else{
      addSVG('circle',{cx:x,cy:y,r:6,fill:'rgba(251,191,36,.2)',stroke:color,'stroke-width':2});
      addSVG('line',{x1:x-9,y1:y,x2:x+9,y2:y,stroke:color,'stroke-width':1});
      addSVG('line',{x1:x,y1:y-9,x2:x,y2:y+9,stroke:color,'stroke-width':1});
      if(item.label){const t=addSVG('text',{x:x+10,y:y-8,fill:color,'font-size':12,'paint-order':'stroke',stroke:'#07101a','stroke-width':3});t.textContent=item.label;}
    }
  });
}
function updateEditorStatus(text){if($('ext_editor_status'))$('ext_editor_status').textContent=text;}
function setEditorTool(tool){
  editorTool=tool;
  rulerStart=null;
  if($('ext_ruler'))$('ext_ruler').checked=tool==='ruler';
  ['ext_annotate_btn','ext_ruler','ext_roi_rect_tool','ext_roi_trapezoid_tool'].forEach(function(id){
    if($(id))$(id).classList.toggle('ext-tool-active',
      (id==='ext_ruler'&&tool==='ruler')||(id==='ext_annotate_btn'&&tool==='annotate')||
      (id==='ext_roi_rect_tool'&&tool==='roi_rect')||(id==='ext_roi_trapezoid_tool'&&tool==='roi_trapezoid'));
  });
  if(typeof setTool==='function')setTool(tool==='pan'?'pan':'select');
  if(canvas)canvas.style.cursor=tool==='pan'?'grab':(['annotate','ruler','roi_rect','roi_trapezoid'].includes(tool)?'crosshair':'default');
  const messages={ruler:'Ruler active: click two points inside the image.',annotate:'Annotation active: click in the image to add a note marker.',roi_rect:'Rectangle ROI preview: click two opposite corners.',roi_trapezoid:'Trapezoid ROI preview: click two opposite corners.'};
  updateEditorStatus(messages[tool]||('Tool: '+tool));
  scheduleWorkspaceSave();drawPrecisionOverlay();
}
function pointFromEvent(event){
  const rect=canvas.getBoundingClientRect();
  const x=(event.clientX-rect.left)*(canvas.width/rect.width),y=(event.clientY-rect.top)*(canvas.height/rect.height);
  const b=extImageBounds();
  if(x<b.ix||x>b.ix+b.iw||y<b.iy||y>b.iy+b.ih)return null;
  let u=(x-b.ix)/b.iw,v=(y-b.iy)/b.ih;
  if(extSnap){u=Math.round(u*20)/20;v=Math.round(v*20)/20;}
  u=Math.max(0,Math.min(1,u));v=Math.max(0,Math.min(1,v));
  return {x:b.ix+u*b.iw,y:b.iy+v*b.ih,u:u,v:v};
}
function refreshAnnotationList(){
  const root=$('ext_annotations_list');if(!root)return;root.replaceChildren();
  if(!extAnnotations.length){const empty=document.createElement('div');empty.className='small-muted';empty.textContent='No custom annotations.';root.appendChild(empty);return;}
  extAnnotations.forEach(function(item,index){
    const row=document.createElement('div');row.className='ext-list-row';
    const label=document.createElement('span');label.textContent=(index+1)+'. '+(item.kind||'marker')+(item.label?': '+item.label:'');row.appendChild(label);
    const remove=document.createElement('button');remove.type='button';remove.className='ghost';remove.textContent='Delete';remove.onclick=function(){extAnnotations.splice(index,1);refreshAnnotationList();drawPrecisionOverlay();scheduleWorkspaceSave();};row.appendChild(remove);root.appendChild(row);
  });
  syncLayerControls();
}
function onCustomPointerDown(event){
  if(!['annotate','ruler','roi_rect','roi_trapezoid'].includes(editorTool)||event.button!==0)return;
  const point=pointFromEvent(event);if(!point)return;
  event.preventDefault();event.stopPropagation();event.stopImmediatePropagation();
  if(editorTool==='annotate'){
    let label=window.prompt('Annotation label (optional):','');
    if(label===null)return;
    label=String(label).trim().slice(0,80);
    extAnnotations.push({kind:label?'note':'marker',u:point.u,v:point.v,label:label,color:'#fbbf24'});
    if(extAnnotations.length>250)extAnnotations.shift();
    refreshAnnotationList();syncLayerControls();drawPrecisionOverlay();scheduleWorkspaceSave();
    updateEditorStatus('Annotation placed at U '+(point.u*100).toFixed(1)+'%, V '+(point.v*100).toFixed(1)+'%.');
  }else if(!rulerStart){
    rulerStart=point;updateEditorStatus(editorTool==='ruler'?'Ruler start marked. Click the second point.':'ROI first corner marked. Click the opposite corner.');drawPrecisionOverlay();
  }else{
    const start=rulerStart;rulerStart=null;
    if(editorTool==='ruler'){
      const distance=Math.hypot((point.u-start.u)*extImageBounds().iw,(point.v-start.v)*extImageBounds().ih);
      extAnnotations.push({kind:'ruler',u:start.u,v:start.v,u2:point.u,v2:point.v,label:distance.toFixed(1)+' px',color:'#22d3ee'});
      updateEditorStatus('Ruler saved: '+distance.toFixed(1)+' image pixels.');syncLayerControls();
    }else{
      const x=Math.min(start.u,point.u),y=Math.min(start.v,point.v),w=Math.abs(point.u-start.u),h=Math.abs(point.v-start.v);
      if(w<0.005||h<0.005){updateEditorStatus('Custom ROI is too small; draw it again with a larger area.');return;}
      const kind=editorTool;
      const generatedName='Preview ROI '+(extAnnotations.length+1);
      const typedLabel=window.prompt('Custom ROI label:',generatedName);
      if(typedLabel===null){drawPrecisionOverlay();return;}
      const item={kind:kind,x:x,y:y,w:w,h:h,label:String(typedLabel||generatedName).trim().slice(0,80),color:'#22d3ee'};
      if(kind==='roi_trapezoid')item.topFactor=Number($('ext_roi_top_factor').value)||0.5;
      extAnnotations.push(item);updateEditorStatus('Preview ROI added. This shape does not alter robot perception or control.');
    }
    if(extAnnotations.length>250)extAnnotations.shift();
    refreshAnnotationList();drawPrecisionOverlay();scheduleWorkspaceSave();
  }
}
function drawSparkline(id,values){
  const c=$(id);if(!c)return;const w=c.width,h=c.height,ctx=c.getContext('2d');ctx.clearRect(0,0,w,h);ctx.strokeStyle='rgba(148,163,184,.18)';ctx.lineWidth=1;
  for(let y=1;y<4;y++){ctx.beginPath();ctx.moveTo(0,h*y/4);ctx.lineTo(w,h*y/4);ctx.stroke();}
  const valid=values.filter(function(v){return Number.isFinite(v);});if(valid.length<2)return;
  let min=Math.min.apply(null,valid),max=Math.max.apply(null,valid);if(max-min<0.001){max=min+1;}
  ctx.beginPath();ctx.strokeStyle='#22d3ee';ctx.lineWidth=2;
  valid.forEach(function(v,i){const x=i*(w-8)/(valid.length-1)+4,y=h-5-(v-min)/(max-min)*(h-12);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();
  ctx.fillStyle='#9fb3c8';ctx.font='10px sans-serif';ctx.fillText(max.toFixed(1),4,11);ctx.fillText(min.toFixed(1),4,h-3);
}
function addFrameSnapshot(){
  if(!lastFrameImage||!lastFrameImage.complete||!lastFrameImage.naturalWidth){showToast('No decoded camera frame is available yet');return;}
  try{
    const temp=document.createElement('canvas');const maxW=640;const scale=Math.min(1,maxW/lastFrameImage.naturalWidth);temp.width=Math.max(1,Math.round(lastFrameImage.naturalWidth*scale));temp.height=Math.max(1,Math.round(lastFrameImage.naturalHeight*scale));
    temp.getContext('2d').drawImage(lastFrameImage,0,0,temp.width,temp.height);
    const item={timestamp:new Date().toISOString(),src:temp.toDataURL('image/jpeg',.85),width:temp.width,height:temp.height};extFrameGallery.unshift(item);extFrameGallery=extFrameGallery.slice(0,20);renderFrameGallery();showToast('Frame snapshot added to session history');
  }catch(err){showToast('Frame snapshot failed: '+err.message);}
}
function renderFrameGallery(){
  const root=$('ext_frame_gallery');if(!root)return;root.replaceChildren();
  extFrameGallery.forEach(function(item,index){
    const card=document.createElement('div');card.className='ext-gallery-card';const img=document.createElement('img');img.src=item.src;img.alt='Frame snapshot '+(index+1);card.appendChild(img);
    const info=document.createElement('div');info.textContent=new Date(item.timestamp).toLocaleTimeString()+' · '+item.width+'×'+item.height;card.appendChild(info);
    const row=document.createElement('div');row.style.display='flex';row.style.gap='3px';row.style.padding='4px';
    const cmp=document.createElement('button');cmp.type='button';cmp.className='ghost';cmp.textContent='Compare';cmp.style.flex='1';cmp.onclick=function(){showFrameComparison(item);};row.appendChild(cmp);
    const save=document.createElement('a');save.className='ghost';save.textContent='Save';save.href=item.src;save.download='frame-snapshot-'+(index+1)+'.jpg';save.style.textDecoration='none';save.style.fontSize='11px';row.appendChild(save);card.appendChild(row);root.appendChild(card);
  });
}
function showFrameComparison(item){
  const modal=$('ext_frame_compare');if(!modal)return;
  $('ext_compare_old').src=item.src;
  if(lastFrameImage&&lastFrameImage.complete&&lastFrameImage.naturalWidth){const c=document.createElement('canvas');c.width=lastFrameImage.naturalWidth;c.height=lastFrameImage.naturalHeight;c.getContext('2d').drawImage(lastFrameImage,0,0);$('ext_compare_live').src=c.toDataURL('image/jpeg',.85);}
  $('ext_frame_compare_title').textContent='Snapshot '+new Date(item.timestamp).toLocaleString()+' vs current frame';
  modal.style.display='flex';
}
function downloadText(data,filename,mime){
  const blob=new Blob([data],{type:mime||'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();setTimeout(function(){URL.revokeObjectURL(url);},500);
}
function collectWorkspace(){
  const layers={};
  EXT_LAYERS.forEach(function(key){layers[key]={visible:!!(ui.visible||{})[key],opacity:Number((ui.opacity||{})[key]==null?1:(ui.opacity||{})[key])};});
  layers.ANNOTATIONS={visible:extAnnotationsVisible,opacity:1};layers.GRID={visible:extGrid,opacity:1};
  const panels={};document.querySelectorAll('.right-panel details.dock-panel').forEach(function(panel){if(panel.id)panels[panel.id]=panel.open;});
  const rect=document.querySelector('.right-panel').getBoundingClientRect();
  const paneWidth=parseFloat(getComputedStyle(document.querySelector('.container')).getPropertyValue('--right-pane-width'))||rect.width||315;
  return {view:{zoom:workspaceZoom,panX:viewPanX,panY:viewPanY,grid:extGrid,snap:extSnap,crosshair:extCrosshair,showRuler:editorTool==='ruler',overlays:!!showRectsCheckbox.checked,tool:editorTool,rightPaneWidth:paneWidth},
    panels:panels,layers:layers,annotations:extAnnotations};
}
async function saveWorkspace(){
  const response=await nativeFetch('/api/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'save_workspace',workspace:collectWorkspace()})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));return data;
}
function scheduleWorkspaceSave(){
  if(extSaveTimer)clearTimeout(extSaveTimer);
  extSaveTimer=setTimeout(function(){saveWorkspace().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Workspace persistence failed: '+err.message);});},450);
}
function applyWorkspace(workspace){
  if(!workspace||typeof workspace!=='object')return;
  const view=workspace.view||{};
  if(typeof view.zoom==='number'&&typeof setWorkspaceZoom==='function'){workspaceZoom=Math.max(.3,Math.min(4,view.zoom));viewPanX=Number(view.panX)||0;viewPanY=Number(view.panY)||0;$('workspace_zoom').value=String(workspaceZoom);}
  extGrid=!!view.grid;extSnap=!!view.snap;extCrosshair=!!view.crosshair;
  if($('ext_grid'))$('ext_grid').checked=extGrid;if($('ext_snap'))$('ext_snap').checked=extSnap;if($('ext_crosshair'))$('ext_crosshair').checked=extCrosshair;
  if($('ext_overlays'))$('ext_overlays').checked=view.overlays!==false;
  if(typeof view.overlays==='boolean')showRectsCheckbox.checked=view.overlays;
  editorTool=['select','pan','annotate','ruler','roi_rect','roi_trapezoid'].includes(view.tool)?view.tool:'select';
  const savedLayers=workspace.layers||{};
  extAnnotationsVisible=!savedLayers.ANNOTATIONS||savedLayers.ANNOTATIONS.visible!==false;
  if(typeof view.rightPaneWidth==='number'&&view.rightPaneWidth>=250&&view.rightPaneWidth<=700)document.querySelector('.container').style.setProperty('--right-pane-width',view.rightPaneWidth+'px');
  Object.keys(workspace.panels||{}).forEach(function(id){const panel=$(id);if(panel&&panel.tagName==='DETAILS')panel.open=!!workspace.panels[id];});
  Object.keys(workspace.layers||{}).forEach(function(key){const layer=workspace.layers[key];if(!layer)return;if(EXT_LAYERS.includes(key)){ui.visible[key]=layer.visible!==false;ui.opacity[key]=Number(layer.opacity==null?1:layer.opacity);}});
  extGrid=extGrid&&(!savedLayers.GRID||savedLayers.GRID.visible!==false);
  extAnnotations=Array.isArray(workspace.annotations)?jsonClone(workspace.annotations).slice(0,250):[];
  syncLayerControls();syncLegacyLayerControls();refreshAnnotationList();renderWorkspaceCanvas();drawPrecisionOverlay();scheduleWorkspaceSave();
}
function syncLegacyLayerControls(){
  const map={RL:'rl',LL:'ll',CW:'cw',ST:'st',OBJ:'obj',BEV:'bev'};
  Object.keys(map).forEach(function(key){const vis=$('vis_'+map[key]),color=$('color_'+map[key]);if(vis)vis.checked=ui.visible[key]!==false;if(color)color.value=(ui.colors||{})[key]||'#ffffff';});
}
function syncLayerControls(){
  const root=$('ext_layer_rows');if(!root)return;root.replaceChildren();
  EXT_LAYERS.forEach(function(key){
    const row=document.createElement('div');row.className='ext-layer-row';
    const check=document.createElement('input');check.type='checkbox';check.checked=ui.visible[key]!==false;check.title='Show/hide '+key;check.onchange=function(){ui.visible[key]=check.checked;syncLegacyLayerControls();saveUILayers();};row.appendChild(check);
    const label=document.createElement('span');label.textContent=({RL:'Right lane',LL:'Left lane',CW:'Crosswalk',ST:'Sign / tag',OBJ:'Object region',BEV:'Bird eye view'})[key]||key;row.appendChild(label);
    const color=document.createElement('input');color.type='color';color.value=(ui.colors||{})[key]||'#ffffff';color.title='Layer color';color.oninput=function(){ui.colors[key]=color.value;syncLegacyLayerControls();renderWorkspaceCanvas();scheduleUILayerSave();};row.appendChild(color);
    const opacity=document.createElement('input');opacity.type='range';opacity.min='0';opacity.max='1';opacity.step='.05';opacity.value=String((ui.opacity||{})[key]==null?1:ui.opacity[key]);opacity.title='Layer opacity';opacity.oninput=function(){ui.opacity=ui.opacity||{};ui.opacity[key]=Number(opacity.value);renderWorkspaceCanvas();drawPrecisionOverlay();scheduleUILayerSave();};row.appendChild(opacity);
    root.appendChild(row);
  });
  const annotationRow=document.createElement('div');annotationRow.className='ext-layer-row';annotationRow.style.gridTemplateColumns='18px minmax(0,1fr) auto';
  const annotationCheck=document.createElement('input');annotationCheck.type='checkbox';annotationCheck.checked=extAnnotationsVisible;annotationCheck.title='Show/hide user annotations and custom ROI previews';
  annotationCheck.onchange=function(){extAnnotationsVisible=annotationCheck.checked;drawPrecisionOverlay();scheduleWorkspaceSave();};
  annotationRow.appendChild(annotationCheck);
  const annotationLabel=document.createElement('span');annotationLabel.textContent='Annotations / custom ROI previews';annotationRow.appendChild(annotationLabel);
  const annotationNote=document.createElement('span');annotationNote.className='small-muted';annotationNote.textContent=String(extAnnotations.length);annotationRow.appendChild(annotationNote);
  root.appendChild(annotationRow);
}
let uiLayerSaveTimer=null;
function scheduleUILayerSave(){if(uiLayerSaveTimer)clearTimeout(uiLayerSaveTimer);uiLayerSaveTimer=setTimeout(function(){saveUILayers().catch(function(err){showToast('Layer save failed: '+err.message);});},250);}
async function saveUILayers(){
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const response=await nativeFetch('/set_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({colors:ui.colors,visible:ui.visible,opacity:ui.opacity||{}})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  const after=await readConfig().catch(function(){return currentConfig;});rememberUndo(before,after);currentConfig=after;drawPrecisionOverlay();scheduleWorkspaceSave();return data;
}
function applyConfigToUI(snapshot){
  const cfg=normalizedConfig(snapshot);if(!cfg)return;
  currentConfig=cfg;values=jsonClone(cfg.values||values);advanced=jsonClone(cfg.advanced||advanced);ui=jsonClone(cfg.ui||ui);
  document.querySelectorAll('#inputs_container input[name]').forEach(function(input){if(Object.prototype.hasOwnProperty.call(values,input.name))input.value=String(values[input.name]);});
  const advancedInputs={lane_threshold:'LANE_THRESHOLD',cross_thresh:'CROSSWALK_THRESHOLD',crosswalk_sleep:'CROSSWALK_SLEEP',crosswalk_thresh_spend:'CROSSWALK_THRESH_SPEND',read_sign_threshold:'READ_SIGN_THRESHOLD',turn_right:'TURN_RIGHT',turn_left:'TURN_LEFT',straight:'STRAIGHT',stop_lvl:'STOP'};
  Object.keys(advancedInputs).forEach(function(id){if($(id)&&advanced[advancedInputs[id]]!=null)$(id).value=String(advanced[advancedInputs[id]]);});
  if($('run_lvl'))$('run_lvl').value=advanced.RUN_LVL||'MOVE';if($('with_sign'))$('with_sign').checked=!!advanced.WITH_SIGN;if($('with_apriltag'))$('with_apriltag').checked=!!advanced.WITH_APRILTAG;
  if(typeof updateInputsFromValues==='function')updateInputsFromValues();
  if(typeof updateShapeUIFromData==='function')updateShapeUIFromData();
  const runtime=cfg.runtime||{};if(runtime.target_processing_fps!=null&&$('ext_target_fps'))$('ext_target_fps').value=String(runtime.target_processing_fps);
  syncLegacyLayerControls();syncLayerControls();
  if(typeof window.syncPropertiesSelection==='function'&&$('prop_target'))window.syncPropertiesSelection($('prop_target').value);
  renderWorkspaceCanvas();drawPrecisionOverlay();
}
async function applyFullConfig(snapshot,label,trackForUndo){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const body=normalizedConfig(snapshot);if(!body)throw new Error('Configuration snapshot is invalid.');
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  internalConfigWrite++;
  try{
    const response=await nativeFetch('/api/config/full',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
    applyConfigToUI(data.config);
    const after=normalizedConfig(data.config);
    if(trackForUndo)rememberUndo(before,after);
    noteWorkspaceEvent('info',label||'Configuration restored');return data.config;
  }finally{internalConfigWrite--;}
}
async function doUndo(){
  if(!undoStack.length)return;const target=undoStack.pop(),previous=currentConfig?jsonClone(currentConfig):null;
  if(previous)redoStack.push(previous);
  try{const result=await applyFullConfig(target,'Undo configuration change');currentConfig=normalizedConfig(result);restoreTrackingStack();}
  catch(err){undoStack.push(target);if(previous&&redoStack.length)redoStack.pop();restoreTrackingStack();showToast('Undo failed: '+err.message);}
}
async function doRedo(){
  if(!redoStack.length)return;const target=redoStack.pop(),previous=currentConfig?jsonClone(currentConfig):null;
  if(previous)undoStack.push(previous);
  try{const result=await applyFullConfig(target,'Redo configuration change');currentConfig=normalizedConfig(result);restoreTrackingStack();}
  catch(err){redoStack.push(target);if(previous&&undoStack.length)undoStack.pop();restoreTrackingStack();showToast('Redo failed: '+err.message);}
}
async function refreshWorkspaceProfiles(){
  const data=await nativeFetch('/api/workspace',{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();});
  workspaceProfileNames=data.profiles||[];const select=$('ext_profile_select');select.replaceChildren();
  if(!workspaceProfileNames.length){const o=document.createElement('option');o.value='';o.textContent='No saved profiles';select.appendChild(o);}
  workspaceProfileNames.forEach(function(name){const o=document.createElement('option');o.value=name;o.textContent=name;select.appendChild(o);});
  if(data.workspace&&Object.keys(data.workspace).length)applyWorkspace(data.workspace);
}
async function profileAction(action){
  const name=String($('ext_profile_name').value||$('ext_profile_select').value||'').trim();if(!name)throw new Error('Enter or select a workspace profile name.');
  if(action==='delete'&&!confirm('Delete workspace profile "'+name+'"?'))return;
  const response=await nativeFetch('/api/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action==='save'?'save_profile':action==='load'?'load_profile':'delete_profile',name:name,workspace:collectWorkspace()})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  if(action==='load')applyWorkspace(data.workspace);await refreshWorkspaceProfileNamesOnly();showToast('Workspace profile '+action+': '+name);
}
async function refreshWorkspaceProfileNamesOnly(){
  const d=await nativeFetch('/api/workspace',{cache:'no-store'}).then(function(r){return r.json();});
  workspaceProfileNames=d.profiles||[];const s=$('ext_profile_select');s.replaceChildren();if(!workspaceProfileNames.length){const o=document.createElement('option');o.value='';o.textContent='No saved profiles';s.appendChild(o);}
  workspaceProfileNames.forEach(function(n){const o=document.createElement('option');o.value=n;o.textContent=n;s.appendChild(o);});
}
async function refreshPresets(){
  const data=await nativeFetch('/api/config/presets',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
  presetNames=data.presets||[];const select=$('ext_preset_select');select.replaceChildren();
  if(!presetNames.length){const o=document.createElement('option');o.value='';o.textContent='No saved presets';select.appendChild(o);}
  presetNames.forEach(function(item){const o=document.createElement('option');o.value=item.name;o.textContent=item.name+' · '+item.mode;select.appendChild(o);});
}
async function presetAction(action){
  const name=String($('ext_preset_name').value||$('ext_preset_select').value||'').trim();if(!name)throw new Error('Enter or select a preset name.');
  if(action==='delete'&&!confirm('Delete configuration preset "'+name+'"?'))return;
  if(action==='apply'&&!confirm('Apply preset "'+name+'"? This changes live robot configuration.'))return;
  const before=action==='apply'?(currentConfig?jsonClone(currentConfig):await readConfig()):null;
  const response=await nativeFetch('/api/config/presets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action,name:name})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  if(action==='apply'){applyConfigToUI(data.config);const after=normalizedConfig(data.config);if(!sameConfig(before,after)){undoStack.push(before);undoStack=undoStack.slice(-40);redoStack=[];updateUndoButtons();}showToast('Preset applied: '+name);}
  await refreshPresets();if(action==='save')noteWorkspaceEvent('info','Saved configuration preset: '+name);
}
function renderConfigDiff(current,saved){
  const sections=[['ROI values','values'],['Advanced controls','advanced'],['UI settings','ui'],['Runtime settings','runtime']];const lines=[];
  sections.forEach(function(section){const key=section[1],a=current[key]||{},b=saved[key]||{},names=Array.from(new Set(Object.keys(a).concat(Object.keys(b)))).sort(),changes=[];
    names.forEach(function(name){if(JSON.stringify(a[name])!==JSON.stringify(b[name]))changes.push(name+': current='+JSON.stringify(a[name])+' → preset='+JSON.stringify(b[name]));});
    if(changes.length)lines.push('['+section[0]+']',...changes);
  });
  $('ext_config_diff').textContent=lines.join(String.fromCharCode(10))||'No differences between the current configuration and this preset.';
}
async function comparePreset(){
  const name=$('ext_preset_select').value;if(!name)throw new Error('Choose a preset to compare.');
  const response=await nativeFetch('/api/config/presets?name='+encodeURIComponent(name),{cache:'no-store'});
  const data=await response.json();if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  renderConfigDiff(currentConfig||await readConfig(),data.config);
}
async function refreshHistory(){
  const data=await nativeFetch('/api/config/history',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
  historyItems=data.items||[];const select=$('ext_history_select');select.replaceChildren();
  if(!historyItems.length){const o=document.createElement('option');o.value='';o.textContent='No saved history';select.appendChild(o);}
  historyItems.slice().reverse().forEach(function(item){const o=document.createElement('option');o.value=String(item.index);o.textContent=new Date(item.timestamp*1000).toLocaleString()+' · '+item.label;select.appendChild(o);});
}
async function restoreHistory(){
  const index=$('ext_history_select').value;if(index==='')throw new Error('Choose a history snapshot first.');
  if(!confirm('Restore the selected configuration snapshot?'))return;
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const response=await nativeFetch('/api/config/history',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'restore',index:Number(index)})});
  const data=await response.json();if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  applyConfigToUI(data.config);const after=normalizedConfig(data.config);
  if(!sameConfig(before,after)){undoStack.push(before);undoStack=undoStack.slice(-40);redoStack=[];updateUndoButtons();}
  showToast('Configuration history restored');await refreshHistory();
}
function importFullConfigFile(file){
  const reader=new FileReader();reader.onload=async function(){try{
    const parsed=JSON.parse(String(reader.result||''));const normalized=normalizedConfig(parsed);
    if(!normalized||!normalized.values||!normalized.advanced||!normalized.ui)throw new Error('JSON is missing required full configuration sections.');
    if(normalized.mode!==String('{{ mode }}').toLowerCase())throw new Error('File mode does not match this dashboard.');
    if(!confirm('Import this full configuration into the live robot runtime?'))return;
    const result=await applyFullConfig(normalized,'Imported full configuration',true);showToast('Full configuration imported');currentConfig=normalizedConfig(result);await refreshHistory();
  }catch(err){showToast('Import failed: '+err.message);}};reader.onerror=function(){showToast('Could not read the selected file');};reader.readAsText(file);
}
async function exportFullConfig(){
  const config=await readConfig();config.exported_at=new Date().toISOString();downloadText(JSON.stringify(config,null,2),'roboy-'+String('{{ mode }}').toLowerCase()+'-full-config.json','application/json');noteWorkspaceEvent('info','Exported full configuration');
}
window.exportFullConfig=exportFullConfig;
window.reloadFullConfig=async function(){
  const config=await readConfig();
  currentConfig=config;
  applyConfigToUI(config);
  undoStack=[];redoStack=[];updateUndoButtons();
  showToast('Reloaded active configuration from the robot');
  noteWorkspaceEvent('info','Reloaded full configuration from runtime');
  return config;
};
async function refreshRuntime(){
  try{
    const health=await nativeFetch('/api/health',{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();});
    const h=health.health||{},m=health.metrics||{},timing=m.timing||{},camera=timing.camera||{},perception=timing.perception||{},loop=timing.loop||{},rate=health.processing_rate||{};
    const fps=Number(rate.achieved_fps)||Number(m.avg_fps)||0;extRuntimeSample.push({fps:fps,loop:Number(loop.mean_ms)||0,perception:Number(perception.mean_ms)||0});extRuntimeSample=extRuntimeSample.slice(-60);
    drawSparkline('ext_fps_chart',extRuntimeSample.map(function(v){return v.fps;}));drawSparkline('ext_latency_chart',extRuntimeSample.map(function(v){return v.loop;}));drawSparkline('ext_perception_chart',extRuntimeSample.map(function(v){return v.perception;}));
    const faults=h.faults||{};const faultNames=Object.keys(faults);$('ext_health_summary').textContent='State: '+(h.state||h.lifecycle||'UNKNOWN')+' · FPS: '+fps.toFixed(1)+' · Faults: '+faultNames.length;
    $('ext_runtime_details').textContent=JSON.stringify({health:h,metrics:m,processing_rate:rate,control:health.control,camera:health.camera,stream:health.stream},null,2);
    $('ext_sign_status').textContent=JSON.stringify(health.sign_detector||((h.resources||{}).sign_detector)||{active:false},null,2);
    $('ext_confidence_status').textContent=JSON.stringify({perception_confidence:health.perception_confidence,speed_decision:health.speed_decision},null,2);
    $('ext_obstacle_status').textContent=JSON.stringify(health.obstacle_diagnostics||null,null,2);
  }catch(err){$('ext_health_summary').textContent='Runtime telemetry unavailable: '+err.message;}
}
function renderLiveFeatureControls(snapshot){
  const root=$('ext_live_feature_rows');if(!root)return;root.replaceChildren();
  const live=snapshot.live||{},canControl=!!snapshot.controls_enabled&&STREAM_CONTROL_ALLOWED;
  const checks=[
    ['DETECT_OBJECT','Object detection',live.DETECT_OBJECT],
    ['USE_BEV','Bird’s-eye transform',live.USE_BEV],
    ['RECORD_VIDEO','Video recording',live.RECORD_VIDEO]
  ];
  checks.forEach(function(item){
    const feature=item[0],meta=item[2]||{},row=document.createElement('div');row.className='ext-list-row';
    const left=document.createElement('div');left.style.display='grid';left.style.gap='2px';left.style.minWidth='0';
    const title=document.createElement('strong');title.textContent=item[1];left.appendChild(title);
    const note=document.createElement('span');note.className='small-muted';note.textContent=meta.description||'';left.appendChild(note);row.appendChild(left);
    const control=document.createElement('input');control.type='checkbox';control.checked=!!meta.enabled;control.disabled=!canControl||!meta.available;control.title=meta.available?'Live control':'Unsupported by active mode/lane pipeline';
    control.onchange=function(){applyLiveFeature(feature,control.checked).catch(function(err){showToast(err.message);refreshFeatureStatus();});};row.appendChild(control);root.appendChild(row);
  });
  const marker=live.marker_mode||{},row=document.createElement('div');row.className='ext-list-row';
  const label=document.createElement('label');label.textContent='Marker detector';label.style.flex='1';row.appendChild(label);
  const select=document.createElement('select');[['none','Off'],['sign','Traffic signs'],['apriltag','AprilTag']].forEach(function(pair){const opt=document.createElement('option');opt.value=pair[0];opt.textContent=pair[1];select.appendChild(opt);});
  select.value=marker.value||'none';select.disabled=!canControl||!marker.available;select.onchange=function(){applyLiveFeature('marker_mode',select.value).catch(function(err){showToast(err.message);refreshFeatureStatus();});};row.appendChild(select);root.appendChild(row);
  if(!canControl){const note=document.createElement('div');note.className='small-muted';note.textContent='Read-only mode: live feature changes are disabled.';root.appendChild(note);}
}
async function applyLiveFeature(feature,value){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const descriptions={DETECT_OBJECT:'Change object detection for live frames?',USE_BEV:'Change the bird’s-eye transform live? Re-check lane overlays before moving.',RECORD_VIDEO:'Change video recording state?',marker_mode:'Change the active sign/AprilTag detector?'};
  if(!confirm((descriptions[feature]||'Apply this live feature change?')+' This update is saved to the active mode config.'))return;
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const response=await nativeFetch('/api/features',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({feature:feature,value:value})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  const after=await readConfig();
  rememberUndo(before,after);
  currentConfig=after;showToast('Updated '+feature);noteWorkspaceEvent('info','Live feature changed: '+feature+'='+String(value));await refreshFeatureStatus();
}
async function refreshFeatureStatus(){
  try{
    const mode=await nativeFetch('/api/mode',{cache:'no-store'}).then(function(r){return r.json();});const f=mode.features||{},c=mode.capabilities||{};
    const features=await nativeFetch('/api/features',{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();});
    renderLiveFeatureControls(features);
    const rows=[
      ['Traffic lights',features.restart_required&&features.restart_required.TRAFFIC_LIGHTS_ENABLED],
      ['Confidence-aware speed',features.restart_required&&features.restart_required.CONFIDENCE_AWARE_ENABLED],
      ['Adaptive obstacle avoidance',features.restart_required&&features.restart_required.ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED],
      ['Encoder map',features.restart_required&&features.restart_required.ENCODER_MAP_ENABLED]
    ];
    const newline=String.fromCharCode(10);
    $('ext_feature_status').textContent=rows.map(function(r){const meta=r[1]||{};return r[0]+': '+(meta.enabled?'enabled':'disabled')+' — '+(meta.reason||'startup configuration');}).join(newline)+newline+newline+'Lane detector: '+(f.lane_detector||'unknown')+newline+'ML lane detector: '+String(!!f.ml_lane_detector)+newline+'Mode capabilities:'+newline+JSON.stringify(c,null,2);
    if(f.encoder_map){$('ext_encoder_embed').hidden=false;$('ext_encoder_status').textContent='Encoder odometry is active.';if(!$('ext_encoder_frame').src||!$('ext_encoder_frame').src.endsWith('/encoder-map'))$('ext_encoder_frame').src='/encoder-map';}
    else{$('ext_encoder_embed').hidden=true;$('ext_encoder_status').textContent='Encoder map is disabled (enable with --encoder-map and compatible firmware, then restart).';}
    const setStatusSectionVisible=function(element,visible){if(!element)return;element.style.display=visible?'':'none';if(element.previousElementSibling)element.previousElementSibling.style.display=visible?'':'none';};
    setStatusSectionVisible($('ext_traffic_status'),mode.mode==='city');
    setStatusSectionVisible($('ext_race_status'),mode.mode==='race');
    window.extActiveMode=mode.mode;
  }catch(err){$('ext_feature_status').textContent='Feature query failed: '+err.message;}
}
async function refreshTrafficAndRace(){
  const mode=window.extActiveMode;
  if(mode==='city'){
    try{
      const light=await nativeFetch('/api/traffic-lights',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.reason||j.message||('HTTP '+r.status));return j;});
      $('ext_traffic_status').textContent=JSON.stringify(light,null,2);
    }catch(err){$('ext_traffic_status').textContent='Traffic-light status unavailable: '+err.message;}
    return;
  }
  if(mode==='race'){
    try{
      const race=await nativeFetch('/api/race',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.reason||j.message||('HTTP '+r.status));return j;});
      $('ext_race_status').textContent=JSON.stringify(race,null,2);
    }catch(err){$('ext_race_status').textContent='Race lifecycle unavailable: '+err.message;}
  }
}
async function refreshCameraSettings(){
  try{
    const data=await nativeFetch('/api/camera/settings',{cache:'no-store'}).then(function(r){return r.json();});const c=data.camera||{};
    cameraSupportedControlNames=c.control_names||[];cameraSettingsEditable=!!c.supported;
    $('ext_camera_support').textContent=c.supported?'Picamera2 controls detected. Available controls: '+cameraSupportedControlNames.join(', '):'Not editable: '+(c.reason||'camera controls unavailable');
    const ranges=c.control_ranges||{};
    [['ExposureTime','ext_exposure'],['AnalogueGain','ext_gain']].forEach(function(pair){
      const range=ranges[pair[0]]||{},input=$(pair[1]);
      if(range.min!=null&&Number.isFinite(Number(range.min)))input.min=String(range.min);
      else input.removeAttribute('min');
      if(range.max!=null&&Number.isFinite(Number(range.max)))input.max=String(range.max);
      else input.removeAttribute('max');
      const step=pair[0]==='ExposureTime'?'100':'0.1';input.step=step;
      input.title=(range.min!=null||range.max!=null)?'Sensor limits: '+(range.min==null?'unreported':range.min)+' to '+(range.max==null?'unreported':range.max):'The API validates against sensor-supported limits';
    });
    const controls=c.controls||{};if(controls.ExposureTime!=null)$('ext_exposure').value=String(controls.ExposureTime);if(controls.AnalogueGain!=null)$('ext_gain').value=String(controls.AnalogueGain);
    $('ext_auto_exposure').checked=!!controls.AeEnable;$('ext_auto_wb').checked=!!controls.AwbEnable;
    updateCameraControlsEnabled();
  }catch(err){$('ext_camera_support').textContent='Camera capability read failed: '+err.message;}
}
function updateCameraControlsEnabled(){
  const writable=!!cameraSettingsEditable&&STREAM_CONTROL_ALLOWED;
  $('ext_exposure').disabled=!writable||$('ext_auto_exposure').checked||!cameraSupportedControlNames.includes('ExposureTime');
  $('ext_gain').disabled=!writable||$('ext_auto_exposure').checked||!cameraSupportedControlNames.includes('AnalogueGain');
  $('ext_auto_exposure').disabled=!writable||!cameraSupportedControlNames.includes('AeEnable');
  $('ext_auto_wb').disabled=!writable||!cameraSupportedControlNames.includes('AwbEnable');
  $('ext_apply_camera').disabled=!writable||!cameraSupportedControlNames.some(function(key){return ['ExposureTime','AnalogueGain','AeEnable','AwbEnable'].includes(key);});
}
async function refreshProcessingRate(){
  try{
    const data=await nativeFetch('/api/processing-rate',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
    if(data.target_fps!=null)$('ext_target_fps').value=String(data.target_fps);
    $('ext_fps_status').textContent=data.available?'Live · '+Number(data.target_fps).toFixed(1)+' FPS':'Unavailable';
    $('ext_target_fps').disabled=!data.available||!STREAM_CONTROL_ALLOWED;$('ext_apply_fps').disabled=!data.available||!STREAM_CONTROL_ALLOWED;
  }catch(err){$('ext_fps_status').textContent=err.message;}
}
async function refreshSafety(){
  try{const data=await nativeFetch('/api/safety',{cache:'no-store'}).then(function(r){return r.json();});
    $('ext_safety_state').textContent='Software stop: '+(data.software_stop_active?'ACTIVE':'inactive')+' · RUN_LVL='+data.run_level;
    $('ext_software_stop').disabled=!data.controls_enabled;$('ext_software_resume').disabled=!data.controls_enabled;
  }catch(err){$('ext_safety_state').textContent='Safety status read failed: '+err.message;}
}
async function refreshServerLogs(){
  const level=encodeURIComponent($('ext_log_level').value||'ALL'),q=encodeURIComponent($('ext_log_search').value||'');
  try{
    const data=await nativeFetch('/api/logs?limit=200&level='+level+'&q='+q,{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
    serverLogsVisible=data.items||[];$('ext_server_logs').textContent=serverLogsVisible.map(function(item){return new Date(item.timestamp*1000).toLocaleTimeString()+' '+item.level.padEnd(8)+' '+item.logger+' — '+item.message;}).join(String.fromCharCode(10))||'No matching in-memory runtime logs.';
  }catch(err){$('ext_server_logs').textContent='Log API unavailable: '+err.message;}
}
async function safetyAction(action){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  if(action==='stop'&&!confirm('Request the active Python mode loop to stop robot motion? This is software control, not a hardware E-stop.'))return;
  if(action==='resume'&&!confirm('Resume motion? Confirm the track is clear and the robot is safe to move.'))return;
  const data=await nativeFetch('/api/safety',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action})}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
  showToast(action==='stop'?'Software stop requested':'Motion resume requested');noteWorkspaceEvent(action==='stop'?'warn':'info','Dashboard software '+action+' requested');await refreshSafety();
}
async function applyProcessingRate(){
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const fps=Number($('ext_target_fps').value);const data=await nativeFetch('/api/processing-rate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_fps:fps})}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
  $('ext_fps_status').textContent='Saved · '+Number(data.target_fps).toFixed(1)+' FPS';currentConfig=await readConfig().catch(function(){return currentConfig;});rememberUndo(before,currentConfig);showToast('Processing-rate limit applied and saved');
}
async function applyCameraControls(){
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const payload={};
  if(cameraSupportedControlNames.includes('AeEnable')){
    payload.AeEnable=!!$('ext_auto_exposure').checked;
  }
  if(cameraSupportedControlNames.includes('AwbEnable')){
    payload.AwbEnable=!!$('ext_auto_wb').checked;
  }
  if(!$('ext_auto_exposure').checked){
    if(cameraSupportedControlNames.includes('ExposureTime'))payload.ExposureTime=Number($('ext_exposure').value);
    if(cameraSupportedControlNames.includes('AnalogueGain'))payload.AnalogueGain=Number($('ext_gain').value);
  }
  if(!Object.keys(payload).length)throw new Error('This camera does not expose any supported runtime controls.');
  const response=await nativeFetch('/api/camera/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));await refreshCameraSettings();currentConfig=await readConfig().catch(function(){return currentConfig;});rememberUndo(before,currentConfig);showToast('Runtime camera controls applied');
}
function buildCommandPalette(){
  const commands=[
    ['Export full configuration','export','Ctrl+Shift+E'],['Import full configuration','import',''],['Undo','undo','Ctrl+Z'],['Redo','redo','Ctrl+Y'],
    ['Fit camera frame','fit','0'],['Toggle ROI overlays','overlays','O'],['Toggle grid','grid','G'],['Toggle crosshair','crosshair','X'],
    ['Use annotation tool','annotate','N'],['Use pixel ruler','ruler','R'],['Draw rectangle ROI preview','roi_rect',''],['Draw trapezoid ROI preview','roi_trapezoid',''],
    ['Save workspace layout','workspace',''],['Save workspace profile','profile',''],['Save configuration preset','preset',''],
    ['Capture frame snapshot','snapshot',''],['Refresh runtime diagnostics','health',''],['Refresh server logs','logs',''],
    ['Open encoder map','encoder',''],['Open camera controls','camera',''],['Request software stop','stop',''],['Resume motion (confirmation)','resume','']
  ];
  const list=$('ext_command_list');list.replaceChildren();
  commands.forEach(function(entry){const b=document.createElement('button');b.type='button';b.dataset.command=entry[1];b.textContent=entry[0]+(entry[2]?' · '+entry[2]:'');b.onclick=function(){closeCommandPalette();executeCommand(entry[1]);};list.appendChild(b);});
  $('ext_command_search').addEventListener('input',function(){const q=this.value.toLowerCase();list.querySelectorAll('button').forEach(function(b){b.hidden=!b.textContent.toLowerCase().includes(q);});});
}
function openCommandPalette(){const m=$('ext_command_palette');m.style.display='flex';$('ext_command_search').value='';$('ext_command_search').focus();$('ext_command_search').dispatchEvent(new Event('input'));}
function closeCommandPalette(){$('ext_command_palette').style.display='none';}
function executeCommand(name){
  const actions={
    export:exportFullConfig,import:function(){$('ext_config_file').click();},undo:doUndo,redo:doRedo,
    fit:function(){fitWorkspaceView();},overlays:function(){$('ext_overlays').click();},grid:function(){$('ext_grid').click();},crosshair:function(){$('ext_crosshair').click();},
    annotate:function(){setEditorTool('annotate');},ruler:function(){$('ext_ruler').click();},
    roi_rect:function(){setEditorTool('roi_rect');},roi_trapezoid:function(){setEditorTool('roi_trapezoid');},
    snapshot:addFrameSnapshot,workspace:function(){saveWorkspace().then(function(){showToast('Workspace saved');}).catch(function(e){showToast(e.message);});},
    profile:function(){$('ext_editor_panel').open=true;$('ext_profile_name').focus();},
    preset:function(){$('ext_config_panel').open=true;$('ext_preset_name').focus();},
    health:function(){refreshRuntime().then(function(){showToast('Runtime diagnostics refreshed');});},
    logs:refreshServerLogs,
    camera:function(){$('ext_camera_panel').open=true;$('ext_camera_panel').scrollIntoView({behavior:'smooth',block:'nearest'});},
    encoder:function(){if($('ext_encoder_embed').hidden)showToast('Encoder map requires --encoder-map and compatible firmware restart.');else $('ext_encoder_frame').scrollIntoView({behavior:'smooth'});},
    stop:function(){safetyAction('stop').catch(function(e){showToast(e.message);});},
    resume:function(){safetyAction('resume').catch(function(e){showToast(e.message);});}
  };
  if(actions[name])Promise.resolve(actions[name]()).catch(function(err){showToast(err.message||String(err));});
}
function enableReadOnlyState(){
  if(STREAM_CONTROL_ALLOWED)return;
  ['ext_export_config','ext_import_config','ext_undo','ext_redo','ext_preset_save','ext_preset_apply','ext_preset_delete','ext_history_restore','ext_profile_save','ext_profile_delete','ext_apply_fps','ext_apply_camera','ext_software_stop','ext_software_resume','ext_save_workspace'].forEach(function(id){if($(id))$(id).disabled=true;});
}
function initializeResize(){
  const container=document.querySelector('.container'),panel=document.querySelector('.right-panel');if(!container||!panel)return;
  let active=false,startX=0,startWidth=315;
  panel.addEventListener('pointerdown',function(e){const bounds=panel.getBoundingClientRect();if(e.clientX-bounds.left>7||window.innerWidth<721)return;active=true;startX=e.clientX;startWidth=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||bounds.width;panel.setPointerCapture(e.pointerId);e.preventDefault();});
  panel.addEventListener('pointermove',function(e){if(!active)return;const delta=startX-e.clientX;const width=Math.max(250,Math.min(700,startWidth+delta));container.style.setProperty('--right-pane-width',width+'px');});
  panel.addEventListener('pointerup',function(){if(!active)return;active=false;scheduleWorkspaceSave();});
  panel.addEventListener('pointercancel',function(){active=false;});
}
function installExtension(){
  const stage=$('canvas_stage');if(stage&&canvas){
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.id='ext_precision_overlay';svg.setAttribute('aria-hidden','true');stage.appendChild(svg);
    canvas.addEventListener('pointerdown',onCustomPointerDown,true);
    canvas.addEventListener('pointermove',function(e){const rect=canvas.getBoundingClientRect();const x=(e.clientX-rect.left)*(canvas.width/rect.width),y=(e.clientY-rect.top)*(canvas.height/rect.height);extCrosshairPoint={x:x,y:y};if(extCrosshair)drawPrecisionOverlay();});
  }
  if($('ext_export_annotations'))$('ext_export_annotations').onclick=function(){downloadText(JSON.stringify(extAnnotations,null,2),'roboy-annotations.json','application/json');};
  $('ext_grid').addEventListener('change',function(){extGrid=this.checked;drawPrecisionOverlay();scheduleWorkspaceSave();});
  $('ext_snap').addEventListener('change',function(){extSnap=this.checked;scheduleWorkspaceSave();});
  $('ext_crosshair').addEventListener('change',function(){extCrosshair=this.checked;drawPrecisionOverlay();scheduleWorkspaceSave();});
  $('ext_overlays').addEventListener('change',function(){showRectsCheckbox.checked=this.checked;renderWorkspaceCanvas();scheduleWorkspaceSave();});
  showRectsCheckbox.addEventListener('change',function(){if($('ext_overlays'))$('ext_overlays').checked=this.checked;});
  $('ext_annotate_btn').onclick=function(){setEditorTool(editorTool==='annotate'?'select':'annotate');};
  $('ext_ruler').addEventListener('change',function(){setEditorTool(this.checked?'ruler':'select');});
  $('ext_roi_rect_tool').onclick=function(){setEditorTool(editorTool==='roi_rect'?'select':'roi_rect');};
  $('ext_roi_trapezoid_tool').onclick=function(){setEditorTool(editorTool==='roi_trapezoid'?'select':'roi_trapezoid');};
  $('ext_roi_top_factor').addEventListener('input',function(){$('ext_roi_top_factor_label').textContent=Math.round(Number(this.value)*100)+'%';});
  $('ext_clear_annotations').onclick=function(){if(!extAnnotations.length)return;if(confirm('Clear all custom annotations from the workspace?')){extAnnotations=[];refreshAnnotationList();syncLayerControls();drawPrecisionOverlay();scheduleWorkspaceSave();}};
  $('ext_save_workspace').onclick=function(){saveWorkspace().then(function(){showToast('Workspace layout saved');}).catch(function(err){showToast(err.message);});};
  $('ext_capture_frame').onclick=addFrameSnapshot;$('ext_clear_gallery').onclick=function(){extFrameGallery=[];renderFrameGallery();};
  $('ext_profile_save').onclick=function(){profileAction('save').catch(function(e){showToast(e.message);});};$('ext_profile_load').onclick=function(){profileAction('load').catch(function(e){showToast(e.message);});};$('ext_profile_delete').onclick=function(){profileAction('delete').catch(function(e){showToast(e.message);});};
  $('ext_export_config').onclick=function(){exportFullConfig().catch(function(e){showToast(e.message);});};
  $('ext_import_config').onclick=function(){$('ext_config_file').click();};$('ext_config_file').addEventListener('change',function(){if(this.files&&this.files[0])importFullConfigFile(this.files[0]);this.value='';});
  $('ext_undo').onclick=doUndo;$('ext_redo').onclick=doRedo;
  $('ext_preset_save').onclick=function(){presetAction('save').then(refreshHistory).catch(function(e){showToast(e.message);});};
  $('ext_preset_apply').onclick=function(){presetAction('apply').catch(function(e){showToast(e.message);});};
  $('ext_preset_delete').onclick=function(){presetAction('delete').catch(function(e){showToast(e.message);});};
  $('ext_compare_preset').onclick=function(){comparePreset().catch(function(e){showToast(e.message);});};$('ext_history_refresh').onclick=function(){refreshHistory().catch(function(e){showToast(e.message);});};$('ext_history_restore').onclick=function(){restoreHistory().catch(function(e){showToast(e.message);});};
  $('ext_apply_fps').onclick=function(){applyProcessingRate().catch(function(e){showToast(e.message);});};$('ext_apply_camera').onclick=function(){applyCameraControls().catch(function(e){showToast(e.message);});};
  $('ext_software_stop').onclick=function(){safetyAction('stop').catch(function(e){showToast(e.message);});};$('ext_software_resume').onclick=function(){safetyAction('resume').catch(function(e){showToast(e.message);});};
  $('ext_auto_exposure').addEventListener('change',updateCameraControlsEnabled);
  $('ext_log_refresh').onclick=function(){refreshServerLogs();};$('ext_log_level').addEventListener('change',refreshServerLogs);$('ext_log_search').addEventListener('input',function(){clearTimeout(window.extLogDebounce);window.extLogDebounce=setTimeout(refreshServerLogs,250);});
  $('console_filter').addEventListener('input',function(){workspaceConsoleQuery=this.value;renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');});
  $('console_level').addEventListener('change',function(){workspaceConsoleLevel=this.value;renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');});
  $('console_pause').addEventListener('change',function(){workspaceConsolePaused=this.checked;if(!workspaceConsolePaused){renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');}});
  $('console_autoscroll').addEventListener('change',function(){workspaceConsoleAutoScroll=this.checked;if(workspaceConsoleAutoScroll){renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');}});
  $('console_export_btn').onclick=function(){downloadText(JSON.stringify({exported_at:new Date().toISOString(),events:workspaceEvents.map(function(e){return {time:e.time instanceof Date?e.time.toISOString():e.time,level:e.level,message:e.message};}),requests:workspaceApiEvents.map(function(e){return {time:e.time instanceof Date?e.time.toISOString():e.time,level:e.level,message:e.message};})},null,2),'roboy-workspace-console.json','application/json');};
  $('ext_log_export').onclick=function(){downloadText(JSON.stringify(serverLogsVisible,null,2),'roboy-runtime-logs.json','application/json');};
  $('ext_export_annotations').onclick=function(){downloadText(JSON.stringify(extAnnotations,null,2),'roboy-'+String('{{ mode }}').toLowerCase()+'-annotations.json','application/json');};
  $('ext_open_palette').onclick=openCommandPalette;
  $('ext_encoder_reset').onclick=async function(){if(!confirm('Reset only the displayed odometry origin? Hardware counters will not be reset.'))return;const r=await nativeFetch('/api/encoder-map/reset-origin',{method:'POST'});const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));showToast('Displayed odometry origin reset');};
  $('ext_frame_compare_close').onclick=function(){$('ext_frame_compare').style.display='none';};
  $('ext_frame_compare').addEventListener('click',function(e){if(e.target===this)this.style.display='none';});
  $('ext_command_palette').addEventListener('click',function(e){if(e.target===this)closeCommandPalette();});buildCommandPalette();initializeResize();enableReadOnlyState();
  document.addEventListener('keydown',function(e){
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openCommandPalette();return;}
    if($('ext_command_palette').style.display==='flex'&&e.key==='Escape'){closeCommandPalette();return;}
    if(e.target&&(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)||e.target.isContentEditable))return;
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();doUndo();return;}
    if((e.ctrlKey||e.metaKey)&&(e.key.toLowerCase()==='y'||(e.shiftKey&&e.key.toLowerCase()==='z'))){e.preventDefault();doRedo();return;}
    if(!e.ctrlKey&&!e.metaKey&&!e.altKey){
      if(e.key.toLowerCase()==='g')$('ext_grid').click();
      else if(e.key.toLowerCase()==='x')$('ext_crosshair').click();
      else if(e.key.toLowerCase()==='n')setEditorTool('annotate');
      else if(e.key.toLowerCase()==='r'){$('ext_ruler').checked=!$('ext_ruler').checked;$('ext_ruler').dispatchEvent(new Event('change'));}
    }
  });
  document.querySelectorAll('.right-panel details.dock-panel').forEach(function(panel){panel.addEventListener('toggle',scheduleWorkspaceSave);});
  window.addEventListener('resize',drawPrecisionOverlay);
}
async function initializeExtension(){
  try{currentConfig=await readConfig();if(currentConfig.ui&&currentConfig.ui.opacity)ui.opacity=currentConfig.ui.opacity;}catch(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Extended config API unavailable: '+err.message);}
  syncLayerControls();syncLegacyLayerControls();installExtension();refreshAnnotationList();drawPrecisionOverlay();
  refreshWorkspaceProfiles().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Workspace load failed: '+err.message);});
  refreshPresets().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Preset list failed: '+err.message);});
  refreshHistory().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','History read failed: '+err.message);});
  refreshRuntime();refreshFeatureStatus();refreshTrafficAndRace();refreshCameraSettings();refreshProcessingRate();refreshSafety();refreshServerLogs();
  extHealthTimer=setInterval(function(){refreshRuntime();refreshTrafficAndRace();refreshSafety();},1800);
  setInterval(function(){refreshCameraSettings();refreshProcessingRate();},8000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initializeExtension,{once:true});else initializeExtension();
})();
</script>

<div id="ext_frame_compare" style="display:none;position:fixed;inset:0;z-index:99990;background:rgba(0,0,0,.82);align-items:center;justify-content:center;padding:18px">
  <div style="width:min(1000px,96vw);max-height:92vh;overflow:auto;background:#0b1420;border:1px solid var(--border);border-radius:8px;padding:12px">
    <div style="display:flex;gap:10px;align-items:center"><strong id="ext_frame_compare_title">Frame comparison</strong><span style="flex:1"></span><button type="button" class="ghost" id="ext_frame_compare_close">Close</button></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px"><div><div class="small-muted">Saved snapshot</div><img id="ext_compare_old" alt="Saved frame" style="width:100%;background:#02070c"></div><div><div class="small-muted">Current frame</div><img id="ext_compare_live" alt="Current frame" style="width:100%;background:#02070c"></div></div>
  </div>
</div>
<div id="ext_command_palette"><div class="palette-box"><div style="display:flex;align-items:center;gap:8px;margin-bottom:5px"><strong>Command Palette</strong><span class="small-muted">Ctrl+K · Esc to close</span></div><input type="search" id="ext_command_search" placeholder="Search tools, commands, shortcuts…"><div id="ext_command_list"></div></div></div>

</body>
</html>
"""
