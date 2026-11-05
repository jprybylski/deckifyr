# Unit coverage of the trust-policy arguments (issue #89): R only assembles
# CLI flags and type-checks them; what the flags *mean* (and the
# E_UNTRUSTED_BINARY / E_PATH_OUTSIDE_PROJECT errors) is the Python engine's
# job (deckifyr.policy) and is tested there. Mocked like test-build.R /
# test-validate.R -- see test-run-python.R's header comment for why.

capture_cli_args <- function() {
  captured <- new.env()
  captured$args <- NULL
  list(
    env = captured,
    fn = function(args) {
      captured$args <- args
      list(status = "ok")
    }
  )
}

test_that(".trust_args() is empty by default, so existing calls are unchanged", {
  expect_identical(.trust_args(), character())
})

test_that(".trust_args() maps every argument to its CLI flag, in a fixed order", {
  expect_equal(
    .trust_args(
      rscript_bin = "/opt/R/bin/Rscript",
      quarto_bin = "/opt/quarto",
      soffice_bin = "/opt/soffice",
      trusted_binaries_only = TRUE,
      allow_outside_project = TRUE
    ),
    c(
      "--rscript-bin", "/opt/R/bin/Rscript",
      "--quarto-bin", "/opt/quarto",
      "--soffice-bin", "/opt/soffice",
      "--trusted-binaries-only", "--allow-outside-project"
    )
  )
})

test_that(".trust_args() rejects arguments of the wrong type before anything is run", {
  expect_error(.trust_args(quarto_bin = c("a", "b")), "single path string")
  expect_error(.trust_args(soffice_bin = ""), "single path string")
  expect_error(.trust_args(rscript_bin = 1), "single path string")
  expect_error(.trust_args(trusted_binaries_only = "yes"), "single TRUE or FALSE")
  expect_error(.trust_args(allow_outside_project = NA), "single TRUE or FALSE")
})

test_that("deck_build() forwards the trust policy after its own flags", {
  cap <- capture_cli_args()
  local_mocked_bindings(.run_deckifyr_cli = cap$fn)

  deck_build("p.yaml", strict = FALSE, quarto_bin = "/q", trusted_binaries_only = TRUE)

  expect_equal(
    cap$env$args,
    c("build", "p.yaml", "--warn-only", "--quarto-bin", "/q", "--trusted-binaries-only")
  )
})

test_that("deck_validate() forwards the trust policy", {
  cap <- capture_cli_args()
  local_mocked_bindings(.run_deckifyr_cli = cap$fn)

  deck_validate("p.yaml", rscript_bin = "/r", allow_outside_project = TRUE)

  expect_equal(
    cap$env$args,
    c("validate", "p.yaml", "--rscript-bin", "/r", "--allow-outside-project")
  )
})

test_that("deck_preview() and deck_inspect() forward the trust policy", {
  cap <- capture_cli_args()
  local_mocked_bindings(.run_deckifyr_cli = cap$fn)

  deck_preview("p.yaml", soffice_bin = "/s", trusted_binaries_only = TRUE)
  expect_equal(
    cap$env$args,
    c("preview", "p.yaml", "--soffice-bin", "/s", "--trusted-binaries-only")
  )

  deck_inspect("p.yaml", quarto_bin = "/q")
  expect_equal(cap$env$args, c("inspect", "p.yaml", "--quarto-bin", "/q"))
})

test_that("a malformed trust argument fails before the CLI is ever called", {
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) stop("the CLI must not be reached")
  )
  expect_error(deck_build("p.yaml", quarto_bin = 42), "single path string")
  expect_error(deck_validate("p.yaml", trusted_binaries_only = "x"), "single TRUE or FALSE")
})
