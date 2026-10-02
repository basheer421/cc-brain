export default function Distinction() {
  return (
    <section className="bg-[#0a0a0a] py-20 px-6">
      <div className="mx-auto max-w-2xl text-center">
        <span className="font-mono text-[0.65rem] tracking-[0.2em] uppercase text-[#7d8fa8] font-medium">
          Answers, not pages
        </span>
        <div className="w-8 h-px bg-[#7d8fa8] opacity-30 mt-4 mb-5 mx-auto" />
        <h2 className="font-mono text-xl md:text-2xl font-bold text-white mb-4 leading-tight">
          Every session remembers every other session.
        </h2>
        <p className="font-mono text-sm text-[#7d8590] leading-relaxed max-w-xl mx-auto">
          CC Brain stores one claim per fact and returns only the facts that
          match, ranked by relevance, recency and importance. On 20 real
          questions it was as accurate as reading the whole wiki, with 25×
          less context. Cheap enough that your agent checks memory every time.
        </p>
      </div>
    </section>
  )
}
