variable "mgc_api_key" {
  description = "API key da Magalu Cloud."
  type        = string
  sensitive   = true
}

variable "mgc_key_pair_id" {
  description = "Key pair de Object Storage (access key)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "mgc_key_pair_secret" {
  description = "Key pair de Object Storage (secret key)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "environment" {
  description = "Nome curto do ambiente."
  type        = string
  default     = "prod"
}

variable "region" {
  description = "Região (br-ne1, br-se1, br-mgl1, br-mc1)."
  type        = string
  default     = "br-se1"
}

variable "cluster_mode" {
  description = "create cria MKE novo; existing reutiliza um cluster."
  type        = string
  default     = "create"
}

variable "node_count" {
  description = "Réplicas do node pool de aplicação."
  type        = number
  default     = 2
}

variable "node_flavor" {
  description = "Flavor do node pool. Vazio usa o primeiro disponível."
  type        = string
  default     = ""
}

variable "db_instance_type" {
  description = "Instance type do DBaaS. Vazio usa o primeiro disponível."
  type        = string
  default     = ""
}

variable "db_volume_size" {
  description = "Volume do DBaaS em GB."
  type        = number
  default     = 50
}

variable "create_database" {
  description = "Cria DBaaS PostgreSQL."
  type        = bool
  default     = true
}

variable "create_bucket" {
  description = "Cria bucket no Object Storage."
  type        = bool
  default     = true
}

variable "domain" {
  description = "Domínio público (usado no CORS)."
  type        = string
  default     = "openoju.example.com"
}

variable "existing_cluster_id" {
  description = "Cluster existente quando cluster_mode=existing."
  type        = string
  default     = ""
}

variable "db_engine_name" {
  description = "Engine do DBaaS (ex.: postgresql)."
  type        = string
  default     = "postgresql"
}

variable "db_engine_version" {
  description = "Versão do engine. Vazio consulta a API (pode falhar na paginação)."
  type        = string
  default     = ""
}
