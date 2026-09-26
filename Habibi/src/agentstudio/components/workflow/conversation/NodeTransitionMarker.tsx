"use client";

import { GitBranch } from "lucide-react";

interface NodeTransitionMarkerProps {
    nodeName: string;
}

export function NodeTransitionMarker({ nodeName }: NodeTransitionMarkerProps) {
    return (
        <div className="flex items-center gap-2 py-2">
            <div className="h-px flex-1 bg-border" />
            <div className="inline-flex items-center gap-1.5 rounded-full border border-border-information/20 bg-background-information-bold/10 px-3 py-1 text-xs">
                <GitBranch className="h-3 w-3 text-text-information" />
                <span className="font-medium text-text-information dark:text-text-information">{nodeName}</span>
            </div>
            <div className="h-px flex-1 bg-border" />
        </div>
    );
}
