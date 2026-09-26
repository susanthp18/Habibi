"use client";

import { useParams, useSearchParams } from "@/agentstudio-host/shims/next-navigation";

import WorkflowLayout from "../../WorkflowLayout";
import { WorkflowExecutions } from "../components/WorkflowExecutions";

export default function WorkflowRunsPage() {
    const { workflowId } = useParams();
    const searchParams = useSearchParams();

    return (
        <WorkflowLayout showFeaturesNav={false}>
            <WorkflowExecutions
                workflowId={Number(workflowId)}
                searchParams={searchParams}
            />
        </WorkflowLayout>
    );
}
