"""Compatibility entry point for the genuine TOPOS browser and BASE interfaces."""
from topos.ui import parse_request_json, render_streamlit, submit_request

__all__ = ["parse_request_json", "render_streamlit", "submit_request"]

if __name__ == "__main__":
    render_streamlit()
