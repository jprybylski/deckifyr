# Offline mode and python_env (issue #93), unit-level: pyro, processx and the
# CLI are mocked, as in test-run-python.R. The real end-to-end offline proof
# is the last block of test-wiring.R.

# Runs `code` with the given environment variables set (NA unsets) and the
# deckifyr offline/python_env options cleared, restoring everything after.
# Base R only: withr is not a declared dependency of this package.
with_clean_deckifyr_env <- function(code, vars = character(0), opts = list()) {
  all_vars <- c(
    DECKIFYR_OFFLINE = NA, UV_OFFLINE = NA, DECKIFYR_PYTHON_ENV = NA,
    UV_NO_INDEX = NA, UV_PYTHON_DOWNLOADS = NA
  )
  all_vars[names(vars)] <- vars
  old_env <- Sys.getenv(names(all_vars), unset = NA_character_)
  old_opts <- options(deckifyr.offline = NULL, deckifyr.python_env = NULL)
  on.exit({
    options(old_opts)
    for (n in names(old_env)) {
      if (is.na(old_env[[n]])) Sys.unsetenv(n) else do.call(Sys.setenv, as.list(old_env[n]))
    }
  })
  for (n in names(all_vars)) {
    if (is.na(all_vars[[n]])) Sys.unsetenv(n) else do.call(Sys.setenv, as.list(all_vars[n]))
  }
  if (length(opts) > 0) do.call(options, opts)
  code
}

fake_pyro_uv <- function() {
  list(uv = "fake-uv", venv = "fake-venv")
}

test_that(".offline_mode() follows the option, DECKIFYR_OFFLINE and UV_OFFLINE", {
  with_clean_deckifyr_env(expect_false(.offline_mode()))
  with_clean_deckifyr_env(expect_true(.offline_mode()), opts = list(deckifyr.offline = TRUE))
  with_clean_deckifyr_env(expect_true(.offline_mode()), vars = c(DECKIFYR_OFFLINE = "1"))
  with_clean_deckifyr_env(expect_true(.offline_mode()), vars = c(UV_OFFLINE = "true"))
  with_clean_deckifyr_env(expect_false(.offline_mode()), vars = c(UV_OFFLINE = "0"))
  with_clean_deckifyr_env(expect_false(.offline_mode()), opts = list(deckifyr.offline = FALSE))
})

test_that(".with_offline_env() sets the variables for the code and restores them", {
  with_clean_deckifyr_env({
    Sys.setenv(UV_NO_INDEX = "preexisting")
    seen <- .with_offline_env(Sys.getenv(c("UV_OFFLINE", "UV_NO_INDEX", "UV_PYTHON_DOWNLOADS", "DECKIFYR_OFFLINE")))
    expect_equal(
      seen,
      c(UV_OFFLINE = "1", UV_NO_INDEX = "1", UV_PYTHON_DOWNLOADS = "never", DECKIFYR_OFFLINE = "1")
    )
    expect_equal(Sys.getenv("UV_NO_INDEX"), "preexisting")
    expect_equal(Sys.getenv("UV_OFFLINE", unset = "unset"), "unset")
    expect_equal(Sys.getenv("UV_PYTHON_DOWNLOADS", unset = "unset"), "unset")
  }, opts = list(deckifyr.offline = TRUE))
})

test_that(".with_offline_env() restores the variables when the code fails", {
  with_clean_deckifyr_env({
    expect_error(.with_offline_env(stop("boom")), "boom")
    expect_equal(Sys.getenv("UV_OFFLINE", unset = "unset"), "unset")
  }, opts = list(deckifyr.offline = TRUE))
})

test_that(".with_offline_env() changes nothing online", {
  with_clean_deckifyr_env({
    seen <- .with_offline_env(Sys.getenv("UV_OFFLINE", unset = "unset"))
    expect_equal(seen, "unset")
  })
})

test_that("provisioning leaves UV_NO_INDEX alone (uv still needs the index names)", {
  with_clean_deckifyr_env({
    expect_equal(names(.offline_env_vars(provisioning = TRUE)), c("UV_OFFLINE", "DECKIFYR_OFFLINE"))
  }, opts = list(deckifyr.offline = TRUE))
})

test_that("online, the CLI is run exactly as before, with no offline variables", {
  captured <- list()
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = fake_pyro_uv,
    run_python_script = function(uv_path, venv_path, args, script_name, pythonpath,
                                 stderr_callback) {
      captured <<- list(args = args, offline = Sys.getenv("UV_OFFLINE", unset = "unset"))
      list(stdout = "{}")
    },
    .package = "pyro"
  )

  with_clean_deckifyr_env(.run_deckifyr_cli(c("validate", "p.yaml")))

  expect_equal(captured$args, c("run", "-m", "deckifyr", "--json", "validate", "p.yaml"))
  expect_equal(captured$offline, "unset")
})

test_that("offline, the CLI gets --no-sync and the offline variables, then they are restored", {
  captured <- list()
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = fake_pyro_uv,
    run_python_script = function(uv_path, venv_path, args, script_name, pythonpath,
                                 stderr_callback) {
      captured <<- list(
        args = args,
        env = Sys.getenv(c("UV_OFFLINE", "UV_NO_INDEX", "UV_PYTHON_DOWNLOADS", "DECKIFYR_OFFLINE"))
      )
      list(stdout = "{}")
    },
    .package = "pyro"
  )

  for (how in list(
    list(opts = list(deckifyr.offline = TRUE)),
    list(vars = c(DECKIFYR_OFFLINE = "1")),
    list(vars = c(UV_OFFLINE = "1"))
  )) {
    captured <- list()
    with_clean_deckifyr_env({
      .run_deckifyr_cli(c("build", "p.yaml"))
      expect_equal(Sys.getenv("UV_NO_INDEX", unset = "unset"), "unset")
    }, vars = how$vars, opts = how$opts)

    expect_equal(
      captured$args,
      c("run", "--no-sync", "-m", "deckifyr", "--json", "build", "p.yaml")
    )
    expect_equal(
      captured$env,
      c(UV_OFFLINE = "1", UV_NO_INDEX = "1", UV_PYTHON_DOWNLOADS = "never", DECKIFYR_OFFLINE = "1")
    )
  }
})

test_that("an unparseable failure offline carries the offline hint, online it does not", {
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = fake_pyro_uv,
    run_python_script = function(uv_path, venv_path, args, script_name, pythonpath,
                                 stderr_callback) {
      stderr_callback("error: No solution found when resolving dependencies", NULL)
      stop("deckifyr failed.")
    },
    .package = "pyro"
  )

  with_clean_deckifyr_env(
    expect_error(.run_deckifyr_cli(c("build", "p.yaml")), "offline mode is on.*python_env"),
    opts = list(deckifyr.offline = TRUE)
  )
  with_clean_deckifyr_env(
    expect_error(.run_deckifyr_cli(c("build", "p.yaml")), "No solution found")
  )
  msg <- with_clean_deckifyr_env(
    tryCatch(.run_deckifyr_cli(c("build", "p.yaml")), error = conditionMessage)
  )
  expect_false(grepl("offline mode is on", msg))
})

# ---- deck_serve() ---------------------------------------------------------

serve_capture <- function(...) {
  project_dir <- withr_free_tempdir()
  captured <- NULL
  n <- 0L
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(get_venv_uv_paths = fake_pyro_uv, .package = "pyro")
  local_mocked_bindings(socketConnection = function(...) {
    n <<- n + 1L
    if (n == 1L) stop("connection refused")
    textConnection("")
  })
  local_mocked_bindings(
    .launch_server_process = function(uv_path, args, env_vars) {
      captured <<- list(command = uv_path, args = args, env_vars = env_vars)
      structure(list(is_alive = function() TRUE, kill_tree = function() invisible()), class = "fake")
    },
    .wait_for_server = function(...) invisible(TRUE)
  )
  deck_serve(project = project_dir, port = 8322, open_browser = FALSE, ...)
  captured
}

withr_free_tempdir <- function() {
  dir <- tempfile("deckifyr-serve-")
  dir.create(dir)
  dir
}

test_that("deck_serve() launches `uv run` unchanged online", {
  captured <- with_clean_deckifyr_env(serve_capture())
  expect_equal(captured$command, "fake-uv")
  expect_equal(captured$args[1:4], c("run", "-m", "deckifyr", "serve"))
  expect_false(any(c("UV_OFFLINE", "DECKIFYR_OFFLINE") %in% names(captured$env_vars)))
})

test_that("deck_serve() offline adds --no-sync and the offline variables to the server", {
  captured <- with_clean_deckifyr_env(serve_capture(), opts = list(deckifyr.offline = TRUE))
  expect_equal(captured$args[1:5], c("run", "--no-sync", "-m", "deckifyr", "serve"))
  expect_equal(captured$env_vars[["UV_OFFLINE"]], "1")
  expect_equal(captured$env_vars[["UV_NO_INDEX"]], "1")
  expect_equal(captured$env_vars[["UV_PYTHON_DOWNLOADS"]], "never")
  expect_equal(captured$env_vars[["DECKIFYR_OFFLINE"]], "1")
  expect_equal(captured$env_vars[["PYTHONPATH"]], "/fake/python/src")
})

# ---- initialize_deck_project() -------------------------------------------

mock_init_pyro <- function(env = parent.frame()) {
  calls <- new.env()
  calls$group <- NULL
  calls$initialized <- FALSE
  calls$env_during_init <- NULL
  local_mocked_bindings(
    write_group_to_pyproject = function(name, deps) calls$group <- list(name = name, deps = deps),
    initialize_python = function(groups) {
      calls$initialized <- TRUE
      calls$env_during_init <- Sys.getenv(c("UV_OFFLINE", "UV_NO_INDEX"), unset = "unset")
    },
    get_uv_path = function(quiet = FALSE) calls$uv,
    .package = "pyro",
    .env = env
  )
  calls$uv <- "/fake/bin/uv"
  calls
}

test_that("the written dependency group includes the web and preview extras' packages", {
  calls <- mock_init_pyro()
  local_mocked_bindings(.run_deckifyr_cli = function(args) list(created = character(0)))

  with_clean_deckifyr_env(initialize_deck_project("d"))

  expect_equal(calls$group$name, "deckifyr")
  expect_true(all(
    c("python-pptx", "pydantic", "pyyaml", "pillow", "fastapi", "uvicorn", "pymupdf") %in%
      calls$group$deps
  ))
})

test_that("the group's packages cover the web and preview extras in pyproject.toml", {
  skip_if_not(file.exists(test_path("../../pyproject.toml")), "pyproject.toml not available")
  toml <- readLines(test_path("../../pyproject.toml"), warn = FALSE)
  # The package names listed under `<name> = [ ... ]` in [project.optional-dependencies].
  extras <- function(name) {
    start <- grep(paste0("^", name, " = \\["), toml)
    stopifnot(length(start) == 1)
    rest <- toml[(start + 1):length(toml)]
    block <- rest[seq_len(which(grepl("^\\]", rest))[1] - 1)]
    block <- block[grepl('^\\s*"', block)]
    sub('^\\s*"([A-Za-z0-9_.-]+).*', "\\1", block)
  }
  expect_gt(length(extras("web")), 0)
  expect_gt(length(extras("preview")), 0)
  group <- sub("[<>=!~].*", "", .deckifyr_group_deps())
  expect_true(all(extras("web") %in% group))
  expect_true(all(extras("preview") %in% group))
})

test_that("offline, initialization runs with UV_OFFLINE set but not UV_NO_INDEX", {
  calls <- mock_init_pyro()
  local_mocked_bindings(.run_deckifyr_cli = function(args) list(created = character(0)))

  with_clean_deckifyr_env(initialize_deck_project("d"), opts = list(deckifyr.offline = TRUE))

  expect_true(calls$initialized)
  expect_equal(calls$env_during_init, c(UV_OFFLINE = "1", UV_NO_INDEX = "unset"))
  expect_equal(Sys.getenv("UV_OFFLINE", unset = "unset"), "unset")
})

test_that("offline, from_repo is refused before pyro or the CLI is touched", {
  calls <- mock_init_pyro()
  local_mocked_bindings(.run_deckifyr_cli = function(args) stop("the CLI must not run"))

  with_clean_deckifyr_env(
    expect_error(
      initialize_deck_project("d", from_repo = "acme/decks"),
      class = "deckifyr_offline_failure"
    ),
    vars = c(UV_OFFLINE = "1")
  )
  expect_null(calls$group)
  expect_false(calls$initialized)
})

test_that("offline, from_repo's message points at from_dir", {
  mock_init_pyro()
  with_clean_deckifyr_env(
    expect_error(
      initialize_deck_project("d", from_repo = "acme/decks"),
      "from_dir"
    ),
    opts = list(deckifyr.offline = TRUE)
  )
})

test_that("online, from_repo is passed through as before", {
  mock_init_pyro()
  captured <- NULL
  local_mocked_bindings(.run_deckifyr_cli = function(args) {
    captured <<- args
    list(created = character(0))
  })
  with_clean_deckifyr_env(initialize_deck_project("d", from_repo = "acme/decks"))
  expect_equal(captured, c("init", "d", "--from-repo", "acme/decks"))
})

test_that("offline, from_dir is still allowed", {
  mock_init_pyro()
  captured <- NULL
  local_mocked_bindings(.run_deckifyr_cli = function(args) {
    captured <<- args
    list(created = character(0))
  })
  with_clean_deckifyr_env(
    initialize_deck_project("d", from_dir = "tmpl"),
    opts = list(deckifyr.offline = TRUE)
  )
  expect_equal(captured, c("init", "d", "--from-dir", "tmpl"))
})

test_that("offline with uv missing stops before pyro would download it", {
  calls <- mock_init_pyro()
  calls$uv <- NULL
  local_mocked_bindings(.run_deckifyr_cli = function(args) stop("the CLI must not run"))

  with_clean_deckifyr_env(
    expect_error(initialize_deck_project("d"), class = "deckifyr_offline_failure"),
    opts = list(deckifyr.offline = TRUE)
  )
  expect_false(calls$initialized)
  expect_null(calls$group)
})

# ---- python_env -----------------------------------------------------------

# A fake "environment": a directory whose bin/python is a script that reports
# the modules named in FAKE_MISSING as missing for the import probe, and
# otherwise echoes a JSON success line for the CLI.
make_fake_env <- function(missing = "") {
  skip_on_os("windows")
  env <- tempfile("fake-env-")
  dir.create(file.path(env, "bin"), recursive = TRUE)
  python <- file.path(env, "bin", "python")
  writeLines(c(
    "#!/bin/sh",
    'if [ "$1" = "-c" ]; then',
    sprintf("  echo '%s'", missing),
    "  exit 0",
    "fi",
    'echo "{\\"status\\": \\"ok\\", \\"argv\\": \\"$*\\", \\"pythonpath\\": \\"$PYTHONPATH\\"}"'
  ), python)
  Sys.chmod(python, "0755")
  env
}

test_that(".python_exe() finds a venv's interpreter or a project's .venv", {
  skip_on_os("windows")
  env <- make_fake_env()
  expect_equal(.python_exe(env), file.path(env, "bin", "python"))

  project <- tempfile("proj-")
  dir.create(project)
  file.copy(env, file.path(project), recursive = TRUE)
  file.rename(file.path(project, basename(env)), file.path(project, ".venv"))
  expect_equal(.python_exe(project), file.path(project, ".venv", "bin", "python"))

  expect_error(.python_exe(tempdir()), class = "deckifyr_python_env_invalid")
})

test_that(".verify_python_env() returns the interpreter, or names the missing modules", {
  env <- make_fake_env()
  expect_equal(.verify_python_env(env), file.path(env, "bin", "python"))

  broken <- make_fake_env(missing = "yaml,PIL")
  expect_error(.verify_python_env(broken), class = "deckifyr_python_env_invalid")
  expect_error(.verify_python_env(broken), "pyyaml")
  expect_error(.verify_python_env(broken), "pillow")
})

test_that(".configured_python_env() prefers the argument, then option, then env var", {
  with_clean_deckifyr_env({
    expect_null(.configured_python_env())
    expect_equal(.configured_python_env("arg"), "arg")
  })
  with_clean_deckifyr_env(expect_equal(.configured_python_env(), "opt"), opts = list(deckifyr.python_env = "opt"))
  with_clean_deckifyr_env(expect_equal(.configured_python_env(), "envvar"), vars = c(DECKIFYR_PYTHON_ENV = "envvar"))
  with_clean_deckifyr_env(
    expect_equal(.configured_python_env(), "opt"),
    vars = c(DECKIFYR_PYTHON_ENV = "envvar"), opts = list(deckifyr.python_env = "opt")
  )
})

test_that("with a python_env, the CLI runs that interpreter and never touches pyro/uv", {
  skip_on_os("windows")
  env <- make_fake_env()
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = function() stop("pyro must not be used"),
    run_python_script = function(...) stop("uv must not be used"),
    .package = "pyro"
  )

  result <- with_clean_deckifyr_env(
    .run_deckifyr_cli(c("validate", "p.yaml")),
    opts = list(deckifyr.python_env = env)
  )

  expect_equal(result$status, "ok")
  expect_equal(result$argv, "-m deckifyr --json validate p.yaml")
  expect_match(result$pythonpath, "^/fake/python/src")
})

test_that("a python_env failure still surfaces the CLI's structured error", {
  skip_on_os("windows")
  env <- tempfile("fake-env-")
  dir.create(file.path(env, "bin"), recursive = TRUE)
  python <- file.path(env, "bin", "python")
  writeLines(c(
    "#!/bin/sh",
    'echo "{\\"status\\": \\"error\\", \\"code\\": \\"E_SCHEMA_VALIDATION\\", \\"message\\": \\"bad field\\"}" >&2',
    "exit 2"
  ), python)
  Sys.chmod(python, "0755")
  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")

  with_clean_deckifyr_env(
    expect_error(
      .run_deckifyr_cli(c("validate", "p.yaml")),
      "E_SCHEMA_VALIDATION.*bad field"
    ),
    opts = list(deckifyr.python_env = env)
  )
})

test_that("deck_serve() with a python_env launches the interpreter, not uv", {
  skip_on_os("windows")
  env <- make_fake_env()
  captured <- with_clean_deckifyr_env(
    serve_capture(),
    opts = list(deckifyr.python_env = env)
  )
  expect_equal(captured$command, file.path(env, "bin", "python"))
  expect_equal(captured$args[1:3], c("-m", "deckifyr", "serve"))
  expect_false("VIRTUAL_ENV" %in% names(captured$env_vars))
  expect_equal(captured$env_vars[["PYTHONPATH"]], "/fake/python/src")
})

test_that("initialize_deck_project(python_env=) verifies it and skips pyro entirely", {
  skip_on_os("windows")
  env <- make_fake_env()
  local_mocked_bindings(
    write_group_to_pyproject = function(...) stop("pyproject.toml must not be touched"),
    initialize_python = function(...) stop("pyro must not provision"),
    .package = "pyro"
  )
  captured <- NULL
  local_mocked_bindings(.run_deckifyr_cli = function(args) {
    captured <<- list(args = args, env = getOption("deckifyr.python_env"))
    list(created = character(0))
  })

  with_clean_deckifyr_env(
    suppressMessages(initialize_deck_project("d", from_dir = "tmpl", python_env = env))
  )

  expect_equal(captured$args, c("init", "d", "--from-dir", "tmpl"))
  expect_equal(captured$env, env) # visible to the CLI call...
  expect_null(getOption("deckifyr.python_env")) # ...and put back afterwards
})

test_that("initialize_deck_project(python_env=) refuses an environment missing modules", {
  env <- make_fake_env(missing = "pptx")
  local_mocked_bindings(
    write_group_to_pyproject = function(...) stop("pyproject.toml must not be touched"),
    .package = "pyro"
  )
  with_clean_deckifyr_env(
    expect_error(
      initialize_deck_project("d", python_env = env),
      class = "deckifyr_python_env_invalid"
    )
  )
})
