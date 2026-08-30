"use client";

import { filterApi } from "@/lib/api";
import { FilterTab } from "../FilterTab";
import { GG_FILTER_CONFIG } from "../filter-config";

export default function GGWeeklyPage() {
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto w-full">
      <FilterTab
        config={GG_FILTER_CONFIG}
        fetchSingle={(date, params) => filterApi.getGGFilter(date, params)}
        fetchWeekly={(params) => filterApi.getGGWeekly(params)}
      />
    </div>
  );
}
