"use client";

import { filterApi } from "@/lib/api";
import { FilterTab } from "../FilterTab";
import { WIN_FILTER_CONFIG } from "../filter-config";

export default function WinPrecisionWeeklyPage() {
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto w-full">
      <FilterTab
        config={WIN_FILTER_CONFIG}
        fetchSingle={(date) => filterApi.getWinPrecision(date)}
        fetchWeekly={(params) => filterApi.getWinPrecisionWeekly(params as any)}
      />
    </div>
  );
}
