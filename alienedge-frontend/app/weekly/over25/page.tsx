"use client";

import { filterApi } from "@/lib/api";
import { FilterTab } from "../FilterTab";
import { OVER25_FILTER_CONFIG } from "../filter-config";

export default function Over25WeeklyPage() {
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto w-full">
      <FilterTab
        config={OVER25_FILTER_CONFIG}
        fetchSingle={(date, params) => filterApi.getOver25Filter(date, params)}
        fetchWeekly={(params) => filterApi.getOver25Weekly(params)}
      />
    </div>
  );
}
