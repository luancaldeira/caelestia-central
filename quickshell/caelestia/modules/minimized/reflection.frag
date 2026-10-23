#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
};
layout(binding = 1) uniform sampler2D source;
void main() {
    vec2 uv = vec2(qt_TexCoord0.x, 1.0 - qt_TexCoord0.y);
    float fade = pow(max(0.0, 1.0 - qt_TexCoord0.y / 0.23), 2.0);
    fragColor = texture(source, uv) * (qt_Opacity * 0.30 * fade);
}
