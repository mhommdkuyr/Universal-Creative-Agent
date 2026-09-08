import { defineConfig } from "@neon/config/v1";

export default defineConfig({
  preview: {
    aiGateway: true,
    functions: {
      ucoa: {
        name: "UCOA agent API",
        source: "neon/functions/ucoa/index.ts",
      },
    },
  },
});
