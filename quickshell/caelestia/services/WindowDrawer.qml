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

    ListModel { id: motions; dynamicRoles: true }
    function dispatch(method, values) {
        Hypr.dispatch(`function() local p=hl.plugin.caelestia_minimize; if p and p.${method} then p.${method}(${values.join(",")}) end end`);
    }
    function register() { dispatch("enable_drawer", [ShellState.sessionLocked ? "false" : "true",generation]); }
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
                if(index>=0 && motions.get(index).token===frame.token) motions.remove(index);
                return;
            }
            if(![frame.pid,frame.token,frame.monitor,frame.x,frame.y,frame.width,frame.height].every(Number.isFinite) || frame.width<8 || frame.height<8) return;
            if(ShellState.sessionLocked) { complete(frame); return; }
            const values={address:frame.address,pid:frame.pid,token:frame.token,monitor:frame.monitor,
                goalX:frame.x,goalY:frame.y,goalWidth:frame.width,goalHeight:frame.height,minimizing:frame.minimizing};
            if(index>=0 && motions.get(index).token!==frame.token) motions.remove(index);
            const current=indexOf(frame.address);
            if(current>=0) motions.set(current,values);
            else motions.append(values);
        } catch(e) { console.warn("WindowDrawer: invalid handoff",e); }
    }
    function claim(model) { dispatch("claim_drawer", [JSON.stringify(model.address),model.pid,model.token]); }
    function release(model) { dispatch("release_drawer", [JSON.stringify(model.address),model.pid,model.token]); }
    function complete(model) {
        completed++;
        dispatch("complete_drawer", [JSON.stringify(model.address),model.pid,model.token]);
    }
    function attach(address,panel) { panels=Object.assign({},panels,{[address]:panel}); }
    function detach(address) { const next=Object.assign({},panels); delete next[address]; panels=next; }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if(event.name==="caelestia_drawer") root.update(event.data);
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
        function reload(): void { Quickshell.reload(false); }
        function info(): string {
            const result=[];
            for(const panel of Object.values(root.panels)) {
                try { const frame=panel?.info(); if(frame) result.push(frame); } catch(e) {}
            }
            return JSON.stringify({generation:root.generation,completed:root.completed,count:motions.count,active:result});
        }
    }
}
