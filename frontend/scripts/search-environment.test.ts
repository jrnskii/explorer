// @vitest-environment node
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER, PHASE_TEST } from "next/constants"
import { afterEach, beforeEach, expect, test } from "vitest"
import { configureSearchEnvironment } from "./search-environment"

let directory: string
let envPath: string
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), "search-environment-"))
  envPath = join(directory, ".env")
})
afterEach(() => rmSync(directory, { recursive: true, force: true }))

test("connects local frontend searches using the shared root token", () => {
  writeFileSync(envPath, 'APP_ACCESS_TOKEN="shared-secret" # shared with just api\nSCRAPPA_API_KEY=provider-secret\nNEXT_PUBLIC_SECRET=private\n')
  const environment: Record<string, string | undefined> = {}
  configureSearchEnvironment(PHASE_DEVELOPMENT_SERVER, envPath, environment)
  expect(environment).toEqual({
    APP_ACCESS_TOKEN: "shared-secret",
    BACKEND_GRAPHQL_URL: "http://127.0.0.1:8000/graphql",
  })
})

test("accepts a custom backend URL from the root env", () => {
  writeFileSync(envPath, "BACKEND_GRAPHQL_URL=http://127.0.0.1:9000/graphql\n")
  const environment: Record<string, string | undefined> = {}
  configureSearchEnvironment(PHASE_DEVELOPMENT_SERVER, envPath, environment)
  expect(environment.BACKEND_GRAPHQL_URL).toBe("http://127.0.0.1:9000/graphql")
})

test.each(["explicit-secret", ""])("preserves explicit frontend or container settings including %j", (token) => {
  writeFileSync(envPath, "APP_ACCESS_TOKEN=root-secret\nBACKEND_GRAPHQL_URL=http://root/graphql\n")
  const environment = { APP_ACCESS_TOKEN: token, BACKEND_GRAPHQL_URL: "http://backend:8000/graphql" }
  configureSearchEnvironment(PHASE_DEVELOPMENT_SERVER, envPath, environment)
  expect(environment).toEqual({ APP_ACCESS_TOKEN: token, BACKEND_GRAPHQL_URL: "http://backend:8000/graphql" })
})

test("allows previews without a root env and never invents authentication", () => {
  const environment: Record<string, string | undefined> = {}
  configureSearchEnvironment(PHASE_DEVELOPMENT_SERVER, envPath, environment)
  expect(environment.APP_ACCESS_TOKEN).toBeUndefined()
  expect(environment.BACKEND_GRAPHQL_URL).toBe("http://127.0.0.1:8000/graphql")
})

test.each([PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER, PHASE_TEST])("does not load development defaults during %s", (phase) => {
  writeFileSync(envPath, "APP_ACCESS_TOKEN=local-secret\n")
  const environment: Record<string, string | undefined> = {}
  configureSearchEnvironment(phase, envPath, environment)
  expect(environment).toEqual({})
})

test("reports unreadable configuration instead of hiding file errors", () => {
  expect(() => configureSearchEnvironment(PHASE_DEVELOPMENT_SERVER, directory, {})).toThrow()
})
