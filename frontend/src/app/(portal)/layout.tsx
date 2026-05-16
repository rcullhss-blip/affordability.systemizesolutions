import type { Metadata } from "next";
import "./portal.css";

export const metadata: Metadata = {
  title: "First Legal Solicitors — Secure Document Upload",
  description: "Secure credit report upload portal",
};

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
