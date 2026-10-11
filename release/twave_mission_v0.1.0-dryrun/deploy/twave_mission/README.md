# T-Wave dry-run deployment

This deployment is dry-run only: it starts the coordinator and FakeUSVExecutor
and has no hardware-control topics. Run `scripts/check_environment.sh`, then
`scripts/build.sh`, then `scripts/start_dry_run.sh`. State defaults to
`$HOME/.local/state/twave-mission`; override it with `TWAVE_MISSION_STATE_DIR`.

Do not delete `checkpoint.safety-stop.json` to recover from SAFE_STOP. Inspect
it, correct the real cause, and use only the isolated test reset procedure.
