import { useEffect, useRef } from 'react'
import { LAND_RINGS } from '../data/land'

/**
 * A slowly rotating Earth, drawn on a canvas with an orthographic projection.
 *
 * It exists to make the workspace feel like what it is — a window onto a
 * satellite archive — and to answer one question visually before any analysis
 * runs: *where on Earth is this query about?* Pass `focus={[lon, lat]}` and the
 * globe eases round until that point faces the viewer, so typing "Kerala
 * floods" swings the planet to southern India before the pipeline has fetched
 * a single pixel.
 *
 * Deliberately cheap. One canvas, ~1200 coastline vertices, no dependency, no
 * WebGL, no texture download. It idles at roughly 0.02°/frame and stops
 * entirely when the tab is hidden, when the element scrolls out of view, or
 * when the visitor prefers reduced motion — in which case it draws one static
 * frame instead, which is a perfectly good illustration on its own.
 */

const DEG = Math.PI / 180

/** Shortest signed angular distance from `a` to `b`, in degrees. */
function angleDelta(a, b) {
  return ((((b - a) % 360) + 540) % 360) - 180
}

export default function Globe({
  className = '',
  size = 420,
  focus = null,
  idleSpin = 0.035,
  tone = 'dark',
}) {
  const canvasRef = useRef(null)
  // Rotation state lives in a ref, not React state: it changes every frame and
  // must never trigger a re-render.
  const view = useRef({ lon: -80, lat: -12, targetLon: -80, targetLat: -12, t: 0 })
  const focusRef = useRef(focus)
  focusRef.current = focus

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    let width = 0
    let height = 0
    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      width = Math.max(1, Math.round(rect.width))
      height = Math.max(1, Math.round(rect.height))
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()

    const palette =
      tone === 'light'
        ? {
            ocean: ['#dbe8fe', '#93bbfd', '#2a78d6'],
            land: 'rgba(18,133,92,.55)',
            landLine: 'rgba(10,20,36,.22)',
            graticule: 'rgba(10,20,36,.13)',
            limb: 'rgba(42,120,214,.55)',
            marker: '#c8322f',
          }
        : {
            ocean: ['#2a5ea8', '#153f7d', '#071021'],
            land: 'rgba(30,150,110,.62)',
            landLine: 'rgba(190,225,255,.30)',
            graticule: 'rgba(160,200,255,.16)',
            limb: 'rgba(147,187,253,.55)',
            marker: '#ff8a5c',
          }

    /* --- orthographic projection ------------------------------------- */
    // Returns null for points on the far side of the globe, which is what
    // makes the sphere read as a sphere rather than a flat disc of outlines.
    const project = (lon, lat, cx, cy, r, rotLon, rotLat) => {
      const l = (lon - rotLon) * DEG
      const p = lat * DEG
      const p0 = rotLat * DEG
      const cosc = Math.sin(p0) * Math.sin(p) + Math.cos(p0) * Math.cos(p) * Math.cos(l)
      if (cosc < 0) return null
      return [
        cx + r * Math.cos(p) * Math.sin(l),
        cy - r * (Math.cos(p0) * Math.sin(p) - Math.sin(p0) * Math.cos(p) * Math.cos(l)),
      ]
    }

    const draw = () => {
      const cx = width / 2
      const cy = height / 2
      const r = Math.min(width, height) / 2 - 6
      const { lon: rotLon, lat: rotLat } = view.current

      ctx.clearRect(0, 0, width, height)

      // --- ocean sphere, lit from the upper left -----------------------
      const grad = ctx.createRadialGradient(
        cx - r * 0.35, cy - r * 0.4, r * 0.1, cx, cy, r
      )
      grad.addColorStop(0, palette.ocean[0])
      grad.addColorStop(0.55, palette.ocean[1])
      grad.addColorStop(1, palette.ocean[2])
      ctx.beginPath()
      ctx.arc(cx, cy, r, 0, Math.PI * 2)
      ctx.fillStyle = grad
      ctx.fill()

      // --- graticule ---------------------------------------------------
      ctx.strokeStyle = palette.graticule
      ctx.lineWidth = 0.6
      for (let lat = -60; lat <= 60; lat += 30) {
        ctx.beginPath()
        let started = false
        for (let lon = -180; lon <= 180; lon += 4) {
          const pt = project(lon, lat, cx, cy, r, rotLon, rotLat)
          if (!pt) {
            started = false
            continue
          }
          if (started) ctx.lineTo(pt[0], pt[1])
          else {
            ctx.moveTo(pt[0], pt[1])
            started = true
          }
        }
        ctx.stroke()
      }
      for (let lon = -180; lon < 180; lon += 30) {
        ctx.beginPath()
        let started = false
        for (let lat = -88; lat <= 88; lat += 4) {
          const pt = project(lon, lat, cx, cy, r, rotLon, rotLat)
          if (!pt) {
            started = false
            continue
          }
          if (started) ctx.lineTo(pt[0], pt[1])
          else {
            ctx.moveTo(pt[0], pt[1])
            started = true
          }
        }
        ctx.stroke()
      }

      // --- land --------------------------------------------------------
      ctx.fillStyle = palette.land
      ctx.strokeStyle = palette.landLine
      ctx.lineWidth = 0.7
      for (const ring of LAND_RINGS) {
        let started = false
        let drew = false
        ctx.beginPath()
        for (let i = 0; i < ring.length; i++) {
          const pt = project(ring[i][0], ring[i][1], cx, cy, r, rotLon, rotLat)
          if (!pt) {
            started = false
            continue
          }
          if (started) ctx.lineTo(pt[0], pt[1])
          else {
            ctx.moveTo(pt[0], pt[1])
            started = true
          }
          drew = true
        }
        if (drew) {
          ctx.fill()
          ctx.stroke()
        }
      }

      // --- limb glow ----------------------------------------------------
      ctx.beginPath()
      ctx.arc(cx, cy, r, 0, Math.PI * 2)
      ctx.strokeStyle = palette.limb
      ctx.lineWidth = 1.2
      ctx.stroke()

      // --- the located area, when there is one --------------------------
      const f = focusRef.current
      if (f && Number.isFinite(f[0]) && Number.isFinite(f[1])) {
        const pt = project(f[0], f[1], cx, cy, r, rotLon, rotLat)
        if (pt) {
          const pulse = 0.5 + 0.5 * Math.sin(view.current.t / 22)
          ctx.beginPath()
          ctx.arc(pt[0], pt[1], 4 + pulse * 7, 0, Math.PI * 2)
          ctx.strokeStyle = palette.marker
          ctx.globalAlpha = 0.35 * (1 - pulse)
          ctx.lineWidth = 2
          ctx.stroke()
          ctx.globalAlpha = 1
          ctx.beginPath()
          ctx.arc(pt[0], pt[1], 3.4, 0, Math.PI * 2)
          ctx.fillStyle = palette.marker
          ctx.fill()
        }
      }
    }

    /* --- animation ---------------------------------------------------- */
    let raf = 0
    let visible = true
    const tick = () => {
      const v = view.current
      const f = focusRef.current
      if (f && Number.isFinite(f[0]) && Number.isFinite(f[1])) {
        v.targetLon = f[0]
        // Clamp the tilt so the poles never swing fully into view, which reads
        // as the globe falling over.
        v.targetLat = Math.max(-55, Math.min(55, f[1]))
        // Ease towards the target rather than jumping: the movement is the
        // thing that tells the user their location was understood.
        v.lon += angleDelta(v.lon, v.targetLon) * 0.045
        v.lat += (v.targetLat - v.lat) * 0.045
      } else {
        v.lon = ((v.lon + idleSpin + 180) % 360) - 180
        v.lat += (-12 - v.lat) * 0.02
      }
      v.t += 1
      draw()
      raf = requestAnimationFrame(tick)
    }

    const start = () => {
      if (!raf && visible && !reduced) raf = requestAnimationFrame(tick)
    }
    const stop = () => {
      if (raf) cancelAnimationFrame(raf)
      raf = 0
    }

    // Only animate while the globe is actually on screen and the tab is in
    // front. An off-screen canvas repainting 60 times a second is pure cost.
    const io = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting
        if (visible) start()
        else stop()
      },
      { threshold: 0.01 }
    )
    io.observe(canvas)

    const onVisibility = () => {
      if (document.hidden) stop()
      else start()
    }
    document.addEventListener('visibilitychange', onVisibility)

    const ro = new ResizeObserver(() => {
      resize()
      draw()
    })
    ro.observe(canvas)

    draw()
    start()

    return () => {
      stop()
      io.disconnect()
      ro.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [idleSpin, tone])

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{ width: size, height: size, display: 'block' }}
      role="img"
      aria-label="Rotating globe showing the area of interest"
    />
  )
}
