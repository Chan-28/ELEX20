args <- commandArgs(trailingOnly = TRUE)
project_root <- if (length(args) >= 1) {
  normalizePath(args[[1]], winslash = "/", mustWork = FALSE)
} else {
  normalizePath(file.path(getwd()), winslash = "/", mustWork = FALSE)
}

lib_dir <- file.path(project_root, "R-Portable", "library")
dir.create(lib_dir, recursive = TRUE, showWarnings = FALSE)

.libPaths(c(lib_dir, .libPaths()))
options(install.packages.compile.from.source = "never")
options(repos = c(CRAN = "https://cran.rstudio.com/"))

required <- c("ggplot2", "dplyr", "tidyr", "scales", "GGally")
installed <- rownames(installed.packages(lib.loc = .libPaths()))
missing <- setdiff(required, installed)

if (length(missing) > 0) {
  cat("Instalando pacotes R faltantes em:", lib_dir, "\n")
  install.packages(missing, lib = lib_dir, dependencies = TRUE, type = "binary")
} else {
  cat("Pacotes R ja estao instalados em biblioteca local.\n")
}

cat("Bibliotecas ativas do R:\n")
print(.libPaths())
cat("Concluido.\n")
