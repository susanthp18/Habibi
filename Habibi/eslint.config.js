import js from "@eslint/js";
import eslintPluginPrettier from "eslint-plugin-prettier/recommended";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

/**
 * `no-silent-mutation`: every `useMutation({...})` in `src/api` declares
 * `meta: { errors: "toast" | "caller" }`. See src/lib/mutation-errors.ts —
 * a rejected write that renders as nothing happening is the studio's
 * most-shipped defect, and the choice of who surfaces it must be explicit.
 */
const noSilentMutation = {
  rules: {
    "no-silent-mutation": {
      meta: { type: "problem", schema: [] },
      create(context) {
        return {
          CallExpression(node) {
            if (node.callee.type !== "Identifier" || node.callee.name !== "useMutation") return;
            const arg = node.arguments[0];
            if (!arg || arg.type !== "ObjectExpression") return;
            const meta = arg.properties.find(
              (p) => p.type === "Property" && p.key.type === "Identifier" && p.key.name === "meta",
            );
            const errors =
              meta &&
              meta.value.type === "ObjectExpression" &&
              meta.value.properties.find(
                (p) =>
                  p.type === "Property" && p.key.type === "Identifier" && p.key.name === "errors",
              );
            if (!errors) {
              context.report({
                node,
                message:
                  'useMutation needs meta: { errors: "toast" | "caller" } — say who surfaces a failed write.',
              });
            }
          },
        };
      },
    },
  },
};

export default tseslint.config(
  { ignores: ["dist", ".output", ".vinxi"] },
  {
    files: ["src/api/**/*.{ts,tsx}"],
    plugins: { "silent-mutation": noSilentMutation },
    rules: { "silent-mutation/no-silent-mutation": "error" },
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "server-only",
              message:
                "TanStack Start does not use the Next.js `server-only` package. Rename the module to `*.server.ts` or mark it with `@tanstack/react-start/server-only`.",
            },
          ],
        },
      ],
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
  {
    files: ["src/components/**/*.{ts,tsx}", "src/routes/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "server-only",
              message:
                "TanStack Start does not use the Next.js `server-only` package. Rename the module to `*.server.ts` or mark it with `@tanstack/react-start/server-only`.",
            },
            {
              name: "@/api/config",
              importNames: [
                "USE_MOCK",
                "mockDelay",
                "apiGet",
                "apiPost",
                "apiPatch",
                "apiDelete",
                "apiUpload",
                "apiGetBlob",
                "apiEventStream",
              ],
              message:
                "USE_MOCK lives in api/config.ts. Screens consume a named capability from the domain api/ module (WP-049).",
            },
          ],
        },
      ],
    },
  },
  eslintPluginPrettier,
);
