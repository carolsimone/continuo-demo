# An ML python node, built exactly like service-py: the engine-matched runtime
# base plus this service's contracts and scripts. The only addition is the model
# library, layered on the way the runtime template prescribes — switch to root
# for the pip install, then back to uid 65532 (a frozen contract with
# executor-controller's validation pod securityContext).
FROM ghcr.io/carolsimone/continuo-python-runtime-postgres:v0.4.0
COPY contracts/ /app/contracts/
COPY scripts/ /app/scripts/
# xgboost-cpu, not xgboost: the plain wheel declares an ~250MB nvidia-nccl GPU
# dependency this CPU node never uses. The script uses the native train/DMatrix
# API, so no scikit-learn is needed either.
USER root
RUN pip install --no-cache-dir "xgboost-cpu==3.4.1"
USER 65532:65532
