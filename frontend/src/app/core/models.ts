export type VideoStatus =
  | 'uploaded'
  | 'queued'
  | 'analyzing'
  | 'ready'
  | 'failed'
  | 'expired';
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'canceled';
export type ReviewStatus = 'new' | 'confirmed' | 'dismissed';

export interface Video {
  id: string;
  filename: string;
  source_path: string | null;
  storage_backend: string;
  proxy_path: string | null;
  thumbnail_path: string | null;
  size_bytes: number;
  duration_s: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  recorded_at: string | null;
  status: VideoStatus;
  error: string | null;
  profile_id: string | null;
  created_at: string;
  event_count: number;
  job_id: string | null;
  job_status: JobStatus | null;
  job_progress: number | null;
  job_stage: string | null;
}

export interface Job {
  id: string;
  video_id: string;
  status: JobStatus;
  stage: string;
  progress: number;
  message: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EventItem {
  id: string;
  video_id: string;
  start_s: number;
  end_s: number;
  start_wallclock: string | null;
  end_wallclock: string | null;
  score: number;
  peak_score: number;
  bbox: number[] | null;
  label: string;
  thumbnail_path: string | null;
  clip_path: string | null;
  review_status: ReviewStatus;
  notes: string | null;
  created_at: string;
}

export interface Mask {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Profile {
  id: string;
  name: string;
  masks: Mask[];
  roi: Record<string, unknown> | null;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface UploadResponse {
  video: Video;
  job: Job | null;
}

export interface UploadInit {
  upload_id: string;
  filename: string;
  part_size: number;
  total_parts: number;
  received_parts: number[];
  storage_backend: 'local' | 's3';
  part_urls: string[];
}

export interface UploadPartResult {
  upload_id: string;
  received: number;
  total_parts: number;
  complete: boolean;
  etag: string | null;
}

export interface UploadSession extends UploadInit {
  status: string;
  error: string | null;
  created_at: string;
}

export interface Health {
  status: string;
  media_root: string;
  data_dir: string;
  media_free_bytes: number;
  media_total_bytes: number;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  status: string;
}

export interface PermissionGroup {
  id: string;
  name: string;
  description: string;
  permissions: string[];
  is_system: boolean;
}

export interface Me {
  user: {
    id: string;
    email: string;
    display_name: string;
    is_platform_admin: boolean;
  };
  organization: Organization | null;
  permissions: string[];
  groups: PermissionGroup[];
}

export interface SetupStatus {
  setup_required: boolean;
  oidc_enabled: boolean;
}

export interface Member {
  id: string;
  user_id: string;
  email: string;
  display_name: string;
  status: string;
  groups: PermissionGroup[];
  created_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated {
  api_key: ApiKey;
  key: string;
}

export interface WebhookEndpoint {
  id: string;
  name: string;
  url: string;
  events: string[];
  active: boolean;
  last_success_at: string | null;
  failure_count: number;
  created_at: string;
  updated_at: string;
}

export interface WebhookEndpointCreated {
  endpoint: WebhookEndpoint;
  secret: string;
}

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  status: string;
  attempts: number;
  next_attempt_at: string | null;
  response_status: number | null;
  response_body: string | null;
  duration_ms: number | null;
  delivered_at: string | null;
  created_at: string;
}

export interface AuditLog {
  id: string;
  actor_user_id: string | null;
  actor_api_key_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  metadata_json: Record<string, unknown>;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface PrivacySettings {
  organization_id: string;
  legal_basis: string;
  retention_media_days: number;
  retention_event_months: number;
  retention_access_logs_months: number;
  retention_audit_months: number;
  dpo_name: string | null;
  dpo_email: string | null;
  privacy_policy_version: string | null;
  privacy_policy_url: string | null;
  camera_notice_text: string | null;
  updated_at: string;
}

export interface DataSubjectRequest {
  id: string;
  organization_id: string;
  protocol: string;
  type: string;
  status: string;
  requester_name: string;
  requester_email: string;
  description: string;
  date_range_start: string | null;
  date_range_end: string | null;
  camera_profile_id: string | null;
  assigned_user_id: string | null;
  due_at: string | null;
  resolution: string | null;
  created_at: string;
  updated_at: string;
}

export interface InvitationInfo {
  organization_name: string;
  organization_slug: string;
  email: string;
  expires_at: string;
  groups: string[];
  requires_password: boolean;
}

export const PERMISSIONS = [
  'organization.view',
  'organization.manage',
  'members.view',
  'members.invite',
  'members.manage',
  'groups.manage',
  'videos.view',
  'videos.upload',
  'videos.manage',
  'videos.analyze',
  'events.view',
  'events.review',
  'profiles.view',
  'profiles.manage',
  'jobs.view',
  'jobs.cancel',
  'api_keys.manage',
  'webhooks.manage',
  'audit.view',
  'privacy.manage',
  'data_subject_requests.manage',
] as const;

export const API_KEY_SCOPES = [
  'ingest:write',
  'videos:read',
  'events:read',
  'profiles:read',
] as const;

export const WEBHOOK_EVENTS = [
  'event.created',
  'analysis.completed',
  'analysis.failed',
  'video.created',
] as const;

export interface BulkDeleteFailure {
  id: string;
  status: number;
  detail: string;
}

export interface BulkDeleteResult {
  deleted: string[];
  failed: BulkDeleteFailure[];
}
