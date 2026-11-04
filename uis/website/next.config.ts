import path from "path";
import type { NextConfig } from "next";

const API_UPSTREAM =
  process.env.API_UPSTREAM_URL ?? "http://localhost:8020";

/** Monorepo raíz — subimos dos niveles desde uis/website */
const repoRoot = path.resolve(__dirname, "../..");

const nextConfig: NextConfig = {
  // CRÍTICO para SSE (Server-Sent Events):
  // La compresión gzip de Next.js bufferea la respuesta en lugar de hacer
  // flush de cada frame, por lo que un stream `text/event-stream` nunca llega
  // al navegador (content-encoding: gzip + chunked => el reader se queda
  // esperando indefinidamente). Deshabilitarla permite que los eventos
  // atraviesen el proxy de rewrites en tiempo real.
  compress: false,
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
        source: "/api/rfp/:path*",
        destination: `${API_UPSTREAM}/api/rfp/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${API_UPSTREAM}/:path*`,
      },
    ];
  },
};

export default nextConfig;
