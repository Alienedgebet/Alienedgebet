import { AlertTriangle } from "lucide-react";

interface ErrorStateProps {
  message: string;
}

export function ErrorState({ message }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <AlertTriangle className="h-5 w-5 text-accent-red" />
      <p className="max-w-sm text-xs text-text-muted">{message}</p>
    </div>
  );
}
