"use client";

/**
 * Review and approval for one tool's immutable revisions.
 *
 * Editing a tool writes a new draft revision; nothing a released agent calls
 * changes until a revision is submitted with a live policy and approved. The
 * approval decision itself is not made here: the engine's own review route is
 * closed to the Studio proxy, so the buttons come from the host slot
 * "@/host/ToolReview", which posts to PayInt's reviewer-authorised endpoint.
 */

import { Loader2, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
    listToolRevisionsApiV1ToolsToolUuidRevisionsGet,
    submitToolRevisionApiV1ToolsToolUuidRevisionsRevisionSubmitPost,
} from "@/client/sdk.gen";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { JsonEditor, validateJson } from "@/components/ui/json-editor";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import ToolReview from "@/host/ToolReview";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

export type ToolRevisionState =
    | "draft"
    | "submitted"
    | "approved"
    | "rejected"
    | "revoked"
    | "legacy";

export interface ToolRevision {
    revision: number;
    digest: string;
    state: ToolRevisionState;
    snapshot: {
        name?: string;
        description?: string;
        category?: string;
        definition?: Record<string, unknown>;
    };
    policy: Record<string, unknown>;
    authoredBy: number;
    reviewedBy: number | null;
    createdAt: string;
    publishedUsage: number;
}

const CHANNELS = ["inbound", "outbound", "whatsapp"] as const;

const STATE_STYLE: Record<ToolRevisionState, string> = {
    draft: "bg-muted text-muted-foreground",
    submitted: "bg-amber-500/10 text-amber-600",
    approved: "bg-green-500/10 text-green-600",
    rejected: "bg-destructive/10 text-destructive",
    revoked: "bg-destructive/10 text-destructive",
    legacy: "bg-muted text-muted-foreground",
};

/** Functions an MCP revision's cached discovery found, with their digests. */
function discoveredFunctions(revision: ToolRevision | undefined) {
    const definition = (revision?.snapshot?.definition ?? {}) as Record<string, unknown>;
    const config = (definition.config ?? {}) as Record<string, unknown>;
    const discovered = Array.isArray(config.discovered_tools) ? config.discovered_tools : [];
    return discovered
        .map((item) => item as { name?: string; description?: string; schema_digest?: string })
        .filter((item): item is { name: string; description?: string; schema_digest: string } =>
            Boolean(item.name && item.schema_digest)
        );
}

export interface ToolRevisionPanelProps {
    toolUuid: string;
    /** Bumped by the page after a save, so the new draft shows immediately. */
    reloadKey?: number;
    onLatestRevision?: (revision: number | null) => void;
}

export function ToolRevisionPanel({
    toolUuid,
    reloadKey = 0,
    onLatestRevision,
}: ToolRevisionPanelProps) {
    const { user, getAccessToken, loading } = useAuth();

    const [revisions, setRevisions] = useState<ToolRevision[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [isSubmitting, setIsSubmitting] = useState(false);

    const [risk, setRisk] = useState("read");
    const [channels, setChannels] = useState<string[]>(["inbound"]);
    const [minIdentity, setMinIdentity] = useState("challenge");
    const [egressFields, setEgressFields] = useState("");
    const [successPath, setSuccessPath] = useState("ok");
    const [successValue, setSuccessValue] = useState("true");
    const [errorCodePath, setErrorCodePath] = useState("");
    const [idempotencyParameter, setIdempotencyParameter] = useState("");
    const [allowedFunctions, setAllowedFunctions] = useState<string[]>([]);
    const [resultSchema, setResultSchema] = useState('{\n    "type": "object"\n}');

    const load = useCallback(async () => {
        if (loading || !user) return;
        try {
            const accessToken = await getAccessToken();
            const response = await listToolRevisionsApiV1ToolsToolUuidRevisionsGet({
                path: { tool_uuid: toolUuid },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.error || !response.data) {
                throw new Error(detailFromError(response.error, "Failed to load tool revisions"));
            }
            setRevisions(response.data as unknown as ToolRevision[]);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load tool revisions");
        }
    }, [loading, user, getAccessToken, toolUuid]);

    useEffect(() => {
        load();
    }, [load, reloadKey]);

    // Newest first, as the engine orders them.
    const latest = revisions?.[0];

    useEffect(() => {
        onLatestRevision?.(latest ? latest.revision : null);
    }, [latest, onLatestRevision]);

    // A rejected revision carries the policy it was judged on. Editing the tool
    // opens a fresh draft, so start that draft from the last policy anyone
    // actually wrote rather than from the defaults again — once, so a reload
    // while the reviewer is typing cannot throw their edits away.
    const appliedPolicyRef = useRef<number | null>(null);

    useEffect(() => {
        const source = revisions?.find(
            (entry) => entry.policy && Object.keys(entry.policy).length > 0
        );
        if (!source || appliedPolicyRef.current === source.revision) return;
        appliedPolicyRef.current = source.revision;
        const policy = source.policy;
        if (typeof policy.risk === "string") setRisk(policy.risk);
        if (Array.isArray(policy.channels)) setChannels(policy.channels as string[]);
        if (typeof policy.min_identity === "string") setMinIdentity(policy.min_identity);
        if (Array.isArray(policy.egress_fields))
            setEgressFields((policy.egress_fields as string[]).join(", "));
        if (typeof policy.success_path === "string") setSuccessPath(policy.success_path);
        if (policy.success_value !== undefined)
            setSuccessValue(JSON.stringify(policy.success_value));
        if (typeof policy.error_code_path === "string") setErrorCodePath(policy.error_code_path);
        if (typeof policy.idempotency_parameter === "string")
            setIdempotencyParameter(policy.idempotency_parameter);
        if (policy.allowed_mcp_functions && typeof policy.allowed_mcp_functions === "object")
            setAllowedFunctions(Object.keys(policy.allowed_mcp_functions));
        const schema = policy.result_schema as Record<string, unknown> | undefined;
        if (schema && Object.keys(schema).length > 0)
            setResultSchema(JSON.stringify(schema, null, 4));
    }, [revisions]);

    const functions = useMemo(() => discoveredFunctions(latest), [latest]);
    const isMcp = latest?.snapshot?.category === "mcp";
    const schemaCheck = validateJson(resultSchema);
    const isPlatform = risk === "platform";

    const blocked = useMemo(() => {
        if (!latest || latest.state !== "draft") return "";
        if (channels.length === 0) return "Choose at least one channel.";
        if (isPlatform) return "";
        if (!successPath.trim()) return "A live tool needs the response field that means success.";
        if (!schemaCheck.valid) return schemaCheck.error || "The result schema is not valid JSON.";
        if (risk === "write" && !idempotencyParameter.trim())
            return "A live write needs an idempotency parameter.";
        if (risk === "write" && minIdentity !== "challenge")
            return "A live write requires challenge-level identity.";
        if (isMcp && allowedFunctions.length === 0)
            return "Approve at least one discovered MCP function.";
        return "";
    }, [
        latest,
        channels,
        isPlatform,
        successPath,
        schemaCheck.valid,
        schemaCheck.error,
        risk,
        idempotencyParameter,
        minIdentity,
        isMcp,
        allowedFunctions,
    ]);

    const buildPolicy = () => {
        let parsedSuccessValue: unknown = successValue;
        try {
            parsedSuccessValue = JSON.parse(successValue);
        } catch {
            // A bare string such as `ACCEPTED` is a legitimate success value.
        }
        return {
            risk,
            channels,
            min_identity: minIdentity,
            egress_fields: egressFields
                .split(/[\n,]/)
                .map((field) => field.trim())
                .filter(Boolean),
            success_path: isPlatform ? null : successPath.trim(),
            success_value: parsedSuccessValue,
            error_code_path: errorCodePath.trim() || null,
            idempotency_parameter: idempotencyParameter.trim() || null,
            allowed_mcp_functions: Object.fromEntries(
                functions
                    .filter((item) => allowedFunctions.includes(item.name))
                    .map((item) => [item.name, item.schema_digest])
            ),
            result_schema: isPlatform ? {} : (schemaCheck.parsed as Record<string, unknown>),
        };
    };

    const handleSubmit = async () => {
        if (!latest || blocked) return;
        setIsSubmitting(true);
        try {
            const accessToken = await getAccessToken();
            const response = await submitToolRevisionApiV1ToolsToolUuidRevisionsRevisionSubmitPost({
                path: { tool_uuid: toolUuid, revision: latest.revision },
                body: buildPolicy() as Record<string, unknown>,
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.error) {
                setError(detailFromError(response.error, "Failed to submit this revision"));
                return;
            }
            setError(null);
            await load();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to submit this revision");
        } finally {
            setIsSubmitting(false);
        }
    };

    if (!revisions) {
        return (
            <Card>
                <CardHeader>
                    <CardTitle>Review and approval</CardTitle>
                </CardHeader>
                <CardContent>
                    <Skeleton className="h-24 w-full" />
                </CardContent>
            </Card>
        );
    }

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4" />
                    Review and approval
                </CardTitle>
                <CardDescription>
                    Saving writes a new draft revision. A released agent keeps calling the revision
                    it was published with until a reviewer approves a newer one.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                {error && (
                    <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-sm">
                        {error}
                    </div>
                )}

                {latest?.state === "draft" && (
                    <div className="space-y-4">
                        <div className="grid gap-4 sm:grid-cols-2">
                            <div className="space-y-2">
                                <Label htmlFor="revision-risk">Risk</Label>
                                <Select value={risk} onValueChange={setRisk}>
                                    <SelectTrigger id="revision-risk">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="read">Read — looks something up</SelectItem>
                                        <SelectItem value="write">Write — changes a record</SelectItem>
                                        <SelectItem value="platform">Platform — a PayInt handler</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="revision-identity">Minimum identity</Label>
                                <Select value={minIdentity} onValueChange={setMinIdentity}>
                                    <SelectTrigger id="revision-identity">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="none">None</SelectItem>
                                        <SelectItem value="endpoint">Known endpoint</SelectItem>
                                        <SelectItem value="challenge">Verified on the call</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label>Channels</Label>
                            <div className="flex flex-wrap gap-4">
                                {CHANNELS.map((channel) => (
                                    <label key={channel} className="flex items-center gap-2 text-sm">
                                        <Checkbox
                                            checked={channels.includes(channel)}
                                            onCheckedChange={(checked) =>
                                                setChannels((current) =>
                                                    checked
                                                        ? [...current, channel]
                                                        : current.filter((item) => item !== channel)
                                                )
                                            }
                                        />
                                        {channel}
                                    </label>
                                ))}
                            </div>
                        </div>

                        {!isPlatform && (
                            <>
                                <div className="grid gap-4 sm:grid-cols-2">
                                    <div className="space-y-2">
                                        <Label htmlFor="revision-success-path">Success field</Label>
                                        <Input
                                            id="revision-success-path"
                                            value={successPath}
                                            onChange={(e) => setSuccessPath(e.target.value)}
                                            placeholder="data.ok"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="revision-success-value">Success value</Label>
                                        <Input
                                            id="revision-success-value"
                                            value={successValue}
                                            onChange={(e) => setSuccessValue(e.target.value)}
                                            placeholder="true"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="revision-error-path">Error code field (optional)</Label>
                                        <Input
                                            id="revision-error-path"
                                            value={errorCodePath}
                                            onChange={(e) => setErrorCodePath(e.target.value)}
                                            placeholder="data.error_code"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="revision-idempotency">Idempotency parameter</Label>
                                        <Input
                                            id="revision-idempotency"
                                            value={idempotencyParameter}
                                            onChange={(e) => setIdempotencyParameter(e.target.value)}
                                            placeholder="request_id"
                                        />
                                        <p className="text-xs text-muted-foreground">
                                            Required for a write: the engine sends one stable key per
                                            attempt, so a retry cannot post twice.
                                        </p>
                                    </div>
                                </div>

                                {/* An MCP call carries only what the model passes, so
                                    there is no context to approve or withhold. */}
                                {!isMcp && (
                                    <div className="space-y-2">
                                        <Label htmlFor="revision-egress">Context fields this tool may receive</Label>
                                        <Input
                                            id="revision-egress"
                                            value={egressFields}
                                            onChange={(e) => setEgressFields(e.target.value)}
                                            placeholder="initial_context.customer_id, gathered_context.amount"
                                        />
                                        <p className="text-xs text-muted-foreground">
                                            Nothing else from the call leaves with the request, so
                                            every field the URL, presets or body template read must
                                            be listed here.
                                        </p>
                                    </div>
                                )}

                                <JsonEditor
                                    value={resultSchema}
                                    onChange={setResultSchema}
                                    label="Result schema"
                                    description="A response that does not match is refused before the agent hears it."
                                    minHeight="140px"
                                    error={schemaCheck.valid ? null : schemaCheck.error}
                                />
                            </>
                        )}

                        {isMcp && !isPlatform && (
                            <div className="space-y-2">
                                <Label>Approved MCP functions</Label>
                                {functions.length === 0 ? (
                                    <p className="text-sm text-muted-foreground">
                                        No functions discovered yet. Save the tool to refresh discovery.
                                    </p>
                                ) : (
                                    <div className="space-y-2">
                                        {functions.map((item) => (
                                            <label
                                                key={item.name}
                                                className="flex items-start gap-2 text-sm"
                                            >
                                                <Checkbox
                                                    checked={allowedFunctions.includes(item.name)}
                                                    onCheckedChange={(checked) =>
                                                        setAllowedFunctions((current) =>
                                                            checked
                                                                ? [...current, item.name]
                                                                : current.filter((n) => n !== item.name)
                                                        )
                                                    }
                                                />
                                                <span>
                                                    <span className="font-mono">{item.name}</span>
                                                    {item.description && (
                                                        <span className="block text-xs text-muted-foreground">
                                                            {item.description}
                                                        </span>
                                                    )}
                                                </span>
                                            </label>
                                        ))}
                                    </div>
                                )}
                                <p className="text-xs text-muted-foreground">
                                    Only these run, and only while their schema still matches what you
                                    approved.
                                </p>
                            </div>
                        )}

                        {blocked && <p className="text-sm text-muted-foreground">{blocked}</p>}
                        <Button onClick={handleSubmit} disabled={Boolean(blocked) || isSubmitting}>
                            {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                            Submit revision {latest.revision} for review
                        </Button>
                    </div>
                )}

                <div className="space-y-2">
                    <Label>Revision history</Label>
                    {revisions.length === 0 && (
                        <p className="text-sm text-muted-foreground">No revisions yet.</p>
                    )}
                    {revisions.map((revision) => (
                        <div
                            key={revision.revision}
                            className="flex flex-wrap items-center gap-3 border border-border rounded-lg px-3 py-2 text-sm"
                        >
                            <span className="font-medium">r{revision.revision}</span>
                            <Badge className={STATE_STYLE[revision.state]}>{revision.state}</Badge>
                            <span className="font-mono text-xs text-muted-foreground">
                                {revision.digest.slice(0, 8)}
                            </span>
                            <span className="text-xs text-muted-foreground">
                                {revision.publishedUsage > 0
                                    ? `pinned by ${revision.publishedUsage} released version(s)`
                                    : "not released"}
                            </span>
                            <span className="ml-auto">
                                <ToolReview
                                    toolUuid={toolUuid}
                                    revision={revision.revision}
                                    state={revision.state}
                                    onReviewed={load}
                                />
                            </span>
                        </div>
                    ))}
                </div>
            </CardContent>
        </Card>
    );
}
