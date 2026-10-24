#include "../hypr/plugins/caelestia-minimize/BubbleMotion.hpp"
#include <cassert>
#include <iostream>
using namespace BubbleMotion;
static bool near(double a,double b) { return std::abs(a-b)<1e-7; }
int main() {
    for (const Rect body : {Rect{100,80,1400,900},Rect{-1800,130,840,500},Rect{220,60,440,900}}) {
        const Rect port{body.x+body.width/2-24,1080-58,48,48};
        const auto closed=frame(port,body,0),opened=frame(port,body,1);
        assert(near(closed.x,port.x)&&near(closed.y,port.y)&&near(closed.width,48)&&near(closed.height,48));
        assert(near(opened.x,body.x)&&near(opened.y,body.y)&&near(opened.width,body.width)&&near(opened.height,body.height));
        auto lastWidth=0.;
        for (int i=0;i<=1000;i++) {
            const auto p=i/1000.;
            const auto value=frame(port,body,p);
            assert(std::isfinite(value.x)&&std::isfinite(value.y));
            assert(value.width>=48&&value.height>=48);
            assert(value.width>=lastWidth);
            assert(value.width<=body.width*1.05&&value.height<=body.height*1.05);
            const auto radius=rounding(value,p,12);
            assert(radius>=0&&radius<=std::min(value.width,value.height)/2);
            // Large, readable windows remain opaque. Fading belongs at the dock.
            if(p>=.14) assert(near(alpha(p),1));
            const Rect movedPort{port.x+2350,port.y-640,48,48};
            const Rect movedBody{body.x+2350,body.y-640,body.width,body.height};
            const auto moved=frame(movedPort,movedBody,p);
            assert(near(moved.x,value.x+2350)&&near(moved.y,value.y-640));
            lastWidth=value.width;
        }
    }
    assert(alpha(0)==0&&attachment(0)==1&&attachment(1)==0);
    std::cout<<"Bubble endpoints, monitor offsets, positive geometry, rounding and late opacity passed\n";
}
