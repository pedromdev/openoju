import { HttpClient, HttpEvent, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { AuthService } from './auth.service';
import {
  ApiKey,
  ApiKeyCreated,
  AuditLog,
  DataSubjectRequest,
  EventItem,
  Member,
  Organization,
  PermissionGroup,
  PrivacySettings,
  Profile,
  ReviewStatus,
  UploadInit,
  UploadPartResult,
  UploadResponse,
  UploadSession,
  Video,
  WebhookDelivery,
  WebhookEndpoint,
  WebhookEndpointCreated,
} from './models';

const API = '/api/v1';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);
  readonly base = API;

  private org(path: string): string {
    return `${this.auth.orgBase()}${path}`;
  }

  health(): Observable<import('./models').Health> {
    return this.http.get<import('./models').Health>(`${API}/health`);
  }

  // -- catalog ---------------------------------------------------------
  listVideos(): Observable<Video[]> {
    return this.http.get<Video[]>(this.org('/videos'));
  }

  getVideo(id: string): Observable<Video> {
    return this.http.get<Video>(this.org(`/videos/${id}`));
  }

  getVideoEvents(id: string): Observable<EventItem[]> {
    return this.http.get<EventItem[]>(this.org(`/videos/${id}/events`));
  }

  analyzeVideo(id: string): Observable<import('./models').Job> {
    return this.http.post<import('./models').Job>(
      this.org(`/videos/${id}/analyze`),
      {},
    );
  }

  deleteVideo(id: string): Observable<void> {
    return this.http.delete<void>(this.org(`/videos/${id}`));
  }

  bulkDeleteVideos(ids: string[]): Observable<import('./models').BulkDeleteResult> {
    return this.http.post<import('./models').BulkDeleteResult>(
      this.org('/videos/bulk-delete'),
      { ids },
    );
  }

  uploadVideo(
    file: File,
    profileId?: string | null,
  ): Observable<HttpEvent<UploadResponse>> {
    const form = new FormData();
    form.append('file', file);
    if (profileId) {
      form.append('profile_id', profileId);
    }
    return this.http.post<UploadResponse>(this.org('/videos/upload'), form, {
      reportProgress: true,
      observe: 'events',
    });
  }

  initUpload(
    filename: string,
    size: number,
    profileId?: string | null,
  ): Observable<UploadInit> {
    return this.http.post<UploadInit>(this.org('/uploads/init'), {
      filename,
      size,
      profile_id: profileId || null,
    });
  }

  uploadPart(
    uploadId: string,
    partNumber: number,
    part: Blob,
  ): Observable<HttpEvent<UploadPartResult>> {
    return this.http.put<UploadPartResult>(
      this.org(`/uploads/${uploadId}/parts/${partNumber}`),
      part,
      {
        headers: { 'Content-Type': 'application/octet-stream' },
        reportProgress: true,
        observe: 'events',
      },
    );
  }

  uploadPresigned(
    url: string,
    part: Blob,
  ): Observable<HttpEvent<HttpResponse<unknown>>> {
    return this.http.put(url, part, {
      headers: { 'Content-Type': 'application/octet-stream' },
      reportProgress: true,
      observe: 'events',
      responseType: 'text',
    }) as Observable<HttpEvent<HttpResponse<unknown>>>;
  }

  completeUpload(
    uploadId: string,
    parts?: { part_number: number; etag?: string | null }[],
  ): Observable<UploadResponse> {
    return this.http.post<UploadResponse>(this.org(`/uploads/${uploadId}/complete`), {
      parts: parts ?? null,
    });
  }

  getUpload(uploadId: string): Observable<UploadSession> {
    return this.http.get<UploadSession>(this.org(`/uploads/${uploadId}`));
  }

  cancelUpload(uploadId: string): Observable<void> {
    return this.http.delete<void>(this.org(`/uploads/${uploadId}`));
  }

  importVideos(
    path: string,
    profileId?: string | null,
    recursive = true,
  ): Observable<UploadResponse[]> {
    return this.http.post<UploadResponse[]>(this.org('/videos/import'), {
      path,
      profile_id: profileId || null,
      recursive,
    });
  }

  scanFolder(
    path?: string | null,
    profileId?: string | null,
    recursive = true,
  ): Observable<UploadResponse[]> {
    return this.http.post<UploadResponse[]>(this.org('/videos/scan'), {
      path: path || null,
      profile_id: profileId || null,
      recursive,
    });
  }

  getJob(id: string): Observable<import('./models').Job> {
    return this.http.get<import('./models').Job>(this.org(`/jobs/${id}`));
  }

  cancelJob(id: string): Observable<import('./models').Job> {
    return this.http.post<import('./models').Job>(
      this.org(`/jobs/${id}/cancel`),
      {},
    );
  }

  listProfiles(): Observable<Profile[]> {
    return this.http.get<Profile[]>(this.org('/profiles'));
  }

  createProfile(payload: {
    name: string;
    masks: Profile['masks'];
    roi: Profile['roi'];
    settings: Profile['settings'];
  }): Observable<Profile> {
    return this.http.post<Profile>(this.org('/profiles'), payload);
  }

  updateProfile(
    id: string,
    payload: {
      name: string;
      masks: Profile['masks'];
      roi: Profile['roi'];
      settings: Profile['settings'];
    },
  ): Observable<Profile> {
    return this.http.put<Profile>(this.org(`/profiles/${id}`), payload);
  }

  deleteProfile(id: string): Observable<void> {
    return this.http.delete<void>(this.org(`/profiles/${id}`));
  }

  reviewEvent(
    id: string,
    reviewStatus: ReviewStatus,
    notes?: string,
  ): Observable<EventItem> {
    return this.http.patch<EventItem>(this.org(`/events/${id}`), {
      review_status: reviewStatus,
      notes: notes ?? null,
    });
  }

  videoStreamUrl(id: string): string {
    return this.org(`/videos/${id}/stream`);
  }

  videoThumbnailUrl(id: string): string {
    return this.org(`/videos/${id}/thumbnail?v=mid`);
  }

  eventThumbnailUrl(id: string): string {
    return this.org(`/events/${id}/thumbnail?v=mid`);
  }

  eventClipUrl(id: string): string {
    return this.org(`/events/${id}/clip`);
  }

  jobEventsUrl(id: string): string {
    return this.org(`/jobs/${id}/events`);
  }

  jobLogUrl(id: string): string {
    return this.org(`/jobs/${id}/log`);
  }

  // -- administration --------------------------------------------------
  listMembers(): Observable<Member[]> {
    return this.http.get<Member[]>(this.org('/members'));
  }

  inviteMember(email: string, groupIds: string[]): Observable<{
    membership_id: string;
    invitation_id: string;
    token: string;
    expires_at: string;
  }> {
    return this.http.post<{
      membership_id: string;
      invitation_id: string;
      token: string;
      expires_at: string;
    }>(this.org('/members/invite'), { email, group_ids: groupIds });
  }

  updateMember(
    id: string,
    status: string,
    groupIds?: string[],
  ): Observable<Member> {
    return this.http.patch<Member>(this.org(`/members/${id}`), {
      status,
      group_ids: groupIds ?? null,
    });
  }

  listGroups(): Observable<PermissionGroup[]> {
    return this.http.get<PermissionGroup[]>(this.org('/groups'));
  }

  createGroup(payload: {
    name: string;
    description: string;
    permissions: string[];
  }): Observable<PermissionGroup> {
    return this.http.post<PermissionGroup>(this.org('/groups'), payload);
  }

  updateGroup(
    id: string,
    payload: { name: string; description: string; permissions: string[] },
  ): Observable<PermissionGroup> {
    return this.http.put<PermissionGroup>(this.org(`/groups/${id}`), payload);
  }

  listApiKeys(): Observable<ApiKey[]> {
    return this.http.get<ApiKey[]>(this.org('/api-keys'));
  }

  createApiKey(name: string, scopes: string[]): Observable<ApiKeyCreated> {
    return this.http.post<ApiKeyCreated>(this.org('/api-keys'), { name, scopes });
  }

  revokeApiKey(id: string): Observable<void> {
    return this.http.delete<void>(this.org(`/api-keys/${id}`));
  }

  listWebhooks(): Observable<WebhookEndpoint[]> {
    return this.http.get<WebhookEndpoint[]>(this.org('/webhooks'));
  }

  createWebhook(payload: {
    name: string;
    url: string;
    events: string[];
    active: boolean;
  }): Observable<WebhookEndpointCreated> {
    return this.http.post<WebhookEndpointCreated>(this.org('/webhooks'), payload);
  }

  updateWebhook(
    id: string,
    payload: { name: string; url: string; events: string[]; active: boolean },
  ): Observable<WebhookEndpoint> {
    return this.http.put<WebhookEndpoint>(this.org(`/webhooks/${id}`), payload);
  }

  deleteWebhook(id: string): Observable<void> {
    return this.http.delete<void>(this.org(`/webhooks/${id}`));
  }

  testWebhook(id: string): Observable<{ delivery: WebhookDelivery }> {
    return this.http.post<{ delivery: WebhookDelivery }>(
      this.org(`/webhooks/${id}/test`),
      {},
    );
  }

  webhookDeliveries(id: string): Observable<WebhookDelivery[]> {
    return this.http.get<WebhookDelivery[]>(this.org(`/webhooks/${id}/deliveries`));
  }

  retryWebhookDelivery(
    endpointId: string,
    deliveryId: string,
  ): Observable<WebhookDelivery> {
    return this.http.post<WebhookDelivery>(
      this.org(`/webhooks/${endpointId}/deliveries/${deliveryId}/retry`),
      {},
    );
  }

  getPrivacy(): Observable<PrivacySettings> {
    return this.http.get<PrivacySettings>(this.org('/privacy'));
  }

  updatePrivacy(payload: Partial<PrivacySettings>): Observable<PrivacySettings> {
    return this.http.put<PrivacySettings>(this.org('/privacy'), payload);
  }

  listDsr(): Observable<DataSubjectRequest[]> {
    return this.http.get<DataSubjectRequest[]>(this.org('/data-subject-requests'));
  }

  updateDsr(id: string, status: string, resolution?: string): Observable<DataSubjectRequest> {
    return this.http.patch<DataSubjectRequest>(
      this.org(`/data-subject-requests/${id}`),
      { status, resolution: resolution ?? null },
    );
  }

  exportDsr(id: string): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(
      this.org(`/data-subject-requests/${id}/export`),
    );
  }

  executeDsrDeletion(id: string): Observable<{
    deleted_events: number;
    skipped_legal_hold: number;
  }> {
    return this.http.post<{ deleted_events: number; skipped_legal_hold: number }>(
      this.org(`/data-subject-requests/${id}/execute-deletion`),
      {},
    );
  }

  listAudit(): Observable<AuditLog[]> {
    return this.http.get<AuditLog[]>(this.org('/audit'));
  }

  runRetention(): Observable<Record<string, number>> {
    return this.http.post<Record<string, number>>(this.org('/retention/run'), {});
  }

  listOrganizations(): Observable<Organization[]> {
    return this.auth.listOrganizations();
  }
}
