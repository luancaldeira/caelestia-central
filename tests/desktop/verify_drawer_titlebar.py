"""Opt-in native titlebar continuity check using tiny, temporary private crops.

Requires the live Caelestia session, Kitty, grim, Pillow and hyprbars with a
visible, light title. No desktop recording or retained media is produced.
"""
import argparse
import json
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true',required=True)
parser.add_argument('--backend',choices=('wayland','x11'),default='wayland')
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
pointer=root/'tests/desktop/virtual-pointer'
assert pointer.is_file(),'Run sh tests/desktop/build-pointer.sh first'
def run(*args):return subprocess.check_output(args,text=True,stderr=subprocess.PIPE).strip()
def clients():return json.loads(run('hyprctl','clients','-j'))
def shell(target,method,*args):return run('qs','-c','caelestia','ipc','call',target,method,*args)
def info():return json.loads(shell('windowdrawer','info'))
def hub():return json.loads(shell('minimized','info'))
def wait(test,message,timeout=5):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  value=test()
  if value:return value
  time.sleep(.05)
 raise AssertionError(message)
def click(x,y):run(str(pointer),str(round(x)),str(round(y)),'0','click')
backend=args.backend
media=tempfile.TemporaryDirectory(prefix='central-titlebar-')
base=Path(media.name)
assert shell('lock','isLocked')=='false'
assert not info()['count'],'Wait for the active window transition to finish'
klass='caelestia-titlebar-check-'+backend
originals={(c['address'],c['pid']) for c in clients()};active=json.loads(run('hyprctl','activewindow','-j'));ws=json.loads(run('hyprctl','activeworkspace','-j'))['name'];before=hub();cursor=json.loads(run('hyprctl','cursorpos','-j'));owned=None;report={}
assert not any(c['workspace']['name']=='918' or c['class']==klass for c in clients())
def frame():return next((f for f in info()['active'] if f['address']==owned['address'][2:]),None)
def last(token):return next((f for f in info()['recent'] if f['address']==owned['address'][2:] and f['token']==token),None)
def check(action):
 f=wait(lambda:(f if (f:=frame()) and f['started'] else None),'motion missing');token=f['token'];time.sleep(max(0,(f['startedAt']+470-time.time()*1000)/1000))
 f=frame();assert f and f['decorated'] and f['captureTop']>0 and not f['nativeFrameAt'],f
 x=round(f['x']+f['width']/2-160);y=round(f['y']+1);roi=f'{x},{y} 320x13'
 imageBefore=base/f'titlebar-{backend}-{action}-before.png';imageAfter=base/f'titlebar-{backend}-{action}-after.png'
 run('grim','-g',roi,str(imageBefore))
 done=wait(lambda:last(token),'did not finish');time.sleep(.08);run('grim','-g',roi,str(imageAfter))
 a=Image.open(imageBefore).convert('RGB');b=Image.open(imageAfter).convert('RGB')
 # Bright glyphs must be present while the native client is still masked.
 count=lambda im:sum(min(p)>150 for p in (im.get_flattened_data() if hasattr(im,"get_flattened_data") else im.getdata()))
 left=count(a);right=count(b);error=ImageStat.Stat(ImageChops.difference(a,b)).mean
 report[action]={'decorated':f['decorated'],'captureTop':f['captureTop'],'sourceSize':[f['sourceWidth'],f['sourceHeight']],'imageSize':[f['width'],f['height']],'titlePixelsBefore':left,'titlePixelsAfter':right,'meanColorError':error,'handoffFallback':done['handoffFallback'],'maxFrameMs':done['maxFrameMs'],'meanFrameMs':done['meanFrameMs']}
 print(action,json.dumps(report[action]),flush=True)
 assert left>80 and right>80,(left,right)
 assert min(left,right)/max(left,right)>.7,(left,right)
 assert max(error)<12,error
 assert done['edgeErrorPx']==0 and done['elasticity']==0 and not done['handoffFallback'],done
try:
 run('hyprctl','dispatch','hl.dsp.focus({workspace="918"})');time.sleep(.6)
 cmd=shlex.join(['kitty','-o','linux_display_server='+backend,'--class',klass,'--title','Caelestia titlebar continuity'])
 run('hyprctl','dispatch','function() hl.plugin.caelestia_minimize.prepare_launch('+json.dumps(klass)+',900,1030,48,48,""); hl.dispatch(hl.dsp.exec_cmd('+json.dumps(cmd)+')) end')
 owned=wait(lambda:next((c for c in clients() if c['class']==klass),None),'fixture missing');check('open')
 shell('minimized','minimizeWindow',owned['address']);wait(lambda:not frame(),'minimize did not finish');wait(lambda:next(c for c in clients() if c['address']==owned['address'])['workspace']['name']=='special:caelestia-minimized','not minimized')
 if not hub()['open']:shell('minimized','toggle')
 shell('minimized','tab','1');run(str(pointer),'985','900');time.sleep(.65)
 for method in ('next','previous'):
  for _ in range(20):
   if hub().get('selected')==owned['address'][2:]:break
   shell('minimized',method)
  if hub().get('selected')==owned['address'][2:]:break
 assert hub()['selected']==owned['address'][2:];o=hub()['origin'];click(o['x']+o['width']/2,o['y']+o['height']/2);check('restore')
finally:
 if owned and any(c['address']==owned['address'] and c['pid']==owned['pid'] for c in clients()):run('hyprctl','dispatch','hl.dsp.window.close({window='+json.dumps('address:'+owned['address'])+'})')
 if hub()['open']:shell('minimized','toggle')
 if active.get('address'):run('hyprctl','dispatch','hl.dsp.focus({window='+json.dumps('address:'+active['address'])+'})')
 else:run('hyprctl','dispatch','hl.dsp.focus({workspace='+json.dumps(ws)+'})')
 if before['open']:shell('minimized','toggle');shell('minimized','tab',str(before['tab']))
 run(str(pointer),str(cursor['x']),str(cursor['y']))
 media.cleanup()
 (root/'test-results').mkdir(exist_ok=True)
 (root/f'test-results/titlebar-{backend}.json').write_text(json.dumps(report,indent=2))
assert originals <= {(c['address'],c['pid']) for c in clients()}
