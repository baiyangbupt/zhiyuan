export type GatewayConversationEventType =
  | 'reply'
  | 'card'
  | 'assistant.delta'
  | 'assistant.completed'
  | 'planning.status'
  | 'evidence.updated'
  | 'recommendation.card'
  | 'action.proposed'
  | 'recoverable.error';

export interface GatewayConversationEvent {
  type: GatewayConversationEventType;
  sessionId?: string;
  content?: string;
  payload?: Record<string, unknown>;
  evidenceIds?: string[];
  artifactId?: string;
}

export interface ConversationArtifact {
  artifactId: string;
  artifactType: 'candidate' | 'comparison' | 'plan_draft' | 'review';
  stateVersion: number;
  title?: string;
  items?: Array<Record<string, unknown>>;
  blockingFindings?: string[];
  warnings?: string[];
  limitations?: string[];
  [key: string]: unknown;
}

export interface ConversationEvidence {
  evidenceId: string;
  sourceLevel?: 'authoritative' | 'computed' | 'planner_experience' | string;
  dataVersion: string;
  limitations: string[];
  scope?: Record<string, unknown>;
  [key: string]: unknown;
}
