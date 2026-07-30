import Hero from './components/Hero'
import Distinction from './components/Distinction'
import Features from './components/Features'
import Footer from './components/Footer'

export default function App() {
  return (
    <main className="bg-black">
      <Hero />
      <Distinction />
      <div className="relative h-16 overflow-hidden">
        <svg
          className="absolute inset-0 w-full h-full"
          viewBox="0 0 1440 64"
          preserveAspectRatio="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <polygon points="0,0 1440,0 1440,0 0,64" fill="#0a0a0a" />
          <polygon points="0,64 1440,0 1440,64" fill="#000000" />
          <line x1="0" y1="64" x2="1440" y2="0" stroke="#7d8fa8" strokeWidth="1" strokeOpacity="0.3" />
        </svg>
      </div>
      <Features />
      <Footer />
    </main>
  )
}
