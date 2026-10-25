pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs.services

Singleton {
    id: root
    readonly property alias motions: motions
    readonly property double generation: Date.now()
    property int completed: 0
    property var panels: ({})
    property var recent: []
    // Opt-in live diagnostic: inspect the final exported frame before revealing
    // the native client. The compositor's lease timeout still restores it.
    property bool holdHandoff: false
    signal presented(var frame)

    ListModel { id: motions; dynamicRoles: true }
    function dispatch(method, values) {
        Hypr.dispatch(`function() local p=hl.plugin.caelestia_minimize; if p and p.${method} then p.${method}(${values.join(",")}) end end`);
    }
    function register() { dispatch("enable_drawer", [ShellState.sessionLocked ? "false" : "true",generation,Quickshell.processId]); }
    function indexOf(address) {
        for(let i=0;i<motions.count;i++) if(motions.get(i).address===address) return i;
        return -1;
    }
    function update(data) {
        try {
            const frame=JSON.parse(data);
            if(!frame.address) return;
            const index=indexOf(frame.address);
            if(frame.done) {
                if(index>=0 && motions.get(index).token===frame.token) {
                    try {
                        const report=panels[frame.address]?.info();
                        if(report) recent=recent.slice(-7).concat([Object.assign(report,{completedAt:Date.now()})]);
                    } catch(e) {}
                    motions.remove(index);
                }
                return;
            }
            if(![frame.pid,frame.token,frame.monitor,frame.x,frame.y,frame.width,frame.height].every(Number.isFinite) || frame.width<8 || frame.height<8) return;
            if(ShellState.sessionLocked) { complete(frame); return; }
            const values={address:frame.address,pid:frame.pid,token:frame.token,monitor:frame.monitor,
                goalX:frame.x,goalY:frame.y,goalWidth:frame.width,goalHeight:frame.height,minimizing:frame.minimizing,
                goalRounding:Number.isFinite(frame.rounding) ? Math.max(0,frame.rounding) : -1,
                decorated:frame.decorated===true,captureLeft:frame.captureLeft ?? 0,captureTop:frame.captureTop ?? 0,
                captureRight:frame.captureRight ?? 0,captureBottom:frame.captureBottom ?? 0,
                shadowLeft:frame.shadowLeft ?? 0,shadowTop:frame.shadowTop ?? 0,
                shadowRight:frame.shadowRight ?? 0,shadowBottom:frame.shadowBottom ?? 0};
            if(index>=0 && motions.get(index).token!==frame.token) motions.remove(index);
            const current=indexOf(frame.address);
            if(current>=0) motions.set(current,values);
            else motions.append(Object.assign(values,{receivedAt:Date.now()}));
        } catch(e) { console.warn("WindowDrawer: invalid handoff",e); }
    }
    function claim(model) { dispatch("claim_drawer", [JSON.stringify(model.address),model.pid,model.token]); }
    function release(model,releaseId) { dispatch("release_drawer", [JSON.stringify(model.address),model.pid,model.token,releaseId]); }
    function complete(model) {
        completed++;
        dispatch("complete_drawer", [JSON.stringify(model.address),model.pid,model.token]);
    }
    function attach(address,panel) { panels=Object.assign({},panels,{[address]:panel}); }
    function detach(address,panel) {
        if(panels[address]!==panel) return;
        const next=Object.assign({},panels); delete next[address]; panels=next;
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if(event.name==="caelestia_drawer") root.update(event.data);
            else if(event.name==="caelestia_drawer_presented") {
                try { root.presented(JSON.parse(event.data)); }
                catch(e) { console.warn("WindowDrawer: invalid presentation acknowledgment",e); }
            }
            else if(event.name==="caelestia_drawer_ready") root.register();
        }
    }
    Connections {
        target: ShellState
        function onSessionLockedChanged() { root.register(); if(ShellState.sessionLocked) motions.clear(); }
    }
    Component.onCompleted: register()
    Component.onDestruction: dispatch("enable_drawer", ["false",generation])
    IpcHandler {
        target: "windowdrawer"
        function hold(enabled: bool): void { root.holdHandoff=enabled; }
        function reload(): void { Quickshell.reload(false); }
        function info(): string {
            const result=[];
            for(const panel of Object.values(root.panels)) {
                try { const frame=panel?.info(); if(frame) result.push(frame); } catch(e) {}
            }
            return JSON.stringify({generation:root.generation,completed:root.completed,count:motions.count,active:result,recent:root.recent});
        }
    }
}
