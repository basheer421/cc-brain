import chilling from '../assets/illustrations/chilling.svg'
import absurdCh1 from '../assets/illustrations/absurd-ch1-08.png'
import jumping from '../assets/illustrations/jumping.svg'
import unboxing from '../assets/illustrations/unboxing.svg'

interface Feature {
  label: string
  heading: string
  description: string
  illustration: string | null
  isAbsurd?: boolean
}

const features: Feature[] = [
  {
    label: 'Always watching',
    heading: 'Lives in your menu bar.',
    description:
      'A native macOS app that watches your agent sessions — Claude Code via filesystem events, Hermes via lifecycle hooks. No browser extensions, no plugins, no configuration beyond an API key.',
    illustration: chilling,
  },
  {
    label: 'Not a log dump',
    heading: 'Summaries that rewrite themselves.',
    description:
      'Every conversation turn triggers an incremental rewrite. Goal, progress, key decisions, current state — a living document, not a static export.',
    illustration: absurdCh1,
    isAbsurd: true,
  },
  {
    label: 'The whole point',
    heading: 'New chat, full context.',
    description:
      'Summaries write to ~/.claude/CLAUDE.md. Your next Claude Code session reads them automatically. No copy-pasting, no "here\'s what I was working on."',
    illustration: jumping,
  },
  {
    label: 'Your model, your cost',
    heading: 'Any OpenAI-compatible endpoint.',
    description:
      'OpenRouter by default — or point it at your own vLLM box and summarize for free. Swap models with one config change. Summarization doesn\'t need frontier intelligence.',
    illustration: unboxing,
  },
]

function FeatureSection({
  feature,
  index,
}: {
  feature: Feature
  index: number
}) {
  const isEven = index % 2 === 0
  const bgClass = isEven ? 'bg-black' : 'bg-[#0a0a0a]'

  return (
    <section className={`${bgClass} py-20 px-6`}>
      <div
        className={`mx-auto max-w-4xl flex flex-col ${
          isEven ? 'md:flex-row' : 'md:flex-row-reverse'
        } items-center gap-12 md:gap-16`}
      >
        <div className="flex-1 min-w-0">
          <span className="font-mono text-[0.65rem] tracking-[0.2em] uppercase text-[#7d8fa8] font-medium">
            {feature.label}
          </span>
          <div className="w-8 h-px bg-[#7d8fa8] opacity-30 mt-4 mb-5" />
          <h2 className="font-mono text-xl md:text-2xl font-bold text-white mb-3 leading-tight">
            {feature.heading}
          </h2>
          <p className="font-mono text-sm text-[#7d8590] leading-relaxed max-w-md">
            {feature.description}
          </p>
        </div>

        {feature.illustration && (
          <div className="w-48 md:w-64 shrink-0 opacity-70">
            <img
              src={feature.illustration}
              alt=""
              className="w-full h-auto"
              style={{ filter: feature.isAbsurd ? 'invert(1)' : 'invert(1) grayscale(1) brightness(0.8) contrast(1.1)' }}
            />
          </div>
        )}
      </div>
    </section>
  )
}

export default function Features() {
  return (
    <>
      {features.map((feature, i) => (
        <FeatureSection key={feature.label} feature={feature} index={i} />
      ))}
    </>
  )
}
