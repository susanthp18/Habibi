// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
  },
  vite: {
    server: {
      proxy: {
        // Pipecat SmallWebRTC offer — Habibi Live voice never opens :7860 HTML.
        // Point VOICE_RTC_TARGET at the API (http://127.0.0.1:8000) when the
        // backend runs with VOICE_EMBEDDED_HOST=true; it serves /api/offer
        // itself, so the same prefix rewrite applies to either target.
        "/voice-rtc": {
          target: process.env.VOICE_RTC_TARGET || "http://127.0.0.1:7860",
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/voice-rtc/, ""),
        },
      },
    },
  },
});
