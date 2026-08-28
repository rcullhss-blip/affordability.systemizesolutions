import type { Metadata } from "next";
import "./portal.css";
import { RequireAuth } from "@/components/auth/RequireAuth";

const FIRM = process.env.NEXT_PUBLIC_FIRM || "first_legal";
const FIRM_NAME = FIRM === "barings" ? "Barings Law"
  : FIRM === "accord" ? "Accord Solicitors"
  : "First Legal Solicitors";

export const metadata: Metadata = {
  title: `${FIRM_NAME} — Secure Document Upload`,
  description: "Secure credit report upload portal",
};

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return <RequireAuth>{children}</RequireAuth>;
}
