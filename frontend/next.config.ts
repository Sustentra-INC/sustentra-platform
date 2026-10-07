import type { NextConfig } from "next";

// Local dev proxies same-origin `/api/v1/*` to the backend so the browser sends
// the `__Host-session` cookie without CORS. In production Caddy routes `/api/*`
// to the API, so this rewrite is a dev-only convenience. (FE-001)
const API_URL =
  process.env.BACKEND_INTERNAL_URL ?? process.env.NEXT_PUBLIC_BACKEND_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image (node server.js).
  output: "standalone",
  experimental: {
    // The dev rewrite below buffers request bodies (10 MB by default), which cut off
    // document uploads. Match the upload limit (INFRA-007: 25 MB + multipart envelope).
    // Prod is unaffected: Caddy sends /api/* straight to the API.
    proxyClientMaxBodySize: "26mb",
  },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${API_URL}/api/v1/:path*` }];
  },
};

export default nextConfig;
