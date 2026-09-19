export default function Distinction() {
  return (
    <section className="bg-[#0a0a0a] py-20 px-6">
      <div className="mx-auto max-w-3xl">
        <div className="text-center mb-12">
          <span className="font-mono text-[0.65rem] tracking-[0.2em] uppercase text-[#7d8fa8] font-medium">
            Cross-session memory
          </span>
          <div className="w-8 h-px bg-[#7d8fa8] opacity-30 mt-4 mb-5 mx-auto" />
          <h2 className="font-mono text-xl md:text-2xl font-bold text-white mb-4 leading-tight">
            Every session remembers every other session.
          </h2>
          <p className="font-mono text-sm text-[#7d8590] leading-relaxed max-w-xl mx-auto">
            CC Brain writes structured Markdown summaries to a single folder.
            Any agent, or you, can search them instantly.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-6">
          <div className="border border-[#1e1e1e] rounded-lg p-5">
            <div className="font-mono text-white text-sm font-bold mb-2">
              Cross-agent awareness
            </div>
            <p className="font-mono text-xs text-[#7d8590] leading-relaxed">
              Start a session in one agent, continue in another. Every summary
              lands in the same directory, so the next chat already knows what
              happened, regardless of which tool wrote it.
            </p>
          </div>

          <div className="border border-[#1e1e1e] rounded-lg p-5">
            <div className="font-mono text-white text-sm font-bold mb-2">
              Instant recall via grep
            </div>
            <p className="font-mono text-xs text-[#7d8590] leading-relaxed">
              Need to find that auth refactor from last week?{' '}
              <span className="text-[#d97757]">grep -r "OAuth" ~/.cc-brain/summaries/</span>{' '}
              hits every session from every agent. Plain Markdown, no database,
              no vendor lock-in.
            </p>
          </div>

          <div className="border border-[#1e1e1e] rounded-lg p-5">
            <div className="font-mono text-white text-sm font-bold mb-2">
              Automatic, not manual
            </div>
            <p className="font-mono text-xs text-[#7d8590] leading-relaxed">
              No "remember this" commands. No writing memory files yourself.
              Every conversation turn is summarized in real-time. The memory
              builds itself while you work.
            </p>
          </div>
        </div>

        <div className="mt-10 border border-[#1e1e1e] rounded-lg p-5 bg-black">
          <pre className="font-mono text-xs text-[#7d8590] leading-relaxed overflow-x-auto">
            <span className="text-[#57606a]">$</span>{' '}
            <span className="text-white">grep -rl "Patroni" ~/.cc-brain/summaries/</span>
            {'\n'}
            <span className="text-[#d97757]">my-infra-1726...md</span>
            {'\n'}
            <span className="text-[#7d8fa8]">h-db-migration-1726...md</span>
            {'\n'}
            <span className="text-[#58a6ff]">p-ha-cluster-1726...md</span>
            {'\n\n'}
            <span className="text-[#57606a]"># Three agents, three sessions, one keyword. Instant context.</span>
          </pre>
        </div>
      </div>
    </section>
  )
}
