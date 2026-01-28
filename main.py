
from __future__ import annotations

import argparse

from src.app.controller_host import HostController
from src.app.controller_guest import GuestController
from src.app.controller_pvc import PvCController, PvCConfig


def run_host(port: int, renju: bool) -> None:
    ctrl = HostController(port=port, renju=renju)
    print("HostController initialized")
    ctrl.run()


def run_join(host: str, port: int, name: str) -> None:
    ctrl = GuestController(host=host, port=port, name=name)
    ctrl.run()


def run_pvc(renju: bool, lvl: int) -> None:
    cfg = PvCConfig(renju=renju, lvl=lvl, board_size=15, tick_sec=1.0)
    ctrl = PvCController(config=cfg)
    ctrl.run()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    ap_host = sub.add_parser("host")
    ap_host.add_argument("--port", type=int, default=33333)
    ap_host.add_argument(
        "--renju",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable renju rules (default: True)",
    )

    ap_join = sub.add_parser("join")
    ap_join.add_argument("--host", required=True)
    ap_join.add_argument("--port", type=int, default=33333)
    ap_join.add_argument("--name", default="Guest")

    ap_pvc = sub.add_parser("pvc")
    ap_pvc.add_argument(
        "--renju",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable renju rules (default: True)",
    )
    ap_pvc.add_argument(
        "--lvl",
        type=int,
        default=3,
        choices=range(1, 6),
        help="Set computer difficulty level (1-5)",
    )

    args = ap.parse_args()

    if args.mode == "host":
        run_host(args.port, args.renju)
    elif args.mode == "pvc":
        run_pvc(args.renju, args.lvl)
    else:
        run_join(args.host, args.port, args.name)


if __name__ == "__main__":
    main()
