import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getVoicesApiV1UserConfigurationsVoicesProviderGet } from "@/client/sdk.gen";
import { fetchVoicePreviewUrl } from "@/lib/voicePreview";

import { VoiceSelector } from "./VoiceSelector";

vi.mock("@/client/sdk.gen", () => ({ getVoicesApiV1UserConfigurationsVoicesProviderGet: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: true, loading: false }) }));
vi.mock("@/lib/voicePreview", () => ({ fetchVoicePreviewUrl: vi.fn(), PREVIEW_PROVIDERS: new Set(["openrouter", "azure_speech", "fish"]) }));
vi.mock("@/components/ui/popover", () => ({
    Popover: ({ children }: { children: ReactNode }) => <>{children}</>,
    PopoverContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    PopoverTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

const model = "fish-audio/s2.1-pro-free:free";
const page = (id: string, hasMore: boolean) => ({ data: { provider: "openrouter", voices: [{
    voice_id: id, name: id, language: "en", reference_languages: ["en"], styles: [], tags: [], locales: [], multilingual: false,
}], pagination: { page_number: 1, page_size: 50, has_more: hasMore } } });

beforeEach(() => vi.clearAllMocks());

describe("OpenRouter voice catalog", () => {
    it("preserves the selected ID when paging and searches the server", async () => {
        vi.mocked(getVoicesApiV1UserConfigurationsVoicesProviderGet).mockResolvedValueOnce(page("first", true) as never)
            .mockResolvedValue(page("second", false) as never);
        const onChange = vi.fn();
        render(<VoiceSelector provider="openrouter" value="selected-off-page" model={model} onChange={onChange} showFilters />);
        await screen.findByText("first");
        expect(screen.getAllByRole("combobox")[0]!.textContent).toContain("selected-off-page");
        fireEvent.click(screen.getByRole("button", { name: "Next" }));
        await screen.findByText("second");
        expect(getVoicesApiV1UserConfigurationsVoicesProviderGet).toHaveBeenLastCalledWith({
            path: { provider: "openrouter" }, query: { model, page_number: 2, q: undefined },
        });
        expect(onChange).not.toHaveBeenCalled();
        fireEvent.change(screen.getByPlaceholderText("Search voices..."), { target: { value: "indian" } });
        await waitFor(() => expect(getVoicesApiV1UserConfigurationsVoicesProviderGet).toHaveBeenLastCalledWith({
            path: { provider: "openrouter" }, query: { model, page_number: 1, q: "indian" },
        }));
        expect(screen.getByText(/Languages describe reference recordings/)).toBeTruthy();
        expect(screen.queryByText("Multilingual")).toBeNull();
        expect(onChange).not.toHaveBeenCalled();
    });

    it("previews with the chosen model and free-form style even on another catalog voice", async () => {
        vi.mocked(getVoicesApiV1UserConfigurationsVoicesProviderGet).mockResolvedValue(page("preview-voice", false) as never);
        vi.mocked(fetchVoicePreviewUrl).mockRejectedValue(new Error("Synthetic preview rejection"));
        render(<VoiceSelector provider="openrouter" value="selected" model={model} onChange={vi.fn()} styleVoice="selected"
            previewSettings={{ model, style: "warm and reassuring", api_key: "temporary-test-key" }} />);
        await screen.findByText("preview-voice");
        const buttons = screen.getAllByRole("button");
        fireEvent.click(buttons.find(button => button.querySelector("svg.lucide-volume-2"))!);
        await waitFor(() => expect(fetchVoicePreviewUrl).toHaveBeenCalledWith("openrouter", {
            model, style: "warm and reassuring", api_key: "temporary-test-key", voice: "preview-voice",
        }));
        expect(await screen.findByText("Synthetic preview rejection")).toBeTruthy();
    });
});

describe("Fish Audio voice catalog", () => {
    it("pages Fish's own catalog and plays a voice's recorded sample without synthesizing", async () => {
        vi.mocked(getVoicesApiV1UserConfigurationsVoicesProviderGet).mockResolvedValue({ data: { provider: "fish", voices: [{
            voice_id: "amir", name: "Amir", language: "en", reference_languages: ["en", "hi"], styles: [], tags: [], locales: [],
            preview_url: "https://platform.r2.fish.audio/sample.mp3",
        }], pagination: { page_number: 1, page_size: 50, has_more: false } } } as never);
        const play = vi.spyOn(window.HTMLMediaElement.prototype, "play").mockResolvedValue();
        render(<VoiceSelector provider="fish" value="amir" model="s2.1-pro-free" onChange={vi.fn()} />);
        await screen.findAllByText("Amir");
        expect(getVoicesApiV1UserConfigurationsVoicesProviderGet).toHaveBeenCalledWith({
            path: { provider: "fish" }, query: { model: "s2.1-pro-free", page_number: 1, q: undefined },
        });
        const buttons = screen.getAllByRole("button");
        fireEvent.click(buttons.find(button => button.querySelector("svg.lucide-volume-2"))!);
        await waitFor(() => expect(play).toHaveBeenCalled());
        expect(fetchVoicePreviewUrl).not.toHaveBeenCalled();
    });
});
