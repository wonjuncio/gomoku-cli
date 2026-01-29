from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.app.controller_base import BaseController, ControllerEvent, EventType
from src.core.board import Player, Position
from src.cli.commands import Command, CommandProcessor, CommandType
from src.cli.view import CliView, Message, MessageType
from src.core.game import Game
from src.core.move import Move
from src.net.protocol import MsgType, NetMessage
from src.net.transport import Transport


class RequestKind(Enum):
    SWAP = "SWAP"
    UNDO = "UNDO"
    RESTART = "RESTART"


@dataclass
class PendingRequest:
    kind: RequestKind
    direction: str  # "IN" (host->guest) or "OUT" (guest->host)


class GuestController(BaseController):
    """
    Guest (non-authoritative) controller:
      - Connects to host
      - Sends MOVE requests; host responds by broadcasting APPLY/TURN/WIN or snapshot
      - SWAP/UNDO/RESTART require mutual consent via REQ/RESP
      - Maintains a mirrored Game locally (host is source of truth)
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        name: str = "Guest",
        tick_sec: float = 1.0,
    ) -> None:
        self.host = host
        self.port = port
        self.name = name
        self._you_color: Player = Player.WHITE

        self.transport: Optional[Transport] = None
        self.host_name: str = "Host"

        # These are determined by MATCH
        self.renju: bool = True
        self.board_size: int = 15

        # placeholder local game (will be recreated after MATCH)
        game = Game(board_size=15, starting_player=self._you_color, renju=True)

        view = CliView(
            you_name=name,
            you_color=self._you_color,
            opp_name="(connecting...)",
            opp_color=self._you_color.opponent(),
        )
        cmd = CommandProcessor(board_size=15)
        super().__init__(game=game, view=view, command_processor=cmd, tick_sec=tick_sec)

        self._pending: Optional[PendingRequest] = None

        # Snapshot assembly
        self._snapshot_mode: bool = False

    # ============================================================
    # Base hooks
    # ============================================================

    def on_start(self) -> None:
        print(f"[GUEST] Connecting to {self.host}:{self.port}...")
        print("[GUEST] Waiting for host to start server...")

        self.transport = Transport.connect(self.host, self.port)

        # Send HELLO
        self.transport.send(NetMessage(MsgType.HELLO, {"v": "1", "name": self.name}))

        # Wait for MATCH (and optionally WELCOME/TURN/BOARD)
        match = self._wait_for(MsgType.MATCH, timeout_sec=10.0)
        if match is None:
            self.view.set_message(Message(MessageType.ERR, "Handshake failed: no MATCH"))
            self.stop()
            return

        self.board_size = match.get_int("size", 15)
        self.renju = match.get_bool01("renju", True)
        self._you_color = Player(match.get_int("you", Player.WHITE.value))

        # Recreate game with correct size & renju.
        # starting_player will be set by ENDSTATE/TURN later, but initialize safe default.
        self.game = Game(board_size=self.board_size, starting_player=self._you_color, renju=self.renju)

        # Update command processor and view to reflect actual board size/colors
        self.cmd = CommandProcessor(board_size=self.board_size)

        self.view = CliView(
            you_name=self.name,
            you_color=self._you_color,
            opp_name=self.host_name,
            opp_color=self._you_color.opponent(),
        )

        # Ask for state snapshot right away (host may also send it automatically)
        self.transport.send(NetMessage(MsgType.STATE, {}))

        self.view.set_info("Connected. Waiting for host...")
        self._dirty = True

    def on_stop(self) -> None:
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass

    def on_quit_requested(self) -> None:
        if self.transport is not None:
            try:
                self.transport.send(NetMessage(MsgType.QUIT, {"msg": "guest quit"}))
            except Exception:
                pass
        self.view.set_message(Message(MessageType.QUIT, "Exiting..."))
        self._dirty = True

    @property
    def you_color(self) -> Player:
        return self._you_color
    
    # ============================================================
    # External events
    # ============================================================

    def poll_external_events(self) -> None:
        if self.transport is None:
            return
        while True:
            try:
                msg = self.transport.inbox.get_nowait()
            except queue.Empty:
                return
            self.push_event(ControllerEvent(EventType.REMOTE, msg))

    def handle_event(self, event: ControllerEvent) -> None:
        if event.type != EventType.REMOTE:
            return

        msg: NetMessage = event.payload  # type: ignore[assignment]

        if msg.type == MsgType.QUIT:
            self.view.set_quit("Host left.")
            self._dirty = True
            self.stop()
            return

        if msg.type == MsgType.ERR:
            self.view.set_error(msg.get("msg", "Remote error"))
            self._dirty = True
            return

        # Authoritative incremental updates
        if msg.type == MsgType.APPLY:
            self._handle_apply(msg)
            return

        if msg.type == MsgType.TURN:
            self._handle_turn(msg)
            return

        if msg.type == MsgType.WIN:
            self._handle_win(msg)
            return

        # Snapshot sync
        if msg.type == MsgType.BOARD:
            self._begin_snapshot(msg)
            return

        if msg.type == MsgType.STONE:
            self._apply_snapshot_stone(msg)
            return

        if msg.type == MsgType.ENDSTATE:
            self._end_snapshot(msg)
            return

        # Consent flow
        if msg.type == MsgType.REQ:
            self._handle_incoming_request(msg)
            return

        if msg.type == MsgType.RESP:
            self._handle_response(msg)
            return

        if msg.type == MsgType.MATCH:
            self._handle_match_update(msg)
            return

        # Ignore others (WELCOME/HELLO/etc.)

    # ============================================================
    # User commands
    # ============================================================

    def handle_command(self, command: Command) -> None:
        # y/n response for incoming requests
        if command.type in (CommandType.ACCEPT, CommandType.DECLINE):
            self._handle_yes_no(command.type == CommandType.ACCEPT)
            return

        if self._pending is not None:
            self.view.set_error(f"Pending {self._pending.kind.value}. Respond first (y/n).")
            self._dirty = True
            return

        if command.type == CommandType.SWAP:
            if not self.game.board.is_empty_board():
                self.view.set_error("Swap is only allowed before the game starts.")
                self._dirty = True
                return
            self._request_to_host(RequestKind.SWAP)
            return

        if command.type == CommandType.RESTART:
            self._request_to_host(RequestKind.RESTART)
            return

        if command.type == CommandType.UNDO:
            if not self.can_request_undo():
                self.view.set_error("You can undo only if the last stone is yours.")
                self._dirty = True
                return
            self._request_to_host(RequestKind.UNDO)
            return

        self.view.set_error("Unknown/unsupported command. Use /help")
        self._dirty = True

    # ============================================================
    # User move
    # ============================================================

    def handle_move(self, pos: Position) -> None:
        if self.transport is None:
            self.view.set_error("No connection.")
            self._dirty = True
            return

        # Guest only requests move; host validates and broadcasts APPLY/TURN/WIN
        if self.game.winner is not None:
            self.view.set_error("Game is over.")
            self._dirty = True
            return

        if self.game.current_player != self.you_color:
            self.view.set_error("Not your turn.")
            self._dirty = True
            return

        self.transport.send(NetMessage(MsgType.MOVE, {"x": str(pos.x), "y": str(pos.y)}))
        self.view.set_move(f"{pos.x}, {pos.y} ({pos}) [sent]", is_you=True)
        self._dirty = True

    # ============================================================
    # Authoritative message handlers
    # ============================================================

    def _handle_apply(self, msg: NetMessage) -> None:
        x = msg.get_int("x", 0)
        y = msg.get_int("y", 0)
        color = Player(msg.get_int("color", Player.EMPTY.value))
        pos = Position(x, y)

        # Mirror apply (do NOT call game.make_move; host is authoritative)
        try:
            self.game.board.place(pos, color)
        except Exception:
            # Desync safety: request snapshot
            if self.transport:
                self.transport.send(NetMessage(MsgType.STATE, {}))
            self.view.set_error("Desync detected. Requested STATE.")
            self._dirty = True
            return

        self.game.move_history.append(Move(position=pos, player=color))
        self.game.last_move = pos

        if color == self.you_color:
            self.view.set_move(f"{pos.x}, {pos.y} ({pos})", is_you=True)
        else:
            self.view.set_move(f"{pos.x}, {pos.y} ({pos})", is_you=False)
        self._dirty = True

    def _handle_turn(self, msg: NetMessage) -> None:
        self.game.current_player = Player(msg.get_int("color", Player.BLACK.value))
        self.view.set_message(None)  # clear stale [SWAP] / request message
        self._dirty = True

    def _handle_win(self, msg: NetMessage) -> None:
        self.game.winner = Player(msg.get_int("color", Player.BLACK.value))
        # Winner line is shown by view state indicator; message can be generic
        self.view.set_info("GAME OVER")
        self._dirty = True

    # ============================================================
    # Snapshot handlers
    # ============================================================

    def _begin_snapshot(self, msg: NetMessage) -> None:
        size = msg.get_int("size", self.board_size)
        if size != self.game.board.size:
            # Recreate game if size differs
            self.board_size = size
            self.game = Game(board_size=size, starting_player=self._you_color, renju=self.renju)
            self.cmd = CommandProcessor(board_size=size)
        else:
            self.game.board.clear()

        self.game.move_history.clear()
        self.game.last_move = None
        self.game.winner = None
        self._snapshot_mode = True

    def _apply_snapshot_stone(self, msg: NetMessage) -> None:
        if not self._snapshot_mode:
            return
        x = msg.get_int("x", 0)
        y = msg.get_int("y", 0)
        color = Player(msg.get_int("color", Player.EMPTY.value))
        if color == Player.EMPTY:
            return
        pos = Position(x, y)
        try:
            self.game.board.place(pos, color)
        except Exception:
            # ignore duplicates during snapshot
            pass

    def _end_snapshot(self, msg: NetMessage) -> None:
        turn = Player(msg.get_int("turn", self._you_color.value))
        winner_val = msg.get_int("winner", Player.EMPTY.value)
        winner = None if winner_val == Player.EMPTY.value else Player(winner_val)

        self.game.current_player = turn
        self.game.winner = winner
        self._snapshot_mode = False

        self.view.set_info("State updated.")
        self._dirty = True

    def _handle_match_update(self, msg: NetMessage) -> None:
        self.board_size = msg.get_int("size", self.board_size)
        self.renju = msg.get_bool01("renju", self.renju)

        new_you = Player(msg.get_int("you", self._you_color.value))
        if new_you != self._you_color:
            self._you_color = new_you

            # View도 새 색으로 갱신 (opp는 반대색)
            self.view = CliView(
                you_name=self.name,
                you_color=self._you_color,
                opp_name=self.host_name,
                opp_color=self._you_color.opponent(),
            )

            self.view.set_swap("SWAP applied. Colors changed.")

    # ============================================================
    # Consent flow (REQ/RESP)
    # ============================================================

    def _request_to_host(self, kind: RequestKind) -> None:
        if self.transport is None:
            self.view.set_error("No connection.")
            self._dirty = True
            return

        # SWAP only before start (still ask; host can decline)
        self._pending = PendingRequest(kind=kind, direction="OUT")
        self.transport.send(NetMessage(MsgType.REQ, {"kind": kind.value, "from": self.name}))
        self._set_request_message(kind, outgoing=True)

    def _handle_incoming_request(self, msg: NetMessage) -> None:
        if self.transport is None:
            return

        if self._pending is not None:
            # Busy; auto decline
            self.transport.send(NetMessage(MsgType.RESP, {"kind": msg.get("kind", ""), "ok": "0", "from": self.name, "msg": "busy"}))
            self.view.set_error("Got request while another is pending. Auto-declined.")
            self._dirty = True
            return

        kind_s = msg.get("kind", "")
        try:
            kind = RequestKind(kind_s)
        except Exception:
            self.transport.send(NetMessage(MsgType.RESP, {"kind": kind_s, "ok": "0", "from": self.name, "msg": "unknown kind"}))
            self.view.set_error(f"Unknown request kind: {kind_s}")
            self._dirty = True
            return

        self._pending = PendingRequest(kind=kind, direction="IN")
        self._set_request_message(kind, outgoing=False)

    def _handle_response(self, msg: NetMessage) -> None:
        if self._pending is None or self._pending.direction != "OUT":
            return

        kind_s = msg.get("kind", "")
        ok = msg.get_bool01("ok", False)

        if kind_s != self._pending.kind.value:
            return

        if ok:
            # Host will apply and send snapshot; request one just in case
            if self.transport is not None:
                self.transport.send(NetMessage(MsgType.STATE, {}))
            self._set_result_message(self._pending.kind, accepted=True, by_host=True)
        else:
            self._set_result_message(self._pending.kind, accepted=False, by_host=True)

        self._pending = None

    def _handle_yes_no(self, accept: bool) -> None:
        if self._pending is None or self._pending.direction != "IN":
            self.view.set_error("Nothing to accept/decline.")
            self._dirty = True
            return
        if self.transport is None:
            self.view.set_error("No connection.")
            self._pending = None
            self._dirty = True
            return

        kind = self._pending.kind
        self.transport.send(NetMessage(MsgType.RESP, {"kind": kind.value, "ok": "1" if accept else "0", "from": self.name}))

        if accept:
            # Host will apply and sync; ask snapshot just in case
            self.transport.send(NetMessage(MsgType.STATE, {}))
            self._set_result_message(kind, accepted=True, by_host=False)
        else:
            self._set_result_message(kind, accepted=False, by_host=False)

        self._pending = None

    # ============================================================
    # UI helpers
    # ============================================================

    def _set_request_message(self, kind: RequestKind, *, outgoing: bool) -> None:
        if kind == RequestKind.SWAP:
            if outgoing:
                self.view.set_swap("Requested SWAP. Waiting for opponent (y/n).")
            else:
                self.view.set_swap("Opponent requests SWAP. Accept? (y/n)")
            self._dirty = True
            return

        if kind == RequestKind.RESTART:
            if outgoing:
                self.view.set_restart("Requested RESTART. Waiting for opponent (y/n).")
            else:
                self.view.set_restart("Opponent requests RESTART. Accept? (y/n)")
            self._dirty = True
            return

        if kind == RequestKind.UNDO:
            if outgoing:
                self.view.set_undo("Requested UNDO. Waiting for opponent (y/n).")
            else:
                self.view.set_undo("Opponent requests UNDO. Accept? (y/n)")
            self._dirty = True
            return

    def _set_result_message(self, kind: RequestKind, *, accepted: bool, by_host: bool) -> None:
        who = "Opponent" if by_host else "You"
        verdict = "accepted" if accepted else "declined"

        if kind == RequestKind.SWAP:
            self.view.set_swap(f"{who} {verdict} SWAP.")
        elif kind == RequestKind.RESTART:
            self.view.set_restart(f"{who} {verdict} RESTART.")
        else:
            self.view.set_undo(f"{who} {verdict} UNDO.")
        self._dirty = True

    # ============================================================
    # Handshake helper
    # ============================================================

    def _wait_for(self, mtype: MsgType, timeout_sec: float = 10.0) -> Optional[NetMessage]:
        if self.transport is None:
            return None
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                msg = self.transport.inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg.type == mtype:
                return msg
            if msg.type == MsgType.QUIT:
                return None
            if msg.type == MsgType.MATCH:
                self._handle_match_update(msg)
                return None
        return None
