export default function Distinction() {
  return (
    <section className="bg-[#0a0a0a] py-20 px-6">
      <div className="mx-auto max-w-2xl">
        <h2 className="font-mono text-lg md:text-xl font-bold text-white mb-6 leading-tight">
          "How is this different from Claude Code memory?"
        </h2>
        <p className="font-mono text-sm text-[#7d8590] leading-relaxed">
          Claude Code memory is static. You write it, or Claude writes it when
          asked. CC Brain runs in the background — every conversation turn gets
          summarized, every session gets a living document. When you start a new
          chat, it already knows the state of every other session. No one had to
          remember to write anything down.
        </p>
      </div>
    </section>
  )
}
