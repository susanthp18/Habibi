/**
 * The agents list. The vendor UI rendered this on its server; here it is the
 * same page fetched in the browser, re-fetched when a screen calls
 * `router.refresh()` (folders created, agents archived, ...).
 */
import { useCallback, useEffect, useState } from "react";

import {
  getWorkflowsApiV1WorkflowFetchGet,
  listFoldersApiV1FolderGet,
} from "@/agentstudio/client/sdk.gen";
import type { FolderResponse, WorkflowListResponse } from "@/agentstudio/client/types.gen";
import { Card, CardContent } from "@/agentstudio/components/ui/card";
import { CreateWorkflowButton } from "@/agentstudio/components/workflow/CreateWorkflowButton";
import { AgentFolderView } from "@/agentstudio/components/workflow/folders/AgentFolderView";
import { CreateFolderButton } from "@/agentstudio/components/workflow/folders/CreateFolderButton";
import { FolderSection } from "@/agentstudio/components/workflow/folders/FolderSection";
import { UploadWorkflowButton } from "@/agentstudio/components/workflow/UploadWorkflowButton";

import { STUDIO_REFRESH_EVENT } from "./base";

type State =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      active: WorkflowListResponse[];
      archived: WorkflowListResponse[];
      folders: FolderResponse[];
    };

const newestFirst = (a: WorkflowListResponse, b: WorkflowListResponse) =>
  new Date(b.created_at).getTime() - new Date(a.created_at).getTime();

export default function WorkflowListPage() {
  const [state, setState] = useState<State>({ status: "loading" });

  const load = useCallback(async () => {
    const response = await getWorkflowsApiV1WorkflowFetchGet({
      query: { status: "active,archived" },
    });
    if (response.error || !response.data) {
      setState({ status: "error" });
      return;
    }
    const all = Array.isArray(response.data) ? response.data : [response.data];
    // A folder failure must not blank the page: agents still list, ungrouped
    // (the vendor page's behaviour). Folders are grouping, not content.
    const folderResponse = await listFoldersApiV1FolderGet().catch(() => null);
    let folders: FolderResponse[] = [];
    if (folderResponse && !folderResponse.error && folderResponse.data) {
      folders = folderResponse.data;
    }
    setState({
      status: "ready",
      active: all.filter((w) => w.status === "active").sort(newestFirst),
      archived: all.filter((w) => w.status === "archived").sort(newestFirst),
      folders,
    });
  }, []);

  useEffect(() => {
    void load();
    const onRefresh = () => void load();
    window.addEventListener(STUDIO_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(STUDIO_REFRESH_EVENT, onRefresh);
  }, [load]);

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-2xl font-bold">Your Agents</h1>
          <div className="flex gap-2">
            <UploadWorkflowButton />
            <CreateFolderButton />
            <CreateWorkflowButton />
          </div>
        </div>

        {state.status === "loading" && (
          <Card>
            <CardContent className="p-0">
              <div className="h-96 bg-muted/70" />
            </CardContent>
          </Card>
        )}

        {state.status === "error" && (
          <div className="text-text-danger">Failed to load agents. Please try again.</div>
        )}

        {state.status === "ready" && (
          <>
            <div className="mb-8">
              <h2 className="text-xl font-semibold mb-4">Active Agents</h2>
              {state.active.length > 0 || state.folders.length > 0 ? (
                <AgentFolderView workflows={state.active} folders={state.folders} />
              ) : (
                <Card>
                  <CardContent className="p-8 text-center text-muted-foreground">
                    No active agents yet. Create your first agent to get started.
                  </CardContent>
                </Card>
              )}
            </div>
            {state.archived.length > 0 && (
              <div className="mb-8">
                <FolderSection kind="archived" workflows={state.archived} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
