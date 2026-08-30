import type { PredictionColumn } from "./PredictionTable"; // or from "@/components/predictions"
import { VerifyCell, type VerificationData } from "./VerifyCell";

export function createVerifyColumn<T = any>(): PredictionColumn<T> {
  return {
    key: "verify",
    header: "Verify",
    className: "w-20 shrink-0 text-center font-mono",
    render: (r: T) => <VerifyCell data={(r as { verification?: VerificationData })?.verification} />,
  };
}
