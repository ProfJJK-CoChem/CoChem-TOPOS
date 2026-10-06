#!/usr/bin/env python3
"""
CoChem-TOPOS Packaging Configuration.
Authoritative packaging specification for CoChem-TOPOS topological discovery,
conformational search, potential energy surface exploration, and deduplication engine.
Governed by Method Matrix v4, FAIR data principles, and the 6-Tier Environment Matrix.
"""

from __future__ import annotations

from pathlib import Path

from setuptools import find_namespace_packages, setup

# Resolve repository root directory cross-platform
REPO_ROOT = Path(__file__).resolve().parent

# Read long description from README.md
readme_path = REPO_ROOT / "README.md"
long_description = ""
if readme_path.is_file():
    with open(readme_path, encoding="utf-8") as fh:
        long_description = fh.read()

# Authoritative dependency requirements across the 6-Tier Environment Matrix
INSTALL_REQUIRES = [
    "networkx>=3.1",
    "scipy>=1.11.0",
    "numpy>=1.24.0",
    "h5py>=3.9.0",
    "pydantic>=2.4.0",
    "mendeleev>=0.14.0",
    "ase>=3.22.0",
    "jinja2>=3.1.0",
    "psutil>=5.9.0",
    "pyyaml>=6.0.0",
    "tblite[ase]>=0.3.0",
    "ipywidgets>=8.0.0",
    "plotly>=5.15.0",
    "pynvml>=11.5.0",
    "pyzmq>=25.0.0",
    "requests>=2.28.0",
]

EXTRAS_REQUIRE = {
    "dev": [
        "pytest>=7.0.0",
        "pytest-cov>=4.0.0",
        "ruff>=0.1.0",
        "mypy>=1.8.0",
        "types-PyYAML>=6.0.0",
        "types-requests>=2.28.0",
    ],
    "hpc": [
        "h5py>=3.9.0",
        "psutil>=5.9.0",
        "pynvml>=11.5.0",
        "pyzmq>=25.0.0",
    ],
    "mlff": [
        "tblite[ase]>=0.3.0",
        "ase>=3.22.0",
        "networkx>=3.1",
    ],
    "ui": [
        "ipywidgets>=8.0.0",
        "plotly>=5.15.0",
    ],
    "all": [
        "pytest>=7.0.0",
        "pytest-cov>=4.0.0",
        "ruff>=0.1.0",
        "mypy>=1.8.0",
        "types-PyYAML>=6.0.0",
        "types-requests>=2.28.0",
        "h5py>=3.9.0",
        "psutil>=5.9.0",
        "pynvml>=11.5.0",
        "pyzmq>=25.0.0",
        "tblite[ase]>=0.3.0",
        "ase>=3.22.0",
        "networkx>=3.1",
        "ipywidgets>=8.0.0",
        "plotly>=5.15.0",
    ],
}

if __name__ == "__main__":
    setup(
        name="cochem-topos",
        version="0.1.0",
        description=(
            "CoChem-TOPOS: Topological Discovery, Conformational Search, "
            "and Deduplication Engine for CoChem-Studio"
        ),
        long_description=long_description,
        long_description_content_type="text/markdown",
        author="Dr. Joshua John Klaassen / CoChem Project",
        author_email="info@cochem.org",
        url="https://github.com/ProfJJK-CoChem/CoChem-TOPOS",
        license="Apache-2.0",
        python_requires=">=3.10",
        packages=find_namespace_packages(
            where=".",
            include=[
                "bench_engine",
                "bench_engine.*",
                "cascade_engine",
                "cascade_engine.*",
                "ci_tools",
                "ci_tools.*",
                "cochem",
                "cochem.*",
                "cochem_topos",
                "cochem_topos.*",
                "configs",
                "configs.*",
                "core_engine",
                "core_engine.*",
                "escalation",
                "escalation.*",
                "export_utils",
                "export_utils.*",
                "frontend",
                "frontend.*",
                "interfaces",
                "interfaces.*",
                "mechanics",
                "mechanics.*",
                "mm",
                "mm.*",
                "orchestrator",
                "orchestrator.*",
                "schemas",
                "schemas.*",
                "scripts",
                "scripts.*",
                "telemetry",
                "telemetry.*",
                "topology",
                "topology.*",
                "topos",
                "topos.*",
            ],
            exclude=[
                "tests*",
                "test_calc*",
                "notebooks*",
                "vib_tmp*",
                ".agent_artifacts*",
                ".trash*",
            ],
        ),
        package_dir={"": "."},
        py_modules=[
            "cochem_topos_web",
            "gpu_point",
            "hetero_config",
            "make_notebook",
            "pes_h5",
        ],
        install_requires=INSTALL_REQUIRES,
        extras_require=EXTRAS_REQUIRE,
        include_package_data=True,
        classifiers=[
            "Development Status :: 4 - Beta",
            "Intended Audience :: Science/Research",
            "Topic :: Scientific/Engineering :: Chemistry",
            "Topic :: Scientific/Engineering :: Physics",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.10",
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12",
            "Programming Language :: Python :: 3.13",
            "Programming Language :: Python :: 3.14",
            "Operating System :: OS Independent",
        ],
        entry_points={
            "console_scripts": [
                "cochem-topos-abcluster=topology.cochem_topos_abcluster:main",
                "cochem-topos-crest-union=topology.cochem_topos_crest_union:main",
                "cochem-topos-cleanup=export_utils.cochem_topos_cleanup:main",
                "cochem-topos-voila=frontend.cochem_topos_voila_runner:main",
                "cochem-topos-pes=pes_h5:main",
                "cochem-topos-hetero=hetero_config:main",
                "cochem-topos-gpu=gpu_point:main",
                "cochem-topos-notebook=make_notebook:main",
                "topos-ui=topos.ui:main",
                "topos-test-runner=topos.cli.test_runner:main",
            ],
        },
    )
