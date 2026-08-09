import { redirect } from "next/navigation";

/** Legacy /alerts → Live Alert Scanner (code 6). */
export default function AlertsRedirect() {
  redirect("/live/alerts");
}
