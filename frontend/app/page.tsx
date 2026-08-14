import { redirect } from "next/navigation";

/**
 * The front door.
 *
 * This used to be the internal skeleton's notes to itself - "this skeleton
 * prioritizes upload, extraction traceability..." - which is what anyone
 * opening the bare address would read, including a client you sent the link to.
 *
 * The client-facing product is the intake flow, so the root goes there. The
 * internal pages are still at their own addresses, unchanged.
 */
export default function HomePage() {
  redirect("/intake/login");
}
