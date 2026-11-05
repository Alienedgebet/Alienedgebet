import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// ============================================================
// SAFE NUMERIC FORMATTING
// ============================================================
// WHY THIS EXISTS
// ---------------
// Two production crashes had the same shape: a column renderer called
// `.toFixed()` straight on a value that was not a number.
//
//   1. Win page   — `e.Market_Power_Scores.Win_Dominance.toFixed`
//                   threw because the pillar is legitimately `null` for
//                   teams whose inputs were never reported (schema v3).
//   2. Over 2.5   — `e.Odds.toFixed is not a function` because the row
//                   arrived from the CSV recovery path, where every value
//                   is a STRING ('1.41'), not a float.
//
// Both took down the ENTIRE page: React unmounts the tree on a render
// throw and app/error.tsx replaced the whole market with
// "Something went wrong".
//
// `fmt` is the single safe door for a table cell. It never throws, and it
// renders an absent measurement as a dash rather than inventing a number:
//
//   fmt(null)             -> "—"     (not measured)
//   fmt(undefined)        -> "—"
//   fmt(NaN)              -> "—"
//   fmt('1.41')           -> "1.41"  (numeric string, coerced)
//   fmt(1.4149, 2)        -> "1.41"
//   fmt('abc')            -> "—"     (not numeric at all)
//
// A dash is deliberate. `null` means "could not be measured"; rendering it
// as 0 would claim the measurement happened and returned zero, which is the
// fabrication this project has already had to undo once (see the schema-v3
// note on DnaV2Profile.Market_Power_Scores).
//
// The type is deliberately wide. It accepts whatever a heterogeneous engine
// payload can hand us so a call site never has to narrow before formatting.

/** The placeholder for a value that is absent or not a number. */
export const NO_VALUE = "—"

/**
 * Coerce anything a JSON/CSV payload can produce into a finite number,
 * or `null` when no honest number can be read.
 *
 * Numeric strings are accepted on purpose: the CSV recovery path in
 * main.py (`_recover_engine_output_from_disk`) parses with
 * `csv.DictReader`, so every value comes back as a string. Rejecting
 * `'1.41'` would push the bug straight back to the caller.
 */
export function toFiniteNumber(
  value: unknown
): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null
  }
  // Booleans are never a measurement here, even though JS coerces them.
  if (typeof value === "boolean") return null
  if (typeof value === "string") {
    const trimmed = value.trim()
    if (trimmed === "") return null
    const parsed = Number(trimmed)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

/**
 * Format a possibly-absent, possibly-typed-loosely value for display.
 *
 * @param value  the raw field from the payload
 * @param digits decimal places, default 1
 * @param dash   what to render when no number can be read
 */
export function fmt(
  value: unknown,
  digits = 1,
  dash: string = NO_VALUE
): string {
  const n = toFiniteNumber(value)
  if (n === null) return dash
  return n.toFixed(digits)
}

/**
 * Same as {@link fmt} but keeps the raw value when it is a plain
 * non-numeric string, so text columns can use one helper too.
 */
export function fmtOrText(
  value: unknown,
  digits = 1,
  dash: string = NO_VALUE
): string {
  const n = toFiniteNumber(value)
  if (n !== null) return n.toFixed(digits)
  if (typeof value === "string" && value.trim() !== "") return value.trim()
  return dash
}
