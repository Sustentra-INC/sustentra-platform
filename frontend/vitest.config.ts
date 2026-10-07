import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Enables React Testing Library's automatic DOM cleanup between tests (it
    // registers on the global `afterEach`). Per-file `@vitest-environment jsdom`
    // comments still select jsdom for component tests; node tests stay on node.
    globals: true,
    // e2e/ is Playwright (TEST-002), run with `npm run test:e2e` against a running stack.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
