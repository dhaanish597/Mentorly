import brandingJson from "@config/branding.json";
import type { BrandingInfo } from "../types/api";

export const FALLBACK_BRANDING: BrandingInfo = {
  productName: brandingJson.productName,
  productNameStatus: brandingJson.productNameStatus,
  shortName: brandingJson.shortName,
  tagline: brandingJson.tagline,
};

export function applyDocumentBranding(branding: BrandingInfo): void {
  document.title = branding.productName;
}
