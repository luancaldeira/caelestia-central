#include "../hypr/plugins/caelestia-minimize/BubbleMotion.hpp"
#include <cassert>
#include <iostream>
using namespace BubbleMotion;
static bool near(double a,double b) { return std::abs(a-b)<1e-7; }
static void equal(const Rect& a,const Rect& b) {
    assert(near(a.x,b.x)&&near(a.y,b.y)&&near(a.width,b.width)&&near(a.height,b.height));
}
int main() {
    const Rect bounds{0,0,1920,1080};
    for (const Rect body : {Rect{100,80,1400,900},Rect{560,130,840,500},Rect{220,60,440,900},Rect{800,400,200,120}}) {
        for (const Rect port : {Rect{787,1074,396,88},Rect{765,1074,440,340}}) {
            const auto closed=frame(port,body,bounds,0),opened=frame(port,body,bounds,1);
            equal(closed,{port.x,port.y,port.width,port.height});
            equal(opened,body);
            double lastAlpha=0.;
            for (int i=0;i<=1000;i++) {
                const auto p=i/1000.;
                const auto value=frame(port,body,bounds,p);
                assert(std::isfinite(value.x)&&std::isfinite(value.y));
                assert(value.width>=48&&value.height>=48);
                const auto radius=rounding(value,p,12);
                assert(radius>=0&&radius<=std::min(value.width,value.height)/2);
                // The first part must match a drawer's fixed-size vertical
                // reveal, rather than a small client scaling up in midair.
                if (p <= .38) {
                    assert(near(value.x,port.x)&&near(value.width,port.width)&&near(value.height,port.height));
                    assert(value.y+value.height >= port.y-4);
                }
                if (p >= .72 && p <= .74) {
                    // Surface detachment precedes the first client pixels.
                    assert(value.y+value.height < port.y-4);
                }
                const auto a=alpha(p);
                assert(a>=lastAlpha&&a>=0&&a<=1);
                if (p<=.74) assert(a==0);
                if (p>=.96) assert(a==1);
                lastAlpha=a;
                const Rect movedPort{port.x-2350,port.y-640,port.width,port.height};
                const Rect movedBody{body.x-2350,body.y-640,body.width,body.height};
                const Rect movedBounds{bounds.x-2350,bounds.y-640,bounds.width,bounds.height};
                const auto moved=frame(movedPort,movedBody,movedBounds,p);
                equal(moved,{value.x-2350,value.y-640,value.width,value.height});
                // The same path is sampled backwards on absorption. Adjacent
                // samples must remain continuous at both material handoffs.
                if(i>0) {
                    const auto before=frame(port,body,bounds,(i-1)/1000.);
                    assert(std::abs(before.x-value.x)<20&&std::abs(before.y-value.y)<20);
                    assert(std::abs(before.width-value.width)<20&&std::abs(before.height-value.height)<20);
                }
            }
            const auto free=frame(port,body,bounds,.72);
            assert(free.y+free.height<=port.y-4-port.height-56+1e-7);
        }
    }
    assert(alpha(0)==0&&alpha(1)==1);
    std::cout<<"Drawer projection, material handoff, reversible path, monitor offsets and continuous geometry passed\n";
}
