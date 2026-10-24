import json,subprocess as s,time,tempfile,os
from pathlib import Path
import argparse
parser=argparse.ArgumentParser(description='Opt-in live X11/Wayland close-isolation regression')
parser.add_argument('--live', action='store_true', required=True, help='allow operation of demo windows and the central in this desktop session')
parser.parse_args()
root=Path(__file__).resolve().parents[2];fixture=root/'tests/desktop/fixture.py'
pointer=root/'tests/desktop/virtual-pointer'
assert pointer.is_file(), 'Run sh tests/desktop/build-pointer.sh first'
def run(*a):return s.check_output(a,text=True,stderr=s.PIPE).strip()
def ipc(m,*a):return run('qs','-c','caelestia','ipc','call','minimized',m,*a)
def info():return json.loads(ipc('info'))
def clients():return json.loads(run('hyprctl','clients','-j'))
def wait(fn,timeout=5):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  v=fn()
  if v:return v
  time.sleep(.04)
 raise AssertionError('Timed out waiting for desktop state')
def click(x,y):run(str(pointer),str(round(x)),str(round(y)),'0','click')
before=info();beforeEntries=json.loads(ipc('list'));cursor=json.loads(run('hyprctl','cursorpos','-j'));active=json.loads(run('hyprctl','activewindow','-j'));workspace=json.loads(run('hyprctl','activeworkspace','-j'))['name']
assert run('qs','-c','caelestia','ipc','call','lock','isLocked')=='false'
reports=[]
try:
 for backend in ('x11','wayland'):
  with tempfile.TemporaryDirectory(prefix='central-close-test-') as d:
   control=Path(d)/'control.json';seq=0;pids=set()
   try:
    cmd='env GDK_BACKEND='+backend+' python3 '+str(fixture)+' --veto --control '+str(control)
    run('hyprctl','dispatch','hl.dsp.exec_cmd('+json.dumps(cmd)+',{workspace="917 silent",no_focus=true})')
    tests=wait(lambda: (ts if len(ts:=[c for c in clients() if c['title'].startswith('Central Demo ')])==3 else None))
    pids={c['pid'] for c in tests}
    for c in tests:
     if backend=='x11':run('python3',str(root/'tests/desktop/x11_state_message.py'),c['title'],'normal');time.sleep(.06)
     seq+=1;control.write_text(json.dumps({'sequence':seq,'action':'minimize','window':c['title'].split()[-1]}))
     wait(lambda: any(e['address']==c['address'][2:] for e in json.loads(ipc('list'))));time.sleep(.7)
    assert all(c['workspace']['name']=='special:caelestia-minimized' for c in clients() if c['pid'] in pids)
    if not info()['open']:ipc('toggle')
    ipc('tab','1');run(str(pointer),'985','900');time.sleep(.65)
    # A rejected close must keep every entry and hidden client intact.
    for name in ('Beta','Alpha','Gamma'):
     target=next(c for c in tests if c['title']=='Central Demo '+name)
     for _ in range(10):
      if info().get('selected')==target['address'][2:]:break
      ipc('next')
     if info().get('selected')!=target['address'][2:]:
      for _ in range(10):
       if info().get('selected')==target['address'][2:]:break
       ipc('previous')
     time.sleep(.5);panel=info();assert panel['selected']==target['address'][2:];origin=panel['origin'];assert origin
     click(origin['x']+origin['width']-24,origin['y']+24)
     if name!='Beta':wait(lambda: all(c['address']!=target['address'] for c in clients()))
     else:time.sleep(.35);assert any(c['address']==target['address'] for c in clients())
     survivors=[c for c in clients() if c['pid'] in pids]
     # Toolkits can update other state after a sibling closes; it is unrelated to restore.
     if backend=='x11':
      for c in survivors:run('python3',str(root/'tests/desktop/x11_state_message.py'),c['title'],'unrelated')
     time.sleep(.4)
     survivors=[c for c in clients() if c['pid'] in pids]
     assert all(c['workspace']['name']=='special:caelestia-minimized' for c in survivors),survivors
     current=info();pointer_now=json.loads(run('hyprctl','cursorpos','-j'))
     if not current['open'] or current['tab']!=1:
      raise AssertionError('Hub closed during test: '+json.dumps({'backend':backend,'target':name,'expectedPointer':{'x':origin['x']+origin['width']-24,'y':origin['y']+24},'pointer':pointer_now,'panel':current}))
     reports.append({'backend':backend,'action':'close '+name,'veto':name=='Beta','remaining':len(survivors),'othersStayedMinimized':True,'hubStayedOpen':True})
   finally:
    for pid in pids:
     try:os.kill(pid,15)
     except ProcessLookupError:pass
    time.sleep(.3)
 assert {e['address'] for e in json.loads(ipc('list'))}=={e['address'] for e in beforeEntries}
finally:
 if info()['open']:ipc('toggle')
 if active.get('address'):run('hyprctl','dispatch','hl.dsp.focus({window='+json.dumps('address:'+active['address'])+'})')
 else:run('hyprctl','dispatch','hl.dsp.focus({workspace='+json.dumps(workspace)+'})')
 if before['open']:ipc('toggle');ipc('tab',str(before['tab']))
 run(str(pointer),str(cursor['x']),str(cursor['y']))
(root/'test-results').mkdir(exist_ok=True)
(root/'test-results/close-isolation.json').write_text(json.dumps({'passed':True,'cases':reports},indent=2));print(json.dumps(reports,indent=2))
