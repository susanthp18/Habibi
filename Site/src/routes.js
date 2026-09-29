import { moduleCount } from "./data/modules";
import { AgentsPage } from "./pages/Agents";
import { CompliancePage } from "./pages/Compliance";
import { DecisionEnginePage } from "./pages/DecisionEngine";
import { DemoPage } from "./pages/Demo";
import { HomePage } from "./pages/Home";
import { InsurancePage } from "./pages/Insurance";
import { LendersPage } from "./pages/Lenders";
import { PlatformPage } from "./pages/Platform";
import { ProductPage } from "./pages/Product";
import { SecurityPage } from "./pages/Security";

export const routes = [
  {
    path: "/",
    title: "PayInt | Collections that move the hour the account does",
    description:
      "A collections operating system for banks and lenders. Voice and WhatsApp agents work every account the hour it moves, under rules they cannot talk their way past.",
    priority: 1,
    component: HomePage,
  },
  {
    path: "/platform/",
    title: "The collections operating system | PayInt",
    description:
      "Event to decision to contact to evidence, in one governed pipeline. See how a failed mandate becomes a compliant conversation and a written promise.",
    nav: "Platform",
    foot: "Platform",
    priority: 0.9,
    component: PlatformPage,
  },
  {
    path: "/decision-engine/",
    title: "Decision intelligence for collections | PayInt",
    description:
      "Ten actions scored in money against doing nothing, hard vetoes before scoring, no language model in the decision, and a full trace behind every choice.",
    nav: "Decision engine",
    foot: "Platform",
    priority: 0.9,
    component: DecisionEnginePage,
  },
  {
    path: "/agents/",
    title: "Voice and WhatsApp agents for collections | PayInt",
    description:
      "Build agents in Voice Studio, rehearse them in Checks and publish behind a release gate. Supervisors can listen, whisper and take over any live call.",
    nav: "Agents",
    foot: "Platform",
    priority: 0.8,
    component: AgentsPage,
  },
  {
    path: "/compliance/",
    title: "Collections compliance and QA on every conversation | PayInt",
    description:
      "Every conversation scored, calling windows checked at plan and at dial, recordings beeped over personal data, and hash-chained evidence an auditor can verify.",
    nav: "Compliance",
    foot: "Platform",
    priority: 0.8,
    component: CompliancePage,
  },
  {
    path: "/security/",
    title: "Deployment and security | PayInt",
    description:
      "Your servers or cloud account, Microsoft sign-in, AI services on your own keys, local post-call models, and row-level tenant isolation.",
    nav: "Security",
    foot: "Platform",
    priority: 0.8,
    component: SecurityPage,
  },
  {
    path: "/product/",
    title: "Every module in PayInt | Product tour",
    description: `The ${moduleCount} screens a collections floor runs on, grouped by the job each one does: live operations, resolution, compliance and QA, Voice Studio and configuration.`,
    foot: "Platform",
    label: `All ${moduleCount} modules`,
    crumb: "Product",
    priority: 0.7,
    component: ProductPage,
  },
  {
    path: "/lenders/",
    title: "Collections software for banks and lenders | PayInt",
    description:
      "A bounce opens a case the minute it arrives, the first compliant touch goes out in the next permitted window, and promises are confirmed in writing on the call.",
    foot: "Industries",
    label: "Banks and lenders",
    priority: 0.8,
    component: LendersPage,
  },
  {
    path: "/insurance/",
    title: "Persistency for insurers, in early access | PayInt",
    description:
      "Most lapse is a missed auto-debit, not a decision to leave. What already works for insurers today, and the renewal workflows we are building with design partners.",
    foot: "Industries",
    label: "Insurance",
    priority: 0.8,
    component: InsurancePage,
  },
  {
    path: "/demo/",
    title: "Book a walkthrough | PayInt",
    description:
      "Thirty minutes, your book, your rules. We run one account end to end: the trigger, the gates, the decision, the conversation and the record it leaves behind.",
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
  return f.split(" | ")[0];
}
