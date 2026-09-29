import { moduleCount } from "./data/modules";
import { AgentsPage } from "./pages/Agents";
import { CompliancePage } from "./pages/Compliance";
import { DecisionEnginePage } from "./pages/DecisionEngine";
import { DemoPage } from "./pages/Demo";
import { HomePage } from "./pages/Home";
import { InsurancePage } from "./pages/Insurance";
import { LendersPage } from "./pages/Lenders";
import { PlatformPage } from "./pages/Platform";
import { PricingPage } from "./pages/Pricing";
import { ProductPage } from "./pages/Product";
import { SecurityPage } from "./pages/Security";

export const routes = [
  {
    path: "/",
    title: "PayInt — collections that move the hour the account does",
    description:
      "A collections operating system for banks, lenders and insurers. Autonomous voice and messaging agents work every account the hour it moves, inside your perimeter.",
    priority: 1,
    component: HomePage,
  },
  {
    path: "/platform/",
    title: "The collections operating system — PayInt",
    description:
      "Event to decision to contact to evidence, in one governed pipeline. See how a failed mandate becomes a compliant conversation in minutes rather than overnight.",
    nav: "Platform",
    foot: "Platform",
    priority: 0.9,
    component: PlatformPage,
  },
  {
    path: "/decision-engine/",
    title: "Decision intelligence for collections — PayInt",
    description:
      "Next-best-treatment scored in money, not a 0-to-1 opinion. Uplift instead of propensity, hard vetoes before scoring, and a decision record behind every action.",
    nav: "Decision engine",
    foot: "Platform",
    priority: 0.9,
    component: DecisionEnginePage,
  },
  {
    path: "/agents/",
    title: "Autonomous voice and messaging agents — PayInt",
    description:
      "Build collections agents in Voice Studio — workflows, tools and knowledge — rehearse them in Checks, and publish behind gates. Claude and Codex can draft; a person still publishes.",
    nav: "Agents",
    foot: "Platform",
    priority: 0.8,
    component: AgentsPage,
  },
  {
    path: "/compliance/",
    title: "Collections compliance and 100% call QA — PayInt",
    description:
      "Every call and message scored, consent and calling-window gates enforced before a contact exists, recordings beeped over the PII, and an audit trail that answers the regulator's question.",
    nav: "Compliance",
    foot: "Platform",
    priority: 0.8,
    component: CompliancePage,
  },
  {
    path: "/security/",
    title: "On-premise deployment and security — PayInt",
    description:
      "Containers on your estate, your identity provider, your keys, your trunks. Records, recordings, transcripts and model weights never leave the perimeter.",
    nav: "Security",
    foot: "Platform",
    priority: 0.8,
    component: SecurityPage,
  },
  {
    path: "/product/",
    title: "Every module in PayInt — product tour",
    description: `The ${moduleCount} screens a collections floor runs on, grouped by the job each one does: live operations, resolution, compliance and QA, Voice Studio and bot configuration.`,
    foot: "Platform",
    label: `All ${moduleCount} modules`,
    priority: 0.7,
    component: ProductPage,
  },
  {
    path: "/lenders/",
    title: "Collections software for banks and lenders — PayInt",
    description:
      "Bounce to live contact in minutes, the whole early book covered inside 48 hours, and promises confirmed in writing before the call ends.",
    foot: "Industries",
    label: "Banks and lenders",
    priority: 0.8,
    component: LendersPage,
  },
  {
    path: "/insurance/",
    title: "Persistency and renewal recovery for insurers — PayInt",
    description:
      "Most lapse is a missed auto-debit, not a decision to leave. Work renewals, failed mandates and revival windows on the same governed pipeline as the lending book.",
    foot: "Industries",
    label: "Insurance",
    priority: 0.8,
    component: InsurancePage,
  },
  {
    path: "/pricing/",
    title: "How PayInt is priced — per resolution, not per minute",
    description:
      "A working decision engine's first effect is fewer calls. Per-minute pricing would punish that, so PayInt is priced on resolved contacts and recovered value.",
    nav: "Pricing",
    foot: "Company",
    priority: 0.7,
    component: PricingPage,
  },
  {
    path: "/demo/",
    title: "Book a walkthrough — PayInt",
    description:
      "Thirty minutes, your book, your rules. We run one live account end to end: the trigger, the gates, the decision, the call and the audit record it leaves behind.",
    foot: "Company",
    label: "Book a walkthrough",
    priority: 0.6,
    component: DemoPage,
  },
];

export const navRoutes = routes.filter((route) => route.nav);

export function routeFor(f) {
  const a = f.replace(/index\.html$/, ""),
    r = a.endsWith("/") ? a : `${a}/`;
  return routes.find((l) => l.path === r) ?? routes[0];
}
export function shortTitle(f) {
  return f.split(" — ")[0];
}
