Cycle 4: Implement code for prompt at D:\__CoChem\__agentic\.prompts\.SRS\CoChem-TOPOS\.in-progress\01_01_create_gitignore.md strictly adhering to Zero-Mock mandate. Target repo is D:\__CoChem\GitHub-Repo\CoChem-TOPOS. Generate unit tests first. IMPORTANT: You MUST update/create `pytest.ini` to restrict `testpaths` to ONLY the tests you are writing for this prompt, otherwise the global 1500+ test suite will run and crash your context. 
Test Failures from previous run:
Output: ============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-8.4.2, pluggy-1.5.0 -- C:\Users\ansac\anaconda3\python.exe
cachedir: .pytest_cache
rootdir: D:\__CoChem\GitHub-Repo\CoChem-TOPOS
configfile: pytest.ini
plugins: anyio-4.10.0, typeguard-4.6.0
collecting ... collected 65 items

tests/test_cascade_orchestrator.py::test_topos04_v4_t1_search_escalation_routing FAILED [  1%]
tests/test_cascade_orchestrator.py::test_compute_true_hessian_directory_lifecycle PASSED [  3%]
tests/test_cascade_orchestrator.py::test_gradient_payload_anti_spoofing_rejection[spoofed_gradient0] PASSED [  4%]
tests/test_cascade_orchestrator.py::test_gradient_payload_anti_spoofing_rejection[spoofed_gradient1] PASSED [  6%]
tests/test_cascade_orchestrator.py::test_gradient_payload_anti_spoofing_rejection[spoofed_gradient2] PASSED [  7%]
tests/test_cascade_orchestrator.py::test_gradient_payload_anti_spoofing_rejection[spoofed_gradient3] PASSED [  9%]
tests/test_cascade_orchestrator.py::test_gradient_payload_anti_spoofing_rejection[spoofed_gradient4] PASSED [ 10%]
tests/test_cascade_orchestrator.py::test_gradient_payload_anti_spoofing_rejection[spoofed_gradient5] PASSED [ 12%]
tests/test_cascade_orchestrator.py::test_gradient_payload_valid_cases[valid_gradient0] FAILED [ 13%]
tests/test_cascade_orchestrator.py::test_gradient_payload_valid_cases[valid_gradient1] PASSED [ 15%]
tests/test_cascade_orchestrator.py::test_gradient_payload_valid_cases[valid_gradient2] PASSED [ 16%]
tests/test_cascade_orchestrator.py::test_gradient_payload_valid_cases[valid_gradient3] PASSED [ 18%]
tests/test_cascade_orchestrator.py::test_gradient_payload_valid_cases[valid_gradient4] PASSED [ 20%]
tests/test_cascade_orchestrator.py::test_gradient_payload_valid_cases[valid_gradient5] PASSED [ 21%]
tests/test_cascade_orchestrator.py::test_gradient_payload_valid_cases[valid_gradient6] PASSED [ 23%]
tests/test_crusher.py::test_topos_crusher_distance_matrix_hash PASSED    [ 24%]
tests/test_crusher.py::test_distance_matrix_hash_rigid_invariance PASSED [ 26%]
tests/test_crusher.py::test_goat_conformer_generation FAILED             [ 27%]
tests/test_crusher.py::test_topos01_inhess_xtb2_preconditioner FAILED    [ 29%]
tests/test_crusher.py::test_topos02_two_stage_deduplication_protocol FAILED [ 30%]
tests/test_crusher.py::test_crest_secondary_crosscheck_subprocess FAILED [ 32%]
tests/test_crusher.py::test_shake_constraints_water FAILED               [ 33%]
tests/test_crusher.py::test_shake_constraints_non_water PASSED           [ 35%]
tests/test_crusher.py::test_apply_spectroscopic_override PASSED          [ 36%]
tests/test_crusher.py::test_dynamic_anneal_threshold PASSED              [ 38%]
tests/test_crusher.py::test_rotamer_merging_neb_barrier FAILED           [ 40%]
tests/test_crusher.py::test_topos_crusher_hdf5_persistence PASSED        [ 41%]
tests/test_crusher.py::test_process_conformer_crest_crosscheck_flag FAILED [ 43%]
tests/test_crusher.py::test_async_process_monomer_phase FAILED           [ 44%]
tests/test_crusher.py::test_async_process_strong_complex_phase FAILED    [ 46%]
tests/test_crusher.py::test_async_process_weak_complex_phase FAILED      [ 47%]
tests/test_crusher.py::test_execute_jax_neb_fallback FAILED              [ 49%]
tests/test_escape.py::test_good_turing_estimator_dynamic_min_sample_size PASSED [ 50%]
tests/test_escape.py::test_good_turing_estimator_calculate_coverage PASSED [ 52%]
tests/test_escape.py::test_good_turing_estimator_is_converged_batch_tracking PASSED [ 53%]
tests/test_escape.py::test_parity_lock_chiral_enantiomer_inversion_detection PASSED [ 55%]
tests/test_escape.py::test_parity_lock_3d_tetrahedral_volume_fallback PASSED [ 56%]
tests/test_escape.py::test_escape_room_shake_constraints PASSED          [ 58%]
tests/test_escape.py::test_escape_room_execute_thermal_shock_success FAILED [ 60%]
tests/test_escape.py::test_escape_room_thermal_shock_missing_calculator_error PASSED [ 61%]
tests/test_escape.py::test_escape_room_thermal_shock_explosion_trap FAILED [ 63%]
tests/test_escape.py::test_escape_room_thermal_shock_parity_lock_rejection FAILED [ 64%]
tests/test_escape.py::test_escape_room_photochemical_shock_honest_engine_routing_and_fallback PASSED [ 66%]
tests/test_escape.py::test_escape_room_photochemical_shock_orca_input_formatting FAILED [ 67%]
tests/test_escape.py::test_escape_room_photochemical_shock_orca_subprocess_execution PASSED [ 69%]
tests/test_master.py::test_topos_master_init PASSED                      [ 70%]
tests/test_master.py::test_topos_master_init_missing_paths PASSED        [ 72%]
tests/test_master.py::test_topos_master_context_manager PASSED           [ 73%]
tests/test_master.py::test_oet_server_ipc_client_defaults_and_custom PASSED [ 75%]
tests/test_master.py::test_oet_server_format_orca_extopt_input PASSED    [ 76%]
tests/test_master.py::test_oet_server_gradient_sign_flip_guard PASSED    [ 78%]
tests/test_master.py::test_oet_server_process_daemon_response_edge_cases FAILED [ 80%]
tests/test_master.py::test_macroscopic_boltzmann_synthesis PASSED        [ 81%]
tests/test_master.py::test_zmq_ui_listener_lifecycle FAILED              [ 83%]
tests/test_master.py::test_run_escalation_pass PASSED                    [ 84%]
tests/test_master.py::test_execute_nested_assembly_pipeline FAILED       [ 86%]
tests/test_gitignore.py::test_gitignore_file_exists PASSED               [ 87%]
tests/test_gitignore.py::test_gitignore_contains_required_sections PASSED [ 89%]
tests/test_gitignore.py::test_gitignore_contains_required_patterns PASSED [ 90%]
tests/test_gitignore.py::test_section1_tripartite_data_workspace_ignored PASSED [ 92%]
tests/test_gitignore.py::test_section2_persistent_databases_and_registries_ignored PASSED [ 93%]
tests/test_gitignore.py::test_section3_raw_structural_data_ignored PASSED [ 95%]
tests/test_gitignore.py::test_section4_quantum_chemical_wavefunctions_and_scratch_tensors_ignored PASSED [ 96%]
tests/test_gitignore.py::test_section5_python_environments_and_ephemeral_ipc_ignored PASSED [ 98%]
tests/test_gitignore.py::test_trackable_source_files_not_ignored PASSED  [100%]

================================== FAILURES ===================================
________________ test_topos04_v4_t1_search_escalation_routing _________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_topos04_v4_t1_search_esca0')

    def test_topos04_v4_t1_search_escalation_routing(
        tmp_path: Path,
    ) -> None:
        """
        Verify TOPOS-04: Tier routing for v4 T1 search escalation.
        Tests end-to-end geometry processing, method matrix tier sequence,
        physical Hessian evaluation with temporary directory lifecycle,
        and SWMR HDF5 dataset persistence.
        """
        config = CascadeConfig(artifact_dir=tmp_path, complex_flag=True)
        orchestrator = CascadeOrchestrator(config=config)
    
        tier_seq = orchestrator._get_tier_sequence(complex_flag=True)
        assert len(tier_seq) == 5
    
        methods = [t.method for t in tier_seq]
        assert methods == [
            "Hand Topology",
            "GOAT XTB2",
            "GOAT-EXPLORE ExtOpt",
            "CREST NCI",
            "r2SCAN-3c",
        ]
    
        tier_names = [t.tier_name for t in tier_seq]
        assert tier_names == ["T1-10s", "T1-1min", "T1-30min", "T1-1h", "T1-3h"]
    
        # Process a water geometry through the cascade
        xyz_data = "3\nWater\nO 0.0 0.0 0.0\nH 0.0 0.76 0.59\nH 0.0 -0.76 0.59\n"
        res = orchestrator.process_geometry("test_geom_01", xyz_data)
    
        # 1. Assertions on OrchestratorPayload output
        assert res.geom_id == "test_geom_01"
>       assert res.final_status == "SUCCESS"
E       AssertionError: assert 'FAILED_PARSE' == 'SUCCESS'
E         
E         - SUCCESS
E         + FAILED_PARSE

tests\test_cascade_orchestrator.py:60: AssertionError
------------------------------ Captured log call ------------------------------
ERROR    CoChem.TOPOS.CascadeOrchestrator:cochem_topos_cascade_orchestrator.py:663 Failed to parse initial geometry for test_geom_01: cannot access local variable 'ase_read' where it is not associated with a value
_____________ test_gradient_payload_valid_cases[valid_gradient0] ______________

valid_gradient = []

    @pytest.mark.parametrize(
        "valid_gradient",
        [
            [],
            [[1.0, 2.0, 3.0]],
            [[0.01, -0.02, 0.005], [0.0, 0.01, -0.005], [-0.01, 0.01, 0.0]],
            [[1e-12, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            [[0.0, 0.0, 1e-8]],
            [1e-15, 0.0, 0.0],
            [-0.5, 0.2, 0.1],
        ],
    )
    def test_gradient_payload_valid_cases(valid_gradient: list) -> None:
        """
        Verify GradientPayload accepts valid non-zero gradients, small floating-point
        gradients above numerical threshold, and legitimately empty gradient lists.
        """
>       payload = GradientPayload(energy=-76.4, gradient=valid_gradient, hessian=[])
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       pydantic_core._pydantic_core.ValidationError: 1 validation error for GradientPayload
E       gradient
E         Value error, Spoofing detected: Empty gradients are strictly prohibited. [type=value_error, input_value=[], input_type=list]
E           For further information visit https://errors.pydantic.dev/2.13/v/value_error

tests\test_cascade_orchestrator.py:176: ValidationError
_______________________ test_goat_conformer_generation ________________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_goat_conformer_generation0')

    def test_goat_conformer_generation(    tmp_path: Path,
    ) -> None:
        """Verify GOAT conformer generation returns expected count and geometry sizes."""
        atoms = Atoms(
            "H2O",
            positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)],
            cell=[10, 10, 10],
            pbc=True,
        )
        crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_goat.h5"))
>       conformers = crusher._execute_goat_conformer_generation(atoms, num_conformers=3)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_crusher.py:84: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
core_engine\cochem_topos_crusher.py:548: in _execute_goat_conformer_generation
    generated_conformers = [f.result() for f in futures]
                            ^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\concurrent\futures\_base.py:456: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\concurrent\futures\_base.py:401: in __get_result
    raise self._exception
C:\Users\ansac\anaconda3\Lib\concurrent\futures\thread.py:59: in run
    result = self.fn(*self.args, **self.kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:526: in _goat_single_worker
    atoms_copy.calc = get_honest_xtb_calculator()
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

method = 'GFN2-xTB'

    def get_honest_xtb_calculator(method="GFN2-xTB"):
>       from xtb.ase.calculator import XTB
E       ModuleNotFoundError: No module named 'xtb'

core_engine\cochem_topos_crusher.py:24: ModuleNotFoundError
___________________ test_topos01_inhess_xtb2_preconditioner ___________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_topos01_inhess_xtb2_preco0')

    def test_topos01_inhess_xtb2_preconditioner(    tmp_path: Path,
    ) -> None:
        """Verify TOPOS-01: Prohibited Calc_Hess=True removed and replaced with InHess XTB2 preconditioner.
    
        Uses CH4 (n_atoms=5 > 3) to ensure tangential kicks are executed and tested.
        """
        atoms = Atoms(
            "CH4",
            positions=[
                [0.0, 0.0, 0.0],
                [0.63, 0.63, 0.63],
                [-0.63, -0.63, 0.63],
                [-0.63, 0.63, -0.63],
                [0.63, -0.63, -0.63],
            ],
            cell=[10, 10, 10],
            pbc=True,
        )
        crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_topos01.h5"))
>       worker_out = crusher._goat_single_worker(atoms, kick_magnitude=0.5)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_crusher.py:109: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
core_engine\cochem_topos_crusher.py:526: in _goat_single_worker
    atoms_copy.calc = get_honest_xtb_calculator()
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

method = 'GFN2-xTB'

    def get_honest_xtb_calculator(method="GFN2-xTB"):
>       from xtb.ase.calculator import XTB
E       ModuleNotFoundError: No module named 'xtb'

core_engine\cochem_topos_crusher.py:24: ModuleNotFoundError
________________ test_topos02_two_stage_deduplication_protocol ________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_topos02_two_stage_dedupli0')

    def test_topos02_two_stage_deduplication_protocol(    tmp_path: Path,
    ) -> None:
        """Verify TOPOS-02: Two-Stage Deduplication Protocol with CREST cross-check and CREGEN referee deduplication."""
        crusher = ToposCrusher(bthr=0.001, hdf5_path=str(tmp_path / "test_topos02.h5"))
        atoms1 = Atoms(
            "H2O",
            positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)],
            cell=[10, 10, 10],
            pbc=True,
        )
        res1 = crusher.process_conformer(atoms1, energy_kcal=-10.0)
        assert res1["status"] == "accepted"
    
        # Secondary CREST crosscheck fallback execution test
>       crest_ensemble = crusher._execute_crest_secondary_crosscheck(atoms1, num_conformers=3)
                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_crusher.py:131: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
core_engine\cochem_topos_crusher.py:195: in _execute_crest_secondary_crosscheck
    return self._execute_goat_conformer_generation(base_atoms, num_conformers=num_conformers)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:548: in _execute_goat_conformer_generation
    generated_conformers = [f.result() for f in futures]
                            ^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\concurrent\futures\_base.py:449: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\concurrent\futures\_base.py:401: in __get_result
    raise self._exception
C:\Users\ansac\anaconda3\Lib\concurrent\futures\thread.py:59: in run
    result = self.fn(*self.args, **self.kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:526: in _goat_single_worker
    atoms_copy.calc = get_honest_xtb_calculator()
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

method = 'GFN2-xTB'

    def get_honest_xtb_calculator(method="GFN2-xTB"):
>       from xtb.ase.calculator import XTB
E       ModuleNotFoundError: No module named 'xtb'

core_engine\cochem_topos_crusher.py:24: ModuleNotFoundError
_________________ test_crest_secondary_crosscheck_subprocess __________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_crest_secondary_crosschec0')

    def test_crest_secondary_crosscheck_subprocess(tmp_path: Path) -> None:
        """Verify external CREST binary execution branch in _execute_crest_secondary_crosscheck."""
        from ase.io import write as ase_write
    
        crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_crest_subp.h5"))
        atoms = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
    
>       result = crusher._execute_crest_secondary_crosscheck(atoms, num_conformers=2)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_crusher.py:149: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
core_engine\cochem_topos_crusher.py:195: in _execute_crest_secondary_crosscheck
    return self._execute_goat_conformer_generation(base_atoms, num_conformers=num_conformers)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:548: in _execute_goat_conformer_generation
    generated_conformers = [f.result() for f in futures]
                            ^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\concurrent\futures\_base.py:456: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\concurrent\futures\_base.py:401: in __get_result
    raise self._exception
C:\Users\ansac\anaconda3\Lib\concurrent\futures\thread.py:59: in run
    result = self.fn(*self.args, **self.kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:526: in _goat_single_worker
    atoms_copy.calc = get_honest_xtb_calculator()
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

method = 'GFN2-xTB'

    def get_honest_xtb_calculator(method="GFN2-xTB"):
>       from xtb.ase.calculator import XTB
E       ModuleNotFoundError: No module named 'xtb'

core_engine\cochem_topos_crusher.py:24: ModuleNotFoundError
________________________ test_shake_constraints_water _________________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_shake_constraints_water0')

    def test_shake_constraints_water(tmp_path: Path) -> None:
        """Verify RATTLE / SHAKE algorithm freezes O-H bond lengths (0.9572 A) and H-H distance (1.5136 A)."""
        crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_shake.h5"))
        # Distorted water molecule with O at origin and stretched O-H bonds
        distorted_water = Atoms(
            symbols=["O", "H", "H"],
            positions=[
                (0.0, 0.0, 0.0),  # O
                (0.0, 1.10, 0.0),  # Distorted H1 (1.1 A vs 0.9572 A)
                (0.0, -0.40, 0.90),  # Distorted H2
            ],
        )
        constrained_water = crusher._apply_shake_constraints(distorted_water)
        pos = constrained_water.positions
        symbols = constrained_water.get_chemical_symbols()
    
        o_idx = symbols.index("O")
        h_indices = [i for i, s in enumerate(symbols) if s == "H"]
    
        d_oh1 = float(np.linalg.norm(pos[h_indices[0]] - pos[o_idx]))
        d_oh2 = float(np.linalg.norm(pos[h_indices[1]] - pos[o_idx]))
        d_hh = float(np.linalg.norm(pos[h_indices[0]] - pos[h_indices[1]]))
    
>       assert np.isclose(d_oh1, 0.9572, atol=1e-3)
E       assert np.False_
E        +  where np.False_ = <function isclose at 0x00000275A19A6330>(1.1, 0.9572, atol=0.001)
E        +    where <function isclose at 0x00000275A19A6330> = np.isclose

tests\test_crusher.py:176: AssertionError
______________________ test_rotamer_merging_neb_barrier _______________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_rotamer_merging_neb_barri0')

    def test_rotamer_merging_neb_barrier(    tmp_path: Path,
    ) -> None:
        """Verify NEB barrier evaluation and rotamer merging during conformer processing."""
        crusher = ToposCrusher(bthr=0.001, hdf5_path=str(tmp_path / "test_neb_merge.h5"))
        atoms1 = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
        isomer_a = Atoms("O", positions=[(0, 0, 0)])
        isomer_b = Atoms("H2", positions=[(0, 0.76, 0.59), (0, -0.76, 0.59)])
    
        # First accept initial basin
        res1 = crusher.process_conformer(atoms1, energy_kcal=-10.0)
        assert res1["status"] == "accepted"
    
        # Create candidate duplicate
        atoms_dup = atoms1.copy()
        atoms_dup.positions += 1e-5
    
        # Run honestly - will calculate true barrier
>       res_merge = crusher.process_conformer(
            candidate=atoms_dup,
            energy_kcal=-10.1,
            isomer_a=isomer_a,
            isomer_b=isomer_b,
        )

tests\test_crusher.py:277: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
core_engine\cochem_topos_crusher.py:288: in process_conformer
    barrier = self._execute_jax_neb(candidate, existing_atoms)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:406: in _execute_jax_neb
    return _execute_ase_neb_barrier(isomer_a, isomer_b)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

img_a = Atoms(symbols='H2O', pbc=False), img_b = Atoms(symbols='H2O', pbc=False)

    def _execute_ase_neb_barrier(img_a: Atoms, img_b: Atoms) -> float:
        if img_a is None or img_b is None or len(img_a) != len(img_b):
            return 999.0
>       from ase.neb import NEB
E       ModuleNotFoundError: No module named 'ase.neb'

core_engine\cochem_topos_crusher.py:371: ModuleNotFoundError
________________ test_process_conformer_crest_crosscheck_flag _________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_process_conformer_crest_c0')

    def test_process_conformer_crest_crosscheck_flag(    tmp_path: Path,
    ) -> None:
        """Verify process_conformer with run_crest_crosscheck=True executes union screening."""
        crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_crosscheck.h5"))
        atoms = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
    
>       res = crusher.process_conformer(atoms, energy_kcal=-10.0, run_crest_crosscheck=True)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_crusher.py:324: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
core_engine\cochem_topos_crusher.py:257: in process_conformer
    crest_ensemble = self._execute_crest_secondary_crosscheck(candidate)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:195: in _execute_crest_secondary_crosscheck
    return self._execute_goat_conformer_generation(base_atoms, num_conformers=num_conformers)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:548: in _execute_goat_conformer_generation
    generated_conformers = [f.result() for f in futures]
                            ^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\concurrent\futures\_base.py:449: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\concurrent\futures\_base.py:401: in __get_result
    raise self._exception
C:\Users\ansac\anaconda3\Lib\concurrent\futures\thread.py:59: in run
    result = self.fn(*self.args, **self.kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:526: in _goat_single_worker
    atoms_copy.calc = get_honest_xtb_calculator()
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

method = 'GFN2-xTB'

    def get_honest_xtb_calculator(method="GFN2-xTB"):
>       from xtb.ase.calculator import XTB
E       ModuleNotFoundError: No module named 'xtb'

core_engine\cochem_topos_crusher.py:24: ModuleNotFoundError
______________________ test_async_process_monomer_phase _______________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_async_process_monomer_pha0')

    def test_async_process_monomer_phase(    tmp_path: Path,
    ) -> None:
        """Verify asynchronous monomer search phase returns accepted monomer conformers."""
        crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_monomer_phase.h5"))
        atoms = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
    
>       result = asyncio.run(crusher.process_monomer_phase(atoms))
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_crusher.py:335: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:195: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:118: in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\base_events.py:725: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:561: in process_monomer_phase
    energy = self._execute_mace_off24m_screen(initial_geometry)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:334: in _execute_mace_off24m_screen
    calc = get_honest_xtb_calculator()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

method = 'GFN2-xTB'

    def get_honest_xtb_calculator(method="GFN2-xTB"):
>       from xtb.ase.calculator import XTB
E       ModuleNotFoundError: No module named 'xtb'

core_engine\cochem_topos_crusher.py:24: ModuleNotFoundError
___________________ test_async_process_strong_complex_phase ___________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_async_process_strong_comp0')

    def test_async_process_strong_complex_phase(    tmp_path: Path,
    ) -> None:
        """Verify asynchronous strong complex assembly phase combining monomer pairs with clearance."""
        crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_strong_phase.h5"))
    
        # Empty monomers
        empty_res = asyncio.run(crusher.process_strong_complex_phase([]))
        assert empty_res == {"strong_complexes": []}
    
        # Monomer list
        m1 = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
        m2 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
        monomers = [{"atoms": m1, "status": "accepted"}, {"atoms": m2, "status": "accepted"}]
    
>       result = asyncio.run(crusher.process_strong_complex_phase(monomers))
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_crusher.py:359: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:195: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:118: in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\base_events.py:725: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:616: in process_strong_complex_phase
    e = self._execute_mace_off24m_screen(cand, isomer_a, iso_b)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:334: in _execute_mace_off24m_screen
    calc = get_honest_xtb_calculator()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

method = 'GFN2-xTB'

    def get_honest_xtb_calculator(method="GFN2-xTB"):
>       from xtb.ase.calculator import XTB
E       ModuleNotFoundError: No module named 'xtb'

core_engine\cochem_topos_crusher.py:24: ModuleNotFoundError
------------------------------ Captured log call ------------------------------
WARNING  root:cochem_topos_crusher.py:585 No monomers available for Strong Complex Assembly.
____________________ test_async_process_weak_complex_phase ____________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_async_process_weak_comple0')

    def test_async_process_weak_complex_phase(    tmp_path: Path,
    ) -> None:
        """Verify asynchronous weak complex assembly phase with clearance and LAM_TRIGGER_REQUIRED handling."""
        crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_weak_phase.h5"))
    
        # Pool size < 2
        insufficient_res = asyncio.run(crusher.process_weak_complex_phase([], []))
        assert insufficient_res == {"weak_complexes": []}
    
        m1 = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
        s1 = Atoms(
            "CH4",
            positions=[
                [0.0, 0.0, 0.0],
                [0.63, 0.63, 0.63],
                [-0.63, -0.63, 0.63],
                [-0.63, 0.63, -0.63],
                [0.63, -0.63, -0.63],
            ],
        )
        monomers = [{"atoms": m1, "status": "accepted"}]
        strong_complexes = [{"atoms": s1, "status": "accepted"}]
    
>       result = asyncio.run(crusher.process_weak_complex_phase(monomers, strong_complexes))
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_crusher.py:388: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:195: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:118: in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\base_events.py:725: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:688: in process_weak_complex_phase
    e = self._execute_mace_off24m_screen(cand, isomer_a, iso_b)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:334: in _execute_mace_off24m_screen
    calc = get_honest_xtb_calculator()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

method = 'GFN2-xTB'

    def get_honest_xtb_calculator(method="GFN2-xTB"):
>       from xtb.ase.calculator import XTB
E       ModuleNotFoundError: No module named 'xtb'

core_engine\cochem_topos_crusher.py:24: ModuleNotFoundError
________________________ test_execute_jax_neb_fallback ________________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_execute_jax_neb_fallback0')

    def test_execute_jax_neb_fallback(    tmp_path: Path,
    ) -> None:
        """Verify ASE physical NEB barrier estimation computation."""
        crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_neb.h5"))
        atoms1 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
        atoms2 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.90)])
    
>       barrier = crusher._execute_jax_neb(atoms1, atoms2)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_crusher.py:400: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
core_engine\cochem_topos_crusher.py:406: in _execute_jax_neb
    return _execute_ase_neb_barrier(isomer_a, isomer_b)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

img_a = Atoms(symbols='H2', pbc=False), img_b = Atoms(symbols='H2', pbc=False)

    def _execute_ase_neb_barrier(img_a: Atoms, img_b: Atoms) -> float:
        if img_a is None or img_b is None or len(img_a) != len(img_b):
            return 999.0
>       from ase.neb import NEB
E       ModuleNotFoundError: No module named 'ase.neb'

core_engine\cochem_topos_crusher.py:371: ModuleNotFoundError
_______________ test_escape_room_execute_thermal_shock_success ________________

    def test_escape_room_execute_thermal_shock_success() -> None:
        """
        Verify deterministic Langevin thermal shock trajectory execution with attached calculator.
        Verifies that Langevin MD steps proceed, updates atomic coordinates, and returns valid Atoms.
        """
        room = EscapeRoom(temperature_k=300.0, seed=42)
        atoms = Atoms(
            ["O", "H", "H"],
            positions=[[0.0, 0.0, 0.0], [0.0, 0.76, 0.59], [0.0, -0.76, 0.59]],
        )
        atoms.calc = LennardJones(sigma=1.0, epsilon=0.1)
    
        initial_pos = atoms.positions.copy()
>       result = room.execute_thermal_shock(atoms, steps=20, dt_fs=1.0)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_escape.py:302: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <core_engine.cochem_topos_escape.EscapeRoom object at 0x00000275A4D24B90>
seed_atoms = Atoms(symbols='OH2', pbc=False, calculator=LennardJones(...))
steps = 20, dt_fs = 1.0

    def execute_thermal_shock(self, seed_atoms: Atoms, steps: int = 100, dt_fs: float = 4.0) -> Atoms:
        """
        Runs a deterministic Langevin trajectory.
        Uses SHAKE constraints and checks for geometric explosion.
        """
        md_atoms = seed_atoms.copy()
    
        if md_atoms.calc is None:
>           raise ValueError("No calculator attached. Cannot run thermal shock.")
E           ValueError: No calculator attached. Cannot run thermal shock.

core_engine\cochem_topos_escape.py:171: ValueError
________________ test_escape_room_thermal_shock_explosion_trap ________________

    def test_escape_room_thermal_shock_explosion_trap() -> None:
        """
        Verify exploded geometry trap: when atoms violate minimum distance threshold (< 0.4 A),
        the trap aborts the trajectory early and safely returns None.
        """
        room = EscapeRoom(temperature_k=300.0, seed=42)
        # Place two atoms dangerously close (0.2 A < 0.4 A threshold)
        exploded_atoms = Atoms(["O", "H"], positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.2]])
        exploded_atoms.calc = LennardJones()
    
>       result = room.execute_thermal_shock(exploded_atoms, steps=10, dt_fs=1.0)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_escape.py:333: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <core_engine.cochem_topos_escape.EscapeRoom object at 0x00000275A4B82FD0>
seed_atoms = Atoms(symbols='OH', pbc=False, calculator=LennardJones(...))
steps = 10, dt_fs = 1.0

    def execute_thermal_shock(self, seed_atoms: Atoms, steps: int = 100, dt_fs: float = 4.0) -> Atoms:
        """
        Runs a deterministic Langevin trajectory.
        Uses SHAKE constraints and checks for geometric explosion.
        """
        md_atoms = seed_atoms.copy()
    
        if md_atoms.calc is None:
>           raise ValueError("No calculator attached. Cannot run thermal shock.")
E           ValueError: No calculator attached. Cannot run thermal shock.

core_engine\cochem_topos_escape.py:171: ValueError
____________ test_escape_room_thermal_shock_parity_lock_rejection _____________

    def test_escape_room_thermal_shock_parity_lock_rejection() -> None:
        """
        Verify that if a thermal shock trajectory violates chiral parity invariance,
        ParityLock blocks acceptance and execute_thermal_shock returns None.
        (This test used to force rejection via monkeypatch. Now we test that
        a regular thermal shock preserves parity and succeeds.)
        """
        room = EscapeRoom(temperature_k=300.0, seed=42)
        atoms = Atoms(
            ["O", "H", "H"],
            positions=[[0.0, 0.0, 0.0], [0.0, 0.76, 0.59], [0.0, -0.76, 0.59]],
        )
        atoms.calc = LennardJones(sigma=1.0, epsilon=0.1)
    
>       result = room.execute_thermal_shock(atoms, steps=20, dt_fs=1.0)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_escape.py:351: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <core_engine.cochem_topos_escape.EscapeRoom object at 0x00000275AA97A2C0>
seed_atoms = Atoms(symbols='OH2', pbc=False, calculator=LennardJones(...))
steps = 20, dt_fs = 1.0

    def execute_thermal_shock(self, seed_atoms: Atoms, steps: int = 100, dt_fs: float = 4.0) -> Atoms:
        """
        Runs a deterministic Langevin trajectory.
        Uses SHAKE constraints and checks for geometric explosion.
        """
        md_atoms = seed_atoms.copy()
    
        if md_atoms.calc is None:
>           raise ValueError("No calculator attached. Cannot run thermal shock.")
E           ValueError: No calculator attached. Cannot run thermal shock.

core_engine\cochem_topos_escape.py:171: ValueError
_________ test_escape_room_photochemical_shock_orca_input_formatting __________

    def test_escape_room_photochemical_shock_orca_input_formatting() -> None:
        """
        Verify ORCA TD-DFT MECP input syntax formatting generated by EscapeRoom.format_orca_mecp_input
        adheres to computational chemistry specifications.
        """
        room = EscapeRoom()
        atoms = Atoms(["H", "H"], positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        excited_state = 2
>       orca_input = room.format_orca_mecp_input(atoms, excited_state=excited_state)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: 'EscapeRoom' object has no attribute 'format_orca_mecp_input'

tests\test_escape.py:378: AttributeError
_____________ test_oet_server_process_daemon_response_edge_cases ______________

    def test_oet_server_process_daemon_response_edge_cases() -> None:
        """Verify daemon response parsing across valid data, empty payloads, and missing keys."""
        client = OETServerIPCClient(scf_tole=1e-5)
    
        # 1. Normal payload with forces
        forces = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
        resp = client.process_daemon_response({"energy": -42.5, "forces": forces})
        assert resp["status"] == "SUCCESS"
        assert resp["energy_hartree"] == -42.5
        assert resp["scf_threshold"] == 1e-5
        np.testing.assert_array_almost_equal(resp["gradients_hartree_bohr"], -forces)
    
        # 2. Empty payload (default fallback)
>       resp_empty = client.process_daemon_response({})
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_master.py:173: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <core_engine.cochem_topos_master.OETServerIPCClient object at 0x00000275AA61B570>
response = {}

    def process_daemon_response(self, response: dict) -> dict:
        """
        Processes response payload from oet_server daemon.
        Applies gradient sign-flip guard and float32 precision check.
        """
        if "energy" not in response:
>           raise ValueError("Daemon response missing 'energy' key. Calculation failed.")
E           ValueError: Daemon response missing 'energy' key. Calculation failed.

core_engine\cochem_topos_master.py:82: ValueError
_______________________ test_zmq_ui_listener_lifecycle ________________________

master_integrator = <core_engine.cochem_topos_master.TOPOSMasterIntegrator object at 0x00000275AA97A780>

    def test_zmq_ui_listener_lifecycle(master_integrator: TOPOSMasterIntegrator) -> None:
        """Verify the ZMQ UI listener daemon receives commands and returns ACKs without socket leaks."""
        async def run_listener_test() -> None:
            port = master_integrator.zmq_port
            ui_task = asyncio.create_task(master_integrator._zmq_ui_listener())
    
            client_ctx = zmq.asyncio.Context()
            client_sock = client_ctx.socket(zmq.REQ)
            client_sock.connect(f"tcp://127.0.0.1:{port}")
    
            try:
                # Send test command
                await client_sock.send_json({"command": "PING", "payload": "status_check"})
                response = await client_sock.recv_json()
                assert response["status"] == "ACK"
                assert response["message"] == "Command received"
            finally:
                client_sock.close(linger=0)
                client_ctx.term()
                ui_task.cancel()
                await asyncio.gather(ui_task, return_exceptions=True)
    
>       asyncio.run(run_listener_test())

tests\test_master.py:232: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:195: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:118: in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\base_events.py:725: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    async def run_listener_test() -> None:
        port = master_integrator.zmq_port
        ui_task = asyncio.create_task(master_integrator._zmq_ui_listener())
    
        client_ctx = zmq.asyncio.Context()
        client_sock = client_ctx.socket(zmq.REQ)
        client_sock.connect(f"tcp://127.0.0.1:{port}")
    
        try:
            # Send test command
            await client_sock.send_json({"command": "PING", "payload": "status_check"})
            response = await client_sock.recv_json()
>           assert response["status"] == "ACK"
E           AssertionError: assert 'ERROR' == 'ACK'
E             
E             - ACK
E             + ERROR

tests\test_master.py:224: AssertionError
____________________ test_execute_nested_assembly_pipeline ____________________

tmp_path = WindowsPath('C:/Users/ansac/AppData/Local/Temp/pytest-of-ansac/pytest-7249/test_execute_nested_assembly_p0')

    def test_execute_nested_assembly_pipeline(tmp_path: Path) -> None:
        """Verify execute_nested_assembly_pipeline executes monomer, strong, and weak complex phases and escalates."""
        config_file, hdf5_file = create_mock_environment(tmp_path)
        port = get_free_port()
    
        async def run_pipeline() -> None:
            master = TOPOSMasterIntegrator(
                config_path=str(config_file),
                hdf5_path=str(hdf5_file),
                zmq_port=port,
            )
            try:
                h2 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
                await master.execute_nested_assembly_pipeline(h2)
            finally:
                master.close()
    
>       asyncio.run(run_pipeline())

tests\test_master.py:273: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:195: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\runners.py:118: in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
C:\Users\ansac\anaconda3\Lib\asyncio\base_events.py:725: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
tests\test_master.py:269: in run_pipeline
    await master.execute_nested_assembly_pipeline(h2)
core_engine\cochem_topos_master.py:177: in execute_nested_assembly_pipeline
    monomer_result = await self.crusher.process_monomer_phase(initial_geometry)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:561: in process_monomer_phase
    energy = self._execute_mace_off24m_screen(initial_geometry)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
core_engine\cochem_topos_crusher.py:334: in _execute_mace_off24m_screen
    calc = get_honest_xtb_calculator()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

method = 'GFN2-xTB'

    def get_honest_xtb_calculator(method="GFN2-xTB"):
>       from xtb.ase.calculator import XTB
E       ModuleNotFoundError: No module named 'xtb'

core_engine\cochem_topos_crusher.py:24: ModuleNotFoundError
=========================== short test summary info ===========================
FAILED tests/test_cascade_orchestrator.py::test_topos04_v4_t1_search_escalation_routing
FAILED tests/test_cascade_orchestrator.py::test_gradient_payload_valid_cases[valid_gradient0]
FAILED tests/test_crusher.py::test_goat_conformer_generation - ModuleNotFound...
FAILED tests/test_crusher.py::test_topos01_inhess_xtb2_preconditioner - Modul...
FAILED tests/test_crusher.py::test_topos02_two_stage_deduplication_protocol
FAILED tests/test_crusher.py::test_crest_secondary_crosscheck_subprocess - Mo...
FAILED tests/test_crusher.py::test_shake_constraints_water - assert np.False_
FAILED tests/test_crusher.py::test_rotamer_merging_neb_barrier - ModuleNotFou...
FAILED tests/test_crusher.py::test_process_conformer_crest_crosscheck_flag - ...
FAILED tests/test_crusher.py::test_async_process_monomer_phase - ModuleNotFou...
FAILED tests/test_crusher.py::test_async_process_strong_complex_phase - Modul...
FAILED tests/test_crusher.py::test_async_process_weak_complex_phase - ModuleN...
FAILED tests/test_crusher.py::test_execute_jax_neb_fallback - ModuleNotFoundE...
FAILED tests/test_escape.py::test_escape_room_execute_thermal_shock_success
FAILED tests/test_escape.py::test_escape_room_thermal_shock_explosion_trap - ...
FAILED tests/test_escape.py::test_escape_room_thermal_shock_parity_lock_rejection
FAILED tests/test_escape.py::test_escape_room_photochemical_shock_orca_input_formatting
FAILED tests/test_master.py::test_oet_server_process_daemon_response_edge_cases
FAILED tests/test_master.py::test_zmq_ui_listener_lifecycle - AssertionError:...
FAILED tests/test_master.py::test_execute_nested_assembly_pipeline - ModuleNo...
======================== 20 failed, 45 passed in 4.28s ========================

Error: 