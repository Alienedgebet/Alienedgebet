/** Lightweight date helpers — kept out of lib/api.ts so the shell/layout
 *  client bundle does not pull the full axios API client during first compile. */

export const getTodayDate = (): string =>
  new Date().toISOString().split("T")[0];

export const shiftDate = (date: string, days: number): string => {
  const d = new Date(`${date}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().split("T")[0];
};

export const formatDate = (date: string): string =>
  new Date(date).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
