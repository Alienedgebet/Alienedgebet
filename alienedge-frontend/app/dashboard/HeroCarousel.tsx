"use client";

import { useEffect, useCallback, useState } from "react";
import Image from "next/image";
import { ArrowRight, ChevronLeft, ChevronRight, Signal } from "lucide-react";
import { cn } from "@/lib/utils";

interface HeroCarouselProps {
  peakConfidence: number;
  scrollTargetId: string;
}

interface Slide {
  lines: string[];
  sub: string;
}

// Slide 1 is the brand line — closing word is "ACCURACY." (not "PROFITS.")
// per the no-wallet/no-betting-vocabulary rule in .cursorrules. Slide 2 makes
// the engine architecture the headline: the 6 tree markets each run
// Normal -> Psychology -> Aggregator before a pick reaches the feed.
const SLIDES: Slide[] = [
  {
    lines: ["DATA-DRIVEN.", "SMARTER.", "ACCURACY."],
    sub: "Join thousands of smart analysts making better decisions daily with AlienEdge.",
  },
  {
    lines: ["NORMAL.", "PSYCHOLOGY.", "AGGREGATOR."],
    sub: "6 engine chains — Win, GG, Overs, Corners & Underdog — filtered through 3 stages to cut weak fixtures.",
  },
];

const AUTOPLAY_MS = 5000;

/**
 * The mascot render sits on a plain near-black backdrop (not true alpha
 * transparency). This mask keeps the character opaque while fading its
 * flat black corners to transparent, so it blends into the CSS nebula
 * background instead of showing a hard rectangle edge.
 */
const MASCOT_MASK = "radial-gradient(ellipse 60% 90% at 50% 40%, black 65%, transparent 100%)";

/**
 * Dashboard hero — strict two-layer architecture so the background never
 * flashes/unmounts as slides advance:
 *
 * Layer 1 (static, OUTSIDE any AnimatePresence): the fixed-height frame,
 * the CSS nebula/planet-ring backdrop, the mascot, and the dark
 * left-to-right gradient that keeps text readable. These render exactly
 * once for the component's lifetime — the mascot is anchored directly to
 * the section (percentage-height against an explicit-height ancestor,
 * which reliably resolves) rather than to a flex item, which is what
 * caused it to render as a tiny thumbnail in an earlier version.
 *
 * Layer 2 (animated foreground): only the headline/CTA column, keyed to
 * `index` so it swaps every 5s (pauses on hover). The phone mockup that
 * used to sit on the right was removed — it kept forcing an awkward
 * position/size trade-off against the mascot, so the mascot now owns the
 * whole right side instead. Pagination controls sit in their own static
 * layer on top, independent of the slide transition.
 */
export function HeroCarousel({ peakConfidence, scrollTargetId }: HeroCarouselProps) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  const goTo = useCallback((i: number) => setIndex((i + SLIDES.length) % SLIDES.length), []);
  const next = useCallback(() => goTo(index + 1), [goTo, index]);
  const prev = useCallback(() => goTo(index - 1), [goTo, index]);

  useEffect(() => {
    if (paused) return;
    const t = setInterval(() => setIndex((i) => (i + 1) % SLIDES.length), AUTOPLAY_MS);
    return () => clearInterval(t);
  }, [paused]);

  const slide = SLIDES[index];

  const handleScroll = () => {
    document.getElementById(scrollTargetId)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <section
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      className="relative h-[400px] w-full overflow-hidden rounded-2xl bg-nebula shadow-elevated"
    >
      {/* ---------- Layer 1: static background — never re-renders on slide change ---------- */}
      {/* Decorative "planet ring" glows — pure CSS, echoes the circular portal shapes in the reference art. Purple/indigo only, no diffuse blue wash. */}
      <div className="pointer-events-none absolute right-[8%] top-[8%] h-44 w-44 rounded-full border-2 border-accent-indigo/35 blur-[1px] [transform:rotate(-18deg)_scaleY(0.35)]" />
      <div className="pointer-events-none absolute right-[14%] top-[14%] h-64 w-64 rounded-full border border-accent-purple/25 blur-[2px] [transform:rotate(-18deg)_scaleY(0.35)]" />
      <div className="pointer-events-none absolute right-[6%] top-[42%] h-24 w-24 rounded-full bg-accent-purple/25 blur-2xl" />
      <div className="pointer-events-none absolute left-[6%] bottom-[10%] h-32 w-32 rounded-full bg-accent-indigo/20 blur-2xl" />

      {/* Mascot — anchored to the section (explicit h-[400px]), not to a flex item, so its percentage height reliably resolves to a real size every time. Width is derived from the source's native 1024x1536 (2:3) ratio via aspect-ratio, replicating the old <img height-only> sizing without a JS-measured intrinsic box.
          `unoptimized`: this machine has no `sharp` binary available, so Next's
          on-demand image route falls back to a pure-JS/WASM codec that is slow
          enough to peg the CPU and stall the whole dev server on a 1.35MB
          source. Serving the file as-is (same bytes the old <img> served)
          keeps the aspect-ratio/CLS/priority benefits of next/image without
          that server-side re-encode. Once `sharp` is installed, drop this
          prop to get real on-the-fly resizing/WebP. */}
      <div className="pointer-events-none absolute bottom-0 right-[4%] hidden h-[115%] aspect-[2/3] sm:block">
        <Image
          src="/hero-alien-mascot.png"
          alt="AlienEdge mascot"
          fill
          priority
          unoptimized
          sizes="480px"
          className="object-contain"
          style={{ maskImage: MASCOT_MASK, WebkitMaskImage: MASCOT_MASK }}
        />
      </div>

      <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-bg-primary via-bg-primary/70 to-transparent" />

      {/* ---------- Layer 2: animated foreground — only this swaps every 5s ---------- */}
      <div className="relative z-10 flex h-full items-center px-8 md:px-14">
          <div key={`text-${index}`} className="flex max-w-md flex-col gap-4">
            <h1 className="font-sans text-4xl font-extrabold leading-[1.05] text-text-primary drop-shadow-[0_0_22px_rgba(99,102,241,0.5)] sm:text-5xl">
              {slide.lines.map((line, i) => (
                <span
                  key={i}
                  className={cn(
                    "block",
                    i === slide.lines.length - 1 &&
                      "text-accent-amber drop-shadow-[0_0_26px_rgba(245,158,11,0.6)]"
                  )}
                >
                  {line}
                </span>
              ))}
            </h1>
            <p className="max-w-sm text-sm leading-relaxed text-text-secondary">{slide.sub}</p>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={handleScroll}
                className="group inline-flex w-fit items-center gap-2 rounded-lg border border-accent-cyan bg-accent-cyan/10 px-5 py-2.5 text-sm font-semibold text-accent-cyan shadow-glow-cyan transition-all duration-150 hover:bg-accent-cyan/20"
              >
                View Elite Picks
                <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1" />
              </button>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-accent-green/30 bg-accent-green/10 px-3 py-1.5 text-xs font-semibold text-accent-green">
                <Signal className="h-3 w-3" />
                {peakConfidence.toFixed(0)}% Peak Confidence
              </span>
            </div>
          </div>
      </div>

      {/* ---------- Static controls layer — arrows + dots never animate with the slide ---------- */}
      <div className="absolute bottom-5 left-8 z-20 flex items-center gap-3 md:left-14">
        <button
          aria-label="Previous slide"
          onClick={prev}
          className="flex h-7 w-7 items-center justify-center rounded-full border border-border-bright/60 bg-bg-primary/40 text-text-muted backdrop-blur-sm transition-colors hover:border-border-bright hover:text-text-primary"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <button
          aria-label="Next slide"
          onClick={next}
          className="flex h-7 w-7 items-center justify-center rounded-full border border-border-bright/60 bg-bg-primary/40 text-text-muted backdrop-blur-sm transition-colors hover:border-border-bright hover:text-text-primary"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
        <div className="flex items-center gap-1.5">
          {SLIDES.map((_, i) => (
            <button
              key={i}
              aria-label={`Go to slide ${i + 1}`}
              onClick={() => goTo(i)}
              className={cn(
                "h-1.5 rounded-full transition-all duration-300",
                i === index ? "w-6 bg-accent-indigo" : "w-1.5 bg-border-bright hover:bg-text-muted"
              )}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
