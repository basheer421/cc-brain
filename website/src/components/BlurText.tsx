import { motion, type TargetAndTransition } from 'motion/react'
import { useEffect, useRef, useState, useMemo } from 'react'

type AnimationKeyframes = Record<string, unknown>

const buildKeyframes = (
  from: AnimationKeyframes,
  steps: AnimationKeyframes[]
): Record<string, unknown[]> => {
  const keys = new Set([
    ...Object.keys(from),
    ...steps.flatMap((s) => Object.keys(s)),
  ])

  const keyframes: Record<string, unknown[]> = {}
  keys.forEach((k) => {
    keyframes[k] = [from[k], ...steps.map((s) => s[k])]
  })
  return keyframes
}

interface BlurTextProps {
  text?: string
  delay?: number
  className?: string
  animateBy?: 'words' | 'letters'
  direction?: 'top' | 'bottom'
  threshold?: number
  rootMargin?: string
  animationFrom?: AnimationKeyframes
  animationTo?: AnimationKeyframes[]
  easing?: (t: number) => number
  onAnimationComplete?: () => void
  stepDuration?: number
}

export default function BlurText({
  text = '',
  delay = 200,
  className = '',
  animateBy = 'words',
  direction = 'top',
  threshold = 0.1,
  rootMargin = '0px',
  animationFrom,
  animationTo,
  easing = (t) => t,
  onAnimationComplete,
  stepDuration = 0.35,
}: BlurTextProps) {
  const elements = animateBy === 'words' ? text.split(' ') : text.split('')
  const [inView, setInView] = useState(false)
  const ref = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    if (!ref.current) return
    const el = ref.current
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true)
          observer.unobserve(el)
        }
      },
      { threshold, rootMargin }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [threshold, rootMargin])

  const defaultFrom = useMemo(
    () =>
      direction === 'top'
        ? { filter: 'blur(10px)', opacity: 0, y: -50 }
        : { filter: 'blur(10px)', opacity: 0, y: 50 },
    [direction]
  )

  const defaultTo = useMemo(
    () => [
      {
        filter: 'blur(5px)',
        opacity: 0.5,
        y: direction === 'top' ? 5 : -5,
      },
      { filter: 'blur(0px)', opacity: 1, y: 0 },
    ],
    [direction]
  )

  const fromSnapshot = animationFrom ?? defaultFrom
  const toSnapshots = animationTo ?? defaultTo

  const stepCount = toSnapshots.length + 1
  const totalDuration = stepDuration * (stepCount - 1)
  const times = Array.from({ length: stepCount }, (_, i) =>
    stepCount === 1 ? 0 : i / (stepCount - 1)
  )

  return (
    <p
      ref={ref}
      className={className}
      style={{ display: 'flex', flexWrap: 'wrap', gap: animateBy === 'words' ? '0.25em' : undefined }}
    >
      {elements.map((segment, index) => {
        const animateKeyframes = buildKeyframes(fromSnapshot, toSnapshots)

        const spanTransition = {
          duration: totalDuration,
          times,
          delay: (index * delay) / 1000,
          ease: easing,
        }

        return (
          <motion.span
            className="inline-block will-change-[transform,filter,opacity]"
            key={index}
            initial={fromSnapshot as TargetAndTransition}
            animate={
              (inView ? animateKeyframes : fromSnapshot) as TargetAndTransition
            }
            transition={spanTransition}
            onAnimationComplete={
              index === elements.length - 1 ? onAnimationComplete : undefined
            }
          >
            {segment === ' ' ? ' ' : segment}
            {animateBy === 'words' && index < elements.length - 1 && ' '}
          </motion.span>
        )
      })}
    </p>
  )
}
