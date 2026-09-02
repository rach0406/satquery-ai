import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-dist-min'

/*
 * Palette notes
 * -------------
 * These slots are the `series` scale from tailwind.config.js, validated on the
 * light chart surface (#ffffff): all six clear the lightness band, the chroma
 * floor, adjacent-pair CVD separation, the normal-vision floor and 3:1
 * contrast against paper.
 *
 * Composition charts ("what is this scene made of") use a SINGLE hue rather
 * than one colour per class: the class name is already on the category axis,
 * so colour there would be redundant encoding - and a six-way categorical
 * split cannot clear the all-pairs CVD floor. The thematic class colours live
 * on the map, where they are always paired with a labelled legend.
 */
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#4a3aa7']

const INK = {
  surface: '#ffffff',
  grid: 'rgba(51,71,100,0.13)',
  zero: 'rgba(51,71,100,0.30)',
  text: '#334764',
  muted: '#697d9c',
  single: '#2a78d6',
}

const FONT = {
  family: 'Inter, Segoe UI, system-ui, sans-serif',
  size: 12,
  color: INK.text,
}

const CONFIG = {
  displayModeBar: true,
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d', 'toggleSpikelines'],
  toImageButtonOptions: { format: 'png', scale: 2, filename: 'satquery-chart' },
}

function baseLayout(extra = {}) {
  return {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: FONT,
    margin: { l: 58, r: 18, t: 12, b: 48 },
    hovermode: 'closest',
    /* Plotly's default modebar is drawn for a dark canvas; on paper it reads
       as a block of grey squares sitting on the plot. */
    modebar: {
      bgcolor: 'rgba(255,255,255,0)',
      color: 'rgba(105,125,156,0.62)',
      activecolor: '#2a78d6',
    },
    hoverlabel: {
      bgcolor: '#ffffff',
      bordercolor: '#d3dde9',
      font: { ...FONT, size: 12, color: '#0a1424' },
      align: 'left',
    },
    showlegend: false,
    xaxis: {
      gridcolor: INK.grid,
      zerolinecolor: INK.zero,
      linecolor: 'rgba(51,71,100,0.22)',
      tickfont: { ...FONT, size: 11.5, color: INK.muted },
      titlefont: { ...FONT, size: 12, color: INK.muted },
      automargin: true,
    },
    yaxis: {
      gridcolor: INK.grid,
      zerolinecolor: INK.zero,
      linecolor: 'rgba(0,0,0,0)',
      tickfont: { ...FONT, size: 11.5, color: INK.muted },
      titlefont: { ...FONT, size: 12, color: INK.muted },
      automargin: true,
    },
    ...extra,
  }
}

function build(spec) {
  if (!spec) return null
  const t = spec.type

  // ---- histogram: single hue, magnitude ---------------------------------
  if (t === 'histogram') {
    const traces = [
      {
        type: 'bar',
        x: spec.x,
        y: spec.y,
        marker: {
          color: spec.color || INK.single,
          line: { width: 0 },
        },
        width: (spec.bin_width || 0.05) * 0.86, // 2px-equivalent surface gap
        hovertemplate: `%{x:.3f}<br><b>%{y:,}</b> px<extra></extra>`,
        name: spec.xlabel || 'count',
      },
    ]
    const shapes = (spec.markers || []).map((m) => ({
      type: 'line',
      x0: m.x,
      x1: m.x,
      yref: 'paper',
      y0: 0,
      y1: 1,
      line: { color: m.color || '#eb6834', width: 2, dash: 'dot' },
    }))
    const annotations = (spec.markers || []).map((m, i) => ({
      x: m.x,
      yref: 'paper',
      y: 1 - i * 0.11,
      text: m.label,
      showarrow: false,
      font: { ...FONT, size: 11, color: m.color || '#eb6834' },
      bgcolor: 'rgba(255,255,255,0.92)',
      borderpad: 3,
      xanchor: 'left',
      xshift: 6,
    }))
    return {
      traces,
      layout: baseLayout({
        shapes,
        annotations,
        bargap: 0.06,
        xaxis: { ...baseLayout().xaxis, title: { text: spec.xlabel || '' } },
        yaxis: { ...baseLayout().yaxis, title: { text: spec.ylabel || '' } },
      }),
    }
  }

  // ---- bar: magnitude by category, single hue ---------------------------
  if (t === 'bar') {
    const useSemantic = Array.isArray(spec.colors) && spec.colors.length === spec.x.length
    return {
      traces: [
        {
          type: 'bar',
          x: spec.x,
          y: spec.y,
          marker: {
            color: useSemantic ? spec.colors : INK.single,
            line: { width: 0 },
          },
          text: spec.y.map((v) => (typeof v === 'number' ? v.toLocaleString() : v)),
          textposition: 'outside',
          textfont: { ...FONT, size: 11, color: INK.muted },
          cliponaxis: false,
          hovertemplate: `<b>%{x}</b><br>%{y:,} ${spec.ylabel || ''}<extra></extra>`,
        },
      ],
      layout: baseLayout({
        bargap: 0.34,
        margin: { l: 58, r: 18, t: 18, b: 78 },
        xaxis: { ...baseLayout().xaxis, tickangle: spec.x.some((s) => String(s).length > 12) ? -26 : 0 },
        yaxis: { ...baseLayout().yaxis, title: { text: spec.ylabel || '' } },
      }),
    }
  }

  // ---- grouped bar: two dates, two validated hues ------------------------
  if (t === 'grouped_bar') {
    return {
      traces: spec.series.map((s, i) => ({
        type: 'bar',
        name: s.name,
        x: spec.x,
        y: s.y,
        marker: { color: s.color || SERIES[i % SERIES.length], line: { width: 0 } },
        hovertemplate: `<b>%{x}</b><br>${s.name}: %{y:,} ${spec.ylabel || ''}<extra></extra>`,
      })),
      layout: baseLayout({
        barmode: 'group',
        bargap: 0.3,
        bargroupgap: 0.08,
        showlegend: true,
        legend: {
          orientation: 'h',
          y: 1.14,
          x: 0,
          font: { ...FONT, size: 11.5, color: INK.muted },
          bgcolor: 'rgba(0,0,0,0)',
        },
        margin: { l: 58, r: 18, t: 40, b: 78 },
        xaxis: { ...baseLayout().xaxis, tickangle: -18 },
        yaxis: { ...baseLayout().yaxis, title: { text: spec.ylabel || '' } },
      }),
    }
  }

  // ---- line / band: change over time ------------------------------------
  if (t === 'line') {
    const traces = []
    spec.series.forEach((s, i) => {
      if (s.fill && s.y_upper) {
        traces.push({
          type: 'scatter',
          mode: 'lines',
          x: [...spec.x, ...[...spec.x].reverse()],
          y: [...s.y_upper, ...[...s.y].reverse()],
          fill: 'toself',
          fillcolor: 'rgba(42,120,214,0.14)',
          line: { width: 0 },
          hoverinfo: 'skip',
          name: s.name,
          showlegend: true,
        })
        return
      }
      traces.push({
        type: 'scatter',
        mode: s.mode || 'lines+markers',
        x: spec.x,
        y: s.y,
        name: s.name,
        line: {
          color: s.color || SERIES[i % SERIES.length],
          width: 2,
          dash: s.dash || 'solid',
          shape: 'linear',
        },
        marker: { size: 8, color: s.color || SERIES[i % SERIES.length] },
        hovertemplate: `%{x}<br><b>%{y:.4f}</b><extra>${s.name}</extra>`,
      })
    })
    return {
      traces,
      layout: baseLayout({
        showlegend: true,
        legend: {
          orientation: 'h',
          y: 1.16,
          x: 0,
          font: { ...FONT, size: 11.5, color: INK.muted },
          bgcolor: 'rgba(0,0,0,0)',
        },
        hovermode: 'x unified',
        margin: { l: 58, r: 18, t: 42, b: 60 },
        xaxis: {
          ...baseLayout().xaxis,
          title: { text: spec.xlabel || '' },
          showspikes: true,
          spikecolor: 'rgba(51,71,100,0.42)',
          spikethickness: 1,
          spikedash: 'dot',
          spikemode: 'across',
        },
        yaxis: { ...baseLayout().yaxis, title: { text: spec.ylabel || '' } },
      }),
    }
  }
  return null
}

export default function Chart({ spec, height = 260 }) {
  const ref = useRef(null)

  useEffect(() => {
    const node = ref.current
    if (!node || !spec) return
    const built = build(spec)
    if (!built) return
    Plotly.react(node, built.traces, { ...built.layout, height }, CONFIG)

    const ro = new ResizeObserver(() => {
      try {
        Plotly.Plots.resize(node)
      } catch {
        /* node already torn down */
      }
    })
    ro.observe(node)
    return () => {
      ro.disconnect()
      try {
        Plotly.purge(node)
      } catch {
        /* already purged */
      }
    }
  }, [spec, height])

  if (!spec) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}
