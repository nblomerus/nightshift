import type { NextConfig } from "next";

// The lab's data comes from the stdlib floor server (api/floor.py: make floor), proxied under /api.
const FLOOR_API = process.env.NIGHTSHIFT_FLOOR_API ?? "http://127.0.0.1:18765";

const nextConfig: NextConfig = {
  devIndicators: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${FLOOR_API}/api/:path*` }];
  },
};

export default nextConfig;
