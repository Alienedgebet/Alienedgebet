"use client";

import { useEffect } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[AlienEdge]", error);
  }, [error]);

  return (
    <div className="flex min-h-[calc(100vh-56px)] flex-col items-center justify-center gap-4 p-6">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-accent-amber/20 bg-accent-amber/5">
        <AlertTriangle className="h-6 w-6 text-accent-amber" />
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-text-primary">Something went wrong</p>
        <p className="mt-1 max-w-xs text-xs text-text-secondary">
          {error.message || "An unexpected error occurred. Try refreshing the page."}
        </p>
        {error.digest && (
          <p className="mt-2 font-mono text-2xs text-text-dim">
            digest: {error.digest}
          </p>
        )}
      </div>
      <button
        onClick={reset}
        className="flex items-center gap-2 rounded border border-border px-4 py-2 text-xs text-text-secondary transition-colors hover:border-border-bright hover:text-text-primary"
      >
        <RotateCcw className="h-3 w-3" />
        Try again
      </button>
    </div>
  );
}
