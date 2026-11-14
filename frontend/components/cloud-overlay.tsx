"use client"

import { useEffect, useRef } from "react"

import {
  CLOUD_FRAGMENT_SHADER,
  CLOUD_VERTEX_SHADER,
  cloudColor,
} from "@/lib/cloud-shader"
import { cn } from "@/lib/utils"

// Clouds are soft, so render at a fraction of the display resolution.
const RENDER_SCALE = 0.5
const OPACITY = 0.9
// Reduced motion keeps the clouds alive but drifting at a gentle quarter speed.
const REDUCED_MOTION_SPEED = 0.25
// How quickly the dense top bank eases in or out (per second).
const TOP_EASE_RATE = 3

function compile(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader)
    return null
  }
  return shader
}

function createProgram(gl: WebGLRenderingContext) {
  const vertex = compile(gl, gl.VERTEX_SHADER, CLOUD_VERTEX_SHADER)
  const fragment = compile(gl, gl.FRAGMENT_SHADER, CLOUD_FRAGMENT_SHADER)
  const program = gl.createProgram()
  if (!vertex || !fragment || !program) return null
  gl.attachShader(program, vertex)
  gl.attachShader(program, fragment)
  gl.linkProgram(program)
  gl.deleteShader(vertex)
  gl.deleteShader(fragment)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program)
    return null
  }
  return program
}

/**
 * Decorative WebGL cloud layer that hugs the viewport borders. Purely visual:
 * it ignores pointer events, is hidden from assistive technology, follows the
 * light/dark theme, slows under `prefers-reduced-motion`, and silently
 * renders nothing when WebGL is unavailable.
 */
export function CloudOverlay({
  className,
  denseTop = false,
}: {
  className?: string
  /** Thickens the clouds along the top edge, easing in and out. */
  denseTop?: boolean
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const denseTopRef = useRef(denseTop)
  useEffect(() => {
    denseTopRef.current = denseTop
  }, [denseTop])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const gl = canvas.getContext("webgl", {
      alpha: true,
      premultipliedAlpha: true,
      antialias: false,
    })
    if (!gl) return
    const program = createProgram(gl)
    if (!program) return

    gl.useProgram(program)
    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    // One oversized triangle covers the whole viewport.
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      gl.STATIC_DRAW
    )
    const position = gl.getAttribLocation(program, "a_position")
    gl.enableVertexAttribArray(position)
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0)

    const uResolution = gl.getUniformLocation(program, "u_resolution")
    const uTime = gl.getUniformLocation(program, "u_time")
    const uColor = gl.getUniformLocation(program, "u_color")
    const uOpacity = gl.getUniformLocation(program, "u_opacity")
    const uTop = gl.getUniformLocation(program, "u_top")
    gl.uniform1f(uOpacity, OPACITY)
    let top = denseTopRef.current ? 1 : 0
    gl.clearColor(0, 0, 0, 0)

    const root = document.documentElement
    const applyTheme = () => {
      const [r, g, b] = cloudColor(root.classList.contains("dark"))
      gl.uniform3f(uColor, r, g, b)
    }
    applyTheme()

    const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)")
    let frame = 0
    let last = 0
    let time = 0

    const resize = () => {
      const width = Math.max(1, Math.round(canvas.clientWidth * RENDER_SCALE))
      const height = Math.max(1, Math.round(canvas.clientHeight * RENDER_SCALE))
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width
        canvas.height = height
      }
      gl.viewport(0, 0, width, height)
      gl.uniform2f(uResolution, width, height)
    }

    const draw = () => {
      gl.uniform1f(uTop, top)
      gl.uniform1f(uTime, time)
      gl.clear(gl.COLOR_BUFFER_BIT)
      gl.drawArrays(gl.TRIANGLES, 0, 3)
    }

    // Accumulating scaled deltas lets the speed change without the clouds jumping.
    const tick = (now: number) => {
      const speed = motion?.matches ? REDUCED_MOTION_SPEED : 1
      const dt = last ? (now - last) / 1000 : 0
      if (last) time += dt * speed
      const target = denseTopRef.current ? 1 : 0
      top = motion?.matches
        ? target
        : top + (target - top) * Math.min(1, dt * TOP_EASE_RATE)
      last = now
      draw()
      frame = requestAnimationFrame(tick)
    }

    resize()
    frame = requestAnimationFrame(tick)

    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(canvas)
    const themeObserver = new MutationObserver(applyTheme)
    themeObserver.observe(root, { attributes: true, attributeFilter: ["class"] })

    const onContextLost = (event: Event) => {
      event.preventDefault()
      cancelAnimationFrame(frame)
    }
    canvas.addEventListener("webglcontextlost", onContextLost)

    return () => {
      cancelAnimationFrame(frame)
      resizeObserver.disconnect()
      themeObserver.disconnect()

      canvas.removeEventListener("webglcontextlost", onContextLost)
      gl.deleteBuffer(buffer)
      gl.deleteProgram(program)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      data-testid="cloud-overlay"
      className={cn("pointer-events-none h-full w-full", className)}
    />
  )
}
