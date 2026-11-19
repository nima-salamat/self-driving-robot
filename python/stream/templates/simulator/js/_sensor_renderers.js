function drawLidar(points){
  const canvas=$("lidar-view"); if(!canvas) return;
  const ctx=canvas.getContext("2d"),w=canvas.width,h=canvas.height;
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#081018";ctx.fillRect(0,0,w,h);
  const maxRange=Math.max(1,Number(($("lidar-range")||{}).value)||50);
  const scale=Math.min((w-42)/(2*maxRange),(h-42)/(2*maxRange));
  const cx=w/2,cy=h/2;
  ctx.lineWidth=1;ctx.strokeStyle="#26394a";
  for(let x=0;x<=w;x+=Math.max(36,Math.round(w/12))){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}
  for(let y=0;y<=h;y+=Math.max(28,Math.round(h/8))){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  for(let r=5;r<=maxRange;r+=5){
    ctx.beginPath();ctx.arc(cx,cy,r*scale,0,Math.PI*2);ctx.strokeStyle="#334858";ctx.stroke();
    ctx.fillStyle="#7d93a7";ctx.font="10px ui-monospace,monospace";
    ctx.fillText(r+" m",cx+4,cy-r*scale+11);
  }
  ctx.strokeStyle="#71879b";ctx.setLineDash([4,5]);
  ctx.beginPath();ctx.moveTo(cx,8);ctx.lineTo(cx,h-8);ctx.moveTo(8,cy);ctx.lineTo(w-8,cy);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle="#b4c6d7";ctx.font="11px system-ui";ctx.fillText("FRONT ↑",cx+7,13);
  let visible=0;
  (points||[]).forEach(function(p){
    if(!Array.isArray(p)||p.length<2)return;
    const fx=Number(p[0]),lat=Number(p[1]);
    if(!Number.isFinite(fx)||!Number.isFinite(lat))return;
    const x=cx+lat*scale,y=cy-fx*scale;
    if(x<3||x>w-3||y<3||y>h-3)return;
    const distance=Math.hypot(fx,lat);
    ctx.fillStyle=distance<8?"#ff8178":distance<20?"#ffd079":"#75d6ff";
    ctx.fillRect(x,y,2.5,2.5);visible++;
  });
  ctx.save();ctx.translate(cx,cy);ctx.fillStyle="#e7f4ff";ctx.strokeStyle="#79cbff";ctx.lineWidth=1.5;
  ctx.beginPath();ctx.moveTo(0,-12);ctx.lineTo(10,8);ctx.lineTo(0,4);ctx.lineTo(-10,8);ctx.closePath();ctx.fill();ctx.stroke();ctx.restore();
  setText("lidar-note","360° top-down cloud · "+visible+" displayed points · near points red, medium range amber, farther points cyan. Diagram scale: 0–1500 cm; rings are 250 cm apart.");
}
function avisRangeStatus(value,threshold,key){
  if(value===null||value===undefined||!Number.isFinite(Number(value))||Number(value)<0)return "No valid reading";
  const distance=Number(value);
  if(threshold>0&&distance<=threshold)return key==="front"?"Front brake threshold reached":"Within threshold · monitor only";
  if(threshold>0&&distance<=Math.max(threshold*1.5,threshold+10))return "Near configured threshold";
  return "Range available";
}
function avisRangeColor(value,threshold,key){
  if(value===null||value===undefined||!Number.isFinite(Number(value))||Number(value)<0)return "#7d8b9b";
  const distance=Number(value);
  if(threshold>0&&distance<=threshold)return key==="front"?"#ff8178":"#ffd079";
  if(threshold>0&&distance<=Math.max(threshold*1.5,threshold+10))return "#ffd079";
  return "#75d6ff";
}
function drawAvisSensors(ranges,stale){
  const canvas=$("avis-sensor-view");if(!canvas)return;
  const ctx=canvas.getContext("2d"),w=canvas.width,h=canvas.height;
  ctx.clearRect(0,0,w,h);
  const background=ctx.createLinearGradient(0,0,w,h);
  background.addColorStop(0,"#102131");background.addColorStop(.52,"#0b1723");background.addColorStop(1,"#09121b");
  ctx.fillStyle=background;ctx.fillRect(0,0,w,h);
  // Low-contrast technical grid.
  ctx.strokeStyle="#213448";ctx.lineWidth=1;
  for(let x=18;x<w;x+=36){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}
  for(let y=18;y<h;y+=36){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}

  const maxRange=1500,cx=w/2,carY=h*.79,frontY=carY-76;
  const scale=Math.min((w*.40)/maxRange,(h*.60)/maxRange);
  const configuredAngle=Number(($("avis-angle")||{}).value);
  const sideAngle=Number.isFinite(configuredAngle)?Math.max(0,Math.min(90,configuredAngle)):30;
  const threshold=Math.max(0,Number(($("obstacle-stop-distance")||{}).value)||0);

  // Semicircular distance bands use the same 0–1500 cm scale as the sensor values.
  for(let distance=250;distance<=maxRange;distance+=250){
    const radius=distance*scale;
    ctx.beginPath();ctx.arc(cx,frontY,radius,Math.PI,Math.PI*2);
    ctx.strokeStyle=stale?"#2b3947":"#294459";ctx.lineWidth=distance===maxRange?1.5:1;
    ctx.setLineDash(distance===maxRange?[4,5]:[]);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle="#7e98ae";ctx.font="10px ui-monospace,Consolas,monospace";ctx.textAlign="left";
    ctx.fillText(distance+" cm",cx+7,frontY-radius+13);
  }
  ctx.fillStyle="#9bb4c9";ctx.font="700 10px ui-monospace,Consolas,monospace";ctx.textAlign="center";
  ctx.fillText("FRONT  ↑",cx,17);

  const sensors=[
    {key:"left",label:"LEFT",x:cx-24,y:frontY+4,angle:-sideAngle},
    {key:"front",label:"FRONT",x:cx,y:frontY-8,angle:0},
    {key:"right",label:"RIGHT",x:cx+24,y:frontY+4,angle:sideAngle}
  ];
  sensors.forEach(function(sensor){
    const raw=ranges&&ranges[sensor.key]!==undefined?ranges[sensor.key]:null;
    const valid=raw!==null&&raw!==undefined&&Number.isFinite(Number(raw))&&Number(raw)>=0;
    const measured=valid?Number(raw):null;
    const distance=valid?Math.min(maxRange,measured):95;
    const theta=sensor.angle*Math.PI/180,spread=5.5*Math.PI/180;
    const radius=distance*scale,ex=sensor.x+Math.sin(theta)*radius,ey=sensor.y-Math.cos(theta)*radius;
    let color=stale?"#75889a":avisRangeColor(raw,threshold,sensor.key);
    // Soft field-of-view cone behind the measurement ray.
    if(valid){
      ctx.save();ctx.globalAlpha=stale ? 0.035 : 0.10;ctx.fillStyle=color;ctx.beginPath();
      ctx.moveTo(sensor.x,sensor.y);ctx.arc(sensor.x,sensor.y,radius,theta-Math.PI/2-spread,theta-Math.PI/2+spread);ctx.closePath();ctx.fill();ctx.restore();
    }
    ctx.save();ctx.strokeStyle=color;ctx.lineWidth=valid?2.5:1.6;ctx.setLineDash(valid?[]:[5,5]);
    ctx.beginPath();ctx.moveTo(sensor.x,sensor.y);ctx.lineTo(ex,ey);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle=color;ctx.beginPath();ctx.arc(sensor.x,sensor.y,4.2,0,Math.PI*2);ctx.fill();
    if(valid){
      ctx.beginPath();ctx.arc(ex,ey,4,0,Math.PI*2);ctx.fill();
      const label=(stale?"STALE · ":"")+(measured>maxRange?">1500":numeric(measured,0))+" cm";
      ctx.font="700 11px ui-monospace,Consolas,monospace";
      const width=ctx.measureText(label).width+16;
      let lx=Math.max(8,Math.min(w-width-8,ex-width/2));
      let ly=Math.max(28,Math.min(h-22,ey-27));
      ctx.fillStyle="#08131ee8";ctx.strokeStyle=color;ctx.lineWidth=1;
      ctx.beginPath();ctx.roundRect(lx,ly,width,21,7);ctx.fill();ctx.stroke();
      ctx.fillStyle=stale?"#9aabba":color;ctx.textAlign="center";ctx.fillText(label,lx+width/2,ly+14);
    }else{
      ctx.font="700 10px ui-monospace,Consolas,monospace";ctx.fillStyle="#8497a8";ctx.textAlign="center";
      ctx.fillText("NO ECHO",sensor.x+(sensor.key==="left"?-28:sensor.key==="right"?28:0),sensor.y-16);
    }
    ctx.restore();
  });

  // Vehicle silhouette: body, roof glass, tyres, bumpers and lamps.
  ctx.save();ctx.translate(cx,carY);
  ctx.shadowColor="#000b";ctx.shadowBlur=22;ctx.shadowOffsetY=8;
  const body=ctx.createLinearGradient(-35,-70,35,70);
  body.addColorStop(0,"#9bc4dd");body.addColorStop(.22,"#4b7895");body.addColorStop(.58,"#24435a");body.addColorStop(1,"#172b3d");
  ctx.fillStyle=body;ctx.strokeStyle="#9dd9f2";ctx.lineWidth=2;
  ctx.beginPath();ctx.moveTo(-22,66);ctx.quadraticCurveTo(-34,64,-34,48);ctx.lineTo(-31,-35);
  ctx.quadraticCurveTo(-29,-62,-17,-72);ctx.quadraticCurveTo(0,-78,17,-72);
  ctx.quadraticCurveTo(29,-62,31,-35);ctx.lineTo(34,48);ctx.quadraticCurveTo(34,64,22,66);ctx.closePath();ctx.fill();ctx.stroke();
  ctx.shadowColor="transparent";ctx.shadowBlur=0;ctx.shadowOffsetY=0;
  // Four tyres with subtle highlights.
  [[-34,-43],[26,-43],[-34,30],[26,30]].forEach(function(point){
    ctx.fillStyle="#050a10";ctx.strokeStyle="#506b80";ctx.lineWidth=1;
    ctx.beginPath();ctx.roundRect(point[0],point[1],8,21,3);ctx.fill();ctx.stroke();
    ctx.fillStyle="#263c4d";ctx.fillRect(point[0]+2,point[1]+3,4,15);
  });
  // Panoramic windscreen and rear glass.
  ctx.fillStyle="#142b3d";ctx.strokeStyle="#80b4d0";ctx.lineWidth=1.2;
  ctx.beginPath();ctx.moveTo(-23,-42);ctx.quadraticCurveTo(-20,-55,-13,-58);ctx.lineTo(13,-58);
  ctx.quadraticCurveTo(20,-55,23,-42);ctx.lineTo(19,-18);ctx.quadraticCurveTo(0,-12,-19,-18);ctx.closePath();ctx.fill();ctx.stroke();
  ctx.fillStyle="#1c3548";ctx.beginPath();ctx.moveTo(-19,5);ctx.lineTo(19,5);ctx.lineTo(17,31);
  ctx.quadraticCurveTo(0,37,-17,31);ctx.closePath();ctx.fill();ctx.stroke();
  ctx.strokeStyle="#789db4";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(-19,-9);ctx.lineTo(19,-9);ctx.stroke();
  // Lamps and front emblem.
  ctx.fillStyle="#bfeeff";ctx.shadowColor="#80dfff";ctx.shadowBlur=8;
  ctx.beginPath();ctx.roundRect(-23,-68,10,4,2);ctx.roundRect(13,-68,10,4,2);ctx.fill();
  ctx.shadowBlur=0;ctx.fillStyle="#d7efff";ctx.font="800 9px system-ui";ctx.textAlign="center";
  ctx.fillText("AVIS",0,-1);
  ctx.restore();

  setText("avis-angle-hint","SIDE ANGLE · ±"+numeric(sideAngle,0)+"°");
}
function renderRanges(ranges,frameAgeMs){
  const threshold=Math.max(0,Number(($("obstacle-stop-distance")||{}).value)||0);
  const age=Number(frameAgeMs),ageKnown=frameAgeMs!==null&&frameAgeMs!==undefined&&Number.isFinite(age),hasAnyValue=["left","front","right"].some(function(key){const v=ranges&&ranges[key];return v!==null&&v!==undefined&&Number.isFinite(Number(v))&&Number(v)>=0;}),stale=ageKnown?age>1500:hasAnyValue;
  let valid=0,nearest=null,stopCount=0;
  ["left","front","right"].forEach(function(key){
    const raw=ranges&&ranges[key]!==undefined?ranges[key]:null;
    const good=raw!==null&&raw!==undefined&&Number.isFinite(Number(raw))&&Number(raw)>=0;
    const value=good?Number(raw):null;
    if(good){valid++;nearest=nearest===null?value:Math.min(nearest,value);if(key==="front"&&threshold>0&&value<=threshold)stopCount++;}
    const valueEl=$("range-"+key);
    if(valueEl)valueEl.innerHTML=good?numeric(value,0)+' <span class="unit">cm</span>':'— <span class="unit">cm</span>';
    const bar=$("bar-"+key);
    if(bar){bar.style.width=good?Math.max(0,Math.min(100,value/1500*100))+"%":"0%";bar.style.background=stale?"#7d8b9b":avisRangeColor(value,threshold,key);}
    setText("range-"+key+"-state",stale?"Stale sample":avisRangeStatus(value,threshold,key));
  });
  drawAvisSensors(ranges,stale);
  if(stale){
    setText("avis-sensor-state","Stale · last sample");$("avis-sensor-state").className="pill";
    setText("avis-sensor-note","STALE SAMPLE · last reading "+(Number.isFinite(age)?numeric(age,0)+" ms ago":"not timestamped")+" · values are shown for reference only.");
  }else if(valid===0){
    setText("avis-sensor-state","No valid readings");$("avis-sensor-state").className="pill";
    setText("avis-sensor-note","NO VALID READINGS · unavailable sensors remain marked unknown, never treated as zero.");
  }else if(stopCount){
    setText("avis-sensor-state","Front at threshold");$("avis-sensor-state").className="pill";
    setText("avis-sensor-note","FRONT STOP THRESHOLD · front reading is at or below the configured brake distance.");
  }else{
    setText("avis-sensor-state",valid+"/3 sensors live");$("avis-sensor-state").className="pill live";
    setText("avis-sensor-note","LIVE SAMPLE · nearest measured range "+numeric(nearest,0)+" cm · rays indicate range, not object shape.");
  }
}
function renderEvents(events){
  const consoleEl=$("event-console"); if(!consoleEl)return;
  const valid=(events||[]).slice(-60), fresh=[];
  valid.forEach(function(event){
    const key=String(event.timestamp)+"|"+String(event.level)+"|"+String(event.message);
    if(!seenEvents.has(key)){seenEvents.add(key);fresh.push(event);}
  });
  if(!eventKeys.length) consoleEl.replaceChildren();
  fresh.forEach(function(event){
    const row=document.createElement("div");row.className="event "+String(event.level||"INFO").toUpperCase();
    const t=document.createElement("time");t.textContent=new Date(Number(event.timestamp)*1000).toLocaleTimeString();
    const m=document.createElement("span");m.className="event-msg";m.textContent=event.message||"";
    row.append(t,m);consoleEl.append(row);eventKeys.push(row);
  });
  while(eventKeys.length>100){const old=eventKeys.shift();if(old.parentNode)old.parentNode.removeChild(old);}
  if(!eventKeys.length)consoleEl.textContent="No actuator events yet.";
  consoleEl.scrollTop=consoleEl.scrollHeight;
}
