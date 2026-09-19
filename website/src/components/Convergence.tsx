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
  { name: 'Claude Code', source: '~/.claude/**/*.jsonl', method: 'fsevents', color: '#d97757' },
  { name: 'Hermes', source: '~/.hermes/state.db', method: 'shell hook', color: '#7d8fa8' },
  { name: 'Pi', source: '~/.pi/agent/**/*.jsonl', method: 'fsevents', color: '#58a6ff' },
]

const outputs = [
  { name: 'my-app-17...md', color: '#d97757' },
  { name: 'h-my-app-...md', color: '#7d8fa8' },
  { name: 'p-my-app-...md', color: '#58a6ff' },
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
            Multi-agent support
          </span>
          <div className="w-8 h-px bg-[#7d8fa8] opacity-30 mt-4 mb-5 mx-auto" />
          <h2 className={`${MONO} text-xl md:text-2xl font-bold text-white mb-3 leading-tight`}>
            Three agents. One memory.
          </h2>
          <p className={`${MONO} text-sm text-[#7d8590] leading-relaxed max-w-xl mx-auto`}>
            Claude Code writes JSONL. Hermes writes SQLite. Pi writes JSONL in
            its own format. CC Brain listens to all three and folds every session
            into the same living memory.
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
          <div className="grid grid-cols-3 gap-3 mb-16">
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
              <div className={`${MONO} text-[10px] text-[#7d8fa8]`}>menu bar app</div>
            </div>
          </div>

          {/* Summaries output */}
          <div
            ref={summariesRef}
            className="border border-[#1e1e1e] rounded-lg p-5 text-center"
          >
            <div className={`${MONO} text-xs font-bold text-[#e6ecef] mb-2`}>~/.cc-brain/summaries/</div>
            <div className="flex justify-center gap-4">
              {outputs.map((o) => (
                <span key={o.name} className={`${MONO} text-[11px]`} style={{ color: o.color }}>
                  {o.name}
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
          Event-driven on all sides. No polling. Each agent's summaries carry a
          unique prefix (<span className="text-[#7d8fa8]">h-</span> for Hermes,{' '}
          <span className="text-[#58a6ff]">p-</span> for Pi), so every agent's
          sessions live side by side.
        </p>
      </div>
    </section>
  )
}
