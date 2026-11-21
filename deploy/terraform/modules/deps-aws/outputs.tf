output "database_url" {
  value = var.create_database ? (
    "postgresql+psycopg://${var.db_username}:${random_password.db.result}@${aws_db_instance.this[0].address}:5432/${var.db_name}"
  ) : ""
  sensitive = true
}

output "database_host" {
  value = var.create_database ? aws_db_instance.this[0].address : ""
}

output "bucket" {
  value = var.create_bucket ? aws_s3_bucket.media[0].bucket : ""
}

output "bucket_arn" {
  value = var.create_bucket ? aws_s3_bucket.media[0].arn : ""
}

output "service_account_annotations" {
  value = var.create_irsa ? {
    "eks.amazonaws.com/role-arn" = aws_iam_role.app[0].arn
  } : {}
}
