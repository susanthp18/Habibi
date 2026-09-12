import js from "@eslint/js";
import eslintPluginPrettier from "eslint-plugin-prettier/recommended";
import globals from "globals";
import jsxA11y from "eslint-plugin-jsx-a11y";
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
      "jsx-a11y": jsxA11y,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // The accessibility floor. Introduced at the recommended set; what it
      // found on introduction was fixed rather than baselined.
      ...jsxA11y.flatConfigs.recommended.rules,
      // The design-system inputs render native controls; a <label> wrapping
      // one is associated the way a wrapped <input> is.
      "jsx-a11y/label-has-associated-control": [
        "error",
        {
          controlComponents: ["Input", "Textarea", "SelectField", "Switch", "Checkbox", "Slider"],
          depth: 3,
        },
      ],
      // A scrollable region takes focus so the keyboard can scroll it; a
      // resizable separator takes the pointer and the arrow keys. Both are
      // widgets by ARIA, whatever the default lists say.
      "jsx-a11y/no-noninteractive-tabindex": ["error", { roles: ["region", "separator"] }],

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
    // A focusable separator with aria-valuenow is the ARIA window-splitter
    // pattern: the pointer drags it and the arrow keys move it. aria-query
    // lists `separator` as non-interactive, so the rule cannot tell the
    // splitter from a rule line; the exception is this one file.
    files: ["src/components/shared/SplitPanes.tsx"],
    rules: { "jsx-a11y/no-noninteractive-element-interactions": "off" },
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
                "apiGet",
                "apiPost",
                "apiPatch",
                "apiDelete",
                "apiUpload",
                "apiGetBlob",
                "apiEventStream",
              ],
              message:
                "Screens do not talk to the transport. Consume the domain api/ module's hooks and functions instead.",
            },
          ],
        },
      ],
    },
  },
  eslintPluginPrettier,
);
