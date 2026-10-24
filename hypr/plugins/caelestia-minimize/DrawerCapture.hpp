#pragma once

#include <hyprland/src/managers/screenshare/ScreenshareManager.hpp>
#include <hyprland/src/render/decorations/IHyprWindowDecoration.hpp>
#include <hyprland/src/render/pass/RendererHintsPassElement.hpp>

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

static CBox geometry(PHLWINDOW w) {
    CBox box = w->geometricBox(Desktop::View::IGeometric::GEOMETRIC_CURRENT);
    if (w->m_X11DoesntWantBorders || !w->m_ruleApplicator->decorate().valueOrDefault() ||
        Fullscreen::controller()->getFullscreenModes(w).internal == Fullscreen::FSMODE_FULLSCREEN)
        return box;
    box = g_pDecorationPositioner->getBoxWithIncludedDecos(w);
    // Include native title bars even when configured outside the main surface,
    // and borders, but leave soft shadows outside the moving content frame.
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

    // The desktop lease remains masked. Temporarily unmask only while building
    // this offscreen pass, so native text, buttons, rounding and opacity are
    // captured with the client. No monitor render can run inside this call.
    auto& fade = w->alpha(Desktop::View::WINDOW_ALPHA_FADE)->value();
    const auto savedFade = fade;
    const auto savedSnapshot = renderer.m_bRenderingSnapshot;
    const auto savedFeedback = renderer.m_bBlockSurfaceFeedback;
    fade = found->second.fade;
    renderer.m_bRenderingSnapshot = true;
    renderer.m_bBlockSurfaceFeedback = renderer.shouldRenderWindow(w);
    Render::SRenderModifData translation;
    const auto offset = (monitor->m_position - found->second.box.pos()) * monitor->m_scale;
    translation.modifs.emplace_back(Render::SRenderModifData::RMOD_TYPE_TRANSLATE, offset);
    renderer.addPassElement(makeUnique<CRendererHintsPassElement>(CRendererHintsPassElement::SData{translation}));
    (renderer.*&RendererAccess::renderWindow)(w, monitor, Time::steadyNow(), true, Render::RENDER_PASS_ALL, false, false);
    renderer.addPassElement(makeUnique<CRendererHintsPassElement>(CRendererHintsPassElement::SData{Render::SRenderModifData{}}));
    renderer.m_bBlockSurfaceFeedback = savedFeedback;
    renderer.m_bRenderingSnapshot = savedSnapshot;
    fade = savedFade;
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
