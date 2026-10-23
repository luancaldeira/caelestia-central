#include <wayland-client.h>
#include <linux/input-event-codes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "virtual-pointer.h"
static struct zwlr_virtual_pointer_manager_v1 *manager;
static void global(void *data, struct wl_registry *reg, uint32_t name, const char *interface, uint32_t version) {
 if (!strcmp(interface,"zwlr_virtual_pointer_manager_v1")) manager=wl_registry_bind(reg,name,&zwlr_virtual_pointer_manager_v1_interface,version>2?2:version);
}
static void removed(void *data,struct wl_registry *reg,uint32_t name){}
int main(int argc,char **argv) {
 struct wl_display *d=wl_display_connect(NULL); if(!d)return 1;
 struct wl_registry *r=wl_display_get_registry(d);
 static const struct wl_registry_listener listener={global,removed};
 wl_registry_add_listener(r,&listener,NULL);wl_display_roundtrip(d);if(!manager)return 2;
 struct zwlr_virtual_pointer_v1 *p=zwlr_virtual_pointer_manager_v1_create_virtual_pointer(manager,NULL);
 struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);uint32_t ms=t.tv_sec*1000+t.tv_nsec/1000000;
 if(argc>2)zwlr_virtual_pointer_v1_motion_absolute(p,ms,atoi(argv[1]),atoi(argv[2]),1920,1080);
 if(argc>3 && atoi(argv[3])) {int steps=atoi(argv[3]);zwlr_virtual_pointer_v1_axis_source(p,WL_POINTER_AXIS_SOURCE_WHEEL);zwlr_virtual_pointer_v1_axis_discrete(p,ms,WL_POINTER_AXIS_VERTICAL_SCROLL,wl_fixed_from_int(15*steps),steps);}
 zwlr_virtual_pointer_v1_frame(p);wl_display_roundtrip(d);
 if(argc>4 && !strcmp(argv[4],"click")){zwlr_virtual_pointer_v1_button(p,ms+1,BTN_LEFT,WL_POINTER_BUTTON_STATE_PRESSED);zwlr_virtual_pointer_v1_frame(p);wl_display_roundtrip(d);zwlr_virtual_pointer_v1_button(p,ms+2,BTN_LEFT,WL_POINTER_BUTTON_STATE_RELEASED);zwlr_virtual_pointer_v1_frame(p);wl_display_roundtrip(d);}
 zwlr_virtual_pointer_v1_destroy(p);wl_display_roundtrip(d);wl_display_disconnect(d);return 0;
}
