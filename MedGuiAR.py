"""MedGuiAR entry point: `python MedGuiAR.py` (add `--demo` to run with a simulated camera)."""
import argparse

from medguiar.app import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MedGuiAR medication assistant")
    parser.add_argument("--demo", action="store_true",
                        help="simulated camera and example user; nothing is saved (no webcam needed)")
    main(demo=parser.parse_args().demo)
