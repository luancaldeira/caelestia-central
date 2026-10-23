"""Send a client state request to a test window, without changing focus."""
import ctypes as C,sys
x=C.CDLL('libX11.so.6');U=C.c_ulong;P=C.c_void_p
x.XOpenDisplay.restype=P;x.XDefaultRootWindow.argtypes=[P];x.XDefaultRootWindow.restype=U
x.XQueryTree.argtypes=[P,U,C.POINTER(U),C.POINTER(U),C.POINTER(C.POINTER(U)),C.POINTER(C.c_uint)]
x.XFetchName.argtypes=[P,U,C.POINTER(C.c_char_p)];x.XFree.argtypes=[P]
x.XInternAtom.argtypes=[P,C.c_char_p,C.c_int];x.XInternAtom.restype=U
class Data(C.Union):_fields_=[('b',C.c_char*20),('s',C.c_short*10),('l',C.c_long*5)]
class Client(C.Structure):_fields_=[('type',C.c_int),('serial',U),('send_event',C.c_int),('display',P),('window',U),('message_type',U),('format',C.c_int),('data',Data)]
class Event(C.Union):_fields_=[('client',Client),('pad',C.c_long*24)]
x.XSendEvent.argtypes=[P,U,C.c_int,C.c_long,C.POINTER(Event)];x.XFlush.argtypes=[P];x.XCloseDisplay.argtypes=[P]
d=x.XOpenDisplay(None);root=x.XDefaultRootWindow(d);r=U();p=U();ch=C.POINTER(U)();n=C.c_uint()
x.XQueryTree(d,root,C.byref(r),C.byref(p),C.byref(ch),C.byref(n));target=None
for wid in ch[:n.value]:
 name=C.c_char_p()
 if x.XFetchName(d,wid,C.byref(name)) and name.value:
  title=name.value.decode(errors='replace');x.XFree(name)
  if title==sys.argv[1]:target=wid;break
x.XFree(ch)
assert target,'Test X11 window not found'
e=Event();e.client.type=33;e.client.send_event=1;e.client.display=d;e.client.window=target;e.client.format=32
if sys.argv[2]=='normal':e.client.message_type=x.XInternAtom(d,b'WM_CHANGE_STATE',0);e.client.data.l[0]=1
else:
 e.client.message_type=x.XInternAtom(d,b'_NET_WM_STATE',0);e.client.data.l[0]=0;e.client.data.l[1]=x.XInternAtom(d,b'_NET_WM_STATE_FULLSCREEN',0);e.client.data.l[3]=1
x.XSendEvent(d,root,0,(1<<19)|(1<<20),C.byref(e));x.XFlush(d);x.XCloseDisplay(d)
