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

static std::string normalizedClass(std::string text) {
    std::ranges::transform(text, text.begin(), [](unsigned char c) { return std::tolower(c); });
    if (text.ends_with(".desktop")) text.resize(text.size() - 8);
    return text;
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
        const auto scale = std::min({0.16, 160. / std::max(1., context.size.from.x), 100. / std::max(1., context.size.from.y)});
        context.size.to = (context.size.from * scale).clamp({8,8}, context.size.from);
        context.pos.to = {context.pos.from.x + (context.size.from.x - context.size.to.x) / 2.,
            monitor->m_position.y - context.size.to.y - 12.};
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
    const auto key = reinterpret_cast<uintptr_t>(window.get());
    if (flights.contains(key)) {
        lua_pushboolean(L, true);
        return 1;
    }
    auto& flight = flights[key];
    flight.window = window;
    flight.fromPosition = position->value();
    flight.fromSize = size->value();
    flight.goalPosition = position->goal();
    flight.goalSize = size->goal();
    flight.toPosition = Vector2D(values[0], values[1]);
    flight.toSize = Vector2D(values[2], values[3]);
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
    Animation::mgr()->createAnimation(0.F, flight.progress, position->getConfig().lock(), window, AVARDAMAGE_ENTIRE);
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
        const auto fadeProgress = std::clamp((progress - 0.72F) / 0.28F, 0.F, 1.F);
        w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value() = f.fromAlpha * (1.F - fadeProgress * fadeProgress * (3.F - 2.F * fadeProgress));
        w->updateWindowDecos();
    });
    *flight.progress = 1.F;
    flightTimer->updateTimeout(std::chrono::milliseconds(8));
    lua_pushboolean(L, true);
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
    lua_pushboolean(L, window->positionAnimation()->isBeingAnimated() || window->sizeAnimation()->isBeingAnimated() || flights.contains(reinterpret_cast<uintptr_t>(window.get())));
    lua_setfield(L, -2, "animating");
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
        !HyprlandAPI::addLuaFunction(handle, "caelestia_minimize", "launch_state", launchState))
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
                // A spring can keep settling after the presented rectangle has
                // arrived. Finish at pixel precision rather than displaying a
                // stationary thumbnail while waiting for its mathematical tail.
                const auto distance = std::max({std::abs(flight.toPosition.x - flight.fromPosition.x),
                    std::abs(flight.toPosition.y - flight.fromPosition.y), std::abs(flight.toSize.x - flight.fromSize.x),
                    std::abs(flight.toSize.y - flight.fromSize.y)});
                const bool arrived = flight.progress->value() > 0.9F && distance * (1.F - flight.progress->value()) <= 1.;
                if (arrived || !flight.progress->isBeingAnimated() || Time::steadyNow() - flight.started > std::chrono::seconds(2))
                    finished.emplace_back(key, true);
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
            flight.mapped().progress->resetAllCallbacks();
            flight.mapped().progress->warp();
        }
        listeners.erase(reinterpret_cast<uintptr_t>(w.get()));
    });
    for (const auto& w : Desktop::windowState()->windows())
        observe(w);
    return {"caelestia-minimize", "Native minimize and restore flights for the Caelestia hub", "luancaldeira", "1.5"};
}

APICALL EXPORT void PLUGIN_EXIT() {
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
