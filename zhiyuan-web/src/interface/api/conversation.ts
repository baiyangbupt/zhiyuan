export type GatewayConversationEventType =
  | 'reply'
  | 'card'
  | 'assistant.delta'
  | 'assistant.completed'
  | 'planning.status'
  | 'evidence.updated'
  | 'admission.facts.updated'
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
  admissionMode?: AdmissionMode;
  admissionUnitId?: string;
  groupCode?: string;
  algorithmVersion?: string;
  stateVersion?: number;
  observedAt?: string;
  [key: string]: unknown;
}

export type AdmissionMode = 'major' | 'major_group';

export interface AdmissionMajorDetail {
  majorId: string;
  majorName?: string;
  majorCode?: string;
  majorAdmissionRate: number;
}

export interface AdmissionFact {
  admissionUnitId: string;
  admissionMode: AdmissionMode;
  schoolId: string;
  schoolName?: string;
  majorId?: string;
  majorName?: string;
  groupCode?: string;
  majorItems: AdmissionMajorDetail[];
  unitAdmissionRate: number;
  riskTier: '冲' | '稳' | '保';
  dataVersion?: string;
  algorithmVersion?: string;
  observedAt?: string;
  limitations?: string[];
}
