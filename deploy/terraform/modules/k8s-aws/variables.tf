variable "environment" {
  description = "Nome curto do ambiente (usado em prefixos e tags)."
  type        = string
}

variable "cluster_version" {
  description = "Versão do Kubernetes do EKS."
  type        = string
  default     = "1.37"
}

variable "vpc_cidr" {
  description = "CIDR da VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  description = "Quantidade de zonas de disponibilidade."
  type        = number
  default     = 3
}

variable "node_count" {
  description = "Nós por node group de aplicação."
  type        = number
  default     = 2
}

variable "app_instance_types" {
  description = "Tipos de instância do pool de aplicação (worker de análise)."
  type        = list(string)
  default     = ["m7i.large"]
}

variable "system_instance_types" {
  description = "Tipos de instância do pool de sistema."
  type        = list(string)
  default     = ["m7i.large"]
}

variable "tags" {
  description = "Tags adicionais."
  type        = map(string)
  default     = {}
}

variable "system_node_count" {
  description = "Nós do pool de sistema (addons)."
  type        = number
  default     = 2
}
