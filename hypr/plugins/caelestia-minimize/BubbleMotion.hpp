#pragma once
#include <algorithm>
#include <cmath>

namespace BubbleMotion {
struct Rect { double x, y, width, height; };
inline double smooth(double from, double to, double value) {
    const auto p = std::clamp((value - from) / (to - from), 0., 1.);
    return p * p * (3. - 2. * p);
}
// The closed port is completely behind the bar. Grow through its surface
// before lifting away; evaluate the same path backwards for absorption.
inline Rect frame(const Rect& port, const Rect& body, double openness) {
    const auto p = std::clamp(openness, 0., 1.);
    const auto stretch = .10 * std::pow(std::sin(3.141592653589793 * p), 2.) * (1. - p);
    const auto width = (port.width + (body.width - port.width) * p) * (1. - stretch);
    const auto height = (port.height + (body.height - port.height) * p) * (1. + stretch);
    const auto center = port.x + port.width / 2. + (body.x + body.width / 2. - port.x - port.width / 2.) * smooth(.52, 1., p);
    const auto surface = port.y - 4.;
    const auto rootedBottom = surface + 10.;
    const auto bottom = p <= .58 ? port.y + port.height + (rootedBottom - port.y - port.height) * smooth(0., .26, p)
        : rootedBottom + (body.y + body.height - rootedBottom) * smooth(.58, 1., p);
    return {center - width / 2., bottom - height, width, height};
}
inline double attachment(double openness) { return 1. - smooth(.62, .86, openness); }
inline double rounding(const Rect& rect, double openness, double normal) {
    const auto radius = std::min(rect.width, rect.height) / 2.;
    return std::clamp(normal + (radius - normal) * (1. - smooth(.34, .88, openness)), 0., radius);
}
// Spatial occlusion by the bar replaces a fade in empty space.
inline double alpha(double) { return 1.; }
}
