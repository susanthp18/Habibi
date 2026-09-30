import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { type ServiceConfigurationDefaults, ServiceConfigurationForm } from "./ServiceConfigurationForm";

vi.mock("@/client/sdk.gen", () => ({ getDefaultConfigurationsApiV1UserConfigurationsDefaultsGet: vi.fn() }));
vi.mock("@/context/UserConfigContext", () => ({ useUserConfig: () => ({ userConfig: null }) }));
vi.mock("@/components/VoiceSelector", () => ({ VoiceSelector: () => null }));
vi.mock("@/components/VoicePreviewPanel", () => ({ VoicePreviewPanel: () => null }));

const fish = {"description": "Fish Audio S2.1 Pro, 83 languages detected from the text. Free model; best-effort availability.", "properties": {"provider": {"const": "fish", "default": "fish", "title": "Provider", "type": "string"}, "api_key": {"anyOf": [{"type": "string"}, {"items": {"type": "string"}, "type": "array"}], "title": "Api Key"}, "model": {"const": "s2.1-pro-free", "default": "s2.1-pro-free", "description": "Fish Audio S2.1 Pro Free.", "examples": ["s2.1-pro-free"], "title": "Model", "type": "string"}, "voice": {"default": "7cccb9161ca24b13861f77f038aaa97a", "description": "Fish voice ID. Catalog languages describe reference recordings.", "maxLength": 80, "minLength": 1, "title": "Voice", "type": "string"}, "style": {"anyOf": [{"maxLength": 40, "minLength": 1, "pattern": "^[^\\[\\]\\r\\n]+$", "type": "string"}, {"type": "null"}], "default": null, "description": "Optional speaking style, such as empathetic or calm and conversational.", "title": "Style"}, "speed": {"default": 1.0, "description": "Speaking rate multiplier.", "maximum": 2.0, "minimum": 0.5, "title": "Speed", "type": "number"}, "volume": {"default": 0, "description": "Volume change in dB.", "maximum": 20, "minimum": -20, "title": "Volume", "type": "number"}, "latency": {"default": "balanced", "description": "Streaming mode. Both stream; Fish's 'normal' mode waits for the whole clip, so it is not offered.", "enum": ["balanced", "low"], "title": "Latency", "type": "string"}, "temperature": {"anyOf": [{"maximum": 1, "minimum": 0, "type": "number"}, {"type": "null"}], "default": null, "description": "Expressiveness (Fish default 0.7).", "title": "Temperature"}, "top_p": {"anyOf": [{"exclusiveMinimum": 0, "maximum": 1, "type": "number"}, {"type": "null"}], "default": null, "description": "Diversity (Fish default 0.7).", "title": "Top P"}}, "provider_docs_url": "https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech", "required": ["api_key"], "title": "Fish Audio", "type": "object"};
const plain = (provider: string) => ({ title: provider, required: ["api_key"], properties: { provider: { default: provider }, api_key: { type: "string" }, model: { type: "string", default: "m" } } });
const defaults = {
    llm: { openai: plain("openai") }, tts: { fish }, stt: { deepgram: plain("deepgram") }, embeddings: {}, realtime: {},
    default_providers: { llm: "openai", tts: "fish", stt: "deepgram" },
} as unknown as ServiceConfigurationDefaults;

describe("Fish voice settings", () => {
    it("saves optional numbers left empty as unset, never 0 (Fish refuses top_p 0: run 89)", async () => {
        const onSave = vi.fn();
        render(<ServiceConfigurationForm mode="global" forceRealtime={false} configurationDefaults={defaults}
            initialConfig={{ is_realtime: false, llm: { provider: "openai", api_key: "k", model: "m" },
                tts: { provider: "fish", api_key: "k", voice: "v", latency: "balanced", speed: 1, volume: 0, model: "s2.1-pro-free" },
                stt: { provider: "deepgram", api_key: "k", model: "m" } } as never} onSave={onSave} />);
        await screen.findAllByRole("button");
        await new Promise(resolve => setTimeout(resolve, 300));
        fireEvent.click(screen.getAllByRole("button").find(b => b.getAttribute("type") === "submit")!);
        await waitFor(() => expect(onSave).toHaveBeenCalled());
        const tts = onSave.mock.calls[0][0].tts;
        expect(tts.temperature ?? null).toBeNull();
        expect(tts.top_p ?? null).toBeNull();
        expect(tts).toMatchObject({ provider: "fish", voice: "v", latency: "balanced", speed: 1 });
    });

    it("refuses a value outside the field's bounds before saving (top_p must be more than 0)", async () => {
        const onSave = vi.fn();
        render(<ServiceConfigurationForm mode="global" forceRealtime={false} configurationDefaults={defaults}
            initialConfig={{ is_realtime: false, llm: { provider: "openai", api_key: "k", model: "m" },
                tts: { provider: "fish", api_key: "k", voice: "v", latency: "balanced", speed: 1, volume: 0, model: "s2.1-pro-free" },
                stt: { provider: "deepgram", api_key: "k", model: "m" } } as never} onSave={onSave} />);
        await screen.findAllByRole("button");
        await new Promise(resolve => setTimeout(resolve, 300));
        const voiceTab = screen.getByRole("tab", { name: "Voice" });
        fireEvent.mouseDown(voiceTab);
        fireEvent.click(voiceTab);
        const unset = await screen.findAllByPlaceholderText("Provider default");
        expect(unset.length).toBeGreaterThanOrEqual(2);  // style, temperature, top_p
        fireEvent.change(unset[unset.length - 1]!, { target: { value: "0" } });
        fireEvent.click(screen.getAllByRole("button").find(b => b.getAttribute("type") === "submit")!);
        expect(await screen.findByText("Must be more than 0")).toBeTruthy();
        expect(onSave).not.toHaveBeenCalled();
    });
});
