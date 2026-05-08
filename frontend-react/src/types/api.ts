export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
  email?: string;
  full_name?: string;
  scopes?: string[];
  tenant_id?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface DocumentUploadResponse {
  document_id: string;
  filename: string;
  size_bytes: number;
  task_id?: string;
  message: string;
}

export interface ScrapeRequest {
  url: string;
}

export interface CrawlRequest {
  url: string;
  max_depth?: number;
  max_pages?: number;
}

export interface IngestionStatusResponse {
  task_id: string;
  status: string;
  progress?: Record<string, any>;
  result?: Record<string, any>;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  upload_date: string;
}

export interface DocumentListResponse {
  documents: DocumentInfo[];
  total: number;
}

export interface QueryRequest {
  query: string;
  top_k?: number;
  streaming?: boolean;
  document_id?: string;
  conversation_id?: string;
  use_got?: boolean;
  at_time?: string; 
}

export interface ConfidenceJudgmentResponse {
  score: number;
  reasoning: string;
  grounded_claims: number;
  ungrounded_claims: number;
  hallucination_risk: 'low' | 'medium' | 'high';
}

export interface QueryResponse {
  answer: string;
  sources: Array<Record<string, any>>;
  reasoning_chain: string[];
  confidence: number;
  confidence_judgment?: ConfidenceJudgmentResponse;
  retrieval_method: string;
  processing_time_seconds: number;
  conversation_id?: string;
  drift_expanded?: boolean;
  total_sub_queries?: number;
}

export interface EvalResultData {
  overall_score?: number;
  faithfulness: number;
  answer_relevancy?: number;
  relevancy?: number;
  context_precision?: number;
  precision?: number;
}

export interface Message {
  id: string;
  role: string;
  content: string;
  reasoning?: string[];
  sources?: Array<Record<string, any>>;
  confidence?: number;
  hallucination_risk?: string;
  confidence_reasoning?: string;
  created_at: string;
  eval_result?: EvalResultData;
  evaluating?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages?: Message[];
}

export interface ConversationListResponse {
  conversations: Conversation[];
}

export interface OntologyResponse {
  version: string;
  entity_types: string[];
  relationship_types: string[];
  properties: Record<string, string[]>;
  created_at: string;
  approved: boolean;
}

export interface OntologyUpdateRequest {
  entity_types?: string[];
  relationship_types?: string[];
  properties?: Record<string, string[]>;
  approved?: boolean;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  description?: string;
  properties: Record<string, any>;
  community_id?: number;
  valid_from?: string;
  valid_until?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  properties: Record<string, any>;
  valid_from?: string;
  confidence?: number;
}

export interface GraphVisualizationResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SystemHealthResponse {
  status: string;
  version: string;
  neo4j_connected: boolean;
  redis_connected: boolean;
  workers_active: number;
  timestamp: string;
}

export interface SystemStatsResponse {
  documents_count: number;
  entities_count: number;
  relationships_count: number;
  chunks_count: number;
  ontology_version: string;
}

export interface DriftReport { id: string; detected_at: string; new_entity_types: string[]; new_relationship_types: string[]; removed_entity_types: string[]; removed_relationship_types: string[]; sample_size: number; drift_score: number; status: string; approved_by?: string; approved_at?: string; }
