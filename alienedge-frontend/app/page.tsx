import { redirect } from "next/navigation";

/** Root entry — send users straight into the intelligence shell. */
export default function Home() {
  redirect("/dashboard");
}
