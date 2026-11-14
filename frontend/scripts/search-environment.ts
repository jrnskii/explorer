import { readFileSync } from "node:fs"
import { parseEnv } from "node:util"
import { PHASE_DEVELOPMENT_SERVER } from "next/constants"

/** Next has already loaded frontend/.env* before evaluating its config. */
export function configureSearchEnvironment(
  phase: string,
  rootEnvPath: string,
  environment: Record<string, string | undefined> = process.env,
): void {
  if (phase !== PHASE_DEVELOPMENT_SERVER) return

  let defaults: Record<string, string | undefined> = {}
  try {
    defaults = parseEnv(readFileSync(rootEnvPath, "utf8"))
  } catch (error) {
    if (!(error instanceof Error) || !("code" in error) || error.code !== "ENOENT") throw error
  }

  // Only the proxy's server credentials belong here, never provider keys or NEXT_PUBLIC_*.
  for (const key of ["APP_ACCESS_TOKEN", "BACKEND_GRAPHQL_URL"]) {
    if (environment[key] === undefined && defaults[key] !== undefined) {
      environment[key] = defaults[key]
    }
  }
  environment.BACKEND_GRAPHQL_URL ??= "http://127.0.0.1:8000/graphql"
}
