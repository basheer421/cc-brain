import BrainIcon from '../assets/brain-fill.svg?raw'

export default function Footer() {
  return (
    <footer className="bg-[#0a0a0a] border-t border-white/5">

      <div className="mx-auto max-w-4xl px-6 py-10">
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-10">
          <div className="flex items-center gap-3">
            <div
              className="h-6 w-6 text-white"
              dangerouslySetInnerHTML={{ __html: BrainIcon }}
            />
            <span className="font-mono text-sm font-medium tracking-widest uppercase text-white">
              CC Brain
            </span>
          </div>

          <nav className="flex gap-16 font-mono text-sm">
            <div className="flex flex-col gap-3">
              <span className="text-[0.65rem] tracking-[0.2em] uppercase text-[#7d8fa8] font-medium mb-1">
                Project
              </span>
              <a
                href="https://github.com/basheer421/cc-brain"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#7d8590] hover:text-white transition-colors"
              >
                GitHub
              </a>
              <a
                href="https://github.com/basheer421/cc-brain#install"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#7d8590] hover:text-white transition-colors"
              >
                Install
              </a>
              <a
                href="https://github.com/basheer421/cc-brain/blob/main/LICENSE"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#7d8590] hover:text-white transition-colors"
              >
                MIT License
              </a>
            </div>

            <div className="flex flex-col gap-3">
              <span className="text-[0.65rem] tracking-[0.2em] uppercase text-[#7d8fa8] font-medium mb-1">
                Author
              </span>
              <a
                href="https://github.com/basheer421"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#7d8590] hover:text-white transition-colors"
              >
                basheer421
              </a>
              <a
                href="https://opencode.ai"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#7d8590] hover:text-white transition-colors"
              >
                OpenCode
              </a>
            </div>
          </nav>
        </div>

        <div className="border-t border-white/5 mt-10 pt-6 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <p className="font-mono text-xs text-[#484f58]">
            Open source. Built for developers who talk to AI coding agents all day.
          </p>
          <p className="font-mono text-xs text-[#484f58]">
            Illustrations by{' '}
            <a
              href="https://www.opendoodles.com"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-[#7d8590] transition-colors"
            >
              Open Doodles
            </a>
            {' & '}
            <a
              href="https://absurd.design"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-[#7d8590] transition-colors"
            >
              Absurd Design
            </a>
          </p>
        </div>
      </div>
    </footer>
  )
}
