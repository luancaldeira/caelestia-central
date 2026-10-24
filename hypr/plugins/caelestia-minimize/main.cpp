#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/plugins/HookSystem.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/config/shared/animation/AnimationTree.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
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
#include <hyprland/src/desktop/Workspace.hpp>
#include "BubbleMotion.hpp"

extern "C" {
#include <lua.h>
}

// The shell owns workspace restoration. The native animation starts only after
// the layout has calculated its final geometry. Close motion changes only the
// native snapshot animation context, after the application has actually closed.
static CHyprSignalListener opened, closed, openedLate, activated;
static CFunctionHook* closeMotionHook = nullptr;
static CFunctionHook* roundingHook = nullptr;
static CFunctionHook* roundingPowerHook = nullptr;
static std::unordered_map<uintptr_t, CHyprSignalListener> listeners;

struct BubbleFlight {
    PHLWINDOWREF window;
    PHLANIMVAR<float> progress;
    Vector2D fromPosition, fromSize, goalPosition, goalSize, toPosition, toSize;
    float fadeGoal = 1.F;
    float fromAlpha = 1.F;
    std::string workspace;
    Time::steady_tp started, lastEvent;
    bool minimizing = true;
};
static std::unordered_map<uintptr_t, BubbleFlight> flights;
static SP<CEventLoopTimer> flightTimer;

struct LaunchOrigin {
    std::unordered_set<std::string> classes;
    std::unordered_set<uintptr_t> existing;
    Vector2D position, size;
    Time::steady_tp expires;
    uintptr_t focusedBefore = 0;
};
static std::vector<LaunchOrigin> launchOrigins;
static std::unordered_map<std::string, std::pair<Vector2D, Vector2D>> barOrigins;
static std::string lastLaunchAddress;
static Vector2D lastLaunchPosition, lastLaunchSize;

static bool startBubble(PHLWINDOW window, Vector2D portPosition, Vector2D portSize, bool entering);
static void finishFlight(uintptr_t key, bool hide);

static BubbleMotion::Rect rect(const Vector2D& position, const Vector2D& size) {
    return {position.x, position.y, size.x, size.y};
}

static void bubbleEvent(uintptr_t key, BubbleFlight& flight, bool done = false) {
    const auto window = flight.window.lock();
    const auto now = Time::steadyNow();
    if (!done && now - flight.lastEvent < std::chrono::milliseconds(16)) return;
    flight.lastEvent = now;
    const bool visible = window && window->m_workspace && window->m_workspace->isVisible();
    const auto body = window ? rect(window->positionAnimation()->value(), window->sizeAnimation()->value()) : rect(flight.toPosition, flight.toSize);
    g_pEventManager->postEvent(SHyprIPCEvent{.event = "caelestia_bubble", .data = std::format(
        R"({{"address":"{:x}","x":{:.3f},"y":{:.3f},"width":{:.3f},"height":{:.3f},"portX":{:.3f},"portY":{:.3f},"portWidth":{:.3f},"portHeight":{:.3f},"openness":{:.4f},"visible":{},"done":{}}})",
        key, body.x, body.y, body.width, body.height, flight.toPosition.x, flight.toPosition.y, flight.toSize.x, flight.toSize.y,
        std::clamp(flight.progress->value(), 0.F, 1.F), visible ? "true" : "false", done ? "true" : "false")});
}

// Read temporary rounding directly at render time without changing window rules.
static float bubbleRounding(Desktop::View::CWindow* window) {
    using Original = float (*)(Desktop::View::CWindow*);
    const auto original = reinterpret_cast<Original>(roundingHook->m_original)(window);
    const auto it = flights.find(reinterpret_cast<uintptr_t>(window));
    if (it == flights.end()) return original;
    return BubbleMotion::rounding(rect(window->positionAnimation()->value(), window->sizeAnimation()->value()),
                                 it->second.progress->value(), original);
}

static float bubbleRoundingPower(Desktop::View::CWindow* window) {
    using Original = float (*)(Desktop::View::CWindow*);
    const auto original = reinterpret_cast<Original>(roundingPowerHook->m_original)(window);
    const auto it = flights.find(reinterpret_cast<uintptr_t>(window));
    if (it == flights.end()) return original;
    return 2.F + (original - 2.F) * BubbleMotion::smooth(.34, .88, it->second.progress->value());
}

static std::string normalizedClass(std::string text) {
    std::ranges::transform(text, text.begin(), [](unsigned char c) { return std::tolower(c); });
    if (text.ends_with(".desktop")) text.resize(text.size() - 8);
    return text;
}

struct DepartureGeometry {
    Vector2D position, size;
};

// Closing retains its upward departure; minimizing uses the dock bubble path.
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

static int setBarOrigin(lua_State* L) {
    size_t length = 0;
    const auto name = lua_tolstring(L, 1, &length);
    double v[4] = {};
    bool valid = name && length > 0 && length < 256;
    for (int i = 0; i < 4; ++i) {
        int number = 0;
        v[i] = lua_tonumberx(L, i + 2, &number);
        valid = valid && number && std::isfinite(v[i]) && std::abs(v[i]) <= 100000 && (i < 2 || (v[i] >= 8 && v[i] <= 80));
    }
    if (valid) barOrigins[std::string(name, length)] = {{v[0],v[1]}, {v[2],v[3]}};
    lua_pushboolean(L, valid);
    return 1;
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
    if (match == launchOrigins.end()) {
        // Other launchers and keyboard shortcuts use the same dock origin.
        // Transient dialogs retain their own parent's normal animation.
        const auto monitor = window->m_monitor.lock();
        if (existing || !monitor || window->parent() || window->m_X11DoesntWantBorders) return;
        const auto port = barOrigins.find(monitor->m_name);
        const auto position = port == barOrigins.end() ? Vector2D(monitor->m_position.x + monitor->m_size.x/2.-24., monitor->m_position.y + monitor->m_size.y-6.) : port->second.first;
        const auto size = port == barOrigins.end() ? Vector2D(48.,48.) : port->second.second;
        startBubble(window, position, size, true);
        return;
    }
    const auto origin = *match;
    launchOrigins.erase(match);
    auto& position = window->positionAnimation();
    auto& size = window->sizeAnimation();
    if (!position || !size || !position->enabled() || !size->enabled() || window->m_ruleApplicator->noAnim().valueOrDefault()) return;
    if (!startBubble(window, origin.position, origin.size, true)) return;
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

static bool stillOwnsGeometry(const BubbleFlight& flight, PHLWINDOW window) {
    return window && window->m_isMapped && window->m_workspace && window->m_workspace->m_name == flight.workspace &&
        window->positionAnimation()->goal() == flight.goalPosition && window->sizeAnimation()->goal() == flight.goalSize;
}

static void finishFlight(uintptr_t key, bool hide) {
    auto node = flights.extract(key);
    if (node.empty())
        return;
    auto& flight = node.mapped();
    bubbleEvent(key, flight, true);
    flight.progress->resetAllCallbacks();
    flight.progress->warp();
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
    if (flight.minimizing)
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
    lua_pushboolean(L, startBubble(window, {values[0], values[1]}, {values[2], values[3]}, true));
    return 1;
}

// Native geometry stays full resolution. Only its presented rectangle, rounding
// and late absorption opacity change while it joins the shell's blob surface.
static bool startBubble(PHLWINDOW window, Vector2D portPosition, Vector2D portSize, bool entering) {
    if (!window || !window->m_workspace || window->m_ruleApplicator->noAnim().valueOrDefault()) return false;
    auto& position = window->positionAnimation();
    auto& size = window->sizeAnimation();
    const auto monitor = window->m_monitor.lock();
    if (!monitor || !position || !size || !position->enabled() || !size->enabled()) return false;
    const auto key = reinterpret_cast<uintptr_t>(window.get());
    const auto existing = flights.find(key);
    if (existing != flights.end() && stillOwnsGeometry(existing->second, window)) {
        // Redirect the same animated variable, preserving its current value and
        // spring velocity rather than restarting at an endpoint.
        auto& f = existing->second;
        if (entering && f.minimizing)
            g_pEventManager->postEvent(SHyprIPCEvent{.event = "caelestia_minimize_done", .data = std::format("{:x},{},0", key, window->getPID())});
        f.minimizing = !entering;
        f.started = Time::steadyNow();
        *f.progress = entering ? 1.F : 0.F;
        flightTimer->updateTimeout(std::chrono::milliseconds(8));
        return true;
    }
    const auto presentedPosition = position->value();
    const auto presentedSize = size->value();
    const auto presentedAlpha = window->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value();
    finishFlight(key, false);
    // The initial body belongs behind the bar, including for callers that
    // still supply an icon or preview rectangle from an older shell version.
    const auto registered = barOrigins.find(monitor->m_name);
    const auto center = std::clamp(portPosition.x + portSize.x / 2., monitor->m_position.x + 24., monitor->m_position.x + monitor->m_size.x - 24.);
    portPosition = {center - 24., registered == barOrigins.end() ? monitor->m_position.y + monitor->m_size.y - 6. : registered->second.first.y};
    portSize = {48.,48.};
    auto& f = flights[key];
    f.window = window;
    f.minimizing = !entering;
    f.fromPosition = entering ? position->goal() : presentedPosition;
    f.fromSize = entering ? size->goal() : presentedSize;
    f.goalPosition = position->goal();
    f.goalSize = size->goal();
    f.toPosition = portPosition;
    f.toSize = portSize;
    f.workspace = window->m_workspace->m_name;
    f.started = Time::steadyNow();
    auto& fade = window->alpha(Desktop::View::WINDOW_ALPHA_FADE);
    f.fadeGoal = fade->goal();
    f.fromAlpha = entering ? f.fadeGoal : presentedAlpha;
    fade->setValueAndWarp(f.fadeGoal);
    position->warp();
    size->warp();
    Animation::mgr()->createAnimation(entering ? 0.F : 1.F, f.progress,
        Config::animationTree()->getAnimationPropertyConfig("windowsMove"), window, AVARDAMAGE_ENTIRE);
    const auto update = [key](auto) {
        const auto it = flights.find(key);
        if (it == flights.end()) return;
        auto& f = it->second;
        const auto w = f.window.lock();
        if (!stillOwnsGeometry(f, w)) return;
        const auto p = std::clamp(f.progress->value(), 0.F, 1.F);
        const auto geometry = BubbleMotion::frame(rect(f.toPosition, f.toSize), rect(f.fromPosition, f.fromSize), p);
        w->positionAnimation()->value() = {geometry.x, geometry.y};
        w->sizeAnimation()->value() = {geometry.width, geometry.height};
        w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value() = f.fromAlpha * BubbleMotion::alpha(p);
        w->updateWindowDecos();
        bubbleEvent(key, f);
    };
    f.progress->setUpdateCallback(update);
    update(nullptr);
    *f.progress = entering ? 1.F : 0.F;
    flightTimer->updateTimeout(std::chrono::milliseconds(8));
    return true;
}

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
    lua_pushboolean(L, startBubble(window, {values[0], values[1]}, {values[2], values[3]}, false));
    return 1;
}

static int cancelMinimize(lua_State* L) {
    const auto window = luaWindow(L);
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
    field("rounding", window->rounding());
    field("roundingPower", window->roundingPower());
    lua_pushboolean(L, window->positionAnimation()->isBeingAnimated() || window->sizeAnimation()->isBeingAnimated() || flights.contains(reinterpret_cast<uintptr_t>(window.get())));
    lua_setfield(L, -2, "animating");
    field("fadeAlpha", window->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value());
    field("workspaceFadeAlpha", window->alpha(Desktop::View::WINDOW_ALPHA_MOVE_TO_WORKSPACE)->value());
    field("movingFromMonitor", window->m_monitorMovedFrom);
    const auto flight = flights.find(reinterpret_cast<uintptr_t>(window.get()));
    field("minimizeProgress", flight == flights.end() ? -1 : flight->second.progress->value());
    if (flight != flights.end()) { field("portX", flight->second.toPosition.x); field("portY", flight->second.toPosition.y); }
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
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "set_bar_origin", setBarOrigin))
        throw std::runtime_error("caelestia-minimize: could not register restoration API");
    const auto functions = HyprlandAPI::findFunctionsByName(handle, "_ZNK7Desktop4View26CWindowAnimationController10animateOutEv");
    if (functions.size() != 1)
        throw std::runtime_error("caelestia-minimize: cannot locate native close animation context");
    closeMotionHook = HyprlandAPI::createFunctionHook(handle, functions[0].address, reinterpret_cast<void*>(&closeUp));
    if (!closeMotionHook || !closeMotionHook->hook())
        throw std::runtime_error("caelestia-minimize: cannot attach native close animation context");
    const auto roundingFunctions = HyprlandAPI::findFunctionsByName(handle, "_ZN7Desktop4View7CWindow8roundingEv");
    const auto powerFunctions = HyprlandAPI::findFunctionsByName(handle, "_ZN7Desktop4View7CWindow13roundingPowerEv");
    if (roundingFunctions.size() != 1 || powerFunctions.size() != 1)
        throw std::runtime_error("caelestia-minimize: cannot locate bubble rounding methods");
    roundingHook = HyprlandAPI::createFunctionHook(handle, roundingFunctions[0].address, reinterpret_cast<void*>(&bubbleRounding));
    roundingPowerHook = HyprlandAPI::createFunctionHook(handle, powerFunctions[0].address, reinterpret_cast<void*>(&bubbleRoundingPower));
    if (!roundingHook || !roundingPowerHook || !roundingHook->hook() || !roundingPowerHook->hook())
        throw std::runtime_error("caelestia-minimize: cannot attach bubble rounding methods");
    openedLate = Event::bus()->m_events.window.openLate.listen([](PHLWINDOW w) { animateLaunch(w, false); });
    activated = Event::bus()->m_events.window.active.listen([](PHLWINDOW w, Desktop::eFocusReason) { animateLaunch(w, true); });

    flightTimer = makeShared<CEventLoopTimer>(std::nullopt, [](auto timer, void*) {
        std::vector<std::pair<uintptr_t, bool>> finished;
        for (const auto& [key, flight] : flights) {
            const auto window = flight.window.lock();
            if (!stillOwnsGeometry(flight, window))
                finished.emplace_back(key, false);
            else {
                // The same reversible spring drives the body and its membrane.
                if (!flight.progress->isBeingAnimated() ||
                    (Time::steadyNow() - flight.started > std::chrono::milliseconds(40) &&
                     (flight.minimizing ? flight.progress->value() <= .001F : flight.progress->value() >= .999F)) ||
                    Time::steadyNow() - flight.started > std::chrono::seconds(2))
                    finished.emplace_back(key, flight.minimizing);
            }
        }
        for (const auto& [key, hide] : finished)
            finishFlight(key, hide);
        if (!flights.empty())
            timer->updateTimeout(std::chrono::milliseconds(8));
    }, nullptr);
    g_pEventLoopManager->addTimer(flightTimer);
    opened = Event::bus()->m_events.window.open.listen([](PHLWINDOW w) { observe(w); });
    closed = Event::bus()->m_events.window.close.listen([](PHLWINDOW w) {
        // Closing during a minimize starts at the on-screen presentation,
        // rather than flashing back to its original geometry before the snapshot.
        auto flight = flights.extract(reinterpret_cast<uintptr_t>(w.get()));
        if (!flight.empty()) {
            bubbleEvent(reinterpret_cast<uintptr_t>(w.get()), flight.mapped(), true);
            flight.mapped().progress->resetAllCallbacks();
            flight.mapped().progress->warp();
        }
        listeners.erase(reinterpret_cast<uintptr_t>(w.get()));
    });
    for (const auto& w : Desktop::windowState()->windows())
        observe(w);
    g_pEventManager->postEvent(SHyprIPCEvent{.event="caelestia_bubble_ready",.data="1"});
    return {"caelestia-minimize", "Native minimize and restore flights for the Caelestia hub", "luancaldeira", "1.8"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    if (flightTimer) {
        flightTimer->cancel();
        g_pEventLoopManager->removeTimer(flightTimer);
        flightTimer.reset();
    }
    while (!flights.empty())
        finishFlight(flights.begin()->first, flights.begin()->second.minimizing);
    if (roundingHook) { roundingHook->unhook(); roundingHook = nullptr; }
    if (roundingPowerHook) { roundingPowerHook->unhook(); roundingPowerHook = nullptr; }
    openedLate.reset();
    activated.reset();
    launchOrigins.clear();
    barOrigins.clear();
    if (closeMotionHook) { closeMotionHook->unhook(); closeMotionHook = nullptr; }
    opened.reset();
    closed.reset();
    listeners.clear();
}
