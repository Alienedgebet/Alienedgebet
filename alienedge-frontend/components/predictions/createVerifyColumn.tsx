import type { PredictionColumn } from "./PredictionTable"; // or from "@/components/predictions"
import { VerifyCell, type VerificationData } from "./VerifyCell";

export function createVerifyColumn<T = any>(field: string = "verification"): PredictionColumn<T> {
  return {
    key: field === "verification" ? "verify" : `verify_${field}`,
    header: "Verify",
    className: "w-20 shrink-0 text-center font-mono",
    render: (r: T) => (
      <VerifyCell data={(r as Record<string, VerificationData | undefined>)?.[field]} />
    ),
  };
}
