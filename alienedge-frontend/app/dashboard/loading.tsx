import { Loader2 } from "lucide-react";

export default function DashboardLoading() {
  return (
    <div className="flex min-h-[calc(100vh-56px)] flex-col items-center justify-center gap-3 p-6">
      <Loader2 className="h-6 w-6 animate-spin text-accent-indigo" />
      <p className="text-sm text-text-secondary">Loading dashboard…</p>
    </div>
  );
}
