/**
 * White-label switch for embedding this UI in a host product.
 *
 * When true, the vendor's own commercial surfaces are not rendered: the hosted
 * model tier and its pricing, service keys and credits, and links to the
 * vendor's docs and sites. A host build replaces this module (the AgentStudio
 * port resolves "@/lib/whitelabel" to its own module exporting true).
 */
export const WHITELABEL = false;
