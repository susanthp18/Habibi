// AgentStudio: spoken previews of a voice exactly as configured (Azure voices
// have no hosted samples). The engine synthesizes a short sample with the same
// SSML the live call uses; the result is an object URL the caller must revoke.
import { previewVoiceApiV1UserConfigurationsVoicesProviderPreviewPost } from "@/agentstudio/client/sdk.gen";
import type { VoicePreviewRequest } from "@/agentstudio/client/types.gen";
import { detailFromError } from "@/agentstudio/lib/apiError";

export const PREVIEW_PROVIDERS = new Set(["azure_speech"]);

export async function fetchVoicePreviewUrl(provider: string, body: VoicePreviewRequest): Promise<string> {
    const response = await previewVoiceApiV1UserConfigurationsVoicesProviderPreviewPost({
        path: { provider: provider as "azure_speech" },
        body,
        parseAs: "blob",
    });
    if (response.error) {
        throw new Error(detailFromError(response.error, "Could not preview this voice"));
    }
    return URL.createObjectURL(response.data as unknown as Blob);
}
