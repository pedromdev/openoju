terraform {
  required_version = ">= 1.11.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # backend "gcs" {
  #   bucket = "openoju-tfstate"
  #   prefix = "gcp"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
