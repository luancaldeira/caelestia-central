#pragma once
#include <algorithm>
#include <cmath>

namespace BubbleMotion {
struct Rect { double x, y, width, height; };
inline double smooth(double from, double to, double value) {
    const auto p = std::clamp((value - from) / (to - from), 0., 1.);
    return p * p * (3. - 2. * p);
}
// One path is evaluated in both directions. The lower edge stays attached
// briefly while the body grows, then lifts away from the dock's surface.
inline Rect frame(const Rect& port, const Rect& body, double openness) {
    const auto p = std::clamp(openness, 0., 1.);
    const auto stretch = .10 * std::pow(std::sin(3.141592653589793 * p), 2.) * (1. - p);
    const auto width = (port.width + (body.width - port.width) * p) * (1. - stretch);
    const auto height = (port.height + (body.height - port.height) * p) * (1. + stretch);
    const auto center = port.x + port.width / 2. + (body.x + body.width / 2. - port.x - port.width / 2.) * p;
    const auto bottom = port.y + port.height + (body.y + body.height - port.y - port.height) * std::pow(p, 1.6);
    return {center - width / 2., bottom - height, width, height};
}
inline double attachment(double openness) { return 1. - smooth(.12, .54, openness); }
inline double rounding(const Rect& rect, double openness, double normal) {
    const auto radius = std::min(rect.width, rect.height) / 2.;
    return std::clamp(normal + (radius - normal) * (1. - smooth(.08, .72, openness)), 0., radius);
}
inline double alpha(double openness) { return smooth(0., .14, openness); }
}
