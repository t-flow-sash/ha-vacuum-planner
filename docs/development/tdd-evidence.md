# TDD Evidence

## 2026-09-19 – Findings 1–2: offizieller CLEAN_AREA-Vertrag / HA-Mindestversion / Area-Selector

**RED**

```text
$ .venv/bin/pytest -q tests/test_config_flow.py::test_supported_vacuum_advances_to_multiple_area_selector tests/test_integration_contract.py::test_hacs_metadata_identifies_an_integration_repository
FF [100%]
E AssertionError: {'multiple': True, 'reorder': True} == {'multiple': True}
E KeyError: 'homeassistant'
2 failed in 0.16s
```

Die vorhandenen Adapter-Vertragstests verwenden nun den offiziellen Wert `CLEAN_AREA=16384` und prüfen weiterhin `cleaning_area_id`.

**GREEN**

```text
$ .venv/bin/pytest -q tests/test_config_flow.py::test_supported_vacuum_advances_to_multiple_area_selector tests/test_integration_contract.py::test_hacs_metadata_identifies_an_integration_repository tests/test_native_area_adapter.py
.......... [100%]
10 passed in 0.15s
```

## 2026-09-19 – Finding 3: Dry-run-Sicherheitsgrenze

**RED**

```text
$ .venv/bin/pytest -q tests/test_config_flow.py::test_options_ui_warns_that_disabling_dry_run_enables_vacuum_commands tests/test_config_flow.py::test_options_flow_allows_explicit_dry_run_disable tests/test_integration_lifecycle.py::test_start_next_action_seals_due_work_idempotently_without_hardware_calls
F.. [100%]
E AssertionError: assert 'disabling dry run' in 'configure planner behavior. dry run is enabled by default and prevents control of the vacuum.'
1 failed, 2 passed in 0.21s
```

**GREEN**

```text
$ .venv/bin/pytest -q tests/test_config_flow.py::test_options_ui_warns_that_disabling_dry_run_enables_vacuum_commands tests/test_config_flow.py::test_options_flow_allows_explicit_dry_run_disable tests/test_integration_lifecycle.py::test_start_next_action_seals_due_work_idempotently_without_hardware_calls
... [100%]
3 passed in 0.20s
```

## 2026-09-19 – Finding 6: Response-, Button-, Cancel- und Runtime-Schema-Vertrag

**RED**

```text
$ .venv/bin/pytest -q tests/test_public_actions.py::test_all_public_actions_are_registered_with_explicit_entry_schemas tests/test_public_platforms.py::test_cancel_button_does_not_target_committed_external_work
FF [100%]
E AssertionError: assert 'only' == 'optional'
E AssertionError: cancel button called cancel_block for COMMITTED work
2 failed in 0.13s
```

**GREEN**

```text
$ .venv/bin/pytest -q tests/test_public_actions.py::test_all_public_actions_are_registered_with_explicit_entry_schemas tests/test_public_platforms.py::test_cancel_button_does_not_target_committed_external_work
.. [100%]
2 passed in 0.11s
```

## 2026-09-19 – Finding 5a: normierte Vacuum-Beobachtungen

**RED**

```text
$ .venv/bin/pytest -q tests/test_observer.py
E ModuleNotFoundError: No module named 'custom_components.vacuum_planner.adapters.observation'
1 error in 0.17s
```

This file records the focused RED → GREEN runs used for the three audit-confirmed fixes. The excerpts below are copied from the actual local `pytest` runs in `.venv`; they are intentionally limited to the relevant result and failure lines.

## 1. Native-area preflight boundary and strict capability typing

### Slice 1a — invalid capability values

RED command:

```console
$ .venv/bin/python -m pytest tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service -vv
collected 5 items

tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[negative] FAILED [ 20%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[bool] PASSED [ 40%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[string] PASSED [ 60%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[float] PASSED [ 80%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[object] PASSED [100%]

E       Failed: DID NOT RAISE <class 'ValueError'>

========================= 1 failed, 4 passed in 0.12s ==========================
```

GREEN command:

```console
$ .venv/bin/python -m pytest tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service -vv
collected 5 items

tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[negative] PASSED [ 20%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[bool] PASSED [ 40%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[string] PASSED [ 60%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[float] PASSED [ 80%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[object] PASSED [100%]

============================== 5 passed in 0.11s ===============================
```

### Slice 1b — safe preflight failure remains retryable

RED command:

```console
$ .venv/bin/python -m pytest tests/test_integration_lifecycle.py::test_live_dispatch_preflight_failure_keeps_sealed_block_retryable -vv
collected 1 item

tests/test_integration_lifecycle.py::test_live_dispatch_preflight_failure_keeps_sealed_block_retryable FAILED [100%]

E       AssertionError: Regex pattern did not match.
E        Regex: 'preflight'
E        Input: 'Native area dispatch failed'

============================== 1 failed in 0.22s ===============================
```

GREEN command (including the existing ambiguous-after-call regression and adapter tests):

```console
$ .venv/bin/python -m pytest tests/test_integration_lifecycle.py::test_live_dispatch_preflight_failure_keeps_sealed_block_retryable tests/test_integration_lifecycle.py::test_live_dispatch_exception_after_side_effect_is_quarantined_as_uncertain tests/test_native_area_adapter.py -vv
collected 10 items

tests/test_integration_lifecycle.py::test_live_dispatch_preflight_failure_keeps_sealed_block_retryable PASSED [ 10%]
tests/test_integration_lifecycle.py::test_live_dispatch_exception_after_side_effect_is_quarantined_as_uncertain PASSED [ 20%]
tests/test_native_area_adapter.py::test_native_area_adapter_dispatches_ordered_ha_area_ids PASSED [ 30%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_unavailable_vacuum_before_dispatch PASSED [ 40%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_missing_clean_area_capability PASSED [ 50%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[negative] PASSED [ 60%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[bool] PASSED [ 70%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[string] PASSED [ 80%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[float] PASSED [ 90%]
tests/test_native_area_adapter.py::test_native_area_adapter_rejects_non_capability_values_without_calling_service[object] PASSED [100%]

============================== 10 passed in 0.18s ==============================
```

## 2. Coordinator listener isolation

RED command:

```console
$ .venv/bin/python -m pytest tests/test_coordinator.py::test_listener_failure_is_logged_without_failing_persisted_command -vv
collected 1 item

tests/test_coordinator.py::test_listener_failure_is_logged_without_failing_persisted_command FAILED [100%]

custom_components/vacuum_planner/coordinator.py:56: in async_command
    listener()
E       RuntimeError: listener exploded

============================== 1 failed in 0.15s ===============================
```

GREEN command:

```console
$ .venv/bin/python -m pytest tests/test_coordinator.py::test_listener_failure_is_logged_without_failing_persisted_command -vv
collected 1 item

tests/test_coordinator.py::test_listener_failure_is_logged_without_failing_persisted_command PASSED [100%]

============================== 1 passed in 0.11s ===============================
```

## 3. Sealed-block recovery before current due planning

RED command:

```console
$ .venv/bin/python -m pytest tests/test_integration_lifecycle.py::test_start_next_reuses_persisted_sealed_native_batch_after_restart -vv
collected 1 item

tests/test_integration_lifecycle.py::test_start_next_reuses_persisted_sealed_native_batch_after_restart FAILED [100%]

custom_components/vacuum_planner/__init__.py:201: ValueError
E           ValueError: Configured vacuum has no Home Assistant area mapping

============================== 1 failed in 0.22s ===============================
```

GREEN command:

```console
$ .venv/bin/python -m pytest tests/test_integration_lifecycle.py::test_start_next_reuses_persisted_sealed_native_batch_after_restart -vv
collected 1 item

tests/test_integration_lifecycle.py::test_start_next_reuses_persisted_sealed_native_batch_after_restart PASSED [100%]

============================== 1 passed in 0.17s ===============================
```

After refactoring the preflight/claim boundary, the focused recovery, ambiguity, retryability, and concurrency regressions remained green:

```console
$ .venv/bin/python -m pytest tests/test_integration_lifecycle.py::test_live_dispatch_preflight_failure_keeps_sealed_block_retryable tests/test_integration_lifecycle.py::test_live_dispatch_exception_after_side_effect_is_quarantined_as_uncertain tests/test_integration_lifecycle.py::test_parallel_start_next_claims_native_batch_once tests/test_integration_lifecycle.py::test_start_next_reuses_persisted_sealed_native_batch_after_restart -vv
collected 4 items

tests/test_integration_lifecycle.py::test_live_dispatch_preflight_failure_keeps_sealed_block_retryable PASSED [ 25%]
tests/test_integration_lifecycle.py::test_live_dispatch_exception_after_side_effect_is_quarantined_as_uncertain PASSED [ 50%]
tests/test_integration_lifecycle.py::test_parallel_start_next_claims_native_batch_once PASSED [ 75%]
tests/test_integration_lifecycle.py::test_start_next_reuses_persisted_sealed_native_batch_after_restart PASSED [100%]

============================== 4 passed in 0.17s ===============================
```

## 5. Allowlisted diagnostics and basic Repairs contracts

RED (07:55:52, diagnostics allowlist, stable issue identity, store classification,
and fix-flow direction before the modules existed):

```console
collecting ... collected 4 items
```

That invocation is recorded as `terminal ERROR`. After the minimal diagnostics,
Repairs, and schema-version implementation, its paired run at 07:56:51 is recorded
as GREEN for the same four collected tests.

## 6. Repairs lifecycle reconciliation

RED (07:59:22, the focused lifecycle selection after strict topology validation was
connected):

```console
collecting ... collected 7 items / 4 deselected / 3 selected
```

The tool result is recorded as `terminal ERROR`. After realistic vacuum feature and
registry stubs were installed, the same three-test selection is preserved as GREEN:

```console
... [100%]
3 passed in 0.11s
```

The translation contract then independently went RED at 08:00:38 with one collected
test before the new Repairs keys were added. The completed combined
Diagnostics/Repairs module now verifies as:

```console
$ .venv/bin/python -m pytest tests/test_diagnostics_repairs.py -q
......... [100%]
9 passed in 0.12s
```

## 7. Public entity/action slice closure

The first complete run available for this closure exposed the stale contracts and
hermetic setup gaps (including the absent Area Registry module in several stubs):

```console
$ .venv/bin/python -m pytest -q
..................................................................FF.... [ 30%]
............FF..F.F............F.F...................................... [ 61%]
........................................................................ [ 92%]
..................                                                       [100%]
8 failed, 226 passed in 0.73s
```

The same RED checkpoint reported `18` Ruff findings and `10` mypy errors. The
failures were fixed without making Area Registry part of safety validation: strict
entity capability and area-mapping validation remains in `topology.py`, while area
names are an optional cosmetic projection. A focused regression now proves that
`skip_area_today` uses the next Home Assistant-local midnight and persists through
the shared coordinator; the public schema also rejects the unsupported mop-only
mode.

Final GREEN output:

```console
$ .venv/bin/python -m pytest -q
........................................................................ [ 30%]
........................................................................ [ 61%]
........................................................................ [ 91%]
...................                                                      [100%]
235 passed in 0.51s

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/mypy .
Success: no issues found in 44 source files

$ .venv/bin/bandit -r custom_components -q
# no output; exit status 0

$ .venv/bin/python -m compileall -q custom_components tests
# no output; exit status 0

$ for file in hacs.json custom_components/vacuum_planner/manifest.json \
    custom_components/vacuum_planner/strings.json \
    custom_components/vacuum_planner/translations/de.json \
    custom_components/vacuum_planner/translations/en.json; do \
    .venv/bin/python -m json.tool "$file" >/dev/null; done
validated 5 JSON files

$ git diff --check
# no output; exit status 0
```

## 8. Release-candidate documentation and dashboard contract

The release/documentation tests were written before the new artifacts. After the minimal
release documents and canonical dashboard contract were added, the focused GREEN run was:

```console
$ .venv/bin/python -m pytest tests/test_release_candidate_docs.py -vv
collected 7 items

tests/test_release_candidate_docs.py::test_release_candidate_has_all_required_documents PASSED [ 14%]
tests/test_release_candidate_docs.py::test_local_markdown_links_resolve PASSED [ 28%]
tests/test_release_candidate_docs.py::test_installation_is_hacs_or_manual_and_ui_only PASSED [ 42%]
tests/test_release_candidate_docs.py::test_rollback_requires_backup_and_stopped_home_assistant_for_store_edits PASSED [ 57%]
tests/test_release_candidate_docs.py::test_license_file_records_blocker_without_claiming_mit PASSED [ 71%]
tests/test_release_candidate_docs.py::test_dashboard_artifacts_are_parseable_and_vendor_neutral PASSED [ 85%]
tests/test_release_candidate_docs.py::test_dashboard_template_encodes_product_rules PASSED [100%]

============================== 7 passed in 0.08s ===============================
```

Final full-suite and static-analysis outputs after fixing one line-length finding and marking
the installed PyYAML package as untyped for mypy:

```console
$ .venv/bin/python -m pytest -q
........................................................................ [ 29%]
........................................................................ [ 59%]
........................................................................ [ 89%]
..........................                                               [100%]
242 passed in 0.57s

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/mypy . --strict
Success: no issues found in 45 source files
```

The remaining release gates were run independently and returned:

```console
$ .venv/bin/bandit -q -r custom_components/vacuum_planner
# no output; exit status 0

$ .venv/bin/python -m compileall -q custom_components tests
# no output; exit status 0

$ # json.tool over metadata, translations, and dashboard/mock-states.json
validated 6 JSON files

$ # yaml.safe_load over dashboard/*.yaml
validated 1 YAML file(s)

$ .venv/bin/python -m pytest tests/test_release_candidate_docs.py::test_local_markdown_links_resolve -q
.                                                                        [100%]
1 passed in 0.06s

$ git diff --check && printf 'diff-check passed\n'
diff-check passed
```

### Limitations

- Home Assistant itself is not installed in this isolated project environment, so
  lifecycle/platform tests use explicit registry, state, service, storage, and
  entity stubs. The stubs now include strict capability dependencies where safety
  validation needs them; optional area-name lookup remains independently nullable.
- Bandit is intentionally run over production code (`custom_components`) rather
  than pytest files. Scanning tests reports hundreds of expected `assert` findings
  (`B101`) and test fixture strings misclassified as passwords (`B106`), which does
  not provide a useful production security signal.
- No live vacuum hardware or vendor integration was exercised. The verified public
  projections/actions remain vendor-neutral and do not expose adapter targets.

## 9. Cleanup and final quality-gate repair

After aligning the explicit translation contract with the Repairs catalog and resolving all
Ruff and strict-mypy findings, the focused
regression set returned:

```console
$ .venv/bin/python -m pytest tests/test_integration_contract.py tests/test_config_flow.py tests/test_backend_blockers.py tests/test_diagnostics_repairs.py -q
........................................................................ [ 88%]
.........                                                                [100%]
81 passed in 0.17s
```

The first complete run stalled after 117 tests. A verbose run identified the exact test as
`tests/test_integration_lifecycle.py::test_parallel_start_next_claims_native_batch_once`.
Its fixture predated command-time stable registry resolution and never reached its service
barrier. Adding the required registry identity made the focused test green:

```console
$ .venv/bin/python -m pytest tests/test_integration_lifecycle.py::test_parallel_start_next_claims_native_batch_once -vv
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-8.4.2, pluggy-1.6.0 -- /root/ha-vacuum-planner/.venv/bin/python
cachedir: .pytest_cache
rootdir: /root/ha-vacuum-planner
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 1 item

tests/test_integration_lifecycle.py::test_parallel_start_next_claims_native_batch_once PASSED [100%]

============================== 1 passed in 0.11s ===============================
```

The remaining lifecycle failures were stale direct-dispatch fixtures (which now isolate the
registry resolver explicitly), one runtime-data expectation missing the stable registry ID,
and one legacy default that still expected no mop interval instead of the configured default
of seven days. No production behavior was relaxed to satisfy those tests.

Final complete suite with the requested coverage threshold:

```console
$ .venv/bin/python -m pytest --cov=custom_components/vacuum_planner --cov-report=term-missing --cov-fail-under=90 -q
........................................................................ [ 25%]
........................................................................ [ 51%]
........................................................................ [ 76%]
.................................................................        [100%]
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.15-final-0 _______________

TOTAL                                                       1956    167    91%
Required test coverage of 90% reached. Total coverage: 91.46%
281 passed in 0.77s
```

Final static, security, syntax, data, and diff gates:

```console
$ .venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
All checks passed!
53 files already formatted

$ .venv/bin/python -m mypy . --strict
Success: no issues found in 53 source files

$ .venv/bin/python -m bandit -q -r custom_components/vacuum_planner && printf 'bandit passed\n'
bandit passed

$ .venv/bin/python -m compileall -q custom_components tests && printf 'compileall passed\n'
compileall passed

$ # json.loads over metadata, translations, and dashboard/mock-states.json
validated 6 JSON files

$ # yaml.safe_load over dashboard/*.yaml
validated 1 YAML file(s)

$ git diff --check && git diff --cached --check && printf 'unstaged and staged diff-check passed\n'
unstaged and staged diff-check passed
```

## Runtime handoff and setup rollback blockers (2026-09-19)

Observed TDD results for command-generation invalidation and partial-setup rollback:

```console
# queued stale command RED
1 failed in 0.12s
Failed: DID NOT RAISE StubServiceValidationError

# runtime-liveness focused GREEN
7 passed

# partial-setup rollback RED, then GREEN
3 failed
3 passed
```

Final verification after the typed cleanup callback and owning-module test imports:

```console
$ .venv/bin/pytest -q tests/test_backend_blockers.py tests/test_config_flow.py tests/test_coordinator.py tests/test_integration_lifecycle.py tests/test_native_area_adapter.py tests/test_observer.py
153 passed in 0.22s

$ .venv/bin/python -m pytest --cov=custom_components/vacuum_planner --cov-report=term-missing --cov-fail-under=90 -q
330 passed in 1.07s
Required test coverage of 90% reached. Total coverage: 92.39%

$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
54 files already formatted
$ .venv/bin/mypy . --strict
Success: no issues found in 54 source files

$ .venv/bin/bandit -q -r custom_components/vacuum_planner
# no output; exit status 0
$ .venv/bin/python -m compileall -q custom_components tests
# no output; exit status 0
# json.loads / yaml.safe_load validation
validated 6 JSON files
validated 2 YAML file(s)

$ /tmp/ha-vp-2026.3.1/bin/python -m pytest -c tests_ha/pytest.ini tests_ha -q
# Python 3.14.4; Home Assistant 2026.3.1; plugin 0.13.317
3 passed in 0.30s
$ /tmp/ha-vp-2026.9.3/bin/python -m pytest -c tests_ha/pytest.ini tests_ha -q
# Python 3.14.4; Home Assistant 2026.9.3; plugin 0.13.366
3 passed in 0.28s

$ # three deterministic builds (two clean temporary outputs plus dist), cmp, and sha256sum -c
vacuum_planner-v0.1.0-beta.1.zip: OK
archive bytes identical across 3 builds: yes
sha256: c8947f196ba98b99bbd499d68820b7a5a8b925bc30272761ffd613085fead01d
entries: 30
sorted/fixed timestamps/0644/root/manifest/cache exclusions: verified
```

## Final gate and staging closure (2026-09-19)

Formatter and affected-suite result:

```console
$ .venv/bin/ruff format custom_components/vacuum_planner/__init__.py tests/test_backend_blockers.py
2 files reformatted
$ .venv/bin/python -m pytest -q tests/test_backend_blockers.py tests/test_config_flow.py tests/test_diagnostics_repairs.py tests/test_integration_lifecycle.py
139 passed in 0.30s
```

Final working-tree gates before evidence-only documentation update:

```console
$ .venv/bin/python -m pytest --cov=custom_components/vacuum_planner --cov-report=term-missing --cov-fail-under=90 -q
339 passed in 1.07s
Required test coverage of 90% reached. Total coverage: 92.64%

$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
54 files already formatted
$ .venv/bin/mypy . --strict
Success: no issues found in 54 source files
$ .venv/bin/bandit -q -r custom_components/vacuum_planner
bandit passed
$ .venv/bin/python -m compileall -q custom_components tests tests_ha scripts
compileall passed
# json.loads / yaml.safe_load validation
validated 6 JSON files
validated 2 YAML files
$ git diff --check && git diff --cached --check
unstaged and staged diff-check passed
```

Pinned real Home Assistant lifecycle matrix:

```console
# Python 3.14.4; Home Assistant 2026.3.1; plugin 0.13.317
3 passed in 0.30s
# Python 3.14.4; Home Assistant 2026.9.3; plugin 0.13.366
3 passed in 0.26s
```

Deterministic release rebuild after packaged sources were final:

```console
vacuum_planner-v0.1.0-beta.1.zip: OK
archive bytes identical across 3 builds: yes
sha256: e86f7559276c78fafca72baa487eb282b880b1017b88782e7627caab23b34cfd
entries: 30
sorted/fixed timestamps/0644/root/manifest/cache exclusions: verified
```

## Minimum Safe Beta scope reduction (2026-09-19)

Reduced public surface — observed inventory RED → GREEN:

```console
$ python3 tests/test_minimum_safe_beta_scope.py -v
FAILED (failures=3)
# Removed public surfaces remained in runtime/domain/catalog/docs.

$ python3 tests/test_minimum_safe_beta_scope.py -v
Ran 3 tests in 0.001s
OK
$ python3 -m compileall -q custom_components tests
# exit 0
```

The initial preserved environment lacked pytest. A dedicated development environment was
provided later; the final observed scope-reduction gates are recorded below.

### Final scope-reduction verification

The first focused run against the carried worktree exposed only obsolete hot-reconciliation
expectations:

```console
$ .venv-dev/bin/pytest -q tests/test_minimum_safe_beta_scope.py tests/test_backend_blockers.py -k 'observer or lifecycle or repair or config or queue or public or doc or contract or topology or minimum or blocker'
5 failed, 35 passed in 0.20s
```

After migrating those expectations to the permanent fail-closed contract and adding explicit
state/capability loss, Area Registry loss, no-automatic-revival, and nested-cleanup probes:

```console
$ .venv-dev/bin/pytest -q tests/test_backend_blockers.py
......................................                                   [100%]
38 passed in 0.12s

$ .venv-dev/bin/pytest -q tests/test_minimum_safe_beta_scope.py tests/test_backend_blockers.py tests/test_observer.py tests/test_integration_lifecycle.py tests/test_diagnostics_repairs.py tests/test_config_flow.py tests/test_queue.py tests/test_public_actions.py tests/test_public_platforms.py tests/test_public_entities.py tests/test_documentation_contract.py tests/test_integration_contract.py tests/test_release_candidate_docs.py
........................................................................ [ 36%]
........................................................................ [ 72%]
......................................................                   [100%]
198 passed in 0.43s
```

Final static, parse, and diff gates on the same working tree:

```console
$ .venv-dev/bin/ruff check .
All checks passed!
$ .venv-dev/bin/ruff format --check .
54 files already formatted
$ .venv-dev/bin/mypy .
Success: no issues found in 54 source files
$ .venv-dev/bin/bandit -q -r custom_components/vacuum_planner
bandit passed
$ .venv-dev/bin/python -m compileall -q custom_components tests tests_ha scripts
compileall passed
$ # json.loads / yaml.safe_load over tracked existing JSON/YAML files
validated 6 JSON files
validated 3 YAML files
$ git diff --check && git diff --cached --check
unstaged and staged diff-check passed
```

### Final Minimum Safe Beta candidate

The complete hermetic suite was run with the dedicated Python 3.11 development environment after
scope reduction:

```console
$ .venv-dev/bin/python -m pytest --cov=custom_components/vacuum_planner --cov-report=term-missing --cov-fail-under=90 -q
324 passed in 1.03s
Required test coverage of 90% reached. Total coverage: 92.81%
```

The repository's pinned real-Home-Assistant lifecycle command passed in both isolated matrix
environments:

```console
$ /tmp/ha-vp-2026.3.1/bin/python -m pytest -c tests_ha/pytest.ini tests_ha -q
# Python 3.14.4; Home Assistant 2026.3.1; pytest-homeassistant-custom-component 0.13.317
3 passed in 0.30s

$ /tmp/ha-vp-2026.9.3/bin/python -m pytest -c tests_ha/pytest.ini tests_ha -q
# Python 3.14.4; Home Assistant 2026.9.3; pytest-homeassistant-custom-component 0.13.366
3 passed in 0.29s
```

The final reduced integration source was built into the tracked release directory and two clean
temporary output directories. All three archives and checksum manifests compared byte-for-byte;
`sha256sum -c` passed. Programmatic inspection found 29 source-identical entries in sorted order,
all with timestamp `1980-01-01 00:00:00` and mode `100644`. Removed ad-hoc enqueue, public
lifecycle-event emitter, reconfigure/topology-migration surfaces, `topology_migration.py`, and
`standard-card-template.yaml` were absent.

```console
$ .venv-dev/bin/python scripts/build_release.py --version 0.1.0-beta.1 --output-dir dist
built /root/ha-vacuum-planner/dist/vacuum_planner-v0.1.0-beta.1.zip
sha256 6d358ebb01d2f903c18d32c84c22f457ca6c44afca4e984ecf1fefa246fb4b12
$ (cd dist && sha256sum -c SHA256SUMS)
vacuum_planner-v0.1.0-beta.1.zip: OK
```

## 2026-09-20 Config-Flow `VacuumEntityFeature` regression fix

Live target inspection found Home Assistant Core `2026.9.3`. Official Core and both pinned
lifecycle environments expose `VacuumEntityFeature.CLEAN_AREA == 16384`; the live vacuum states
reported `supported_features` values `31676` and `30524`, both containing that bit. The live
entity-registry entries are active `dreame_vacuum` and `robovac_mqtt` entities. The latter has a
native `options.vacuum.area_mapping`; the former currently has no area mapping and must still be
mapped in Home Assistant before its areas can be selected.

The exact read-only validator harness reproduced the false negative only when the values used their
native runtime type, `VacuumEntityFeature` (`IntFlag`): the same numeric masks represented as plain
API integers passed. Home Assistant's `StateVacuumEntity.supported_features` contract returns that
enum type, while the old validator required `type(value) is int`.

```console
$ .venv-dev/bin/pytest -q tests/test_config_flow.py::test_user_step_accepts_native_clean_area_feature_flags
2 failed in 0.11s
# both 31676 and 30524 remained on the user step

$ .venv-dev/bin/pytest -q tests/test_config_flow.py::test_user_step_accepts_native_clean_area_feature_flags
2 passed in 0.05s

$ .venv-dev/bin/python -m pytest --cov=custom_components/vacuum_planner --cov-report=term-missing --cov-fail-under=90 -q
370 passed in 1.15s
TOTAL 2358 178 92%

$ /tmp/ha-vp-2026.3.1/bin/python -m pytest -c tests_ha/pytest.ini tests_ha -q
3 passed in 0.30s
$ /tmp/ha-vp-2026.9.3/bin/python -m pytest -c tests_ha/pytest.ini tests_ha -q
3 passed in 0.28s

$ ruff check . && ruff format --check .
All checks passed; 54 files already formatted
$ mypy . --strict
Success: no issues found in 54 source files
$ bandit -q -r custom_components/vacuum_planner
# exit 0
$ python -m compileall -q custom_components tests tests_ha scripts
# exit 0; JSON/YAML parse checks also passed

$ .venv-dev/bin/python scripts/build_release.py --version 0.1.0-beta.2 --output-dir dist
built /root/ha-vacuum-planner/dist/vacuum_planner-v0.1.0-beta.2.zip
sha256 5f3a1cb4074c4abfa3487756ad81d17110547c4fd4a54f4e9059f40668502d25
$ (cd dist && sha256sum -c SHA256SUMS)
vacuum_planner-v0.1.0-beta.2.zip: OK
```

Three clean builds (two temporary outputs plus `dist`) were byte-identical. Independent review
then found the same exact-type bug at runtime preflight and observer boundaries. Focused tests for
both real native enum masks failed `2` cases before the preflight fix and passed `2` afterward; the
observer native-enum test failed before the observer fix and passed afterward. The final artifact
for that intermediate checkpoint included all three aligned fail-closed checks; the superseding
artifact checksum is recorded below.

### HA 2026.9 area-plan serialization and UX pilot closure

The supervised live pilot had already recorded the real Home Assistant 2026.9.3 failure before
this repository port: Probatio raised `ValueError: unable to serialize schema: <function
_strict_int>` when the flow reached `area_plan`. After the live patch, the read-only REST flow
reached `area_plan` without a matching log error, and the German frontend API returned the new
step text. No Config Entry or vacuum command was created by that reproduction.

The repository regression tests then reproduced the same boundaries before the live-tested change
was copied. This is the observed RED output; it is not a reconstructed or invented run:

```console
$ .venv-dev/bin/python -m pytest -q tests/test_config_flow.py::test_area_step_collects_ui_only_plan_for_every_area tests/test_config_flow.py::test_area_plan_submit_rejects_malformed_integer_fields_fail_closed tests/test_config_flow.py::test_area_plan_submit_rejects_missing_integer_fields_fail_closed tests/test_integration_contract.py::test_config_flow_has_complete_english_and_german_translations
11 failed in 0.20s

$ /tmp/ha-vp-2026.9.3/bin/python -m pytest -c tests_ha/pytest.ini tests_ha/test_lifecycle.py::test_area_plan_form_schema_is_frontend_serializable -q
ValueError: unable to serialize schema: <function _strict_int ...>
1 failed in 0.26s
```

The final GREEN candidate keeps `int` plus range validators in the displayed schema, repeats the
strict non-bool integer check at submit time for all three numeric fields, resolves the friendly
Area name, and supplies `current`/`total` placeholders. The default, English, and German catalogs
carry the exact schema field keys.

```console
$ .venv-dev/bin/python -m pytest -q tests/test_config_flow.py tests/test_native_area_adapter.py tests/test_backend_blockers.py tests/test_integration_contract.py tests/test_release_candidate_docs.py
147 passed in 0.37s

$ .venv-dev/bin/python -m pytest --cov=custom_components/vacuum_planner --cov-report=term-missing --cov-fail-under=90 -q
377 passed in 1.22s
TOTAL 2367 178 92%
Required test coverage of 90% reached. Total coverage: 92.48%

$ /tmp/ha-vp-2026.3.1/bin/python -m pytest -c tests_ha/pytest.ini tests_ha -q
4 passed in 0.30s
$ /tmp/ha-vp-2026.9.3/bin/python -m pytest -c tests_ha/pytest.ini tests_ha -q
4 passed in 0.30s

$ .venv-dev/bin/ruff check . && .venv-dev/bin/ruff format --check .
All checks passed; 54 files already formatted
$ .venv-dev/bin/mypy . --strict
Success: no issues found in 54 source files
$ .venv-dev/bin/bandit -q -r custom_components/vacuum_planner
# exit 0
$ .venv-dev/bin/python -m compileall -q custom_components tests tests_ha scripts
# exit 0; 6 JSON and 3 YAML files also parsed successfully

$ .venv-dev/bin/python scripts/build_release.py --version 0.1.0-beta.2 --output-dir dist
built /root/ha-vacuum-planner/dist/vacuum_planner-v0.1.0-beta.2.zip
sha256 ebe2eac1dd9827a88317af033ed90a3fc3b374dbd3eb5025554a655a2907d28c
$ (cd dist && sha256sum -c SHA256SUMS)
vacuum_planner-v0.1.0-beta.2.zip: OK
```

Two clean temporary builds and `dist` were byte-identical. The final archive has 29 sorted
members, fixed ZIP timestamps, and byte-for-byte source parity.
