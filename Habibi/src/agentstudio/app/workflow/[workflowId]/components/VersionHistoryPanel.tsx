"use client";

import { formatDistanceToNow } from "date-fns";
import { FileDiff, FileText, LoaderCircle, X } from "lucide-react";
import { useEffect } from "react";

import type { WorkflowVersionResponse } from "@/agentstudio/client/types.gen";
import { Button } from "@/agentstudio/components/ui/button";
import VersionRelease from "@/agentstudio-host/VersionRelease";

interface VersionHistoryPanelProps {
    isOpen: boolean;
    onClose: () => void;
    versions: WorkflowVersionResponse[];
    loading: boolean;
    activeVersionId: number | null;
    onSelectVersion: (version: WorkflowVersionResponse) => void;
    onCompareVersion: (version: WorkflowVersionResponse) => void;
    comparingVersionId: number | null;
    hasMore: boolean;
    loadingMore: boolean;
    onLoadMore: () => void;
    // AgentStudio: release notes and rollback per version.
    workflowId: number;
    onRolledBack: () => void;
}

const statusLabel: Record<string, string> = {
    draft: "Draft",
    published: "Published",
    archived: "Archived",
};

const statusColor: Record<string, string> = {
    draft: "bg-background-warning-bold/20 text-text-warning border-border-warning/30",
    published: "bg-background-success-bold/20 text-text-success border-border-success/30",
    archived: "bg-background-neutral text-text-subtle border-border",
};

export const VersionHistoryPanel = ({
    isOpen,
    onClose,
    versions,
    loading,
    activeVersionId,
    onSelectVersion,
    onCompareVersion,
    comparingVersionId,
    hasMore,
    loadingMore,
    onLoadMore,
    workflowId,
    onRolledBack,
}: VersionHistoryPanelProps) => {
    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape" && isOpen) {
                onClose();
            }
        };
        document.addEventListener("keydown", handleKeyDown);
        return () => document.removeEventListener("keydown", handleKeyDown);
    }, [isOpen, onClose]);

    return (
        <div
            className={`fixed z-51 right-0 top-0 h-full w-80 bg-surface border-l border-border shadow-lg transform transition-transform duration-300 ease-in-out ${
                isOpen ? "translate-x-0" : "translate-x-full"
            }`}
        >
            <div className="p-4 h-full overflow-y-auto">
                <div className="flex justify-between items-center mb-6">
                    <h2 className="text-lg font-semibold text-white">
                        Version History
                    </h2>
                    <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Close version history"
                        onClick={onClose}
                        className="text-text-subtle hover:text-white hover:bg-background-neutral-subtle-hovered"
                    >
                        <X className="w-5 h-5" />
                    </Button>
                </div>

                {loading ? (
                    <div className="flex items-center justify-center py-12">
                        <LoaderCircle className="w-6 h-6 text-text-subtle animate-spin" />
                    </div>
                ) : versions.length === 0 ? (
                    <p className="text-sm text-text-subtle text-center py-8">
                        No versions found.
                    </p>
                ) : (
                    <div className="space-y-2">
                        {versions.map((version, index) => {
                            const isActive = version.id === activeVersionId;
                            const date = version.published_at || version.created_at;
                            const previousVersion = versions[index + 1];
                            const canCompare = Boolean(previousVersion) || hasMore;
                            const compareLabel = previousVersion
                                ? `Compare v${version.version_number} with v${previousVersion.version_number}`
                                : `Compare v${version.version_number} with its previous version`;
                            return (
                                <div
                                    key={version.id}
                                    className={`w-full overflow-hidden rounded-lg border transition-colors ${
                                        isActive
                                            ? "border-border-success/50 bg-background-success-bold/10"
                                            : "border-border bg-background-neutral"
                                    }`}
                                >
                                    <div className="flex w-full">
                                    <button
                                        type="button"
                                        onClick={() => onSelectVersion(version)}
                                        className="min-w-0 flex-1 cursor-pointer p-3 text-left transition-colors hover:bg-background-neutral-subtle-hovered"
                                    >
                                        <div className="mb-1.5 flex items-center justify-between">
                                            <div className="flex items-center gap-2">
                                                <FileText className="h-4 w-4 text-text-subtle" />
                                                <span className="text-sm font-medium text-white">
                                                    v{version.version_number}
                                                </span>
                                            </div>
                                            {version.status !== "archived" && (
                                                <span
                                                    className={`rounded-full border px-2 py-0.5 text-xs ${
                                                        statusColor[version.status] ?? ""
                                                    }`}
                                                >
                                                    {statusLabel[version.status] ?? version.status}
                                                </span>
                                            )}
                                        </div>
                                        <p className="text-xs text-text-subtle">
                                            {formatDistanceToNow(new Date(date), {
                                                addSuffix: true,
                                            })}
                                        </p>
                                    </button>

                                    {canCompare && (
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="icon"
                                            aria-label={compareLabel}
                                            disabled={comparingVersionId !== null}
                                            onClick={() => onCompareVersion(version)}
                                            className="mr-2 h-7 w-7 shrink-0 self-center rounded-md border border-border text-text-subtle hover:bg-background-neutral-subtle-hovered hover:text-white"
                                        >
                                            {comparingVersionId === version.id ? (
                                                <LoaderCircle className="h-4 w-4 animate-spin" />
                                            ) : (
                                                <FileDiff className="h-4 w-4" />
                                            )}
                                        </Button>
                                    )}
                                    </div>
                                    <VersionRelease
                                        workflowId={workflowId}
                                        version={version}
                                        onRolledBack={onRolledBack}
                                    />
                                </div>
                            );
                        })}
                        {hasMore && (
                            <Button
                                variant="ghost"
                                onClick={onLoadMore}
                                disabled={loadingMore}
                                className="w-full text-sm text-text-subtle hover:text-white hover:bg-background-neutral-subtle-hovered"
                            >
                                {loadingMore ? (
                                    <LoaderCircle className="w-4 h-4 animate-spin" />
                                ) : (
                                    "Load more"
                                )}
                            </Button>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};
