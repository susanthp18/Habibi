// The engine previews the selected voice with the same synthesis settings as
// runtime. The result is an object URL the caller must revoke.
import { previewVoiceApiV1UserConfigurationsVoicesProviderPreviewPost } from "@/client/sdk.gen";
import type { VoicePreviewRequest } from "@/client/types.gen";
import { detailFromError } from "@/lib/apiError";

export const PREVIEW_PROVIDERS = new Set(["azure_speech", "openrouter", "fish"]);

export async function fetchVoicePreviewUrl(provider: string, body: VoicePreviewRequest): Promise<string> {
    const response = await previewVoiceApiV1UserConfigurationsVoicesProviderPreviewPost({
        path: { provider: provider as "azure_speech" | "openrouter" | "fish" },
        body,
        parseAs: "blob",
    });
    if (response.error) {
        throw new Error(detailFromError(response.error, "Could not preview this voice"));
    }
    return URL.createObjectURL(response.data as unknown as Blob);
}
