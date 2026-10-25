#pragma once

#include <hyprland/src/managers/screenshare/ScreenshareManager.hpp>
#include <hyprland/src/render/decorations/IHyprWindowDecoration.hpp>
#include <hyprland/src/render/decorations/CHyprDropShadowDecoration.hpp>
#include <hyprland/src/config/ConfigValue.hpp>

// Hyprland's standard toplevel export intentionally omits server decorations.
// Opt in only the owning shell's short-lived drawer captures. Other screencopy
// clients, monitor exports and the shell's ordinary thumbnails keep upstream
// behavior. The complete compositor ABI is checked before these hooks attach.
namespace DrawerCapture {
using namespace Screenshare;

// Access only the fields needed to extend a frame before buffer negotiation.
// Explicit template instantiation permits private member pointers without
// changing the compositor headers or redefining their access specifiers.
template<class Tag, typename Tag::Type Member> struct Access {
    friend typename Tag::Type field(Tag) { return Member; }
};
#define DRAWER_FIELD(Tag, Owner, TypeName, Member) \
    struct Tag { using Type = TypeName Owner::*; friend Type field(Tag); }; \
    template struct Access<Tag, &Owner::Member>
DRAWER_FIELD(SessionType, CScreenshareSession, eScreenshareType, m_type);
DRAWER_FIELD(SessionWindow, CScreenshareSession, PHLWINDOWREF, m_window);
DRAWER_FIELD(SessionClient, CScreenshareSession, wl_client*, m_client);
DRAWER_FIELD(FrameSize, CScreenshareFrame, Vector2D, m_bufferSize);
#undef DRAWER_FIELD

struct Frame {
    WP<CScreenshareFrame> lifetime;
    PHLWINDOWREF window;
    CBox box;
    float fade;
};
static std::unordered_map<const CScreenshareFrame*, Frame> frames;
static CFunctionHook* nextHook = nullptr;
static CFunctionHook* renderHook = nullptr;
static pid_t shellPid = 0;
struct RendererAccess : Render::IHyprRenderer { using IHyprRenderer::renderWindow; };

static bool enabled() { return nextHook && renderHook && shellPid > 0; }

static CBox solidGeometry(PHLWINDOW w) {
    CBox box = w->geometricBox(Desktop::View::IGeometric::GEOMETRIC_CURRENT);
    if (w->m_X11DoesntWantBorders || !w->m_ruleApplicator->decorate().valueOrDefault() ||
        Fullscreen::controller()->getFullscreenModes(w).internal == Fullscreen::FSMODE_FULLSCREEN)
        return box;
    box = g_pDecorationPositioner->getBoxWithIncludedDecos(w);
    // The drawer's solid surface excludes the soft shadow margin.
    for (const auto& deco : w->m_windowDecorations) {
        if ((deco->getDecorationFlags() & DECORATION_NON_SOLID) || deco->getDecorationType() == DECORATION_SHADOW) continue;
        const auto part = g_pDecorationPositioner->getWindowDecorationBox(deco.get());
        if (part.w <= 0 || part.h <= 0) continue;
        const auto left = std::min(box.x, part.x), top = std::min(box.y, part.y);
        const auto right = std::max(box.x + box.w, part.x + part.w);
        const auto bottom = std::max(box.y + box.h, part.y + part.h);
        box = {left, top, right - left, bottom - top};
    }
    return box;
}

static CBox geometry(PHLWINDOW w) {
    auto box=solidGeometry(w);
    if(w->m_X11DoesntWantBorders || !w->m_ruleApplicator->decorate().valueOrDefault() ||
       w->m_ruleApplicator->noShadow().valueOrDefault() ||
       Fullscreen::controller()->getFullscreenModes(w).internal==Fullscreen::FSMODE_FULLSCREEN)
        return box;
    static auto enabled=CConfigValue<Config::INTEGER>("decoration:shadow:enabled");
    static auto range=CConfigValue<Config::INTEGER>("decoration:shadow:range");
    static auto scale=CConfigValue<Config::FLOAT>("decoration:shadow:scale");
    static auto offset=CConfigValue<Config::VEC2>("decoration:shadow:offset");
    if(!*enabled) return box;
    // Use the compositor's shadow footprint even before the first decoration
    // render has populated its extents. Buffer negotiation and the drawer event
    // must agree from the first frame, including asynchronous app startup.
    auto shadow=g_pDecorationPositioner->getBoxWithIncludedDecos(w);
    shadow.expand(*range).scaleFromCenter(std::clamp(*scale,0.F,1.F)).translate({(*offset).x,(*offset).y}).expand(2);
    const auto left=std::min(box.x,shadow.x),top=std::min(box.y,shadow.y);
    const auto right=std::max(box.x+box.w,shadow.x+shadow.w),bottom=std::max(box.y+box.h,shadow.y+shadow.h);
    return {left,top,right-left,bottom-top};
}

static UP<CScreenshareFrame> nextFrame(CScreenshareSession* session, bool cursor) {
    using Original = UP<CScreenshareFrame> (*)(CScreenshareSession*, bool);
    auto frame = reinterpret_cast<Original>(nextHook->m_original)(session, cursor);
    std::erase_if(frames, [](const auto& item) { return item.second.lifetime.expired(); });
    if (!frame || !enabled() || session->*field(SessionType{}) != SHARE_WINDOW) return frame;
    pid_t pid = 0;
    wl_client_get_credentials(session->*field(SessionClient{}), &pid, nullptr, nullptr);
    if (pid != shellPid) return frame;
    const auto w = (session->*field(SessionWindow{})).lock();
    const auto lease = w ? drawerLeases.find(reinterpret_cast<uintptr_t>(w.get())) : drawerLeases.end();
    if (lease == drawerLeases.end()) return frame;
    const auto monitor = session->monitor();
    if (!monitor) return frame;
    const auto box = geometry(w);
    frame.get()->*field(FrameSize{}) = (box.size() * monitor->m_scale).round();
    frames.insert_or_assign(frame.get(), Frame{frame, w, box, lease->second.fadeGoal});
    return frame;
}

static void renderWindow(CScreenshareFrame* frame) {
    using Original = void (*)(CScreenshareFrame*);
    const auto found = frames.find(frame);
    if (found == frames.end() || found->second.lifetime.expired()) {
        reinterpret_cast<Original>(renderHook->m_original)(frame);
        return;
    }
    const auto w = found->second.window.lock();
    const auto monitor = w ? w->m_monitor.lock() : nullptr;
    if (!w || !monitor || frame->done()) return;
    auto& renderer = *g_pHyprRenderer;
    const auto size = frame->bufferSize();
    renderer.m_renderData.fbSize = size;
    renderer.setProjectionType(Render::RPT_EXPORT);
    renderer.m_renderData.transformDamage = false;
    renderer.setViewport(0, 0, size.x, size.y);

    // Build AND execute this private pass in capture-local coordinates. A render
    // hint only translates drawing: surface damage and decoration scissors keep
    // their desktop coordinates, leaving transparent strips at the top/left.
    // Restore the current pose before returning; layout goals and client size
    // never change and no monitor render can interleave with this call.
    auto& fade = w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value();
    auto& position = w->positionAnimation()->value();
    const auto savedFade = fade;
    const auto savedPosition = position;
    const auto savedSnapshot = renderer.m_bRenderingSnapshot;
    const auto savedFeedback = renderer.m_bBlockSurfaceFeedback;
    const auto savedNoSimplify = renderer.m_renderData.noSimplify;
    const auto savedModif = renderer.m_renderData.renderModif;
    Hyprutils::Utils::CScopeGuard restore{[&] {
        position = savedPosition;
        for(const auto& decoration:w->m_windowDecorations)
            if(decoration->getDecorationType()==DECORATION_SHADOW) decoration->updateWindow(w);
        fade = savedFade;
        renderer.m_bBlockSurfaceFeedback = savedFeedback;
        renderer.m_bRenderingSnapshot = savedSnapshot;
        renderer.m_renderData.noSimplify = savedNoSimplify;
        renderer.m_renderData.renderModif = savedModif;
    }};
    // Workspace visibility does not mean the native client is being drawn:
    // the drawer deliberately masks it at fade=0. Its capture must then send
    // presentation/frame feedback, or Qt/GTK clients stop painting and reveal
    // their pending content only after the native handoff.
    renderer.m_bBlockSurfaceFeedback = savedFade > 0.F && renderer.shouldRenderWindow(w);
    fade = found->second.fade;
    position += monitor->m_position - found->second.box.pos();
    // Native shadows cache their box independently of the animated position.
    // Refresh that cache in the same local space, then restore it above.
    for(const auto& decoration:w->m_windowDecorations)
        if(decoration->getDecorationType()==DECORATION_SHADOW) decoration->updateWindow(w);
    renderer.m_bRenderingSnapshot = true;
    renderer.m_renderData.noSimplify = true;
    renderer.m_renderData.renderModif = {};
    // Some decoration plugins (including this Hyprbars version) append directly
    // to m_renderPass instead of currentPass(). Isolate that queue as well, so
    // they execute inside this scope rather than after the pose is restored.
    auto parentPass = std::move(renderer.m_renderPass);
    renderer.m_renderPass = {};
    Hyprutils::Utils::CScopeGuard restorePass{[&] { renderer.m_renderPass = std::move(parentPass); }};
    auto redirect = renderer.redirectPass(&renderer.m_renderPass);
    (renderer.*&RendererAccess::renderWindow)(w, monitor, Time::steadyNow(), true, Render::RENDER_PASS_ALL, false, false);
    renderer.m_renderPass.render(CRegion{CBox{{}, size}});
}

static void attach(HANDLE handle) {
    const auto next = HyprlandAPI::findFunctionsByName(handle, "_ZN11Screenshare19CScreenshareSession9nextFrameEb");
    const auto render = HyprlandAPI::findFunctionsByName(handle, "_ZN11Screenshare17CScreenshareFrame12renderWindowEv");
    if (next.size() != 1 || render.size() != 1)
        throw std::runtime_error("caelestia-minimize: cannot locate decorated drawer export");
    nextHook = HyprlandAPI::createFunctionHook(handle, next[0].address, reinterpret_cast<void*>(&nextFrame));
    renderHook = HyprlandAPI::createFunctionHook(handle, render[0].address, reinterpret_cast<void*>(&renderWindow));
    if (!nextHook || !renderHook || !nextHook->hook() || !renderHook->hook())
        throw std::runtime_error("caelestia-minimize: cannot attach decorated drawer export");
}

static void detach() {
    shellPid = 0;
    if (renderHook) { renderHook->unhook(); renderHook = nullptr; }
    if (nextHook) { nextHook->unhook(); nextHook = nullptr; }
    frames.clear();
}
}
