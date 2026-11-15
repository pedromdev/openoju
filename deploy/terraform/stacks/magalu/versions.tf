terraform {
  required_version = ">= 1.11.0"

  required_providers {
    mgc = {
      source  = "magalucloud/mgc"
      version = "~> 0.56"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # backend "s3" {
  #   bucket = "openoju-tfstate"
  #   key    = "magalu/terraform.tfstate"
  #   region = "br-se1"
  #   endpoints = { s3 = "https://br-se1.magaluobjects.com" }
  #   skip_credentials_validation = true
  #   skip_region_validation      = true
  #   skip_requesting_account_id  = true
  # }
}

provider "mgc" {
  api_key         = var.mgc_api_key
  region          = var.region
  key_pair_id     = var.mgc_key_pair_id
  key_pair_secret = var.mgc_key_pair_secret
}
