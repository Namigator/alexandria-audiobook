(() => {
 const box=document.createElement('section');
 box.id='conversion-live-status';box.hidden=true;
 box.setAttribute('aria-live','polite');
 box.style.cssText='position:sticky;top:0;z-index:1040;background:#eff6ff;color:#172554;border-bottom:2px solid #2563eb;padding:12px 16px;font:14px system-ui;box-shadow:0 2px 6px #0002';
 const title=document.createElement('strong');title.textContent='Audiobook conversion — conversion starting';
 const detail=document.createElement('div');detail.style.cssText='margin:4px 0';
 const progress=document.createElement('progress');progress.max=100;progress.style.cssText='width:100%;height:16px;accent-color:#2563eb';
 const note=document.createElement('div');note.style.cssText='font-size:12px;margin-top:4px';note.textContent='Script preparation → voice generation → MP3 export. Runs while this page is closed.';
 box.append(title,detail,progress,note);document.body.prepend(box);
 async function update(){
  try{
   const response=await fetch('/static/conversion-status.json?t='+Date.now(),{cache:'no-store'});
   if(response.status===404){box.hidden=true;return;}
   if(!response.ok)throw new Error('Progress unavailable');
   const status=await response.json();box.hidden=false;
   title.textContent='Audiobook conversion — '+status.phase;
   detail.textContent=status.message;
   const terminal=/Complete$|Paused$|Needs attention$/.test(status.phase);
   const stale=!terminal && Date.now()/1000-status.updated>45;
   if(stale){detail.textContent+=' · Progress connection interrupted';progress.removeAttribute('value');}
   else if(status.total>0){progress.value=100*status.completed/status.total;}
   else progress.removeAttribute('value');
   box.style.background=status.phase==='Needs attention'?'#fff1f2':status.phase==='Complete'?'#ecfdf5':'#eff6ff';
  }catch(error){detail.textContent='Progress connection unavailable — check that Alexandria is running';progress.removeAttribute('value');}
 }
 update();setInterval(update,3000);
})();
