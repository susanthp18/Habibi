import { Button } from "@/agentstudio/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/agentstudio/components/ui/dialog";

interface WorkflowConfigErrorProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    error: string | null;
    onNavigateToWorkflow: () => void;
}

export const WorkflowConfigErrorDialog = ({
    open,
    onOpenChange,
    error,
    onNavigateToWorkflow
}: WorkflowConfigErrorProps) => {
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Workflow Error</DialogTitle>
                    <DialogDescription className="text-text-danger whitespace-pre-line">
                        {error}
                    </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                    <Button onClick={onNavigateToWorkflow}>
                        Go to Workflow
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
