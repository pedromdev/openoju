variable "environment" {
  description = "Nome curto do ambiente."
  type        = string
  default     = "prod"
}

variable "region" {
  description = "Região AWS."
  type        = string
  default     = "us-east-1"
}

variable "cluster_mode" {
  description = "create cria EKS novo; existing reutiliza um cluster."
  type        = string
  default     = "create"
}

variable "node_count" {
  description = "Nós do pool de aplicação."
  type        = number
  default     = 2
}

variable "domain" {
  description = "Domínio público do OpenOju."
  type        = string
  default     = "openoju.example.com"
}

variable "namespace" {
  description = "Namespace do release Helm."
  type        = string
  default     = "openoju"
}

variable "release_name" {
  description = "Nome do release Helm."
  type        = string
  default     = "openoju"
}

variable "db_instance_class" {
  description = "Classe da instância do RDS."
  type        = string
  default     = "db.t4g.medium"
}

variable "create_database" {
  description = "Cria RDS Postgres."
  type        = bool
  default     = true
}

variable "create_bucket" {
  description = "Cria bucket S3 + IRSA."
  type        = bool
  default     = true
}

variable "multi_az" {
  description = "RDS multi-AZ."
  type        = bool
  default     = false
}

variable "existing_cluster_name" {
  description = "Cluster existente quando cluster_mode=existing."
  type        = string
  default     = ""
}

variable "existing_vpc_id" {
  description = "VPC existente quando cluster_mode=existing."
  type        = string
  default     = ""
}

variable "existing_subnet_ids" {
  description = "Subnets privadas existentes quando cluster_mode=existing."
  type        = list(string)
  default     = []
}

variable "existing_oidc_provider_arn" {
  description = "OIDC provider do cluster existente."
  type        = string
  default     = ""
}

variable "existing_oidc_issuer" {
  description = "Issuer do OIDC provider do cluster existente."
  type        = string
  default     = ""
}

variable "cluster_version" {
  description = "Versão do Kubernetes."
  type        = string
  default     = "1.37"
}

variable "app_instance_types" {
  description = "Tipos de instância do pool de aplicação."
  type        = list(string)
  default     = ["m7i.large"]
}

variable "db_deletion_protection" {
  description = "Protege o RDS contra remoção acidental."
  type        = bool
  default     = true
}

variable "bucket_force_destroy" {
  description = "Permite destruir o bucket com objetos (apenas validação)."
  type        = bool
  default     = false
}

variable "system_node_count" {
  description = "Nós do pool de sistema."
  type        = number
  default     = 2
}
