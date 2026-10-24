"""Three related test windows, including one that can reject close requests."""
import argparse,json
from pathlib import Path
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk,Gdk,GLib
p=argparse.ArgumentParser();p.add_argument('--control',type=Path,required=True);p.add_argument('--veto',action='store_true');p.add_argument('--single',action='store_true');a=p.parse_args()
app=Gtk.Application(application_id='io.github.luancaldeira.CentralMotionTest')
windows={};seen=0

def activate(app):
 css=Gtk.CssProvider();css.load_from_data(b'.alpha { background:#263844; color:#e1eff5; } .beta { background:#36344d; color:#f1e8ff; } .gamma { background:#28423b; color:#e4f5ed; }')
 Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
 for name,subtitle in [('Alpha','A place for your ideas'),('Beta','Keep your workspace in motion'),('Gamma','Everything within reach')][:1 if a.single else 3]:
  w=Gtk.ApplicationWindow(application=app,title='Central Demo '+name);w.set_default_size(780,480);w.add_css_class(name.lower());windows[name]=w
  box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=20);box.set_margin_top(90);box.set_margin_start(70);box.set_margin_end(70)
  title=Gtk.Label(label=name,xalign=0);title.add_css_class('title-1');box.append(title)
  label=Gtk.Label(label=subtitle,xalign=0);label.add_css_class('title-2');box.append(label)
  box.append(Gtk.Label(label='Caelestia Central  /  Motion preview',xalign=0));w.set_child(box)
  if a.veto and name=='Beta':w.connect('close-request',lambda *_: True)
  w.present()
 GLib.timeout_add(30,poll)
def poll():
 global seen
 try:
  c=json.loads(a.control.read_text())
  if c['sequence']!=seen:
   seen=c['sequence'];w=windows[c['window']]
   if c['action']=='minimize':w.minimize()
   elif c['action']=='close':w.close()
 except (OSError,ValueError,KeyError):pass
 return True
app.connect('activate',activate);app.run([])
