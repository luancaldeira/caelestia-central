#pragma once
#include <algorithm>
#include <cmath>

namespace BubbleMotion {
struct Rect { double x, y, width, height; };
inline double smooth(double from, double to, double value) {
    const auto p = std::clamp((value - from) / (to - from), 0., 1.);
    return p * p * (3. - 2. * p);
}
inline Rect mix(const Rect& a, const Rect& b, double p) {
    return {a.x+(b.x-a.x)*p,a.y+(b.y-a.y)*p,a.width+(b.width-a.width)*p,a.height+(b.height-a.height)*p};
}
inline Rect projection(const Rect& port, const Rect& bounds) {
    const auto width=std::clamp(port.width,80.,bounds.width-16.);
    const auto height=std::clamp(port.height,36.,bounds.height*.6);
    return {port.x+port.width/2.-width/2.,port.y-4.-height+2.,width,height};
}
inline Rect detached(const Rect& port, const Rect& body, const Rect& bounds) {
    const auto margin=std::min(64.,std::min(bounds.width,bounds.height)/8.);
    const auto bottom=std::max(bounds.y+margin+64.,port.y-4.-port.height-56.);
    const auto width=std::clamp(body.width*.88,48.,bounds.width-2.*margin);
    const auto height=std::clamp(body.height*.88,48.,std::max(48.,bottom-bounds.y-margin));
    return {std::clamp(body.x+(body.width-width)/2.,bounds.x+margin,bounds.x+bounds.width-margin-width),
            std::clamp(body.y+(body.height-height)/2.,bounds.y+margin,bottom-height),width,height};
}
// Exactly the drawer's reveal first: a fixed-size Caelestia panel slides out
// of the border. Its whole surface then peels away into the window rectangle.
inline Rect frame(const Rect& port, const Rect& body, const Rect& bounds, double openness) {
    const auto p=std::clamp(openness,0.,1.);
    const auto panel=projection(port,bounds);
    const Rect hidden{panel.x,port.y,panel.width,panel.height};
    const auto free=detached(port,body,bounds);
    if(p<=.38) return mix(hidden,panel,smooth(0.,.38,p));
    if(p<=.72) return mix(panel,free,smooth(.38,.72,p));
    return mix(free,body,smooth(.72,1.,p));
}
// The shell surface owns the first part of the motion. Client pixels only
// replace that surface after it has detached, at the exact same rectangle.
inline double alpha(double openness) { return smooth(.74,.96,openness); }
inline double rounding(const Rect& rect,double openness,double normal) {
    return std::min(std::min(rect.width,rect.height)/2.,28.+(normal-28.)*smooth(.72,1.,openness));
}
}
