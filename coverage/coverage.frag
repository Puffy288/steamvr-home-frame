#version 450
// Limit the optional depth shortcut to near-opaque texel interiors.
// The unchanged colour pass still uses the original cutoff and four samples.
layout(set=0,binding=150) uniform texture2D alphaTexture;
layout(set=0,binding=70) uniform sampler alphaSampler;
layout(std140,set=0,binding=0) uniform Material {layout(offset=4) float cutoff;};
layout(location=0) in vec2 uv;
layout(location=0) out vec4 unusedColour;
void main(){
 float a=texture(sampler2D(alphaTexture,alphaSampler),uv).a;
 if(a<mix(cutoff,1.,.9))discard;
 unusedColour=vec4(0);
}
