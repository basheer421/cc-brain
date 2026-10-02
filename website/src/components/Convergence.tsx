import { useEffect, useRef, useState } from 'react'

const MONO = 'font-mono'

function useInView(ref: React.RefObject<HTMLDivElement | null>, threshold = 0.3) {
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true)
          obs.disconnect()
        }
      },
      { threshold },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [ref, threshold])

  return inView
}

const agents = [
  { name: 'Pi', source: '~/.pi/agent/sessions/', method: 'fsevents', color: '#58a6ff' },
  { name: 'Hermes', source: '~/.hermes/sessions/', method: 'fsevents', color: '#7d8fa8' },
]

const outputs = [
  { name: 'recall', color: '#e6ecef' },
  { name: 'timeline', color: '#e6ecef' },
  { name: 'remember', color: '#e6ecef' },
  { name: 'correct', color: '#e6ecef' },
]

const clients = [
  { name: 'Claude Code', color: '#d97757' },
  { name: 'Pi', color: '#58a6ff' },
  { name: 'Hermes', color: '#7d8fa8' },
  { name: 'any MCP client', color: '#57606a' },
]

export default function Convergence() {
  const containerRef = useRef<HTMLDivElement>(null)
  const inView = useInView(containerRef)
  const agentRefs = useRef<(HTMLDivElement | null)[]>([])
  const brainRef = useRef<HTMLDivElement>(null)
  const summariesRef = useRef<HTMLDivElement>(null)
  const [lines, setLines] = useState<{ x1: number; y1: number; x2: number; y2: number; color: string }[]>([])
  const [outLine, setOutLine] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null)
  const [svgSize, setSvgSize] = useState({ w: 0, h: 0 })

  useEffect(() => {
    const update = () => {
      const container = containerRef.current
      const brain = brainRef.current
      const summaries = summariesRef.current
      if (!container || !brain || !summaries) return

      const cRect = container.getBoundingClientRect()
      setSvgSize({ w: cRect.width, h: cRect.height })

      const bRect = brain.getBoundingClientRect()
      const brainTopCenter = { x: bRect.left - cRect.left + bRect.width / 2, y: bRect.top - cRect.top }
      const brainBottomCenter = { x: bRect.left - cRect.left + bRect.width / 2, y: bRect.bottom - cRect.top }

      const sRect = summaries.getBoundingClientRect()
      const summariesTopCenter = { x: sRect.left - cRect.left + sRect.width / 2, y: sRect.top - cRect.top }

      const newLines = agentRefs.current.map((el, i) => {
        if (!el) return { x1: 0, y1: 0, x2: 0, y2: 0, color: agents[i].color }
        const r = el.getBoundingClientRect()
        return {
          x1: r.left - cRect.left + r.width / 2,
          y1: r.bottom - cRect.top,
          x2: brainTopCenter.x,
          y2: brainTopCenter.y,
          color: agents[i].color,
        }
      })
      setLines(newLines)
      setOutLine({
        x1: brainBottomCenter.x,
        y1: brainBottomCenter.y,
        x2: summariesTopCenter.x,
        y2: summariesTopCenter.y,
      })
    }

    update()
    window.addEventListener('resize', update)
    const t = setTimeout(update, 100)
    return () => {
      window.removeEventListener('resize', update)
      clearTimeout(t)
    }
  }, [inView])

  return (
    <section className="bg-black py-20 px-6 overflow-hidden">
      <div className="mx-auto max-w-3xl">
        <div className="text-center mb-12">
          <span
            className={`${MONO} text-[0.65rem] tracking-[0.2em] uppercase text-[#7d8fa8] font-medium`}
          >
            Learn once, recall anywhere
          </span>
          <div className="w-8 h-px bg-[#7d8fa8] opacity-30 mt-4 mb-5 mx-auto" />
          <h2 className={`${MONO} text-xl md:text-2xl font-bold text-white mb-3 leading-tight`}>
            Many agents. One memory.
          </h2>
          <p className={`${MONO} text-sm text-[#7d8590] leading-relaxed max-w-xl mx-auto`}>
            CC Brain learns from Pi and Hermes sessions as they happen, folds
            them into one store of facts and episodes, and serves it over MCP.
            What one agent learned, every agent can recall.
          </p>
        </div>

        <div
          ref={containerRef}
          className={`relative transition-all duration-1000 ${inView ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6'}`}
        >
          {/* SVG lines layer */}
          <svg
            className="absolute inset-0 pointer-events-none"
            width={svgSize.w}
            height={svgSize.h}
            style={{ overflow: 'visible' }}
          >
            {lines.map((l, i) => (
              <line
                key={i}
                x1={l.x1} y1={l.y1}
                x2={l.x2} y2={l.y2}
                stroke={l.color}
                strokeWidth="1"
                strokeOpacity="0.5"
              />
            ))}
            {outLine && (
              <line
                x1={outLine.x1} y1={outLine.y1}
                x2={outLine.x2} y2={outLine.y2}
                stroke="#30363d"
                strokeWidth="1"
                strokeDasharray="4 4"
              />
            )}
          </svg>

          {/* Agent sources */}
          <div className="grid grid-cols-2 gap-3 mb-16 max-w-md mx-auto">
            {agents.map((a, i) => (
              <div
                key={a.name}
                ref={(el) => { agentRefs.current[i] = el; }}
                className="border border-[#1e1e1e] rounded-lg p-4 text-center"
              >
                <div className={`${MONO} text-sm font-bold text-white mb-1`}>{a.name}</div>
                <div className={`${MONO} text-[10px] text-[#7d8590]`}>{a.source}</div>
                <div className={`${MONO} text-[10px] text-[#57606a]`}>{a.method}</div>
              </div>
            ))}
          </div>

          {/* CC Brain center */}
          <div className="flex justify-center mb-16">
            <div
              ref={brainRef}
              className="border border-[#7d8fa8]/40 rounded-lg px-12 py-4 text-center bg-gradient-to-b from-[#7d8fa8]/10 to-transparent"
            >
              <div className={`${MONO} text-sm font-bold text-white`}>CC Brain</div>
              <div className={`${MONO} text-[10px] text-[#7d8fa8]`}>background daemon</div>
            </div>
          </div>

          {/* Summaries output */}
          <div
            ref={summariesRef}
            className="border border-[#1e1e1e] rounded-lg p-5 text-center"
          >
            <div className={`${MONO} text-xs font-bold text-[#e6ecef] mb-1`}>facts · episodes</div>
            <div className={`${MONO} text-[10px] text-[#57606a] mb-3`}>SQLite · keyword + local vector search</div>
            <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 mb-3">
              {outputs.map((o) => (
                <span key={o.name} className={`${MONO} text-[11px]`} style={{ color: o.color }}>
                  {o.name}()
                </span>
              ))}
            </div>
            <div className={`${MONO} text-[10px] text-[#7d8590]`}>
              over MCP to{' '}
              {clients.map((c, i) => (
                <span key={c.name}>
                  <span style={{ color: c.color }}>{c.name}</span>
                  {i < clients.length - 1 ? ' · ' : ''}
                </span>
              ))}
            </div>
          </div>

          {/* Legend */}
          <div className="flex justify-center gap-6 mt-6">
            {agents.map((a) => (
              <div key={a.name} className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: a.color }} />
                <span className={`${MONO} text-[10px] text-[#57606a]`}>{a.name}</span>
              </div>
            ))}
          </div>
        </div>

        <p className={`${MONO} text-center text-xs text-[#57606a] leading-relaxed max-w-lg mx-auto mt-8`}>
          Event-driven, no polling. Every answer is about 2 KB of ranked facts,
          not a page to read. Truncated model output is never saved, and a
          wrong fact is retired with <span className="text-[#7d8fa8]">correct()</span>,
          with its history kept.
        </p>
      </div>
    </section>
  )
}
