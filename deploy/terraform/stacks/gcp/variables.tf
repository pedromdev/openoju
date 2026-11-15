variable "project_id" {
  description = "Projeto GCP."
  type        = string
}

variable "environment" {
  description = "Nome curto do ambiente."
  type        = string
  default     = "prod"
}

variable "region" {
  description = "Região GCP."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Zona para o node pool (single-zone simplifica o laboratório)."
  type        = string
  default     = "us-central1-a"
}

variable "cluster_mode" {
  description = "create cria GKE novo; existing reutiliza um cluster."
  type        = string
  default     = "create"
}

variable "node_count" {
  description = "Nós por zona no pool de aplicação."
  type        = number
  default     = 2
}

variable "machine_type" {
  description = "Tipo de máquina dos nós."
  type        = string
  default     = "e2-standard-4"
}

variable "db_instance_class" {
  description = "Tier do Cloud SQL."
  type        = string
  default     = "db-custom-2-4096"
}

variable "db_disk_size" {
  description = "Disco do Cloud SQL em GB."
  type        = number
  default     = 40
}

variable "create_database" {
  description = "Cria Cloud SQL."
  type        = bool
  default     = true
}

variable "create_bucket" {
  description = "Cria bucket GCS e HMAC keys."
  type        = bool
  default     = true
}

variable "domain" {
  description = "Domínio público."
  type        = string
  default     = "openoju.example.com"
}

variable "namespace" {
  description = "Namespace do Helm."
  type        = string
  default     = "openoju"
}

variable "release_name" {
  description = "Nome do release Helm."
  type        = string
  default     = "openoju"
}

variable "existing_cluster_name" {
  description = "Cluster existente quando cluster_mode=existing."
  type        = string
  default     = ""
}
