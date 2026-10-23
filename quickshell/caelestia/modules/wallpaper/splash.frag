#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 dimensions;
    vec2 center;
    float progress;
    float reduced;
    vec4 accent;
};
layout(binding = 1) uniform sampler2D source;

void main() {
    vec4 old = texture(source, qt_TexCoord0);
    if (reduced > 0.5) {
        fragColor = old * ((1.0 - progress) * qt_Opacity);
        return;
    }
    vec2 point = qt_TexCoord0 * dimensions;
    float farthest = max(max(length(center), length(dimensions-center)),
                         max(length(vec2(dimensions.x,0.0)-center), length(vec2(0.0,dimensions.y)-center)));
    vec2 delta = point - center;
    float angle = atan(delta.y, delta.x);
    // A restrained liquid edge. It converges to a clean circle at both ends.
    float liquid = (sin(angle*3.0+progress*3.1)*0.65 + sin(angle*5.0-progress*2.0)*0.35)
                    * sin(progress*3.14159265) * farthest*0.014;
    float radius = mix(-26.0, farthest+50.0, progress);
    float distance = length(delta) - radius - liquid;
    float coverage = smoothstep(-12.0, 12.0, distance);
    float edge = exp(-pow(distance/7.0, 2.0))*0.13*sin(progress*3.14159265);
    // Premultiplied alpha: the hole shows the real animated wallpaper and UI.
    fragColor = (old*coverage + accent*edge*(1.0-coverage)) * qt_Opacity;
}
