import { act, render } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { CLOUD_COLORS, cloudColor } from "@/lib/cloud-shader"

import { CloudOverlay } from "./cloud-overlay"

type FakeGl = ReturnType<typeof createFakeGl>

function createFakeGl(compileOk = true) {
  return {
    VERTEX_SHADER: 1,
    FRAGMENT_SHADER: 2,
    COMPILE_STATUS: 3,
    LINK_STATUS: 4,
    ARRAY_BUFFER: 5,
    STATIC_DRAW: 6,
    FLOAT: 7,
    COLOR_BUFFER_BIT: 8,
    TRIANGLES: 9,
    createShader: vi.fn(() => ({})),
    shaderSource: vi.fn(),
    compileShader: vi.fn(),
    getShaderParameter: vi.fn(() => compileOk),
    deleteShader: vi.fn(),
    createProgram: vi.fn(() => ({})),
    attachShader: vi.fn(),
    linkProgram: vi.fn(),
    getProgramParameter: vi.fn(() => true),
    deleteProgram: vi.fn(),
    useProgram: vi.fn(),
    createBuffer: vi.fn(() => ({})),
    bindBuffer: vi.fn(),
    bufferData: vi.fn(),
    deleteBuffer: vi.fn(),
    getAttribLocation: vi.fn(() => 0),
    enableVertexAttribArray: vi.fn(),
    vertexAttribPointer: vi.fn(),
    getUniformLocation: vi.fn((_: unknown, name: string) => name),
    uniform1f: vi.fn(),
    uniform2f: vi.fn(),
    uniform3f: vi.fn(),
    clearColor: vi.fn(),
    clear: vi.fn(),
    viewport: vi.fn(),
    drawArrays: vi.fn(),
  }
}

function mockEnvironment({ gl, reducedMotion }: { gl: FakeGl | null; reducedMotion: boolean }) {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    (() => gl) as unknown as typeof HTMLCanvasElement.prototype.getContext
  )
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: reducedMotion,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))
  )
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    }
  )
}

describe("CloudOverlay", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark")
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  test("is a decorative, non-interactive canvas", () => {
    mockEnvironment({ gl: createFakeGl(), reducedMotion: true })
    const { getByTestId } = render(<CloudOverlay className="fixed inset-0" />)
    const canvas = getByTestId("cloud-overlay")
    expect(canvas).toHaveAttribute("aria-hidden", "true")
    expect(canvas).toHaveClass("pointer-events-none", "fixed", "inset-0")
  })

  test("renders nothing and does not throw without WebGL", () => {
    mockEnvironment({ gl: null, reducedMotion: false })
    expect(() => render(<CloudOverlay />)).not.toThrow()
  })

  test("does not draw when the shader fails to compile", () => {
    const gl = createFakeGl(false)
    mockEnvironment({ gl, reducedMotion: false })
    render(<CloudOverlay />)
    expect(gl.drawArrays).not.toHaveBeenCalled()
  })

  test("reduced motion drifts at a quarter of the normal speed", () => {
    const gl = createFakeGl()
    mockEnvironment({ gl, reducedMotion: true })
    const callbacks: FrameRequestCallback[] = []
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      callbacks.push(cb)
      return callbacks.length
    })
    render(<CloudOverlay />)
    act(() => callbacks.shift()?.(1000))
    act(() => callbacks.shift()?.(5000))
    expect(gl.uniform1f).toHaveBeenLastCalledWith("u_time", 1)
  })

  test("animates with requestAnimationFrame and stops on unmount", () => {
    const gl = createFakeGl()
    mockEnvironment({ gl, reducedMotion: false })
    const callbacks: FrameRequestCallback[] = []
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      callbacks.push(cb)
      return callbacks.length
    })
    const cancel = vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {})

    const { unmount } = render(<CloudOverlay />)
    act(() => callbacks.shift()?.(1000))
    act(() => callbacks.shift()?.(3000))
    expect(gl.drawArrays).toHaveBeenCalledTimes(2)
    // Time is relative to the first frame: 2s after start.
    expect(gl.uniform1f).toHaveBeenLastCalledWith("u_time", 2)

    unmount()
    expect(cancel).toHaveBeenCalled()
    expect(gl.deleteProgram).toHaveBeenCalled()
  })

  test("tints the clouds for the active theme and follows theme changes", async () => {
    const gl = createFakeGl()
    mockEnvironment({ gl, reducedMotion: false })
    render(<CloudOverlay />)
    expect(gl.uniform3f).toHaveBeenLastCalledWith("u_color", ...CLOUD_COLORS.light)

    await act(async () => {
      document.documentElement.classList.add("dark")
    })
    expect(gl.uniform3f).toHaveBeenLastCalledWith("u_color", ...CLOUD_COLORS.dark)
  })
})

describe("CloudOverlay dense top", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  const topValues = (gl: FakeGl) =>
    gl.uniform1f.mock.calls.filter(([name]) => name === "u_top").map(([, v]) => v as number)

  test("starts dense when denseTop is set and thin otherwise", () => {
    const dense = createFakeGl()
    mockEnvironment({ gl: dense, reducedMotion: false })
    const callbacks: FrameRequestCallback[] = []
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      callbacks.push(cb)
      return callbacks.length
    })
    const first = render(<CloudOverlay denseTop />)
    act(() => callbacks.shift()?.(1000))
    expect(topValues(dense)).toEqual([1])
    first.unmount()
    callbacks.length = 0

    const thin = createFakeGl()
    mockEnvironment({ gl: thin, reducedMotion: false })
    render(<CloudOverlay />)
    act(() => callbacks.shift()?.(1000))
    expect(topValues(thin)).toEqual([0])
  })

  test("eases toward the new target when denseTop changes", () => {
    const gl = createFakeGl()
    mockEnvironment({ gl, reducedMotion: false })
    const callbacks: FrameRequestCallback[] = []
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      callbacks.push(cb)
      return callbacks.length
    })
    const { rerender } = render(<CloudOverlay denseTop />)
    act(() => callbacks.shift()?.(1000))
    rerender(<CloudOverlay denseTop={false} />)
    act(() => callbacks.shift()?.(1100))
    act(() => callbacks.shift()?.(1200))
    const [first, second, third] = topValues(gl)
    expect(first).toBe(1)
    expect(second).toBeLessThan(1)
    expect(third).toBeLessThan(second)
    expect(third).toBeGreaterThan(0)
  })

  test("snaps under reduced motion", () => {
    const gl = createFakeGl()
    mockEnvironment({ gl, reducedMotion: true })
    const callbacks: FrameRequestCallback[] = []
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      callbacks.push(cb)
      return callbacks.length
    })
    const { rerender } = render(<CloudOverlay denseTop />)
    act(() => callbacks.shift()?.(1000))
    rerender(<CloudOverlay denseTop={false} />)
    act(() => callbacks.shift()?.(1016))
    expect(topValues(gl)).toEqual([1, 0])
  })
})

describe("CloudOverlay density", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  const opacities = (gl: FakeGl) =>
    gl.uniform1f.mock.calls.filter(([name]) => name === "u_opacity").map(([, v]) => v as number)
  const frames = () => {
    const callbacks: FrameRequestCallback[] = []
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      callbacks.push(cb)
      return callbacks.length
    })
    return callbacks
  }

  test("draws at full opacity by default", () => {
    const gl = createFakeGl()
    mockEnvironment({ gl, reducedMotion: false })
    const callbacks = frames()
    render(<CloudOverlay />)
    act(() => callbacks.shift()?.(1000))
    expect(opacities(gl).at(-1)).toBeCloseTo(0.9)
  })

  test("eases down to the requested density and back", () => {
    const gl = createFakeGl()
    mockEnvironment({ gl, reducedMotion: false })
    const callbacks = frames()
    const { rerender } = render(<CloudOverlay />)
    act(() => callbacks.shift()?.(1000))
    rerender(<CloudOverlay density={0.75} />)
    let last = 1000
    for (let i = 0; i < 40; i++) act(() => callbacks.shift()?.((last += 100)))
    expect(opacities(gl).at(-1)).toBeCloseTo(0.9 * 0.75, 2)
    // Eased: some frame lies strictly between the two targets.
    expect(opacities(gl).some((o) => o < 0.9 - 0.001 && o > 0.9 * 0.75 + 0.001)).toBe(true)

    rerender(<CloudOverlay density={1} />)
    for (let i = 0; i < 40; i++) act(() => callbacks.shift()?.((last += 100)))
    expect(opacities(gl).at(-1)).toBeCloseTo(0.9, 2)
  })

  test("snaps under reduced motion", () => {
    const gl = createFakeGl()
    mockEnvironment({ gl, reducedMotion: true })
    const callbacks = frames()
    const { rerender } = render(<CloudOverlay />)
    act(() => callbacks.shift()?.(1000))
    rerender(<CloudOverlay density={0.75} />)
    act(() => callbacks.shift()?.(1016))
    expect(opacities(gl).at(-1)).toBeCloseTo(0.9 * 0.75)
  })
})

describe("cloudColor", () => {
  test("picks the palette for each theme", () => {
    expect(cloudColor(false)).toEqual([1, 1, 1])
    expect(cloudColor(true)).toBe(CLOUD_COLORS.dark)
  })
})
