"""The historical headless physical-pass harness has been retired.

Use ``python -m topos run --request request.json --output-root runs`` for a
calculation. Run the versioned test suite with pytest for verification evidence.
"""
from topos.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
