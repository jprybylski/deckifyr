# Adds a2-ai.r-universe.dev (pyro's home -- it isn't on CRAN) to the
# effective repos list for any R session started from the repo root,
# including CI's `Rscript {0}` steps.
#
# This is the *actual* fix for pyro dependency resolution -- confirmed
# the hard way. DESCRIPTION's `Additional_repositories:` field looks
# like the right mechanism (it's what CRAN policy and tools like
# `remotes::install_deps()` use for exactly this case) and is kept there
# for those tools, but it does NOT make `pak`'s `deps::.` local solve
# see the repo: verified in a clean sandbox (empty lib path, so pak
# can't cheat by finding an already-installed pyro) that lockfile
# creation still fails with Additional_repositories alone, and succeeds
# once `options(repos=)` includes this URL directly, which only happens
# via something like this .Rprofile (or an explicit `options()` call) --
# see CLAUDE.md's architecture notes before changing this.
options(repos = c(a2ai = "https://a2-ai.r-universe.dev", getOption("repos")))
