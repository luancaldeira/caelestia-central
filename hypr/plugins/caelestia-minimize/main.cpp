#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/plugins/HookSystem.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/config/shared/animation/AnimationTree.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/protocols/XDGShell.hpp>
#include <hyprland/src/xwayland/XSurface.hpp>
#include <hyprland/src/managers/EventManager.hpp>
#include <hyprland/src/animation/AnimationManager.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <unordered_map>
#include <algorithm>
#include <charconv>
#include <cmath>
#include <string_view>
#include <sstream>
#include <unordered_set>
#include <cctype>
#include <utility>

extern "C" {
#include <lua.h>
}

// The shell owns workspace restoration. The native animation starts only after
// the layout has calculated its final geometry. Close motion changes only the
// native snapshot animation context, after the application has actually closed.
static CHyprSignalListener opened, closed, openedLate, activated;
static CFunctionHook* closeMotionHook = nullptr;
static std::unordered_map<uintptr_t, CHyprSignalListener> listeners;

struct MinimizeFlight {
    PHLWINDOWREF window;
    PHLANIMVAR<float> progress;
    PHLANIMVAR<float> fadeProgress;
    Vector2D fromPosition, fromSize, goalPosition, goalSize, toPosition, toSize;
    float fadeGoal = 1.F;
    float fromAlpha = 1.F;
    std::string workspace;
    Time::steady_tp started;
};
static std::unordered_map<uintptr_t, MinimizeFlight> flights;
static SP<CEventLoopTimer> flightTimer;

struct LaunchOrigin {
    std::unordered_set<std::string> classes;
    std::unordered_set<uintptr_t> existing;
    Vector2D position, size;
    Time::steady_tp expires;
    uintptr_t focusedBefore = 0;
};
static std::vector<LaunchOrigin> launchOrigins;
static std::string lastLaunchAddress;
static Vector2D lastLaunchPosition, lastLaunchSize;

// The shell's real drawer component owns motion. This lease only suppresses
// the stationary native client while its single GPU image moves in that drawer.
struct DrawerLease {
    PHLWINDOWREF window;
    Vector2D goalPosition, goalSize;
    float fadeGoal = 1.F;
    std::string workspace;
    Time::steady_tp started;
    uint64_t token = 0;
    bool minimizing = false;
    bool claimed = false;
    bool released = false;
};
static std::unordered_map<uintptr_t, DrawerLease> drawerLeases;
static uint64_t nextDrawerToken = 0;
static bool drawerAvailable = false;
static uint64_t drawerOwner = 0;
static PHLWINDOW luaWindow(lua_State* L);

static void drawerEvent(uintptr_t key, const DrawerLease& lease, bool done = false) {
    const auto w=lease.window.lock();
    const auto monitor=w ? w->m_monitor.lock() : nullptr;
    g_pEventManager->postEvent(SHyprIPCEvent{.event="caelestia_drawer",.data=std::format(
        R"({{"address":"{:x}","pid":{},"token":{},"monitor":{},"x":{:.3f},"y":{:.3f},"width":{:.3f},"height":{:.3f},"minimizing":{},"done":{}}})",
        key,w ? w->getPID() : 0,lease.token,monitor ? static_cast<int>(monitor->m_id) : -1,
        lease.goalPosition.x,lease.goalPosition.y,lease.goalSize.x,lease.goalSize.y,
        lease.minimizing ? "true" : "false",done ? "true" : "false")});
}

static void finishDrawer(uintptr_t key,bool complete) {
    auto node=drawerLeases.extract(key);
    if(node.empty()) return;
    auto& lease=node.mapped();
    const auto w=lease.window.lock();
    if(w && w->m_isMapped) {
        auto& fade=w->alpha(Desktop::View::WINDOW_ALPHA_FADE);
        bool hidden=false;
        if(complete && lease.minimizing && w->m_workspace && w->m_workspace->m_name==lease.workspace) {
            fade->setValueAndWarp(0.F);
            const auto selector=std::format("address:0x{:x}",key);
            const auto unpin=w->m_pinned ? std::format("hl.dispatch(hl.dsp.window.pin({{window=\"{}\",action=\"off\"}}));",selector) : "";
            HyprlandAPI::invokeHyprctlCommand("dispatch",std::format(
                "function() {} hl.dispatch(hl.dsp.window.move({{window=\"{}\",workspace=\"special:caelestia-minimized\",follow=false}})) end",unpin,selector));
            hidden=w->m_workspace && w->m_workspace->m_name=="special:caelestia-minimized";
            if(hidden) w->alpha(Desktop::View::WINDOW_ALPHA_MOVE_TO_WORKSPACE)->warp();
        }
        fade->setValueAndWarp(lease.fadeGoal);
        g_pEventManager->postEvent(SHyprIPCEvent{.event="caelestia_minimize_done",.data=std::format("{:x},{},{}",key,w->getPID(),hidden ? 1 : 0)});
    }
    drawerEvent(key,lease,true);
}

static bool startDrawer(PHLWINDOW w,bool minimizing) {
    if(!drawerAvailable || !w || !w->m_workspace || !w->m_workspace->isVisibleNotCovered() ||
       w->m_ruleApplicator->noAnim().valueOrDefault() || !w->positionAnimation()->enabled() || !w->sizeAnimation()->enabled()) return false;
    const auto key=reinterpret_cast<uintptr_t>(w.get());
    auto existing=drawerLeases.find(key);
    if(existing!=drawerLeases.end()) {
        auto& lease=existing->second;
        lease.minimizing=minimizing;
        lease.released=false;
        w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->setValueAndWarp(0.F);
        lease.started=Time::steadyNow();
        drawerEvent(key,lease);
        if(!minimizing) g_pEventManager->postEvent(SHyprIPCEvent{.event="caelestia_minimize_done",.data=std::format("{:x},{},0",key,w->getPID())});
        return true;
    }
    if(drawerLeases.size()>=4) return false;
    DrawerLease lease;
    lease.window=w;
    lease.goalPosition=w->positionAnimation()->goal();
    lease.goalSize=w->sizeAnimation()->goal();
    lease.fadeGoal=w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->goal();
    lease.workspace=w->m_workspace->m_name;
    lease.started=Time::steadyNow();
    lease.token=++nextDrawerToken;
    lease.minimizing=minimizing;
    w->positionAnimation()->warp();
    w->sizeAnimation()->warp();
    // Window export renders a standalone client at alpha=1, independently of
    // its desktop alpha. Quickshell takes one frame; no video stream is used.
    w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->setValueAndWarp(0.F);
    drawerLeases.emplace(key,lease);
    drawerEvent(key,lease);
    flightTimer->updateTimeout(std::chrono::milliseconds(8));
    return true;
}

static int enableDrawer(lua_State* L) {
    const auto owner=lua_isinteger(L,2) ? static_cast<uint64_t>(lua_tointeger(L,2)) : 0;
    // A retiring QML generation must not disable its replacement after reload.
    if(owner<drawerOwner) { lua_pushboolean(L,false); return 1; }
    drawerOwner=owner;
    drawerAvailable=lua_toboolean(L,1);
    if(!drawerAvailable) while(!drawerLeases.empty()) finishDrawer(drawerLeases.begin()->first,true);
    lua_pushboolean(L,true);
    return 1;
}

static int claimDrawer(lua_State* L) {
    const auto w=luaWindow(L);
    const auto it=w ? drawerLeases.find(reinterpret_cast<uintptr_t>(w.get())) : drawerLeases.end();
    const auto valid=it!=drawerLeases.end() && lua_isinteger(L,3) && it->second.token==static_cast<uint64_t>(lua_tointeger(L,3));
    if(valid) it->second.claimed=true;
    lua_pushboolean(L,valid);
    return 1;
}

static int releaseDrawer(lua_State* L) {
    const auto w=luaWindow(L);
    const auto it=w ? drawerLeases.find(reinterpret_cast<uintptr_t>(w.get())) : drawerLeases.end();
    const auto valid=it!=drawerLeases.end() && !it->second.minimizing && lua_isinteger(L,3) && it->second.token==static_cast<uint64_t>(lua_tointeger(L,3));
    if(valid) {
        it->second.released=true;
        w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->setValueAndWarp(it->second.fadeGoal);
    }
    lua_pushboolean(L,valid);
    return 1;
}

static int completeDrawer(lua_State* L) {
    const auto w=luaWindow(L);
    const auto it=w ? drawerLeases.find(reinterpret_cast<uintptr_t>(w.get())) : drawerLeases.end();
    const auto valid=it!=drawerLeases.end() && lua_isinteger(L,3) && it->second.token==static_cast<uint64_t>(lua_tointeger(L,3));
    if(valid) finishDrawer(it->first,true);
    lua_pushboolean(L,valid);
    return 1;
}


static std::string normalizedClass(std::string text) {
    std::ranges::transform(text, text.begin(), [](unsigned char c) { return std::tolower(c); });
    if (text.ends_with(".desktop")) text.resize(text.size() - 8);
    return text;
}

struct DepartureGeometry {
    Vector2D position, size;
};

// Minimize and close share the same shrink and horizontal center. Only the
// screen edge changes; both end twelve logical pixels outside the monitor.
static DepartureGeometry departureGeometry(PHLMONITOR monitor, const Vector2D& position, const Vector2D& size, bool downward) {
    const auto scale = std::min({0.16, 160. / std::max(1., size.x), 100. / std::max(1., size.y)});
    const auto targetSize = (size * scale).clamp({8,8}, size);
    return {{position.x + (size.x - targetSize.x) / 2.,
        downward ? monitor->m_position.y + monitor->m_size.y + 12. : monitor->m_position.y - targetSize.y - 12.}, targetSize};
}

// Retarget the compositor's existing close snapshot. No close request is delayed,
// no live client is resized, and applications retain their unsaved-work dialogs.
static Animation::SViewAnimationContext closeUp(const Desktop::View::CWindowAnimationController* controller) {
    using Original = Animation::SViewAnimationContext (*)(const Desktop::View::CWindowAnimationController*);
    auto context = reinterpret_cast<Original>(closeMotionHook->m_original)(controller);
    for (const auto& w : Desktop::windowState()->windows()) {
        if (!w || &w->m_animationController != controller) continue;
        const auto monitor = w->m_monitor.lock();
        if (!monitor || w->m_X11DoesntWantBorders || w->m_ruleApplicator->noAnim().valueOrDefault()) break;
        context.pos.from = w->position(Desktop::View::IGeometric::GEOMETRIC_CURRENT);
        context.size.from = w->size(Desktop::View::IGeometric::GEOMETRIC_CURRENT);
        const auto departure = departureGeometry(monitor, context.pos.from, context.size.from, false);
        context.size.to = departure.size;
        context.pos.to = departure.position;
        break;
    }
    return context;
}

static int prepareLaunch(lua_State* L) {
    size_t length = 0;
    const auto names = lua_tolstring(L, 1, &length);
    double values[4] = {};
    bool valid = names && length > 0 && length <= 4096;
    for (int i = 0; i < 4; ++i) {
        int number = 0;
        values[i] = lua_tonumberx(L, i + 2, &number);
        valid = valid && number && std::isfinite(values[i]) && std::abs(values[i]) <= 100000 && (i < 2 || (values[i] >= 8 && values[i] <= 16384));
    }
    if (!valid) { lua_pushboolean(L, false); return 1; }
    LaunchOrigin origin;
    if (const auto focus = lua_tostring(L, 6)) {
        std::string_view address(focus);
        if (address.starts_with("0x")) address.remove_prefix(2);
        std::from_chars(address.data(), address.data() + address.size(), origin.focusedBefore, 16);
    }
    std::istringstream stream(std::string(names, length));
    std::string name;
    while (std::getline(stream, name)) if (!name.empty()) origin.classes.insert(normalizedClass(name));
    for (const auto& w : Desktop::windowState()->windows())
        if (w && w->m_isMapped) origin.existing.insert(reinterpret_cast<uintptr_t>(w.get()));
    origin.position = Vector2D(values[0], values[1]);
    origin.size = Vector2D(values[2], values[3]);
    origin.expires = Time::steadyNow() + std::chrono::seconds(12);
    std::erase_if(launchOrigins, [](const auto& o) { return o.expires <= Time::steadyNow(); });
    if (launchOrigins.size() >= 16) launchOrigins.erase(launchOrigins.begin());
    launchOrigins.push_back(std::move(origin));
    lua_pushboolean(L, true);
    return 1;
}

static void animateLaunch(PHLWINDOW window, bool existing) {
    if (!window || !window->m_isMapped || window->isHidden() || window->isX11OverrideRedirect()) return;
    std::erase_if(launchOrigins, [](const auto& o) { return o.expires <= Time::steadyNow(); });
    const auto pointer = reinterpret_cast<uintptr_t>(window.get());
    const auto match = std::ranges::find_if(launchOrigins, [&](const auto& o) {
        return (!existing || (pointer != o.focusedBefore && o.existing.contains(pointer))) &&
            (o.classes.contains(normalizedClass(window->m_class)) || o.classes.contains(normalizedClass(window->m_initialClass)));
    });
    if (match == launchOrigins.end()) return;
    const auto origin = *match;
    launchOrigins.erase(match);
    auto& position = window->positionAnimation();
    auto& size = window->sizeAnimation();
    if (!position || !size || !position->enabled() || !size->enabled() || window->m_ruleApplicator->noAnim().valueOrDefault()) return;
    if(startDrawer(window,false)) {
        lastLaunchAddress=std::format("{:x}",pointer);
        lastLaunchPosition=origin.position;
        lastLaunchSize=origin.size;
        return;
    }
    position->setConfig(Config::animationTree()->getAnimationPropertyConfig("windowsMove"));
    size->setConfig(Config::animationTree()->getAnimationPropertyConfig("windowsMove"));
    position->setValue(origin.position);
    size->setValue(origin.size);
    window->alpha(Desktop::View::WINDOW_ALPHA_FADE)->setValueAndWarp(1.F);
    lastLaunchAddress = std::format("{:x}", pointer);
    lastLaunchPosition = origin.position;
    lastLaunchSize = origin.size;
}

static int launchState(lua_State* L) {
    lua_createtable(L, 0, 6);
    lua_pushinteger(L, launchOrigins.size()); lua_setfield(L, -2, "pending");
    lua_pushstring(L, lastLaunchAddress.c_str()); lua_setfield(L, -2, "address");
    const auto field = [L](const char* name, double value) { lua_pushnumber(L, value); lua_setfield(L, -2, name); };
    field("x", lastLaunchPosition.x); field("y", lastLaunchPosition.y); field("width", lastLaunchSize.x); field("height", lastLaunchSize.y);
    return 1;
}

static bool stillOwnsGeometry(const MinimizeFlight& flight, PHLWINDOW window) {
    return window && window->m_isMapped && window->m_workspace && window->m_workspace->m_name == flight.workspace &&
        window->positionAnimation()->goal() == flight.goalPosition && window->sizeAnimation()->goal() == flight.goalSize;
}

static void finishFlight(uintptr_t key, bool hide) {
    auto node = flights.extract(key);
    if (node.empty())
        return;
    auto& flight = node.mapped();
    flight.progress->resetAllCallbacks();
    flight.progress->warp();
    flight.fadeProgress->resetAllCallbacks();
    flight.fadeProgress->warp();
    const auto window = flight.window.lock();
    if (!window || !window->m_isMapped)
        return;
    const bool owned = stillOwnsGeometry(flight, window);
    hide = hide && owned;
    auto& fade = window->alpha(Desktop::View::WINDOW_ALPHA_FADE);
    const auto presentedAlpha = fade->value();
    // Going to an invisible workspace normally keeps rendering the outgoing
    // window for a second workspace fade. Mask that handoff BEFORE resetting
    // the presented geometry, then complete that fade while still masked.
    if (hide)
        fade->setValueAndWarp(0.F);
    if (owned) {
        window->positionAnimation()->setValueAndWarp(flight.goalPosition);
        window->sizeAnimation()->setValueAndWarp(flight.goalSize);
    } else {
        // A user move/resize can take ownership during flight. Leave its native
        // animation running; otherwise clear any stale presentation-only value.
        if (!window->positionAnimation()->isBeingAnimated())
            window->positionAnimation()->setValueAndWarp(window->positionAnimation()->goal());
        if (!window->sizeAnimation()->isBeingAnimated())
            window->sizeAnimation()->setValueAndWarp(window->sizeAnimation()->goal());
    }
    if (hide) {
        const auto selector = std::format("address:0x{:x}", key);
        const auto unpin = window->m_pinned ? std::format("hl.dispatch(hl.dsp.window.pin({{window=\"{}\",action=\"off\"}}));", selector) : "";
        HyprlandAPI::invokeHyprctlCommand("dispatch", std::format(
            "function() {} hl.dispatch(hl.dsp.window.move({{window=\"{}\",workspace=\"special:caelestia-minimized\",follow=false}})) end", unpin, selector));
        hide = window->m_workspace && window->m_workspace->m_name == "special:caelestia-minimized";
        if (hide)
            window->alpha(Desktop::View::WINDOW_ALPHA_MOVE_TO_WORKSPACE)->warp();
        fade->setValueAndWarp(flight.fadeGoal);
    } else {
        fade->setValueAndWarp(flight.fadeGoal);
        fade->setValue(presentedAlpha);
    }
    g_pEventManager->postEvent(SHyprIPCEvent{.event = "caelestia_minimize_done", .data = std::format("{:x},{},{}", key, window->getPID(), hide ? 1 : 0)});
}

static PHLWINDOW luaWindow(lua_State* L) {
    size_t length = 0;
    const auto text = lua_tolstring(L, 1, &length);
    if (!text || !lua_isinteger(L, 2))
        return nullptr;
    std::string_view address(text, length);
    if (address.starts_with("0x"))
        address.remove_prefix(2);
    uintptr_t pointer = 0;
    const auto parsed = std::from_chars(address.data(), address.data() + address.size(), pointer, 16);
    if (parsed.ec != std::errc{} || parsed.ptr != address.data() + address.size())
        return nullptr;
    for (const auto& window : Desktop::windowState()->windows()) {
        if (window && window->m_isMapped && reinterpret_cast<uintptr_t>(window.get()) == pointer && window->getPID() == lua_tointeger(L, 2))
            return window;
    }
    return nullptr;
}

static int restoreFrom(lua_State* L) {
    const auto window = luaWindow(L);
    if (!window || window->isHidden()) {
        lua_pushboolean(L, false);
        return 1;
    }
    double values[4] = {};
    for (int i = 0; i < 4; ++i) {
        int number = 0;
        values[i] = lua_tonumberx(L, i + 3, &number);
        if (!number || !std::isfinite(values[i]) || std::abs(values[i]) > 100000 || (i >= 2 && (values[i] < 8 || values[i] > 16384))) {
            lua_pushboolean(L, false);
            return 1;
        }
    }
    auto& position = window->positionAnimation();
    auto& size = window->sizeAnimation();
    if (!position || !size || !position->enabled() || !size->enabled()) {
        lua_pushboolean(L, false);
        return 1;
    }
    std::erase_if(launchOrigins, [&](const auto& origin) {
        return origin.classes.contains(normalizedClass(window->m_class)) || origin.classes.contains(normalizedClass(window->m_initialClass));
    });
    if(startDrawer(window,false)) { lua_pushboolean(L,true); return 1; }
    const bool interrupted = flights.contains(reinterpret_cast<uintptr_t>(window.get()));
    const auto presentedPosition = position->value();
    const auto presentedSize = size->value();
    const auto presentedAlpha = window->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value();
    finishFlight(reinterpret_cast<uintptr_t>(window.get()), false);
    // setValue changes the current value, preserving the layout's goal, curve,
    // callbacks and final client size. The compositor animates live content.
    position->setValue(interrupted ? presentedPosition : Vector2D(values[0], values[1]));
    size->setValue(interrupted ? presentedSize : Vector2D(values[2], values[3]));
    if (interrupted)
        window->alpha(Desktop::View::WINDOW_ALPHA_FADE)->setValue(presentedAlpha);
    else
        window->alpha(Desktop::View::WINDOW_ALPHA_FADE)->setValueAndWarp(1.F);
    lua_pushboolean(L, true);
    return 1;
}

// Animate only the presented geometry. Keeping the native goals unchanged also
// keeps the application's surface at full resolution throughout the shrink.
static int minimizeTo(lua_State* L) {
    const auto window = luaWindow(L);
    if (!window || window->isHidden() || !window->m_workspace || window->m_workspace->m_name == "special:caelestia-minimized") {
        lua_pushboolean(L, false);
        return 1;
    }
    double values[4] = {};
    for (int i = 0; i < 4; ++i) {
        int number = 0;
        values[i] = lua_tonumberx(L, i + 3, &number);
        if (!number || !std::isfinite(values[i]) || std::abs(values[i]) > 100000 || (i >= 2 && (values[i] < 8 || values[i] > 16384))) {
            lua_pushboolean(L, false);
            return 1;
        }
    }
    auto& position = window->positionAnimation();
    auto& size = window->sizeAnimation();
    if (!position || !size || !position->enabled() || !size->enabled()) {
        lua_pushboolean(L, false);
        return 1;
    }
    if(startDrawer(window,true)) { lua_pushboolean(L,true); return 1; }
    const auto key = reinterpret_cast<uintptr_t>(window.get());
    if (flights.contains(key)) {
        lua_pushboolean(L, true);
        return 1;
    }
    const auto monitor = window->m_monitor.lock();
    if (!monitor || window->m_ruleApplicator->noAnim().valueOrDefault()) {
        lua_pushboolean(L, false);
        return 1;
    }
    auto& flight = flights[key];
    flight.window = window;
    flight.fromPosition = position->value();
    flight.fromSize = size->value();
    flight.goalPosition = position->goal();
    flight.goalSize = size->goal();
    // The legacy hub rectangle remains accepted above for shell compatibility.
    // Departure now mirrors close instead of shrinking into that rectangle.
    const auto departure = departureGeometry(monitor, flight.fromPosition, flight.fromSize, true);
    flight.toPosition = departure.position;
    flight.toSize = departure.size;
    flight.workspace = window->m_workspace->m_name;
    flight.started = Time::steadyNow();
    auto& fade = window->alpha(Desktop::View::WINDOW_ALPHA_FADE);
    flight.fadeGoal = fade->goal();
    flight.fromAlpha = fade->value();
    fade->setValueAndWarp(flight.fadeGoal);
    fade->value() = flight.fromAlpha;
    position->warp();
    size->warp();
    position->value() = flight.fromPosition;
    size->value() = flight.fromSize;
    Animation::mgr()->createAnimation(0.F, flight.progress, Config::animationTree()->getAnimationPropertyConfig("windowsOut"), window, AVARDAMAGE_ENTIRE);
    Animation::mgr()->createAnimation(0.F, flight.fadeProgress, Config::animationTree()->getAnimationPropertyConfig("fadeOut"), window, AVARDAMAGE_ENTIRE);
    flight.progress->setUpdateCallback([key](auto) {
        const auto it = flights.find(key);
        if (it == flights.end())
            return;
        auto& f = it->second;
        const auto w = f.window.lock();
        if (!stillOwnsGeometry(f, w))
            return;
        const auto progress = std::clamp(f.progress->value(), 0.F, 1.F);
        w->positionAnimation()->value() = f.fromPosition + (f.toPosition - f.fromPosition) * progress;
        w->sizeAnimation()->value() = f.fromSize + (f.toSize - f.fromSize) * progress;
        w->updateWindowDecos();
    });
    flight.fadeProgress->setUpdateCallback([key](auto) {
        const auto it = flights.find(key);
        if (it == flights.end()) return;
        auto& f = it->second;
        const auto w = f.window.lock();
        if (stillOwnsGeometry(f, w))
            w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value() = f.fromAlpha * (1.F - std::clamp(f.fadeProgress->value(), 0.F, 1.F));
    });
    *flight.progress = 1.F;
    *flight.fadeProgress = 1.F;
    flightTimer->updateTimeout(std::chrono::milliseconds(8));
    lua_pushboolean(L, true);
    return 1;
}

static int cancelMinimize(lua_State* L) {
    const auto window = luaWindow(L);
    if(window && drawerLeases.contains(reinterpret_cast<uintptr_t>(window.get()))) {
        finishDrawer(reinterpret_cast<uintptr_t>(window.get()),false);
        lua_pushboolean(L,true);
        return 1;
    }
    if (!window || !flights.contains(reinterpret_cast<uintptr_t>(window.get()))) {
        lua_pushboolean(L, false);
        return 1;
    }
    const auto position = window->positionAnimation()->value();
    const auto size = window->sizeAnimation()->value();
    finishFlight(reinterpret_cast<uintptr_t>(window.get()), false);
    window->positionAnimation()->setValue(position);
    window->sizeAnimation()->setValue(size);
    lua_pushboolean(L, true);
    return 1;
}

// Read-only diagnostics for checking motion and final geometry without relying
// on hyprctl clients, which reports goal geometry even during an animation.
static int animationState(lua_State* L) {
    const auto window = luaWindow(L);
    if (!window) {
        lua_pushnil(L);
        return 1;
    }
    const auto position = window->position(Desktop::View::IGeometric::GEOMETRIC_CURRENT);
    const auto size = window->size(Desktop::View::IGeometric::GEOMETRIC_CURRENT);
    const auto targetPosition = window->position(Desktop::View::IGeometric::GEOMETRIC_GOAL);
    const auto targetSize = window->size(Desktop::View::IGeometric::GEOMETRIC_GOAL);
    lua_createtable(L, 0, 15);
    const auto field = [L](const char* name, double value) { lua_pushnumber(L, value); lua_setfield(L, -2, name); };
    field("x", position.x); field("y", position.y); field("width", size.x); field("height", size.y);
    field("targetX", targetPosition.x); field("targetY", targetPosition.y); field("targetWidth", targetSize.x); field("targetHeight", targetSize.y);
    lua_pushboolean(L, window->positionAnimation()->isBeingAnimated() || window->sizeAnimation()->isBeingAnimated() || flights.contains(reinterpret_cast<uintptr_t>(window.get())) || drawerLeases.contains(reinterpret_cast<uintptr_t>(window.get())));
    lua_setfield(L, -2, "animating");
    lua_pushboolean(L,drawerLeases.contains(reinterpret_cast<uintptr_t>(window.get())));
    lua_setfield(L,-2,"drawerLeased");
    field("rounding",window->rounding());
    field("fadeAlpha", window->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value());
    field("workspaceFadeAlpha", window->alpha(Desktop::View::WINDOW_ALPHA_MOVE_TO_WORKSPACE)->value());
    field("movingFromMonitor", window->m_monitorMovedFrom);
    const auto flight = flights.find(reinterpret_cast<uintptr_t>(window.get()));
    field("minimizeProgress", flight == flights.end() ? -1 : flight->second.progress->value());
    lua_pushboolean(L, window->alpha(Desktop::View::WINDOW_ALPHA_MOVE_TO_WORKSPACE)->isBeingAnimated());
    lua_setfield(L, -2, "workspaceFading");
    return 1;
}

static void observe(PHLWINDOW window) {
    if (!window || !window->m_isMapped)
        return;
    const auto key = reinterpret_cast<uintptr_t>(window.get());
    if (listeners.contains(key))
        return;
    // A previously loaded observer (or the compositor alone) may have left an
    // X11 request cached before we attached. Only handle new protocol requests.
    if (window->m_xwaylandSurface)
        window->m_xwaylandSurface->m_state.requestsMinimize.reset();
    PHLWINDOWREF weak = window;
    auto requested = [weak] {
        const auto w = weak.lock();
        if (!w || !w->m_isMapped)
            return;
        auto& pendingRequest = w->m_xdgSurface
            ? w->m_xdgSurface->m_toplevel->m_state.requestsMinimize
            : w->m_xwaylandSurface->m_state.requestsMinimize;
        // XWayland retains this optional after WM_CHANGE_STATE / _NET_WM_STATE.
        // stateChanged also fires for fullscreen/maximize updates, including
        // toolkit updates when a sibling closes. Consume each request once so
        // those unrelated updates cannot replay an old restore for every window.
        const auto request = std::exchange(pendingRequest, std::nullopt);
        if (request.has_value())
            g_pEventManager->postEvent(SHyprIPCEvent{
                .event = "caelestia_minimize",
                .data = std::format("{:x},{}", reinterpret_cast<uintptr_t>(w.get()), request.value() ? 1 : 0)
            });
    };
    if (window->m_xdgSurface && window->m_xdgSurface->m_toplevel)
        listeners.emplace(key, window->m_xdgSurface->m_toplevel->m_events.stateChanged.listen(requested));
    else if (window->m_xwaylandSurface)
        listeners.emplace(key, window->m_xwaylandSurface->m_events.stateChanged.listen(requested));
}

APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash())
        throw std::runtime_error("caelestia-minimize: rebuild against the running Hyprland version");
    if (!HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "restore_from", restoreFrom) ||
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "animation_state", animationState) ||
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "minimize_to", minimizeTo) ||
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "cancel_minimize", cancelMinimize) ||
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "prepare_launch", prepareLaunch) ||
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "launch_state", launchState) ||
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "enable_drawer", enableDrawer) ||
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "claim_drawer", claimDrawer) ||
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "release_drawer", releaseDrawer) ||
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "complete_drawer", completeDrawer))
        throw std::runtime_error("caelestia-minimize: could not register restoration API");
    const auto functions = HyprlandAPI::findFunctionsByName(handle, "_ZNK7Desktop4View26CWindowAnimationController10animateOutEv");
    if (functions.size() != 1)
        throw std::runtime_error("caelestia-minimize: cannot locate native close animation context");
    closeMotionHook = HyprlandAPI::createFunctionHook(handle, functions[0].address, reinterpret_cast<void*>(&closeUp));
    if (!closeMotionHook || !closeMotionHook->hook())
        throw std::runtime_error("caelestia-minimize: cannot attach native close animation context");
    openedLate = Event::bus()->m_events.window.openLate.listen([](PHLWINDOW w) { animateLaunch(w, false); });
    activated = Event::bus()->m_events.window.active.listen([](PHLWINDOW w, Desktop::eFocusReason) { animateLaunch(w, true); });

    flightTimer = makeShared<CEventLoopTimer>(std::nullopt, [](auto timer, void*) {
        std::vector<std::pair<uintptr_t, bool>> finished;
        for (const auto& [key, flight] : flights) {
            const auto window = flight.window.lock();
            if (!stillOwnsGeometry(flight, window))
                finished.emplace_back(key, false);
            else {
                // Match native close's independent geometry and opacity clocks.
                if ((!flight.progress->isBeingAnimated() && !flight.fadeProgress->isBeingAnimated()) || Time::steadyNow() - flight.started > std::chrono::seconds(2))
                    finished.emplace_back(key, true);
            }
        }
        for (const auto& [key, hide] : finished)
            finishFlight(key, hide);
        std::vector<std::pair<uintptr_t,bool>> drawerDone;
        for(auto& [key,lease]:drawerLeases) {
            const auto w=lease.window.lock();
            if(!w || !w->m_isMapped || !w->m_workspace || w->m_workspace->m_name!=lease.workspace)
                drawerDone.emplace_back(key,false);
            else if(!w->m_workspace->isVisibleNotCovered() ||
                    (!lease.claimed && Time::steadyNow()-lease.started>std::chrono::milliseconds(600)) ||
                    Time::steadyNow()-lease.started>std::chrono::seconds(2))
                drawerDone.emplace_back(key,true);
            else {
                const auto pos=w->positionAnimation()->goal();
                const auto size=w->sizeAnimation()->goal();
                if(pos!=lease.goalPosition || size!=lease.goalSize) {
                    lease.goalPosition=pos; lease.goalSize=size;
                    w->positionAnimation()->warp(); w->sizeAnimation()->warp();
                    drawerEvent(key,lease);
                }
                if(!lease.released) w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value()=0.F;
            }
        }
        for(const auto& [key,complete]:drawerDone) finishDrawer(key,complete);
        if (!flights.empty() || !drawerLeases.empty())
            timer->updateTimeout(std::chrono::milliseconds(8));
    }, nullptr);
    g_pEventLoopManager->addTimer(flightTimer);
    opened = Event::bus()->m_events.window.open.listen([](PHLWINDOW w) { observe(w); });
    closed = Event::bus()->m_events.window.close.listen([](PHLWINDOW w) {
        // Closing during a minimize starts at the on-screen presentation,
        // rather than flashing back to its original geometry before the snapshot.
        auto flight = flights.extract(reinterpret_cast<uintptr_t>(w.get()));
        if (!flight.empty()) {
            flight.mapped().progress->resetAllCallbacks();
            flight.mapped().progress->warp();
            flight.mapped().fadeProgress->resetAllCallbacks();
            flight.mapped().fadeProgress->warp();
        }
        const auto drawer=drawerLeases.extract(reinterpret_cast<uintptr_t>(w.get()));
        if(!drawer.empty()) drawerEvent(reinterpret_cast<uintptr_t>(w.get()),drawer.mapped(),true);
        listeners.erase(reinterpret_cast<uintptr_t>(w.get()));
    });
    for (const auto& w : Desktop::windowState()->windows())
        observe(w);
    g_pEventManager->postEvent(SHyprIPCEvent{.event="caelestia_drawer_ready",.data="1"});
    return {"caelestia-minimize", "Native window handoff for Caelestia drawers", "luancaldeira", "2.0"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    drawerAvailable=false;
    while(!drawerLeases.empty()) finishDrawer(drawerLeases.begin()->first,true);
    if (flightTimer) {
        flightTimer->cancel();
        g_pEventLoopManager->removeTimer(flightTimer);
        flightTimer.reset();
    }
    while (!flights.empty())
        finishFlight(flights.begin()->first, true);
    openedLate.reset();
    activated.reset();
    launchOrigins.clear();
    if (closeMotionHook) { closeMotionHook->unhook(); closeMotionHook = nullptr; }
    opened.reset();
    closed.reset();
    listeners.clear();
}
