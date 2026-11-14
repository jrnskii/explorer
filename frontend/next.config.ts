import type { NextConfig } from "next";
import { resolve } from "node:path";
import { configureSearchEnvironment } from "./scripts/search-environment";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    agentFeedback: true,
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default function config(phase: string): NextConfig {
  configureSearchEnvironment(phase, resolve(import.meta.dirname, "../.env"));
  return nextConfig;
}
