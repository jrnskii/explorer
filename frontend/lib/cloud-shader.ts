/** GLSL sources and colour helpers for the edge cloud overlay. */

export const CLOUD_VERTEX_SHADER = /* glsl */ `
attribute vec2 a_position;
varying vec2 v_uv;
void main() {
  v_uv = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`

/**
 * Domain-warped fractal noise clouds, kept to the viewport borders.
 * Output is premultiplied alpha so it composites over the map without halos.
 */
export const CLOUD_FRAGMENT_SHADER = /* glsl */ `
precision mediump float;

varying vec2 v_uv;
uniform vec2 u_resolution;
uniform float u_time;
uniform vec3 u_color;
uniform float u_opacity;
// 0..1: thickens the bank along the top edge (used while the navbar is visible).
uniform float u_top;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
    mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
    u.y
  );
}

float fbm(vec2 p) {
  float sum = 0.0;
  float amp = 0.5;
  for (int i = 0; i < 5; i++) {
    sum += amp * noise(p);
    p = p * 2.02 + vec2(17.0, 31.0);
    amp *= 0.5;
  }
  return sum;
}

// Cheaper noise for the domain warp, where fine detail is invisible.
float fbm3(vec2 p) {
  float sum = 0.0;
  float amp = 0.5;
  for (int i = 0; i < 3; i++) {
    sum += amp * noise(p);
    p = p * 2.02 + vec2(17.0, 31.0);
    amp *= 0.5;
  }
  return sum;
}

// One cloud layer. The shape is advected by the caller; the warp only evolves
// very slowly (te), so clouds keep their identity while they travel.
float layer(vec2 p, float te) {
  vec2 w = vec2(fbm3(p * 0.6 + te), fbm3(p * 0.6 + 7.3 - te * 0.8));
  return fbm(p + (w - 0.5) * 1.1 + vec2(0.0, te * 0.5));
}

// Two parallax layers: the far one is larger-scale and moves slower than the near one.
float cloudBody(vec2 base, vec2 wind, float time) {
  float te = time * 0.035;
  float far = layer(base * 1.5 - wind * 0.45 * time, te);
  float near = layer(base * 3.0 - wind * time + 11.0, te * 1.6);
  return far * 0.4 + near * 0.6;
}

void main() {
  float aspect = u_resolution.x / u_resolution.y;
  vec2 base = vec2(v_uv.x * aspect, v_uv.y);
  // One steady wind: mostly sideways with a faint upward lean, like a real sky.
  vec2 wind = vec2(0.075, 0.006);

  float body = cloudBody(base, wind, u_time);
  // Sample again a little toward the light (above and left). If there is more
  // cloud that way the pixel is in shadow; if less, it is a sunlit rim.
  float toLight = cloudBody(base + vec2(-0.025, 0.045), wind, u_time);
  float lit = clamp(0.6 + (body - toLight) * 5.0, 0.0, 1.0);
  vec3 shadow = u_color * vec3(0.7, 0.77, 0.9);
  vec3 color = mix(shadow, u_color, lit);

  // 0 in the centre, 1 at the borders. The horizontal axis is compressed and the
  // vertical one stretched, so the bank is thick along the top and bottom and thin
  // along the left and right. The cloud noise is what drifts across this fixed frame.
  vec2 d = (v_uv - 0.5) * 2.0;
  float edge = length(vec2(d.x * 0.6, d.y * 1.2));
  float topness = smoothstep(0.1, 1.0, d.y) * u_top;
  float reach = smoothstep(0.45, 1.05, edge + topness * 0.55 + (body - 0.5) * 0.6);

  float density = smoothstep(0.34, 0.68, body) * 0.8 + 0.2;
  density = mix(density, 1.0, topness * 0.6);
  density *= mix(0.65, 1.0, abs(d.y));
  float alpha = clamp(reach * density, 0.0, 1.0) * u_opacity;

  gl_FragColor = vec4(color * alpha, alpha);
}
`

export type Rgb = readonly [number, number, number]

/** Cloud tint per theme: white in light mode, a dusky blue in dark mode. */
export const CLOUD_COLORS: Record<"light" | "dark", Rgb> = {
  light: [1, 1, 1],
  dark: [0.32, 0.4, 0.58],
}

export const cloudColor = (dark: boolean): Rgb =>
  CLOUD_COLORS[dark ? "dark" : "light"]
