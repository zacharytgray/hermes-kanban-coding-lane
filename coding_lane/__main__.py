import argparse
import sys

from .cli import handle, setup

parser = argparse.ArgumentParser(prog="coding_lane")
setup(parser)
sys.exit(handle(parser.parse_args()))
