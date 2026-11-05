import { Loader2 } from "lucide-react";

/** Short route transition — soft nav should replace this quickly once the page is compiled. */
export default function Loading() {
  return (
    <div className="flex min-h-[calc(100vh-56px)] flex-col items-center justify-center gap-3 p-6">
      <Loader2 className="h-6 w-6 animate-spin text-accent-indigo" />
      <p className="text-sm text-text-secondary">Loading page…</p>
    </div>
  );
}
