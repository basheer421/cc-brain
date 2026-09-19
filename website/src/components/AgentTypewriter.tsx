import { useEffect, useState, useRef } from 'react'

interface Agent {
  name: string
  color: string
}

const AGENTS: Agent[] = [
  { name: 'Claude Code', color: '#d97757' },
  { name: 'Hermes', color: '#7d8fa8' },
  { name: 'Pi', color: '#58a6ff' },
]

interface Props {
  typingSpeed?: number
  deletingSpeed?: number
  pauseDuration?: number
  className?: string
}

export default function AgentTypewriter({
  typingSpeed = 80,
  deletingSpeed = 40,
  pauseDuration = 1800,
  className = '',
}: Props) {
  const [displayed, setDisplayed] = useState('')
  const [agentIdx, setAgentIdx] = useState(0)
  const [charIdx, setCharIdx] = useState(0)
  const [deleting, setDeleting] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    const agent = AGENTS[agentIdx]
    const fullText = agent.name

    if (!deleting) {
      if (charIdx < fullText.length) {
        timeoutRef.current = setTimeout(() => {
          setDisplayed(fullText.slice(0, charIdx + 1))
          setCharIdx(charIdx + 1)
        }, typingSpeed)
      } else {
        timeoutRef.current = setTimeout(() => setDeleting(true), pauseDuration)
      }
    } else {
      if (displayed.length > 0) {
        timeoutRef.current = setTimeout(() => {
          setDisplayed(displayed.slice(0, -1))
        }, deletingSpeed)
      } else {
        setDeleting(false)
        setCharIdx(0)
        setAgentIdx((agentIdx + 1) % AGENTS.length)
      }
    }

    return () => clearTimeout(timeoutRef.current)
  }, [charIdx, displayed, deleting, agentIdx, typingSpeed, deletingSpeed, pauseDuration])

  return (
    <span className={className}>
      <span style={{ color: AGENTS[agentIdx].color }}>{displayed}</span>
      <span className="agent-cursor">|</span>
    </span>
  )
}
