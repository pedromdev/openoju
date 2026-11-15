variable "environment" {
  description = "Nome curto do ambiente."
  type        = string
}

variable "vpc_id" {
  description = "VPC onde o RDS será criado."
  type        = string
}

variable "subnet_ids" {
  description = "Subnets privadas para o RDS."
  type        = list(string)
}

variable "oidc_provider_arn" {
  description = "ARN do OIDC provider do cluster EKS."
  type        = string
}

variable "oidc_issuer" {
  description = "Issuer do OIDC provider do cluster EKS."
  type        = string
}

variable "namespace" {
  description = "Namespace do release Helm (usado na trust policy IRSA)."
  type        = string
  default     = "openoju"
}

variable "service_account_name" {
  description = "ServiceAccount usada pelos pods (default: nome do release)."
  type        = string
  default     = "openoju"
}

variable "db_instance_class" {
  description = "Classe da instância do RDS."
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage" {
  description = "Armazenamento inicial do RDS em GiB."
  type        = number
  default     = 30
}

variable "db_name" {
  description = "Nome do database."
  type        = string
  default     = "openoju"
}

variable "db_username" {
  description = "Usuário master do Postgres."
  type        = string
  default     = "openoju"
}

variable "multi_az" {
  description = "Habilita RDS multi-AZ."
  type        = bool
  default     = false
}

variable "bucket_name" {
  description = "Nome do bucket. Vazio usa openoju-<ambiente>."
  type        = string
  default     = ""
}

variable "cors_origins" {
  description = "Origens permitidas para upload direto no bucket."
  type        = list(string)
  default     = ["https://openoju.example.com"]
}

variable "tags" {
  description = "Tags adicionais."
  type        = map(string)
  default     = {}
}

variable "create_database" {
  description = "Cria o RDS Postgres gerenciado."
  type        = bool
  default     = true
}

variable "create_bucket" {
  description = "Cria o bucket S3 e a role IRSA de acesso."
  type        = bool
  default     = true
}
