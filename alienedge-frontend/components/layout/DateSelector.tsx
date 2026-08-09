"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useSelectedDate } from "@/lib/date-context";
import { getTodayDate, shiftDate } from "@/lib/date-utils";

export function DateSelector() {
  const { date, setDate } = useSelectedDate();
  const isToday = date === getTodayDate();

  return (
    <div className="glass flex items-center gap-1.5 rounded-lg p-1">
      <motion.button
        type="button"
        onClick={() => setDate(shiftDate(date, -1))}
        aria-label="Previous day"
        whileHover={{ scale: 1.08, borderColor: "#253660" }}
        whileTap={{ scale: 0.92 }}
        transition={{ duration: 0.15 }}
        className="flex h-6 w-6 items-center justify-center rounded border border-border text-text-muted transition-colors hover:text-text-primary"
      >
        <ChevronLeft className="h-3 w-3" />
      </motion.button>

      <input
        type="date"
        value={date}
        onChange={(e) => e.target.value && setDate(e.target.value)}
        className="w-[8.5rem] rounded border border-border bg-bg-elevated px-2 py-1 font-mono text-xs text-text-secondary outline-none [color-scheme:dark] transition-colors focus-visible:border-accent-indigo/60 focus-visible:shadow-glow"
      />

      <motion.button
        type="button"
        onClick={() => setDate(shiftDate(date, 1))}
        aria-label="Next day"
        whileHover={{ scale: 1.08, borderColor: "#253660" }}
        whileTap={{ scale: 0.92 }}
        transition={{ duration: 0.15 }}
        className="flex h-6 w-6 items-center justify-center rounded border border-border text-text-muted transition-colors hover:text-text-primary"
      >
        <ChevronRight className="h-3 w-3" />
      </motion.button>

      <AnimatePresence>
        {!isToday && (
          <motion.button
            type="button"
            onClick={() => setDate(getTodayDate())}
            initial={{ opacity: 0, scale: 0.8, width: 0, marginLeft: 0 }}
            animate={{ opacity: 1, scale: 1, width: "auto", marginLeft: 2 }}
            exit={{ opacity: 0, scale: 0.8, width: 0, marginLeft: 0 }}
            transition={{ duration: 0.18, ease: [0.34, 1.56, 0.64, 1] }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="overflow-hidden whitespace-nowrap rounded border border-accent-indigo/30 bg-accent-indigo/10 px-2 py-1 font-mono text-2xs font-medium text-accent-indigo transition-colors hover:bg-accent-indigo/20 hover:shadow-glow"
          >
            Today
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
