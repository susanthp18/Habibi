'use client';

import { useOrgConfig } from '@/agentstudio/context/OrgConfigContext';
import { getLocalTimezone } from '@/agentstudio/lib/dateTime';

export function useOrganizationTimezone() {
    const { organizationPreferences } = useOrgConfig();
    return organizationPreferences?.timezone || getLocalTimezone();
}
