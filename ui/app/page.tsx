"use client";

import dynamic from "next/dynamic";

// The lab floor is entirely client-side (live clocks, server-sent events, the window's size).
const LabApp = dynamic(() => import("@/components/LabApp"), { ssr: false });

export default function Page() {
  return <LabApp />;
}
