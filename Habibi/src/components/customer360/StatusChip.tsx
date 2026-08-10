import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Lozenge, type LozengeProps } from "@/components/ui/lozenge";

export type ChipTone = "neutral" | "brand" | "success" | "warning" | "danger";

const TONE_TO_LOZENGE_TONE: Record<ChipTone, NonNullable<LozengeProps["tone"]>> = {
  neutral: "neutral",
  brand: "information",
  success: "success",
  warning: "warning",
  danger: "danger",
};

type Props = {
  label: string;
  tone?: ChipTone;
  size?: "sm" | "md";
  /** Soft pill only for identity/risk/contactability — status uses rectangular. */
  shape?: "rect" | "pill";
  className?: string;
  title?: string;
  children?: ReactNode;
};

/**
 * Shared C360 status chip — thin wrapper over the Design.md Lozenge primitive, kept so the
 * ~9 existing call sites (and their tone-mapping helpers below) don't need a coordinated
 * rewrite. Sentence case, never all caps — Design.md bans ALL CAPS with no exemptions.
 */
export function StatusChip({
  label,
  tone = "neutral",
  size = "sm",
  shape = "rect",
  className,
  title,
  children,
}: Props) {
  return (
    <Lozenge
      tone={TONE_TO_LOZENGE_TONE[tone]}
      size={size === "md" ? "spacious" : "default"}
      title={title ?? label}
      className={cn(shape === "pill" && "rounded-full", className)}
    >
      {children}
      <span className="truncate">{label}</span>
    </Lozenge>
  );
}

export function ledgerTypeTone(type: string): ChipTone {
  switch (type) {
    case "payment":
      return "success";
    case "fee":
      return "warning";
    case "waiver":
    case "charge":
      return "brand";
    default:
      return "neutral";
  }
}

export function ptpStatusTone(status: string): ChipTone {
  switch (status) {
    case "kept":
      return "success";
    case "broken":
      return "danger";
    case "partial":
      return "warning";
    case "upcoming":
      return "brand";
    default:
      return "neutral";
  }
}

export function disputeStatusTone(status: string): ChipTone {
  switch (status) {
    case "new":
      return "brand";
    case "under_review":
      return "warning";
    case "awaiting_customer":
      return "neutral";
    case "resolved":
      return "success";
    case "rejected":
      return "danger";
    default:
      return "neutral";
  }
}

export function riskTone(level: string): ChipTone {
  switch (level) {
    case "critical":
      return "danger";
    case "high":
      return "warning";
    case "medium":
      return "brand";
    case "low":
      return "success";
    default:
      return "neutral";
  }
}
