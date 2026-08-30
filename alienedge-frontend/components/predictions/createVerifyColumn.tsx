import { VerifyCell, type VerificationData } from "./VerifyCell";
import type { PredictionColumn } from "./PredictionTable";

export function createVerifyColumn<T extends { verification?: VerificationData }>(): PredictionColumn<T> {
  return {
    key: "verify",
    header: "Verify",
    className: "w-20 shrink-0 text-center font-mono",
    render: (r: any) => <VerifyCell data={r?.verification} />,
  };
}
