"""Compatibility entry point. Prefer the installed `intelligent-browser` CLI."""

from crawler import main

if __name__ == "__main__":
    raise SystemExit(main())
