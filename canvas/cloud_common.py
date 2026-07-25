"""Shared GLSL for the procedural cloud layer.

One source of truth so the sky, the water reflection and the god-ray occlusion
all sample the SAME clouds (a cloud overhead reflects in the water and breaks up
the same sun shafts). Injected into each shader's source at build time.

`cloud_layer(dir, sunDir, t, cover)` returns vec4(lit_rgb, coverage) for a unit
world view direction: a drifting value-noise fbm layer on a virtual plane above
the camera, self-shadowed toward the sun (bright sunward tops, dark undersides).
"""

CLOUD_GLSL = """
// ---- procedural clouds (shared: cloud_common.py) ----------------------------
float c_hash(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float c_vnoise(vec2 p){
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float a = c_hash(i),                  b = c_hash(i + vec2(1.0, 0.0));
    float c = c_hash(i + vec2(0.0, 1.0)), d = c_hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float c_fbm(vec2 p){
    float s = 0.0, a = 0.5;
    mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
    for (int i = 0; i < 6; i++){ s += a * c_vnoise(p); p = m * p; a *= 0.5; }
    return s;
}
// raw coverage at a plane point (0..1) for the given wind + threshold
float c_shape(vec2 cp, vec2 wind, float lo){
    float base   = c_fbm(cp * 1.3 + wind);
    float detail = c_fbm(cp * 3.3 + wind * 2.1);
    return smoothstep(lo, lo + 0.26, base * 0.72 + detail * 0.28);
}
// coverage-only (used by the god-ray occluder mask)
float cloud_density(vec3 dir, float t, float cover){
    if (cover <= 0.001 || dir.y <= 0.02) return 0.0;
    vec2 cp = dir.xz / dir.y;
    vec2 wind = vec2(0.9, 0.5) * t * 0.01;
    float lo = mix(0.74, 0.24, clamp(cover, 0.0, 1.0));
    float d = c_shape(cp, wind, lo);
    return d * smoothstep(0.02, 0.20, dir.y);
}
// full lit + self-shadowed cloud sample
vec4 cloud_layer(vec3 dir, vec3 sunDir, float t, float cover){
    if (cover <= 0.001 || dir.y <= 0.02) return vec4(0.0);
    vec2 cp = dir.xz / dir.y;
    vec2 wind = vec2(0.9, 0.5) * t * 0.01;
    float lo = mix(0.74, 0.24, clamp(cover, 0.0, 1.0));
    float base = c_fbm(cp * 1.3 + wind);
    float dens = c_shape(cp, wind, lo) * smoothstep(0.02, 0.20, dir.y);
    // SELF-SHADOW: step toward the sun's plane position and accumulate the
    // cloud that blocks the light -> shaded undersides, bright sunward tops.
    vec3 sd = normalize(sunDir);
    vec2 sp_dir = normalize((sd.xz / max(sd.y, 0.15)) - cp + 1e-4);
    float shadow = 0.0;
    vec2 sp = cp;
    for (int i = 0; i < 4; i++){ sp += sp_dir * 0.32; shadow += c_shape(sp, wind, lo); }
    shadow = clamp(shadow * 0.25, 0.0, 1.0);
    float sunlit = clamp(dot(dir, sd) * 0.5 + 0.5, 0.0, 1.0);
    float form   = smoothstep(0.30, 0.95, base);
    vec3 lit = mix(vec3(0.58, 0.61, 0.68), vec3(1.03, 1.02, 1.00), form);
    lit *= mix(0.85, 1.32, sunlit * sunlit);   // silver lining toward the sun
    lit *= mix(1.0, 0.42, shadow);             // self-shadowed undersides
    return vec4(lit, dens);
}
"""
