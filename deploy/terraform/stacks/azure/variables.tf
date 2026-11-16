variable "subscription_id" {
  description = "Subscription do Azure."
  type        = string
}

variable "environment" {
  description = "Nome curto do ambiente."
  type        = string
  default     = "prod"
}

variable "location" {
  description = "Região do Azure."
  type        = string
  default     = "brazilsouth"
}

variable "region" {
  description = "Alias de location usado pelos tfvars do wizard."
  type        = string
  default     = "brazilsouth"
}

variable "cluster_mode" {
  description = "create cria AKS novo; existing reutiliza um cluster."
  type        = string
  default     = "create"
}

variable "node_count" {
  description = "Nós do pool de aplicação."
  type        = number
  default     = 2
}

variable "node_vm_size" {
  description = "Tamanho das VMs do pool de aplicação."
  type        = string
  default     = "Standard_D2ds_v4"
}

variable "db_instance_class" {
  description = "SKU do PostgreSQL Flexible Server."
  type        = string
  default     = "GP_Standard_D2ds_v5"
}

variable "db_storage_mb" {
  description = "Armazenamento do Postgres em MB."
  type        = number
  default     = 65536
}

variable "create_database" {
  description = "Cria PostgreSQL Flexible Server."
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

variable "cluster_version" {
  description = "Versão do Kubernetes no AKS."
  type        = string
  default     = "1.36"
}

variable "system_node_vm_size" {
  description = "Tamanho das VMs do pool de sistema."
  type        = string
  default     = "Standard_D2ds_v4"
}

variable "system_node_count" {
  description = "Nós do pool de sistema (default pool do AKS)."
  type        = number
  default     = 2
}

variable "existing_acr_name" {
  description = "ACR já existente com a imagem do OpenOju (vazio = sem ACR gerenciado)."
  type        = string
  default     = ""
}

variable "existing_acr_resource_group" {
  description = "Resource group do ACR existente."
  type        = string
  default     = ""
}

variable "storage_container_name" {
  description = "Container do Azure Blob usado pela aplicação."
  type        = string
  default     = "openoju-media"
}
