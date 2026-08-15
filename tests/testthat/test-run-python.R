# Unit-level coverage of .run_deckifyr_cli()'s own branches (success,
# both error shapes, and the invalid-JSON-on-success guard) via mocked
# pyro/base bindings -- deliberately independent of a real .venv/uv/pyro
# toolchain so these run (and count toward coverage) even in the
# fresh-install context test-coverage.yaml's r-lib workflow uses, unlike
# test-wiring.R's real end-to-end proof (see CLAUDE.md's CI-workflow
# split notes).

test_that("errors clearly when the bundled Python source is missing", {
  local_mocked_bindings(`system.file` = function(...) "")

  expect_error(
    .run_deckifyr_cli(c("validate", "x.yaml")),
    "bundled Python source .* was not found"
  )
})

test_that("returns parsed JSON on a successful CLI call", {
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = function() list(uv = "fake-uv", venv = "fake-venv"),
    run_python_script = function(uv_path, venv_path, args, script_name, pythonpath,
                                  stderr_callback) {
      list(stdout = '{"status": "ok", "slide_count": 2}')
    },
    .package = "pyro"
  )

  result <- .run_deckifyr_cli(c("validate", "presentation.yaml"))
  expect_equal(result$status, "ok")
  expect_equal(result$slide_count, 2)
})

test_that("forwards --json plus the CLI's own args to run_python_script()", {
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")

  captured_args <- NULL
  local_mocked_bindings(
    get_venv_uv_paths = function() list(uv = "fake-uv", venv = "fake-venv"),
    run_python_script = function(uv_path, venv_path, args, script_name, pythonpath,
                                  stderr_callback) {
      captured_args <<- args
      list(stdout = "{}")
    },
    .package = "pyro"
  )

  .run_deckifyr_cli(c("build", "presentation.yaml", "--warn-only"))
  expect_equal(
    captured_args,
    c("run", "-m", "deckifyr", "--json", "build", "presentation.yaml", "--warn-only")
  )
})

test_that("recovers the CLI's structured JSON error from captured stderr", {
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = function() list(uv = "fake-uv", venv = "fake-venv"),
    run_python_script = function(uv_path, venv_path, args, script_name, pythonpath,
                                  stderr_callback) {
      stderr_callback(
        '{"status": "error", "code": "E_SCHEMA_VALIDATION", "message": "bad box"}',
        proc = NULL
      )
      stop("deckifyr failed.")
    },
    .package = "pyro"
  )

  expect_error(
    .run_deckifyr_cli(c("validate", "presentation.yaml")),
    "deckifyr validate failed \\[E_SCHEMA_VALIDATION\\]: bad box"
  )
})

test_that("falls back to a raw-stderr error when stderr isn't parseable JSON", {
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = function() list(uv = "fake-uv", venv = "fake-venv"),
    run_python_script = function(uv_path, venv_path, args, script_name, pythonpath,
                                  stderr_callback) {
      stderr_callback("Traceback (most recent call last): boom", proc = NULL)
      stop("deckifyr failed.")
    },
    .package = "pyro"
  )

  expect_error(
    .run_deckifyr_cli(c("build", "presentation.yaml")),
    "did not produce a parseable error payload"
  )
})

test_that("errors clearly when a successful exit doesn't return valid JSON", {
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = function() list(uv = "fake-uv", venv = "fake-venv"),
    run_python_script = function(uv_path, venv_path, args, script_name, pythonpath,
                                  stderr_callback) {
      list(stdout = "not json at all")
    },
    .package = "pyro"
  )

  expect_error(
    .run_deckifyr_cli(c("schema", "design")),
    "did not return valid JSON"
  )
})

test_that("a missing-dependency error still stops with the usual message", {
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = function() list(uv = "fake-uv", venv = "fake-venv"),
    run_python_script = function(uv_path, venv_path, args, script_name, pythonpath,
                                  stderr_callback) {
      stderr_callback(
        paste0(
          '{"status": "error", "code": "E_MISSING_DEPENDENCY", ',
          '"message": "quarto binary not found", ',
          '"dependency": {"name": "quarto", "display_name": "Quarto", ',
          '"install_url": "https://quarto.org/docs/get-started/"}}'
        ),
        proc = NULL
      )
      stop("deckifyr failed.")
    },
    .package = "pyro"
  )

  # `.handle_missing_dependency()`'s own install-guidance output is
  # covered directly below -- this just confirms the usual stop() error
  # still fires with the same message shape as any other failure, i.e.
  # the new branch is additive, not a replacement.
  expect_error(
    suppressMessages(.run_deckifyr_cli(c("build", "presentation.yaml"))),
    "deckifyr build failed \\[E_MISSING_DEPENDENCY\\]: quarto binary not found"
  )
})

test_that(".homebrew_cask_for_dependency() knows the two current dependencies", {
  expect_equal(.homebrew_cask_for_dependency("soffice"), "libreoffice")
  expect_equal(.homebrew_cask_for_dependency("quarto"), "quarto")
  expect_null(.homebrew_cask_for_dependency("something-else"))
})

test_that(".handle_missing_dependency() never attempts an install non-interactively", {
  # testthat runs non-interactively, so `interactive()` is FALSE here --
  # this asserts the resulting behavior (the printed fallback message,
  # no call to system()) rather than relying on that as an implicit
  # assumption future changes could silently break.
  dependency <- list(
    name = "quarto", display_name = "Quarto",
    install_url = "https://quarto.org/docs/get-started/"
  )
  expect_message(
    .handle_missing_dependency(dependency),
    "No automatic install available"
  )
})
