{{- define "openoju.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "openoju.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- /* Determinístico: instalar com `--name openoju` continua gerando
       `openoju-openoju`, então os Services não mudam de nome conforme o release. */ -}}
{{- printf "%s-%s" .Release.Name (default .Chart.Name .Values.nameOverride) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "openoju.labels" -}}
app.kubernetes.io/name: {{ include "openoju.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "openoju.selectorLabels" -}}
app.kubernetes.io/name: {{ include "openoju.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "openoju.componentLabels" -}}
{{ include "openoju.selectorLabels" . }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "openoju.configMapName" -}}
{{ include "openoju.fullname" . }}-config
{{- end -}}

{{- define "openoju.secretName" -}}
{{- default (printf "%s-secrets" (include "openoju.fullname" .)) .Values.existingSecret -}}
{{- end -}}

{{- define "openoju.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "openoju.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "openoju.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | toString) -}}
{{- end -}}

{{- define "openoju.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{- define "openoju.dataClaim" -}}
{{- default (printf "%s-data" (include "openoju.fullname" .)) .Values.data.existingClaim -}}
{{- end -}}

{{- define "openoju.mediaClaim" -}}
{{- default (printf "%s-media" (include "openoju.fullname" .)) .Values.media.existingClaim -}}
{{- end -}}

{{/*
Volume definitions shared by every workload. ``mode`` switches between a PVC
and a per-pod scratch volume, which is what managed object storage needs.
*/}}
{{- define "openoju.volumes" -}}
- name: data
{{- if eq .Values.data.mode "emptyDir" }}
  emptyDir:
{{- toYaml .Values.data.emptyDir | nindent 4 }}
{{- else }}
  persistentVolumeClaim:
    claimName: {{ include "openoju.dataClaim" . }}
{{- end }}
- name: media
{{- if eq .Values.media.mode "emptyDir" }}
  emptyDir:
{{- toYaml .Values.media.emptyDir | nindent 4 }}
{{- else }}
  persistentVolumeClaim:
    claimName: {{ include "openoju.mediaClaim" . }}
{{- end }}
{{- end -}}

{{- define "openoju.volumeMounts" -}}
- name: data
  mountPath: /app/data
- name: media
  mountPath: {{ .Values.config.OJU_MEDIA_ROOT | default "/media" }}
{{- end -}}

{{/*
Environment shared by all workloads. Extra values from ``extraEnv`` and
``extraEnvFrom`` let a cloud preset inject IRSA/Workload Identity without
renaming the chart.
*/}}
{{- define "openoju.env" -}}
envFrom:
  - configMapRef:
      name: {{ include "openoju.configMapName" . }}
  - secretRef:
      name: {{ include "openoju.secretName" . }}
{{- with .Values.extraEnvFrom }}
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.extraEnv }}
env:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{- define "openoju.scheduling" -}}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.topologySpreadConstraints }}
topologySpreadConstraints:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.priorityClassName }}
priorityClassName: {{ . }}
{{- end }}
{{- end -}}

{{/*
VAAPI access is opt-in: cloud nodes do not expose /dev/dri and requesting the
device would keep the worker Pending forever.
*/}}
{{- define "openoju.podSecurityContext" -}}
{{- $ctx := deepCopy .Values.securityContext -}}
{{- if and .Values.vaapi.enabled .Values.vaapi.groupAdd -}}
{{- $_ := set $ctx "supplementalGroups" .Values.vaapi.groupAdd -}}
{{- end -}}
{{- toYaml $ctx -}}
{{- end -}}

{{- define "openoju.vaapiVolume" -}}
{{- if .Values.vaapi.enabled }}
- name: dri
  hostPath:
    path: {{ .Values.vaapi.device | default "/dev/dri" }}
{{- end }}
{{- end -}}

{{- define "openoju.vaapiMount" -}}
{{- if .Values.vaapi.enabled }}
- name: dri
  mountPath: /dev/dri
{{- end -}}
{{- end -}}
