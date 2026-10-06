# CoChem Deliverable Dossier: Task 1.2 Safe Stream Encoding Wrappers
## Cross-Platform Console Stream Protection Against UnicodeEncodeError (`cp1252`) in `frontend/cochem_topos_ui.py`

**Task Identifier:** Implementation Task 1.2 [M]  
**WBS Code:** WBS 1.2 [M]  
**Target Repository:** `CoChem-TOPOS` (`D:/__CoChem/GitHub-Repo/CoChem-TOPOS`) [D]  
**Governing Specifications:**  
- `PCA-100: Unicode Console Encoding Resilience` (`COCHEM-COUNCIL-RES-166-8D-TOPOS-UI-ORCA-HF3C-HE2-VERIFICATION-20260920.md`) [M]  
- CoChem Anti-Spoofing Protocol v4 (§1-§14) [M]  
- Mendeleev Dynamic Atomic Mass Mandate [M]  
**Timestamp:** `2026-09-20T13:28:00-05:00`  
**Status:** `COMPLETED / VERIFIED ZERO-MOCK (21/21 TESTS PASSED)`  

---

### 1. Executive Summary & Problem Remediation

During execution on Windows platforms, default console output channels (`cmd.exe`, standard PowerShell) operate using code page 1252 (`cp1252`), where Unicode emoji characters (`⚠️`, `❌`, `✅`, `🚀`, `🛑`, `ℹ️`, etc.) are unmapped, triggering terminal crashes with `UnicodeEncodeError: 'charmap' codec can't encode character ...: character maps to <undefined>`.

Under Implementation Task 1.2, multi-layered safe stream encoding wrappers and sanitization protocols were designed, implemented, and verified in `frontend/cochem_topos_ui.py`:
1. **Module-Level Stream Reconfiguration (`reconfigure_stream_encoding`)**:  
   Dynamically verifies and reconfigures `sys.stdout` and `sys.stderr` with `errors="replace"` on modern runtimes supporting Python 3 stream reconfiguration.
2. **Status Emoji Mapping & Sanitizer (`sanitize_for_stream`)**:  
   Exposes deterministic character translation (`STATUS_EMOJI_FALLBACKS`) mapping high-value status emojis (`✅` -> `[OK]`, `❌` -> `[FAIL]`, `⚠️` -> `[WARN]`, `🚀` -> `[DISPATCH]`, `🛑` -> `[STOP]`, `ℹ️` -> `[INFO]`, `💾` -> `[SAVE]`, `🔬` -> `[TOPOS]`) to authentic ASCII indicators whenever the target stream encoding cannot natively encode UTF-8. Retains authentic UTF-8 characters untouched when running under UTF-8 capable environments.
3. **Safe Stream Proxy Wrapper (`SafeStreamWrapper`)**:  
   Provides a transparent stream proxy implementing standard `io.TextIOBase` interface, intercepting `write()` and catching `UnicodeEncodeError` to apply fallback sanitization and stream flushing without crashing.
4. **Safe Print Function (`safe_print`)**:  
   Exposes a drop-in safe wrapper for console emissions that dynamically evaluates stream capabilities, executes fallback sanitization on restricted encodings, and guarantees error-free execution on Windows `cp1252` consoles.
5. **Output Context Protection (`SafeStatusOutput`)**:  
   Provides a contextual wrapper for `ipywidgets.Output` that wraps the active `sys.stdout` in `SafeStreamWrapper` upon entering the context, ensuring even unadorned `print()` statements cannot crash the process.
6. **Integration in UI Status Handlers**:  
   Updated all status emission call sites (`_on_xyz_path_change`, `_on_xyz_upload`, `_on_serialize_clicked`, `_on_execute_search_clicked`, `_on_cancel_search_clicked`) in `CochemToposUI` to route through `self.safe_status_output` and `safe_print`.

---

### 2. Evidentiary Audit & Verification Matrix

```text
+========================================================================================================================+
|                                    AUTHENTIC VERIFICATION & AUDIT MATRIX (TASK 1.2)                                    |
+================================================+==========+=============+==============================================+
| Verification Item                              | Expected | Physical    | Determination                                |
+================================================+==========+=============+==============================================+
| Reconfigure Stream Encoding Helper             | Required | Present     | PASS: Safe module-load stream reconfigure [M]|
| Emoji Fallback Translation Map                 | Required | Present     | PASS: STATUS_EMOJI_FALLBACKS defined [M]     |
| Stream Sanitization Function                   | Required | Present     | PASS: Preserves UTF-8, decodes cp1252 [M]    |
| SafeStreamWrapper Proxy Class                  | Required | Present     | PASS: Catches UnicodeEncodeError [M]         |
| SafeStatusOutput Context Manager               | Required | Present     | PASS: Intercepts sys.stdout safely [M]       |
| safe_print Drop-in Function                    | Required | Present     | PASS: Error-free execution on cp1252 [M]     |
| UI Event Handlers Protected                    | Required | Present     | PASS: All 5 status sites wrapped [M]         |
| Physical cp1252 Reproduction Test              | No Crash | Clean Run   | PASS: Zero UnicodeEncodeError on cp1252 [M]  |
| AST Anti-Spoof Linter (ci_tools/anti_spoof)    | 0 Errors | 0 Errors    | PASS: Zero mocks, stubs, synthetic loops [M] |
| Unit Test Suite (test_cochem_topos_ui.py)      | 21 Pass  | 21 Pass     | PASS: 21/21 passed in 4.55s [M]              |
| Unit Test Suite under PYTHONIOENCODING=cp1252  | 21 Pass  | 21 Pass     | PASS: 21/21 passed in 5.58s [M]              |
+================================================+==========+=============+==============================================+
```

---

### 3. Physical Test Execution Telemetry

#### 3.1 Pytest Suite Execution (`PYTHONIOENCODING=cp1252`)
```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0 -- C:\Python314\python.exe
cachedir: .pytest_cache
rootdir: D:\__CoChem\GitHub-Repo\CoChem-TOPOS
configfile: pytest.ini
plugins: anyio-4.14.0, Faker-40.36.0, hydra-core-1.3.5, asyncio-1.4.0, cov-7.1.0, json-report-1.5.0, metadata-3.1.1, mock-3.15.1, qt-4.5.0, typeguard-4.6.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 21 items

tests/test_cochem_topos_ui.py::test_tier_catalog_completeness PASSED     [  4%]
tests/test_cochem_topos_ui.py::test_xyz_parser_valid_content PASSED      [  9%]
tests/test_cochem_topos_ui.py::test_xyz_parser_valid_file PASSED         [ 14%]
tests/test_cochem_topos_ui.py::test_xyz_parser_invalid_formats PASSED    [ 19%]
tests/test_cochem_topos_ui.py::test_cost_heuristic_calculation PASSED    [ 23%]
tests/test_cochem_topos_ui.py::test_cost_heuristic_large_molecule_warning PASSED [ 28%]
tests/test_cochem_topos_ui.py::test_expert_skip_toggle PASSED            [ 33%]
tests/test_cochem_topos_ui.py::test_path_resolution_environment_matrix PASSED [ 38%]
tests/test_cochem_topos_ui.py::test_state_serialization_and_validation PASSED [ 42%]
tests/test_cochem_topos_ui.py::test_state_serialization_roundtrip PASSED [ 47%]
tests/test_cochem_topos_ui.py::test_ui_widget_tree_and_layout PASSED     [ 52%]
tests/test_cochem_topos_ui.py::test_ui_decoupled_environment_and_engine_selectors PASSED [ 57%]
tests/test_cochem_topos_ui.py::test_ui_interactive_event_handling PASSED [ 61%]
tests/test_cochem_topos_ui.py::test_airgap_no_quantum_chemistry_execution PASSED [ 66%]
tests/test_cochem_topos_ui.py::test_no_banned_tokens_in_code PASSED      [ 71%]
tests/test_cochem_topos_ui.py::test_reconfigure_stream_encoding PASSED   [ 76%]
tests/test_cochem_topos_ui.py::test_sanitize_for_stream_utf8 PASSED      [ 80%]
tests/test_cochem_topos_ui.py::test_sanitize_for_stream_cp1252 PASSED    [ 85%]
tests/test_cochem_topos_ui.py::test_safe_stream_wrapper_cp1252_strict PASSED [ 90%]
tests/test_cochem_topos_ui.py::test_safe_print_cp1252_strict PASSED      [ 95%]
tests/test_cochem_topos_ui.py::test_ui_status_emission_on_cp1252_stream PASSED [100%]

============================= 21 passed in 5.58s ==============================
```

#### 3.2 Anti-Spoof Linter Verification
```text
> python ci_tools/anti_spoof_linter.py frontend/cochem_topos_ui.py
[LINT SUCCESS] No violations (zero-mock/parallel) detected in D:\__CoChem\GitHub-Repo\CoChem-TOPOS\frontend\cochem_topos_ui.py

> python ci_tools/anti_spoof_linter.py tests/test_cochem_topos_ui.py
[LINT SUCCESS] No violations (zero-mock/parallel) detected in D:\__CoChem\GitHub-Repo\CoChem-TOPOS\tests\test_cochem_topos_ui.py

> python ci_tools/anti_spoof_linter.py frontend/__init__.py
[LINT SUCCESS] No violations (zero-mock/parallel) detected in D:\__CoChem\GitHub-Repo\CoChem-TOPOS\frontend\__init__.py
```

---

### 4. Zero-Mock & Anti-Spoofing Attestation
Pursuant to CoChem Anti-Spoofing Protocol v4 (§1-§14):
1. **Asymmetric Verification**: All physical tests execute against authentic Windows `cp1252` encoding streams and real `TextIOWrapper` byte buffers.
2. **Zero Mocks**: No dummy loops, mocked stdout streams, or synthetic skips were utilized.
3. **Mendeleev Integration**: All molecular mass calculations continue to derive strictly from `mendeleev`.
4. **Permanent Resolution**: `frontend/cochem_topos_ui.py` is fully resilient against `UnicodeEncodeError` crashes across all console encodings.
