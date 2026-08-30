// -----------------------------------------------------------------------------
// Offer catalog — GET /products.
//
// The catalog used to be a hardcoded array in data/upsell-seed.ts: six products
// with their own ticket bands and ROI strings that nothing reconciled against
// the `products` table check_product_eligibility actually reads. A picker could
// therefore offer a product id the server had never heard of, and the ROI shown
// on a lead could disagree with the ROI stored on it.
//
// Same anti-drift rationale as api/staff.ts and api/teams.ts: never hardcode
// what the database already knows.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { products as mockProducts, type Product } from "@/data/upsell-seed";
import { apiGet, mockDelay, USE_MOCK } from "./config";

/** Wire shape of GET /products (schemas.ProductResponse). */
interface ProductWire {
  id: string;
  name: string;
  category: string | null;
  family: string | null;
  description: string | null;
  minTicket: number | null;
  maxTicket: number | null;
  indicativeROI: string | null;
  roiNumeric: number | null;
  tenorMonthsMin: number | null;
  tenorMonthsMax: number | null;
  marginScore: number;
  isActive: boolean;
  channels: string[];
}

function toProduct(w: ProductWire): Product {
  return {
    id: w.id,
    name: w.name,
    // The UI groups by these three; anything else the DB carries falls into
    // Loan rather than rendering an empty group header.
    category: w.category === "Card" || w.category === "Insurance" ? w.category : "Loan",
    minTicket: w.minTicket ?? 0,
    maxTicket: w.maxTicket ?? 0,
    indicativeROI: w.indicativeROI ?? "",
    description: w.description ?? "",
  };
}

export async function fetchProducts(): Promise<Product[]> {
  if (USE_MOCK) return mockDelay(mockProducts);
  const wire = await apiGet<ProductWire[]>("/products");
  return wire.map(toProduct);
}

export function useProducts() {
  return useQuery({
    queryKey: ["products"],
    queryFn: fetchProducts,
    // The catalog changes when a product manager changes it, not per render.
    staleTime: 5 * 60_000,
  });
}

let catalogCache: Promise<Product[]> | null = null;

export function productCatalog(): Promise<Product[]> {
  if (!catalogCache) {
    catalogCache = fetchProducts().catch((err) => {
      catalogCache = null;
      throw err;
    });
  }
  return catalogCache;
}

/** Look up a product by id, or undefined — callers must handle absence. */
export async function resolveProduct(id: string): Promise<Product | undefined> {
  return (await productCatalog()).find((p) => p.id === id);
}
