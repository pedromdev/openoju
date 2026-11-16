locals {
  create_cluster = var.cluster_mode == "create"
  name           = "openoju-${var.environment}"
  ksa            = "${var.release_name}-openoju"
}

resource "google_compute_network" "this" {
  name                    = "${local.name}-net"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "this" {
  name          = "${local.name}-subnet"
  region        = var.region
  network       = google_compute_network.this.id
  ip_cidr_range = "10.50.0.0/16"

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.51.0.0/16"
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.52.0.0/16"
  }
}

resource "google_compute_router" "this" {
  name    = "${local.name}-router"
  region  = var.region
  network = google_compute_network.this.id
}

resource "google_compute_router_nat" "this" {
  name                               = "${local.name}-nat"
  router                             = google_compute_router.this.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_container_cluster" "this" {
  count = local.create_cluster ? 1 : 0

  name                = local.name
  location            = var.zone
  network             = google_compute_network.this.id
  subnetwork          = google_compute_subnetwork.this.id
  initial_node_count  = 0
  deletion_protection = false

  networking_mode = "VPC_NATIVE"
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  release_channel {
    channel = "REGULAR"
  }
}

resource "google_container_node_pool" "system" {
  count = local.create_cluster ? 1 : 0

  name       = "system"
  cluster    = google_container_cluster.this[0].name
  location   = var.zone
  node_count = var.system_node_count

  node_config {
    machine_type = var.system_machine_type
    labels = {
      "openoju.io/pool" = "system"
    }
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

resource "google_container_node_pool" "app" {
  count = local.create_cluster ? 1 : 0

  name       = "app"
  cluster    = google_container_cluster.this[0].name
  location   = var.zone
  node_count = var.node_count

  node_config {
    machine_type = var.machine_type
    labels = {
      "openoju.io/pool" = "app"
    }
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

resource "random_password" "db" {
  count   = var.create_database ? 1 : 0
  length  = 32
  special = false
}

resource "google_sql_database_instance" "this" {
  count = var.create_database ? 1 : 0

  name                = "${local.name}-pg"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = false

  settings {
    edition           = var.db_edition
    tier              = var.db_instance_class
    disk_size         = var.db_disk_size
    disk_autoresize   = true
    availability_type = "ZONAL"

    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"

      dynamic "authorized_networks" {
        for_each = var.db_authorized_networks
        content {
          name  = "allowed-${authorized_networks.key}"
          value = authorized_networks.value
        }
      }
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "04:00"
      point_in_time_recovery_enabled = true
    }
  }
}

resource "google_sql_database" "this" {
  count = var.create_database ? 1 : 0

  name     = "openoju"
  instance = google_sql_database_instance.this[0].name
}

resource "google_sql_user" "this" {
  count = var.create_database ? 1 : 0

  name     = "openoju"
  instance = google_sql_database_instance.this[0].name
  password = random_password.db[0].result
}

resource "google_storage_bucket" "media" {
  count = var.create_bucket ? 1 : 0

  name                        = "${local.name}-media"
  location                    = upper(var.region)
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type = "Delete"
    }
  }

  cors {
    origin          = ["https://${var.domain}"]
    method          = ["GET", "PUT", "HEAD"]
    response_header = ["ETag"]
    max_age_seconds = 3600
  }
}

resource "google_service_account" "app" {
  account_id   = "${local.name}-s3"
  display_name = "OpenOju object storage"
}

resource "google_storage_bucket_iam_member" "app" {
  count  = var.create_bucket ? 1 : 0
  bucket = google_storage_bucket.media[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.app.email}"
}

resource "google_storage_hmac_key" "app" {
  count = var.create_bucket ? 1 : 0

  service_account_email = google_service_account.app.email
  project               = var.project_id
}

resource "google_service_account_iam_member" "workload_identity" {
  count = local.create_cluster ? 1 : 0

  service_account_id = google_service_account.app.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.namespace}/${local.ksa}]"

  # O pool ${project}.svc.id.goog só existe depois que o cluster é criado.
  depends_on = [google_container_cluster.this]
}

data "google_project" "this" {}

data "google_artifact_registry_repository" "existing" {
  count         = var.existing_gar_repository == "" ? 0 : 1
  location      = var.existing_gar_location != "" ? var.existing_gar_location : var.region
  repository_id = var.existing_gar_repository
}

resource "google_artifact_registry_repository_iam_member" "node_reader" {
  count = var.existing_gar_repository == "" || !local.create_cluster ? 0 : 1

  location   = data.google_artifact_registry_repository.existing[0].location
  repository = data.google_artifact_registry_repository.existing[0].name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${data.google_project.this.number}-compute@developer.gserviceaccount.com"
}
