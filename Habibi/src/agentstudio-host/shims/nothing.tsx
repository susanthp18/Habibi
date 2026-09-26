/**
 * Stand-in for the engine vendor's sales widgets (hire-an-expert nudges,
 * GitHub star badge), which AgentStudio does not ship. Renders nothing.
 */
export function HireExpertNudge(_props: Record<string, unknown>) {
  return null;
}

export const GitHubStarBadge = HireExpertNudge;

export default HireExpertNudge;
