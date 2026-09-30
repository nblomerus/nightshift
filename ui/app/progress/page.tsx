"use client";

import dynamic from "next/dynamic";

// The lab's progress across runs and days (client-only: it polls the floor server).
const Progress = dynamic(() => import("@/components/Progress"), { ssr: false });

export default function Page() {
  return <Progress />;
}
