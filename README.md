# Hazel

Hazel is an [Arches](https://www.archesproject.org/) 8.2 project, run locally and
built for Kubernetes with the
[Arches F&T Container Toolkit](https://github.com/flaxandteal/arches-container-toolkit)
(the `docker/` submodule, branch `arches/8.2`).

| | |
|---|---|
| Arches | `8.2.0a25` (pinned in `pyproject.toml` to match the base image) |
| Base image | `ghcr.io/flaxandteal/arches-base:v8.2.0a25-v1` (`ARCHES_BASE` in `Makefile`) |
| Django project | `hazel` (the `hazel/` package next to `manage.py`) |
| Deployment | [`hazel-fluxcd`](https://github.com/flaxandteal/hazel-fluxcd), `heritwin-{1..5}.f-a-t.link` |

## Running Hazel locally

You need Docker with the Compose plugin, `git` and `make`, on Linux. Elasticsearch
refuses to start when the disk is more than 90% full, so keep at least 10% free.

```sh
git clone --recurse-submodules git@github.com:flaxandteal-arches/hazel.git
cd hazel
make build    # npm install, Arches bootstrap, webpack build
make run      # http://localhost:8000
```

**`make build` wipes the local Postgres database.** Run it once, and again only when
you want a clean database. After that, use `make run`, or `make webpack` for a
frontend rebuild.

If you cloned without `--recurse-submodules`, run `git submodule update --init` first.

Local settings go in `docker/.env`, which is gitignored inside the submodule. The
compose file loads it into every Arches container, and it may be absent. For
example:

```sh
MAPBOX_API_KEY=...
```

Ports: Arches on `8000`, API on `8001`, Postgres on `5432`, Elasticsearch on
`9200`, Cantaloupe on `8182`.

### Common commands

```sh
make manage CMD="createsuperuser"           # any manage.py command
make manage CMD="packages -o load_package -s /web_root/hazel/pkg -y"
make docker-compose CMD="logs -f arches"    # any docker compose command
make install-app URL=https://github.com/... [BRANCH=...]
make down                                   # stop the containers
make clean                                  # remove containers AND all their data
make help
```

`/web_root/hazel` is this repository, mounted into the containers. To work against
an editable Arches checkout, clone it to `../arches` and the Makefile mounts it
too (`docker-compose.volumes.yml`).

## Images and CI

`.github/workflows/project.yml` (from the toolkit's `project.yml`) runs on every
push, on the org's `self-hosted` runners. It builds and pushes:

| Image | Contents |
|---|---|
| `ghcr.io/flaxandteal-arches/hazel` | Django app (`docker/Dockerfile`) |
| `ghcr.io/flaxandteal-arches/hazel_static` | nginx with the built frontend and collected static files |
| `ghcr.io/flaxandteal-arches/hazel_static_py` | the app image with the built frontend, for the Arches `http`/`worker` pods |

The tags are `<branch>-<run id>`, e.g. `main-19346512345`, and Cypress runs against
the result. `hazel-fluxcd` refers to these images. A generic `arches-base` image
cannot stand in for this project: its entrypoint creates an empty
`/web_root/<project>` directory and then runs `startproject`, which fails.

`.github/workflows/main.yml` is Arches' own project CI from `startproject`. It
runs on pull requests only.

## Upgrading Arches

1. Ask whoever publishes `arches-base` for the new tag, and check that it exists:
   `docker manifest inspect ghcr.io/flaxandteal/arches-base:<tag>`.
2. Set `ARCHES_BASE` in `Makefile` and `.github/workflows/project.yml`.
3. Set the `arches==` pin in `pyproject.toml` to the Arches version in that image
   (`docker run --rm --entrypoint /web_root/ENV/bin/pip <image> show arches`).
4. Update the submodule if the toolkit has changed: `git submodule update --remote docker`.
5. Rebuild locally with `make build`, and run `make manage CMD=migrate` against
   any database you want to keep.

## Setting up a new Arches repository like this one

This is how this repository was created, for the next project.
Replace `hazel` with the new project name, which must be a valid Python
identifier and must not match an existing module (`test`, `arches`, ...).

```sh
BASE=ghcr.io/flaxandteal/arches-base:v8.2.0a25-v1
docker pull $BASE

# 1. Generate the project with the Arches inside the base image. Run this from
#    the parent directory, and make sure ./hazel does not exist yet.
#    The npm install at the end fails, because the image has no ssh;
#    make build runs it again.
docker run --rm -v "$PWD":/local_root -w /local_root --entrypoint /bin/bash $BASE \
  -c ". /web_root/ENV/bin/activate && arches-admin startproject hazel && chown -R $(id -u):$(id -g) hazel"
cd hazel && rm -f arches.log

# 2. Toolkit submodule and Makefile
git init -b main
git submodule add -b arches/8.2 https://github.com/flaxandteal/arches-container-toolkit docker
cp -f docker/Makefile Makefile
#    then set ARCHES_BASE = $BASE in Makefile

# 3. Pin Arches to the image's version in pyproject.toml: "arches==8.2.0a25"

# 4. CI workflow and Cypress tests
make create-github-action
#    then in .github/workflows/project.yml:
#      - Build-Arches `context: .` -> `context: ..`, because docker/Dockerfile
#        copies <project>/... relative to the checkout's parent directory
#      - INSTALL_CORAL_PACKAGE "True" -> "False"

# 5. DEBUG static serving in hazel/urls.py
make update-urls-debug
#    check the regex ends in `.*)$'`: on arches/8.2 the toolkit Makefile has
#    `$'` where it needs `$$'`, which drops the `$'` (fixed in this repo's Makefile)

# 6. Add ENV/ and the Cypress artifact folders to .gitignore, then commit and
#    create the GitHub repo
gh repo create flaxandteal-arches/hazel --private --source . --push
```

Then add the images to the Flux repository, using `hazel_static_py` for the
Arches image and `hazel_static` for the static image, with `archesProject: hazel`.

## Licence

AGPL-3.0, as Arches (see `LICENSE`).
