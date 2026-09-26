"use client";

import { ExternalLink, Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/agentstudio/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/agentstudio/components/ui/card";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/agentstudio/components/ui/dialog";
import { Skeleton } from "@/agentstudio/components/ui/skeleton";
import { useAuth } from "@/agentstudio-host/auth";

import DocumentList from "./DocumentList";
import DocumentUpload from "./DocumentUpload";
import TestRetrieval from "./TestRetrieval";

export default function FilesPage() {
    const { user, redirectToLogin, loading } = useAuth();
    const [refreshKey, setRefreshKey] = useState(0);
    const [isUploadOpen, setIsUploadOpen] = useState(false);

    // Redirect if not authenticated
    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    const handleUploadSuccess = () => {
        setRefreshKey(prev => prev + 1);
        setIsUploadOpen(false);
    };

    if (loading || !user) {
        return (
            <div className="container mx-auto px-4 py-8">
                <div className="space-y-4">
                    <Skeleton className="h-12 w-64" />
                    <Skeleton className="h-64 w-full" />
                </div>
            </div>
        );
    }

    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mb-8">
                <h1 className="text-3xl font-bold mb-2">Knowledge Base Files</h1>
                <p className="text-muted-foreground">
                    Upload and manage documents for your voice agents to reference.{" "}
                    <a href={import.meta.env.BASE_URL + "studio/docs/voice-agent/knowledge-base"} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 underline">
                        Learn more <ExternalLink className="h-3 w-3" />
                    </a>
                </p>
            </div>

            <Card>
                <CardHeader>
                    <div className="flex justify-between items-center">
                        <div>
                            <CardTitle>Your Documents</CardTitle>
                            <CardDescription>
                                Documents shared across all agents in your organization
                            </CardDescription>
                        </div>
                        <Button onClick={() => setIsUploadOpen(true)}>
                            <Upload className="w-4 h-4 mr-2" />
                            Upload Document
                        </Button>
                    </div>
                </CardHeader>
                <CardContent>
                    <DocumentList refreshTrigger={refreshKey} />
                </CardContent>
            </Card>

            {/* AgentStudio: check what agents will retrieve before customers ask. */}
            <Card className="mt-6">
                <CardHeader>
                    <CardTitle>Test retrieval</CardTitle>
                    <CardDescription>
                        Ask a question the way a customer would and see the passages an agent receives.
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <TestRetrieval />
                </CardContent>
            </Card>

            <Dialog open={isUploadOpen} onOpenChange={setIsUploadOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Upload Document</DialogTitle>
                        <DialogDescription>
                            Upload a PDF or document file to add to your knowledge base
                        </DialogDescription>
                    </DialogHeader>
                    <DocumentUpload onUploadSuccess={handleUploadSuccess} />
                </DialogContent>
            </Dialog>
        </div>
    );
}
