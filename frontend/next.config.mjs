import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

/**
 * Production: static export to out/, served by FastAPI on one origin.
 * `next dev`: same app, with /api proxied to the backend so calls stay same-origin.
 */
export default function config(phase) {
  /** @type {import('next').NextConfig} */
  const base = {
    output: "export",
    images: { unoptimized: true },
    trailingSlash: false,
    reactStrictMode: true,
  };
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    const backend = process.env.BACKEND_URL || "http://localhost:8000";
    return {
      ...base,
      output: undefined,
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
      },
    };
  }
  return base;
}
