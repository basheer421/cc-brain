import { useState, useCallback, useEffect } from 'react'
import Dither from './Dither'
import BlurText from './BlurText'
import InstallCommand from './InstallCommand'
import AgentTypewriter from './AgentTypewriter'
import './AgentTypewriter.css'
import BrainIcon from '../assets/brain-fill.svg?raw'

function SublineWithTypewriter({ onReady }: { onReady: () => void }) {
  useEffect(() => {
    const t = setTimeout(onReady, 600)
    return () => clearTimeout(t)
  }, [onReady])

  return (
    <div className="text-base md:text-lg font-mono text-white/70 max-w-xl mb-10 animate-fade-in">
      It watches your <AgentTypewriter /> sessions and writes living
      summaries. Next chat picks up where you left off.
    </div>
  )
}

export default function Hero() {
  const [showSubline, setShowSubline] = useState(false)
  const [showCta, setShowCta] = useState(false)

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
          waveColor={[0.49, 0.56, 0.66]}
          colorFadeFrom={[0, 0, 0]}
          colorFadeDuration={2000}
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
          className="text-3xl md:text-5xl font-mono font-bold tracking-tight text-white mb-6"
          onAnimationComplete={handleHeadlineComplete}
        />

        {showSubline && <SublineWithTypewriter onReady={handleSublineComplete} />}

        <div
          className={`w-full max-w-lg transition-all duration-500 ${
            showCta
              ? 'opacity-100 translate-y-0'
              : 'opacity-0 translate-y-3'
          }`}
        >
          <InstallCommand />

          <div className="mt-4 flex items-center justify-center gap-4 font-mono text-sm text-white/50">
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

      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 animate-bounce">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-white/30"
        >
          <path d="M12 5v14M5 12l7 7 7-7" />
        </svg>
      </div>
    </section>
  )
}
