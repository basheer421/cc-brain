import { useState, useEffect, useRef, useCallback } from 'react'
import Dither from './Dither'
import BlurText from './BlurText'
import InstallCommand from './InstallCommand'
import BrainIcon from '../assets/brain-fill.svg?raw'

const TARGET_COLOR: [number, number, number] = [0.49, 0.56, 0.66]
const FADE_DURATION = 2000

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

export default function Hero() {
  const [waveColor, setWaveColor] = useState<[number, number, number]>([0, 0, 0])
  const [showSubline, setShowSubline] = useState(false)
  const [showCta, setShowCta] = useState(false)
  const startTime = useRef<number | null>(null)

  useEffect(() => {
    let raf: number
    const animate = (timestamp: number) => {
      if (startTime.current === null) startTime.current = timestamp
      const elapsed = timestamp - startTime.current
      const t = Math.min(elapsed / FADE_DURATION, 1)
      const eased = t * t * (3 - 2 * t)

      setWaveColor([
        lerp(0, TARGET_COLOR[0], eased),
        lerp(0, TARGET_COLOR[1], eased),
        lerp(0, TARGET_COLOR[2], eased),
      ])

      if (t < 1) {
        raf = requestAnimationFrame(animate)
      }
    }
    raf = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(raf)
  }, [])

  const handleHeadlineComplete = useCallback(() => {
    setShowSubline(true)
  }, [])

  const handleSublineComplete = useCallback(() => {
    setShowCta(true)
  }, [])

  return (
    <section className="relative h-screen w-full overflow-hidden bg-black">
      <div className="absolute inset-0">
        <Dither
          waveColor={waveColor}
          colorNum={25}
          waveAmplitude={0.32}
          waveFrequency={3}
          waveSpeed={0.07}
          enableMouseInteraction={true}
          mouseRadius={0.2}
        />
      </div>

      <div className="absolute top-6 left-6 z-10 flex items-center gap-2">
        <div
          className="h-6 w-6 text-white"
          dangerouslySetInnerHTML={{ __html: BrainIcon }}
        />
        <span className="text-white font-mono font-medium text-sm tracking-widest uppercase">
          CC Brain
        </span>
      </div>

      <div className="relative z-10 flex h-full flex-col items-center justify-center px-6 text-center">
        <BlurText
          text="Your context window has amnesia."
          delay={100}
          animateBy="words"
          direction="bottom"
          className="text-4xl md:text-6xl font-mono font-bold tracking-tight text-white mb-6"
          onAnimationComplete={handleHeadlineComplete}
        />

        {showSubline && (
          <BlurText
            text="CC Brain watches your Claude Code sessions and writes living summaries. Next session picks up where you left off."
            delay={50}
            animateBy="words"
            direction="bottom"
            className="text-base md:text-lg font-mono text-white/70 max-w-xl mb-10"
            onAnimationComplete={handleSublineComplete}
          />
        )}

        <div
          className={`w-full max-w-lg transition-all duration-500 ${
            showCta
              ? 'opacity-100 translate-y-0'
              : 'opacity-0 translate-y-3'
          }`}
        >
          <InstallCommand />

          <div className="mt-4 flex items-center justify-center gap-4 text-sm text-white/50">
            <a
              href="https://github.com/basheer421/cc-brain"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-white/80 transition-colors"
            >
              Star on GitHub
            </a>
            <span>·</span>
            <span>MIT Licensed</span>
          </div>
        </div>
      </div>
    </section>
  )
}
