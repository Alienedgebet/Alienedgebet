"use client";

import { filterApi } from "@/lib/api";
import { FilterTab } from "../FilterTab";
import { WIN_FILTER_CONFIG } from "../filter-config";

export default function WinWeeklyPage() {
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto w-full">
      <FilterTab
        config={WIN_FILTER_CONFIG}
        fetchSingle={(date, params) => filterApi.getWinFilter(date, params)}
        fetchWeekly={(params) => filterApi.getWinWeekly(params)}
      />
    </div>
  );
}
