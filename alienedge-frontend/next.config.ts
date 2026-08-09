import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow both localhost and 127.0.0.1 (and this machine's LAN IP) to load
  // /_next client chunks + HMR. Without this, opening one host while the
  // server binds the other blocks hydration.
  allowedDevOrigins: ["localhost", "127.0.0.1", "172.20.10.2"],
  experimental: {
    // Slow disk: Turbopack FS cache compaction stalls route compiles.
    turbopackFileSystemCacheForDev: false,
  },
};

export default nextConfig;
