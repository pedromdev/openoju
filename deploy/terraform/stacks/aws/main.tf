locals {
  create_cluster = var.cluster_mode == "create"
  name           = "openoju-${var.environment}"

  vpc_id      = local.create_cluster ? module.k8s[0].vpc_id : var.existing_vpc_id
  subnet_ids  = local.create_cluster ? module.k8s[0].private_subnet_ids : var.existing_subnet_ids
  oidc_arn    = local.create_cluster ? module.k8s[0].oidc_provider_arn : var.existing_oidc_provider_arn
  oidc_issuer = local.create_cluster ? module.k8s[0].oidc_issuer : var.existing_oidc_issuer

  cors_origins = ["https://${var.domain}"]
}

module "k8s" {
  source = "../../modules/k8s-aws"
  count  = local.create_cluster ? 1 : 0

  environment           = var.environment
  cluster_version       = var.cluster_version
  node_count            = var.node_count
  app_instance_types    = var.app_instance_types
  system_instance_types = var.app_instance_types
}

module "deps" {
  source = "../../modules/deps-aws"

  environment          = var.environment
  vpc_id               = local.vpc_id
  subnet_ids           = local.subnet_ids
  oidc_provider_arn    = local.oidc_arn
  oidc_issuer          = local.oidc_issuer
  namespace            = var.namespace
  service_account_name = "${var.release_name}-openoju"
  db_instance_class    = var.db_instance_class
  multi_az             = var.multi_az
  cors_origins         = local.cors_origins
  create_database      = var.create_database
  create_bucket        = var.create_bucket
}
