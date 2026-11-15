locals {
  name   = "openoju-${var.environment}"
  bucket = var.bucket_name != "" ? var.bucket_name : "openoju-${var.environment}"
  tags = merge(var.tags, {
    "openoju.io/environment" = var.environment
    Project                  = "openoju"
  })
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "this" {
  count      = var.create_database ? 1 : 0
  name       = "${local.name}-postgres"
  subnet_ids = var.subnet_ids
  tags       = local.tags
}

resource "aws_security_group" "db" {
  count       = var.create_database ? 1 : 0
  name        = "${local.name}-postgres"
  description = "Postgres do OpenOju"
  vpc_id      = var.vpc_id

  ingress {
    description = "Postgres a partir da VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_db_instance" "this" {
  count                      = var.create_database ? 1 : 0
  identifier                 = "${local.name}-postgres"
  engine                     = "postgres"
  engine_version             = "16"
  instance_class             = var.db_instance_class
  allocated_storage          = var.db_allocated_storage
  storage_type               = "gp3"
  storage_encrypted          = true
  db_name                    = var.db_name
  username                   = var.db_username
  password                   = random_password.db.result
  db_subnet_group_name       = aws_db_subnet_group.this[0].name
  vpc_security_group_ids     = [aws_security_group.db[0].id]
  multi_az                   = var.multi_az
  backup_retention_period    = 7
  backup_window              = "04:00-05:00"
  maintenance_window         = "sun:05:00-sun:06:00"
  auto_minor_version_upgrade = true
  deletion_protection        = true
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${local.name}-postgres-final"
  apply_immediately          = false
  tags                       = local.tags
}

resource "aws_s3_bucket" "media" {
  count  = var.create_bucket ? 1 : 0
  bucket = local.bucket
  tags   = local.tags
}

resource "aws_s3_bucket_versioning" "media" {
  count  = var.create_bucket ? 1 : 0
  bucket = aws_s3_bucket.media[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  count  = var.create_bucket ? 1 : 0
  bucket = aws_s3_bucket.media[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "media" {
  count                   = var.create_bucket ? 1 : 0
  bucket                  = aws_s3_bucket.media[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "media" {
  count  = var.create_bucket ? 1 : 0
  bucket = aws_s3_bucket.media[0].id
  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
    filter {}
  }
  rule {
    id     = "expire-old-logs"
    status = "Enabled"
    filter {
      prefix = "org/"
    }
    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "media" {
  count  = var.create_bucket ? 1 : 0
  bucket = aws_s3_bucket.media[0].id
  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "HEAD"]
    allowed_origins = var.cors_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

data "aws_iam_policy_document" "app_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_issuer, "https://", "")}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${var.service_account_name}"]
    }
  }
}

resource "aws_iam_role" "app" {
  count              = var.oidc_provider_arn == "" ? 0 : 1
  name               = "${local.name}-s3"
  assume_role_policy = data.aws_iam_policy_document.app_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "app_s3" {
  statement {
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
      "s3:ListBucketMultipartUploads",
    ]
    resources = [aws_s3_bucket.media[0].arn]
  }
  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.media[0].arn}/*"]
  }
}

resource "aws_iam_role_policy" "app_s3" {
  count  = var.oidc_provider_arn == "" || !var.create_bucket ? 0 : 1
  name   = "${local.name}-s3"
  role   = aws_iam_role.app[0].id
  policy = data.aws_iam_policy_document.app_s3.json
}
