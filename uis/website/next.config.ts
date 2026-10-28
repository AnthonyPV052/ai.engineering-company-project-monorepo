import path from "path";
import type { NextConfig } from "next";

const API_UPSTREAM =
  process.env.API_UPSTREAM_URL ?? "http://localhost:8020";

/** Monorepo raíz — subimos dos niveles desde uis/website */
const repoRoot = path.resolve(__dirname, "../..");

const nextConfig: NextConfig = {
  // webpack es necesario para resolver @repo/* que apunta a ../../src/
  // que está fuera del directorio raíz del proyecto. Turbopack no soporta
  // imports fuera del proyecto (server relative imports not implemented).
  webpack: (config) => {
    if (config.resolve?.alias) {
      config.resolve.alias = {
        ...config.resolve.alias,
        "@repo": path.join(repoRoot, "src"),
      };
    }
    return config;
  },
  async rewrites() {
    return [
      {
        // El gestor ya incluye el prefijo /api en FastAPI. Esta regla debe ir
        // antes de la regla genérica, que se mantiene para los endpoints legados.
        source: "/api/incidents/:path*",
        destination: `${API_UPSTREAM}/api/incidents/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${API_UPSTREAM}/:path*`,
      },
    ];
  },
};

export default nextConfig;
