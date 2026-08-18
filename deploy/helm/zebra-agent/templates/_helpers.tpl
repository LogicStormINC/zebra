{{- define "zebra-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "zebra-agent.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "zebra-agent.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "zebra-agent.labels" -}}
app.kubernetes.io/name: {{ include "zebra-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
{{- end -}}

{{- define "zebra-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "zebra-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "zebra-agent.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "zebra-agent.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "zebra-agent.image" -}}
{{- printf "%s@%s" .Values.image.repository (required "image.digest must be a sha256 digest" .Values.image.digest) -}}
{{- end -}}

{{- define "zebra-agent.cloudEnv" -}}
- name: ZEBRA_PROFILE
  value: {{ required "profile must be cloud or production" .Values.profile | quote }}
- name: ZEBRA_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ required "secrets.databaseUrl.name is required" .Values.secrets.databaseUrl.name | quote }}
      key: {{ required "secrets.databaseUrl.key is required" .Values.secrets.databaseUrl.key | quote }}
- name: ZEBRA_RUNTIME_CLASS
  value: {{ required "runtimeClassName must be gvisor" .Values.runtimeClassName | quote }}
- name: ZEBRA_RUNTIME_IMAGE
  value: {{ required "runtimeImage is required" .Values.runtimeImage | quote }}
- name: ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA
  value: "true"
- name: ZEBRA_DEPLOYMENT_NAMESPACE
  value: {{ required "deploymentNamespace is required" .Values.deploymentNamespace | quote }}
- name: ZEBRA_AUTHORITY_ISSUER
  value: {{ required "config.authorityIssuer is required" .Values.config.authorityIssuer | quote }}
- name: ZEBRA_HISTORY_SCOPE_NAMESPACE
  value: {{ required "config.historyScopeNamespace is required" .Values.config.historyScopeNamespace | quote }}
- name: ZEBRA_CONTINUATION_SCOPE_NAMESPACE
  value: {{ required "config.continuationScopeNamespace is required" .Values.config.continuationScopeNamespace | quote }}
- name: ZEBRA_MEMORY_CURSOR_SIGNING_KEY
  valueFrom:
    secretKeyRef:
      name: {{ required "secrets.memorySigningKey.name is required" .Values.secrets.memorySigningKey.name | quote }}
      key: {{ required "secrets.memorySigningKey.key is required" .Values.secrets.memorySigningKey.key | quote }}
- name: ZEBRA_S3_ENDPOINT
  value: {{ required "config.s3Endpoint is required" .Values.config.s3Endpoint | quote }}
- name: ZEBRA_S3_BUCKET
  value: {{ required "config.s3Bucket is required" .Values.config.s3Bucket | quote }}
- name: ZEBRA_S3_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ required "secrets.s3.name is required" .Values.secrets.s3.name | quote }}
      key: {{ required "secrets.s3.accessKeyKey is required" .Values.secrets.s3.accessKeyKey | quote }}
- name: ZEBRA_S3_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ required "secrets.s3.name is required" .Values.secrets.s3.name | quote }}
      key: {{ required "secrets.s3.secretKeyKey is required" .Values.secrets.s3.secretKeyKey | quote }}
- name: ZEBRA_S3_REGION
  value: {{ .Values.config.s3Region | quote }}
- name: ZEBRA_S3_KEY_PREFIX
  value: {{ .Values.config.s3KeyPrefix | quote }}
- name: ZEBRA_LIVE_REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ required "secrets.liveRedisUrl.name is required" .Values.secrets.liveRedisUrl.name | quote }}
      key: {{ required "secrets.liveRedisUrl.key is required" .Values.secrets.liveRedisUrl.key | quote }}
- name: ZEBRA_LIVE_STREAM_MAX_LENGTH
  value: {{ .Values.config.liveStreamMaxLength | quote }}
- name: ZEBRA_LIVE_STREAM_KEY_PREFIX
  value: {{ .Values.config.liveStreamKeyPrefix | quote }}
{{- if .Values.secrets.apiAuthToken.name }}
- name: ZEBRA_API_AUTH_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.apiAuthToken.name | quote }}
      key: {{ .Values.secrets.apiAuthToken.key | quote }}
{{- end -}}
{{- end -}}

{{- define "zebra-agent.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 65532
runAsGroup: 65532
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "zebra-agent.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end -}}
