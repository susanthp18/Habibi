'use client';

import { useRouter } from '@/agentstudio-host/shims/next-navigation';

import { useOrganizationTimezone } from '@/agentstudio/hooks/useOrganizationTimezone';
import { formatDate } from '@/agentstudio/lib/dateTime';

interface WorkflowCardProps {
    id: number;
    name: string;
    createdAt: string;
}

export function WorkflowCard({ id, name, createdAt }: WorkflowCardProps) {
    const router = useRouter();
    const organizationTimezone = useOrganizationTimezone();

    const handleClick = () => {
        router.push(`/workflow/${id}`);
    };

    return (
        <div
            className="bg-white border rounded-lg overflow-hidden shadow-sm hover:shadow-md transition-all duration-200 p-4 cursor-pointer transform hover:-translate-y-1"
            onClick={handleClick}
        >
            <div>
                <h3 className="text-lg font-semibold mb-2">{name}</h3>
                <p className="text-text-subtle mb-2">
                    Created: {formatDate(createdAt, organizationTimezone)}
                </p>
            </div>
        </div>
    );
}
