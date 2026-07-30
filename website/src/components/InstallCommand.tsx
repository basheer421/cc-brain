import { useState, useCallback } from 'react'

const COMMAND = 'curl -sSL cc-brain.bachir.me | bash'

export default function InstallCommand() {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(COMMAND)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [])

  return (
    <div className="flex items-center gap-3 rounded-lg border border-white/20 bg-white/5 backdrop-blur-sm px-5 py-3 font-mono text-sm text-white/90">
      <span className="text-white/40 select-none">$</span>
      <code className="flex-1 select-all">{COMMAND}</code>
      <button
        onClick={handleCopy}
        className="shrink-0 text-white/40 hover:text-white transition-colors cursor-pointer"
        aria-label="Copy install command"
      >
        {copied ? (
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
            <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
          </svg>
        )}
      </button>
    </div>
  )
}
