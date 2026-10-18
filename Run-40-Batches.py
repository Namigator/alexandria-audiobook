import json,sys,time,os,hashlib,threading,traceback,shutil
from pathlib import Path
for _stream in (sys.stdout,sys.stderr):
 if hasattr(_stream,'reconfigure'):_stream.reconfigure(encoding='utf-8',errors='replace')
if os.name=='nt':
 os.environ.setdefault('HF_HOME',r'F:\Codex\cache\huggingface');os.environ.setdefault('TORCH_HOME',r'F:\Codex\cache\torch')
 os.environ['TEMP']=r'F:\Codex\temp';os.environ['TMP']=r'F:\Codex\temp'
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'app'))
from utils import atomic_json_write
import requests
JOB=Path(os.environ.get('ALEXANDRIA_TRIAL_DIR',str(ROOT/'forty-batch-trial'))).resolve();JOB.relative_to(ROOT);JOB.mkdir(exist_ok=True)
STATE=JOB/'status.json';BANNER=ROOT/'app/static/conversion-status.json'
SPECS=[('short',0,160,16,8,.86),('medium',161,400,16,4,.48),('long',401,800,6,2,.30),('very_long',801,100000,2,1,.14)]
def bucket(chunk):
 length=len(chunk['text'])
 return next(name for name,lo,hi,n,size,rt in SPECS if lo<=length<=hi)
def read_chunks():return json.loads((ROOT/'chunks.json').read_text(encoding='utf-8'))
def words(items):return sum(len(x['text'].split()) for x in items)
def save(data,path):atomic_json_write(data,str(path),max_retries=8)
from importlib.util import spec_from_file_location,module_from_spec
_audit_spec=spec_from_file_location('checkpoint_conversion',ROOT/'Checkpoint-Conversion.py');_audit_module=module_from_spec(_audit_spec);_audit_spec.loader.exec_module(_audit_module)
chunks,_protected_audio=_audit_module.audit(ROOT)
_manifest=json.loads((ROOT/'recovery-manifest.json').read_text(encoding='utf-8'))
assert hashlib.sha256((ROOT/'annotated_script.json').read_bytes()).hexdigest()==_manifest['script_sha256'],'Saved script changed; inspect before resuming'
pending=[(i,c) for i,c in enumerate(chunks) if c['status']!='done']
if not (JOB/'plan.json').exists():
 pools={};summary=[]
 for name,lo,hi,n,size,rt in SPECS:
  pool=sorted([(i,c) for i,c in pending if lo<=len(c['text'])<=hi],key=lambda pair:len(pair[1]['text']))
  count=n*size;assert len(pool)>=count,(name,len(pool),count)
  chosen=[pool[min(len(pool)-1,int((j+.5)*len(pool)/count))][0] for j in range(count)]
  assert len(set(chosen))==count
  pools[name]=[dict(bucket=name,indices=chosen[j:j+size]) for j in range(0,count,size)]
  selected=[chunks[i] for i in chosen];summary.append(dict(bucket=name,batches=n,segments=count,words=words(selected),estimated_minutes=words(selected)*.4/rt/60,max_chars=max(len(c['text']) for c in selected)))
 plan=[]
 for row in range(16):
  for name,*rest in SPECS:
   if row<len(pools[name]):plan.append(pools[name][row])
 assert len(plan)==40 and len({i for b in plan for i in b['indices']})==sum(len(b['indices']) for b in plan)
 save(dict(created=time.time(),batches=plan,summary=summary),JOB/'plan.json')
plan=json.loads((JOB/'plan.json').read_text())
if '--plan-only' in sys.argv:
 print(json.dumps(plan['summary'],indent=2));print('Selected segments:',sum(len(b['indices']) for b in plan['batches']));print('Estimated trial minutes:',round(sum(r['estimated_minutes'] for r in plan['summary']),1));sys.exit(0)
assert not requests.get('http://127.0.0.1:4200/api/status/audio',timeout=20).json()['running'],'Another audio job is active'
lock=JOB/'active.lock';fd=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
for name in ['chunks.json','annotated_script.json','voice_config.json']:
 target=JOB/('before-'+name)
 if not target.exists():shutil.copy2(ROOT/name,target)
if not (JOB/'original-audio-sha256.json').exists():
 protected={c['audio_path']:hashlib.sha256((ROOT/c['audio_path']).read_bytes()).hexdigest() for c in chunks if c['status']=='done'}
 save(protected,JOB/'original-audio-sha256.json')
rows=json.loads((JOB/'measurements.json').read_text()) if (JOB/'measurements.json').exists() else []
started=time.time();state=dict(phase='Running',pid=os.getpid(),started=started,batches_completed=len(rows),batches_total=40,current_batch=len(rows)+1,initial_saved=sum(c['status']=='done' for c in chunks),selected_segments=sum(len(b['indices']) for b in plan['batches']),model_loads=0,voices='Existing custom voices (Ryan/Aiden); one resident Qwen 1.7B model')
stop=threading.Event();mutex=threading.Lock()
def estimates(current):
 cost={}
 for name,lo,hi,n,size,rt in SPECS:
  measured=[r for r in rows if r['bucket']==name and r['words']>0]
  cost[name]=sum(r['seconds'] for r in measured)/sum(r['words'] for r in measured) if measured else .4/rt
 return sum(len(c['text'].split())*cost[bucket(c)] for c in current if c['status']!='done')/3600

def publish():
 with mutex:
  current=read_chunks();saved=sum(c['status']=='done' for c in current)
  state.update(updated=time.time(),elapsed_seconds=time.time()-started,saved_segments=saved,remaining_estimate_hours=estimates(current),measured_buckets=sorted({r['bucket'] for r in rows}))
  save(state,STATE)
  if state['phase']=='Running':
   message=f"Batch {state['current_batch']}/40; {state['batches_completed']} finished; {saved} segments saved. Elapsed {state['elapsed_seconds']/60:.1f} min. {state.get('detail','Loading model')}"
  else:message=state.get('detail','Trial finished')+f" {saved} segments saved; elapsed {state['elapsed_seconds']/60:.1f} min."
  save(dict(phase='Optimized 40-batch trial — '+state['phase'],message=message,completed=state['batches_completed'],total=40,updated=time.time()),BANNER)
def pulse():
 while not stop.wait(8):
  try:publish()
  except Exception as exc:print('Progress update deferred:',exc,file=sys.stderr,flush=True)
thread=None;pm=None
try:
 publish();thread=threading.Thread(target=pulse,daemon=True);thread.start()
 import torch
 from project import ProjectManager
 from pydub import AudioSegment
 pm=ProjectManager(str(ROOT));engine=pm.get_engine();engine._compile_codec_enabled=False;engine._sub_batch_enabled=False
 t0=time.perf_counter();model=engine._init_local_custom();state['model_loads']=1;model_id=id(model)
 with torch.inference_mode():
  model.generate_custom_voice(text='Ready.',language='English',speaker='Ryan',max_new_tokens=48,non_streaming_mode=True)
  engine._warmup_needed=False;state['load_and_warmup_seconds']=time.perf_counter()-t0
  for number,batch in enumerate(plan['batches'],1):
   if number<=len(rows):continue
   if (JOB/'stop-requested').exists():state.update(phase='Paused',detail='Stopped at batch boundary by request.');break
   assert not requests.get('http://127.0.0.1:4200/api/status/audio',timeout=20).json()['running'],'A separate audio job started; stopping trial'
   current=read_chunks();indices=[i for i in batch['indices'] if current[i]['status']!='done']
   state.update(current_batch=number,detail=f"{batch['bucket']} passages, batch size {len(indices)}");publish()
   attempts=[]
   def render(ids,depth=0):
    if not ids:return
    latest=read_chunks();assert all(latest[i]['status']!='done' for i in ids),'Refusing to regenerate completed audio'
    result=pm.generate_chunks_batch(ids,batch_seed=42,batch_size=len(ids),batch_group_by_type=False)
    attempts.append(dict(indices=ids,failed=result['failed']))
    if result['failed']:
     failures=[i for i,msg in result['failed']]
     if depth<2 and len(failures)>1 and all('out of memory' in str(msg).lower() for i,msg in result['failed']):
      torch.cuda.empty_cache();mid=len(failures)//2;render(failures[:mid],depth+1);render(failures[mid:],depth+1)
     else:raise RuntimeError('Batch render failed: '+str(result['failed'])[:1600])
   begin=time.perf_counter();render(indices);torch.cuda.synchronize();elapsed=time.perf_counter()-begin
   assert id(engine._local_custom_model)==model_id,'Unexpected model reload'
   current=read_chunks();duration=0
   for idx in indices:
    c=current[idx];assert c['status']=='done'
    audio=AudioSegment.from_file(ROOT/c['audio_path']);assert len(audio)>0 and audio.rms>0
    duration+=len(audio)/1000
   row=dict(batch=number,bucket=batch['bucket'],indices=indices,segments=len(indices),words=words([current[i] for i in indices]),seconds=elapsed,audio_seconds=duration,realtime=duration/elapsed if elapsed else 0,attempts=attempts)
   rows.append(row);save(rows,JOB/'measurements.json');state['batches_completed']=len(rows);publish();print(json.dumps(row),flush=True)
  else:state.update(phase='Complete',detail='40 optimized batches finished. Full-book conversion is paused.');publish()
except Exception as exc:
 state.update(phase='Needs attention',detail=str(exc));traceback.print_exc()
finally:
 stop.set()
 if thread:thread.join(timeout=15)
 if pm and pm.engine:
  try:pm.engine.unload_models()
  except Exception:traceback.print_exc()
 owned={i for b in plan['batches'] for i in b['indices']};current=read_chunks()
 for i in owned:
  if current[i]['status']=='generating':current[i]['status']='pending'
 save(current,ROOT/'chunks.json')
 protected=json.loads((JOB/'original-audio-sha256.json').read_text())
 assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in protected.items()),'Original audio changed'
 state['original_audio_verified']=True;publish();lock.unlink(missing_ok=True)
 print(json.dumps(state),flush=True)
