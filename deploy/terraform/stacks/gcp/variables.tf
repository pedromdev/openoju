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
  description = "Tipo de máquina dos nós de aplicação."
  type        = string
  default     = "e2-standard-2"
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

variable "system_node_count" {
  description = "Nós do pool de sistema."
  type        = number
  default     = 2
}

variable "system_machine_type" {
  description = "Tipo de máquina do pool de sistema."
  type        = string
  default     = "e2-standard-2"
}

variable "db_authorized_networks" {
  description = "Redes autorizadas a conectar no Cloud SQL (use 0.0.0.0/0 apenas em validação)."
  type        = list(string)
  default     = []
}

variable "existing_gar_repository" {
  description = "Repositório do Artifact Registry com a imagem (vazio = sem GAR gerenciado)."
  type        = string
  default     = ""
}

variable "existing_gar_location" {
  description = "Região do repositório do Artifact Registry."
  type        = string
  default     = ""
}

variable "db_edition" {
  description = "Edição do Cloud SQL (ENTERPRISE aceita tiers compartilhados)."
  type        = string
  default     = "ENTERPRISE"
}

variable "bucket_force_destroy" {
  description = "Permite destruir o bucket com objetos (apenas validação)."
  type        = bool
  default     = false
}
