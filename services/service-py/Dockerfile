# The first python node in the demo estate, built the way the runtime
# repository's template prescribes: the engine-matched runtime base plus this
# service's contracts and scripts. One image serves every node this service
# declares — the harness selects between them from NODE_ID at run time.
# The tag is the runtime version: CI reads it (scripts/image_pins.py) and
# installs the same continuo-runtime CLI, so the hashes CI writes are the ones
# this image's harness recomputes at start.
FROM ghcr.io/carolsimone/continuo-python-runtime-postgres:v0.12.0
COPY contracts/ /app/contracts/
COPY scripts/ /app/scripts/
# The runtime base already declares USER 65532:65532 — a frozen cross-repo
# contract with continuo's executor-controller, which hard-codes that uid in
# its validation pod spec securityContext. Nothing to set here: the harness
# only reads its baked contracts/scripts and writes solely to the warehouse,
# so no ownership changes are needed on top of the base's default user.
