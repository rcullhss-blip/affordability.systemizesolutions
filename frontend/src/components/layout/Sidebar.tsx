"use client";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";

const NAV = [
  { label: "Dashboard", href: "/" },
  { label: "Batches", href: "/batches" },
  { label: "Clients", href: "/clients" },
  { label: "Analytics", href: "/analytics" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-60 shrink-0 min-h-screen bg-gray-900 border-r border-gray-800 flex flex-col p-5 sticky top-0 h-screen overflow-y-auto">
      <div className="mb-8">
        <Link href="/">
          <Image
            src="/logo-white.png"
            alt="Systemize"
            width={140}
            height={40}
            className="object-contain"
            priority
          />
        </Link>
        <p className="text-xs text-gray-500 mt-2">Affordability Platform</p>
      </div>

      <nav className="space-y-0.5 flex-1">
        {NAV.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                active
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-gray-400 hover:bg-gray-800 hover:text-white"
              }`}
            >
              <NavIcon href={item.href} active={active} />
              <span className="ml-2.5">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="pt-4 border-t border-gray-800">
        <p className="text-xs text-gray-600">Fintech-grade legal infrastructure</p>
        <p className="text-xs text-gray-700 mt-0.5">v2.0</p>
      </div>
    </aside>
  );
}

function NavIcon({ href, active }: { href: string; active: boolean }) {
  const cls = `w-4 h-4 shrink-0 ${active ? "text-white" : "text-gray-500"}`;
  if (href === "/")
    return (
      <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    );
  if (href === "/batches")
    return (
      <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    );
  if (href === "/clients")
    return (
      <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
      </svg>
    );
  return (
    <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    </svg>
  );
}
