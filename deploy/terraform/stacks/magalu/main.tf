locals {
  create_cluster = var.cluster_mode == "create"
  name           = "openoju-${var.environment}"
}

data "mgc_kubernetes_version" "available" {
  count = local.create_cluster ? 1 : 0
}

data "mgc_kubernetes_flavor" "available" {
  count = local.create_cluster ? 1 : 0
}

resource "mgc_kubernetes_cluster" "this" {
  count = local.create_cluster ? 1 : 0

  name        = local.name
  version     = data.mgc_kubernetes_version.available[0].versions[0].version
  description = "OpenOju ${var.environment}"
}

resource "mgc_kubernetes_nodepool" "app" {
  count = local.create_cluster ? 1 : 0

  name         = "app"
  cluster_id   = mgc_kubernetes_cluster.this[0].id
  flavor_name  = var.node_flavor != "" ? var.node_flavor : data.mgc_kubernetes_flavor.available[0].nodepool[0].name
  replicas     = var.node_count
  min_replicas = 1
  max_replicas = var.node_count + 4
  version      = mgc_kubernetes_cluster.this[0].version

  labels = {
    "openoju.io/pool" = "app"
  }
}

data "mgc_kubernetes_cluster_kubeconfig" "this" {
  cluster_id = local.create_cluster ? mgc_kubernetes_cluster.this[0].id : var.existing_cluster_id
}

data "mgc_dbaas_instance_types" "available" {
  count = var.create_database ? 1 : 0
}

data "mgc_dbaas_engines" "available" {
  count  = var.create_database ? 1 : 0
  status = "ACTIVE"
}

locals {
  pg_engine = var.create_database ? one([
    for engine in data.mgc_dbaas_engines.available[0].engines :
    engine if can(regex("postgres", lower(engine.name)))
  ]) : null
}

resource "random_password" "db" {
  count   = var.create_database ? 1 : 0
  length  = 24
  special = false
}

resource "mgc_dbaas_instances" "this" {
  count = var.create_database ? 1 : 0

  name                  = "${local.name}-pg"
  user                  = "openoju"
  password              = random_password.db[0].result
  engine_name           = local.pg_engine.name
  engine_version        = local.pg_engine.version
  instance_type         = var.db_instance_type != "" ? var.db_instance_type : data.mgc_dbaas_instance_types.available[0].instance_types[0].name
  volume_size           = var.db_volume_size
  volume_type           = "CLOUD_NVME15K"
  backup_retention_days = 7
  backup_start_at       = "04:00:00"
  deletion_protected    = true
}

data "mgc_dbaas_instance" "this" {
  count = var.create_database ? 1 : 0
  id    = mgc_dbaas_instances.this[0].id
}

resource "mgc_object_storage_buckets" "media" {
  count = var.create_bucket ? 1 : 0

  bucket     = "${local.name}-media"
  versioning = true

  cors = {
    allowed_methods = ["GET", "PUT", "HEAD"]
    allowed_origins = ["https://${var.domain}"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}
