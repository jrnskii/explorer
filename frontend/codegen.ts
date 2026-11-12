import type { CodegenConfig } from "@graphql-codegen/cli";

const config: CodegenConfig = {
  schema: "../shared/graphql/schema_v1.graphql",
  generates: {
    "generated/schema_v1.ts": {
      plugins: ["typescript"],
      config: {
        enumsAsTypes: true,
        strictScalars: true,
        useTypeImports: true,
        scalars: {
          DateTime: "string",
          Decimal: "string",
        },
      },
    },
  },
};

export default config;
