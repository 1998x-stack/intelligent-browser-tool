"""Operator-only local research server entrypoint."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
from .fetcher import SourcePolicy
from .research import ResearchService
from .server import serve


def main():
    parser=argparse.ArgumentParser(description="Evidence Radar: operator-authorized loopback research workspace")
    parser.add_argument("serve",nargs="?",default="serve",choices=["serve"])
    parser.add_argument("--allow-host",action="append",required=True,
                        help="Explicit approved public hostname (repeat for each host)")
    parser.add_argument("--db",default="./outputs/research_workspace.sqlite3")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--token",default=None,
                        help="Session token, preferably use EVIDENCE_RADAR_TOKEN to avoid shell history")
    parser.add_argument("--no-robots",action="store_true",
                        help="Local test-only override; only permitted for synthetic .example hosts")
    args=parser.parse_args()
    if args.no_robots and not all(x.endswith(".example") for x in args.allow_host):
        parser.error("--no-robots is limited to .example integration fixtures")
    policy=SourcePolicy(tuple(args.allow_host),respect_robots=not args.no_robots)
    research=ResearchService(args.db,policy)
    serve(research,port=args.port,token=args.token or os.environ.get("EVIDENCE_RADAR_TOKEN"))


if __name__=="__main__":
    main()
