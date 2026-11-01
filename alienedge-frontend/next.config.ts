import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{
      source: "/(.*)",
      headers: [
        { key: "Content-Security-Policy", value: "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' https://api.alienedge.tech" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        { key: "X-DNS-Prefetch-Control", value: "off" },
      ],
    }, {
      source: "/hero-alien-mascot-login-v1-540.webp",
      headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
    }, {
      source: "/hero-alien-mascot-login-v1-1024.webp",
      headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
    }];
  },
  // /_next client chunks + HMR. Without this, opening one host while the
  // server binds the other blocks hydration.
  allowedDevOrigins: ["localhost", "127.0.0.1", "172.20.10.2"],
  experimental: {
    // Slow disk: Turbopack FS cache compaction stalls route compiles.
    turbopackFileSystemCacheForDev: false,
  },
};

export default nextConfig;
