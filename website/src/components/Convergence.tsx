import { useEffect, useRef, useState } from 'react'

/**
 * Two Brains, One Memory — animated convergence diagram.
 * Claude Code (JSONL / file events) and Hermes (SQLite / lifecycle hooks)
 * both stream into CC Brain, which writes living summaries.
 * Pure SVG + animateMotion, no dependencies.
 */

const MONO = 'font-mono'

function useInView(threshold = 0.35) {
  const ref = useRef<HTMLDivElement>(null)
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
  }, [threshold])

  return { ref, inView }
}

/** A pulse that travels along a path, repeating forever. */
function Pulse({
  pathId,
  dur,
  begin,
  color,
}: {
  pathId: string
  dur: string
  begin: string
  color: string
}) {
  return (
    <circle r="3" fill={color}>
      <animateMotion dur={dur} begin={begin} repeatCount="indefinite" calcMode="linear">
        <mpath href={`#${pathId}`} />
      </animateMotion>
      <animate
        attributeName="opacity"
        values="0;1;1;0"
        keyTimes="0;0.1;0.85;1"
        dur={dur}
        begin={begin}
        repeatCount="indefinite"
      />
    </circle>
  )
}

export default function Convergence() {
  const { ref, inView } = useInView()

  return (
    <section className="bg-black py-20 px-6 overflow-hidden">
      <div className="mx-auto max-w-4xl">
        <div className="text-center mb-4">
          <span
            className={`${MONO} text-[0.65rem] tracking-[0.2em] uppercase text-[#7d8fa8] font-medium`}
          >
            New — Hermes support
          </span>
          <div className="w-8 h-px bg-[#7d8fa8] opacity-30 mt-4 mb-5 mx-auto" />
          <h2 className={`${MONO} text-xl md:text-2xl font-bold text-white mb-3 leading-tight`}>
            Two brains. One memory.
          </h2>
          <p
            className={`${MONO} text-sm text-[#7d8590] leading-relaxed max-w-xl mx-auto`}
          >
            Claude Code writes JSONL. Hermes writes SQLite. CC Brain listens to
            both — file events on one side, lifecycle hooks on the other — and
            folds every session into the same living memory.
          </p>
        </div>

        <div ref={ref} className="relative">
          <svg
            viewBox="0 0 800 380"
            className={`w-full h-auto transition-opacity duration-1000 ${
              inView ? 'opacity-100' : 'opacity-0'
            }`}
            xmlns="http://www.w3.org/2000/svg"
          >
            {/* ---- connection paths ---- */}
            <defs>
              <path id="cc-path" d="M 195 120 C 320 120, 330 190, 400 190" />
              <path id="hermes-path" d="M 605 120 C 480 120, 470 190, 400 190" />
              <path id="out-path" d="M 400 225 L 400 285" />
              <linearGradient id="brainGlow" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#7d8fa8" stopOpacity="0.25" />
                <stop offset="100%" stopColor="#7d8fa8" stopOpacity="0.05" />
              </linearGradient>
            </defs>

            <use href="#cc-path" fill="none" stroke="#30363d" strokeWidth="1" />
            <use href="#hermes-path" fill="none" stroke="#30363d" strokeWidth="1" />
            <use href="#out-path" fill="none" stroke="#30363d" strokeWidth="1" strokeDasharray="3 4" />

            {inView && (
              <>
                {/* Claude Code pulses — file events, steady rhythm */}
                <Pulse pathId="cc-path" dur="2.6s" begin="0s" color="#d97757" />
                <Pulse pathId="cc-path" dur="2.6s" begin="1.3s" color="#d97757" />
                {/* Hermes pulses — hook events, offset rhythm */}
                <Pulse pathId="hermes-path" dur="2.6s" begin="0.65s" color="#7d8fa8" />
                <Pulse pathId="hermes-path" dur="2.6s" begin="1.95s" color="#7d8fa8" />
                {/* Output pulse — summaries */}
                <Pulse pathId="out-path" dur="1.8s" begin="0.9s" color="#e6ecef" />
              </>
            )}

            {/* ---- Claude Code node ---- */}
            <g>
              <rect
                x="55"
                y="82"
                width="140"
                height="76"
                rx="6"
                fill="#0a0a0a"
                stroke="#30363d"
              />
              <text x="125" y="112" textAnchor="middle" className="fill-white" fontFamily="ui-monospace, monospace" fontSize="13" fontWeight="700">
                Claude Code
              </text>
              <text x="125" y="132" textAnchor="middle" fill="#7d8590" fontFamily="ui-monospace, monospace" fontSize="9">
                ~/.claude/**.jsonl
              </text>
              <text x="125" y="146" textAnchor="middle" fill="#57606a" fontFamily="ui-monospace, monospace" fontSize="8">
                fsevents · debounce
              </text>
            </g>

            {/* ---- Hermes node ---- */}
            <g>
              <rect
                x="605"
                y="82"
                width="140"
                height="76"
                rx="6"
                fill="#0a0a0a"
                stroke="#30363d"
              />
              <text x="675" y="112" textAnchor="middle" className="fill-white" fontFamily="ui-monospace, monospace" fontSize="13" fontWeight="700">
                Hermes
              </text>
              <text x="675" y="132" textAnchor="middle" fill="#7d8590" fontFamily="ui-monospace, monospace" fontSize="9">
                ~/.hermes/state.db
              </text>
              <text x="675" y="146" textAnchor="middle" fill="#57606a" fontFamily="ui-monospace, monospace" fontSize="8">
                post_llm_call hook
              </text>
            </g>

            {/* ---- CC Brain node ---- */}
            <g>
              <circle cx="400" cy="190" r="36" fill="url(#brainGlow)" stroke="#7d8fa8" strokeOpacity="0.6">
                {inView && (
                  <animate
                    attributeName="r"
                    values="36;38;36"
                    dur="2.6s"
                    repeatCount="indefinite"
                  />
                )}
              </circle>
              <text x="400" y="186" textAnchor="middle" className="fill-white" fontFamily="ui-monospace, monospace" fontSize="11" fontWeight="700">
                CC Brain
              </text>
              <text x="400" y="200" textAnchor="middle" fill="#7d8fa8" fontFamily="ui-monospace, monospace" fontSize="8">
                🧠 menu bar
              </text>
            </g>

            {/* ---- summaries node ---- */}
            <g>
              <rect
                x="290"
                y="290"
                width="220"
                height="58"
                rx="6"
                fill="#0a0a0a"
                stroke="#30363d"
              />
              <text x="400" y="313" textAnchor="middle" fill="#e6ecef" fontFamily="ui-monospace, monospace" fontSize="10" fontWeight="700">
                ~/.cc-brain/summaries/
              </text>
              <text x="352" y="332" textAnchor="middle" fill="#d97757" fontFamily="ui-monospace, monospace" fontSize="9">
                my-app-17...md
              </text>
              <text x="455" y="332" textAnchor="middle" fill="#7d8fa8" fontFamily="ui-monospace, monospace" fontSize="9">
                h-my-app-17...md
              </text>
            </g>

            {/* legend */}
            <g>
              <circle cx="310" cy="368" r="3" fill="#d97757" />
              <text x="320" y="371" fill="#57606a" fontFamily="ui-monospace, monospace" fontSize="8">
                file events
              </text>
              <circle cx="420" cy="368" r="3" fill="#7d8fa8" />
              <text x="430" y="371" fill="#57606a" fontFamily="ui-monospace, monospace" fontSize="8">
                lifecycle hooks
              </text>
            </g>
          </svg>
        </div>

        <p
          className={`${MONO} text-center text-xs text-[#57606a] leading-relaxed max-w-lg mx-auto mt-4`}
        >
          Event-driven on both sides — no polling. Hermes summaries carry an{' '}
          <span className="text-[#7d8fa8]">h-</span> prefix, so both agents'
          sessions live side by side and every new chat picks up where any of
          them left off.
        </p>
      </div>
    </section>
  )
}
