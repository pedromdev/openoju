{{- define "openoju.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "openoju.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "openoju.labels" -}}
app.kubernetes.io/name: {{ include "openoju.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "openoju.configMapName" -}}
{{ include "openoju.fullname" . }}-config
{{- end -}}

{{- define "openoju.dataClaim" -}}
{{- default (printf "%s-data" (include "openoju.fullname" .)) .Values.data.existingClaim -}}
{{- end -}}

{{- define "openoju.mediaClaim" -}}
{{- default (printf "%s-media" (include "openoju.fullname" .)) .Values.media.existingClaim -}}
{{- end -}}
