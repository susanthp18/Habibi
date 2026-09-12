import type {
  FloorChannel,
  HandlerKind,
  Risk,
  FloorAction,
  AgentFloorStatus,
  RecentTurn,
  ActiveCall,
  AlertKind,
  FloorAlert,
  FloorAgent,
} from "@/api/types/floor";

export const LIVE_QA_STATUS_LABEL: Record<string, string> = {
  would_barge: "Would barge",
  barge: "Barge",
  whisper: "Whisper",
  inbox: "Inbox",
  flagged: "QA flag",
};

export const LIVE_QA_STATUS_TONE: Record<string, "warning" | "danger" | "discovery" | "selected"> =
  {
    would_barge: "warning",
    barge: "danger",
    whisper: "discovery",
    inbox: "selected",
    flagged: "warning",
  };

export const actionLabel: Record<FloorAction, string> = {
  barge: "Take over",
  whisper: "Whisper",
  listen: "Listen",
  inbox: "Open inbox",
};

export const channelLabel: Record<FloorChannel, string> = {
  voice: "Voice",
  whatsapp: "WhatsApp",
  sms: "SMS",
};
