import { redirect } from "next/navigation";

/** Legacy /live → Live Match Edges (codes 1–2). */
export default function LiveIndexRedirect() {
  redirect("/live/edges");
}
