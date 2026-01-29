from __future__ import annotations

import queue
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.app.controller_base import BaseController, ControllerEvent, EventType
from src.core.board import Player, Position
from src.cli.commands import Command, CommandType, CommandProcessor
from src.cli.view import CliView, Message, MessageType
from src.core.game import Game
from src.net.protocol import MsgType, NetMessage
from src.net.transport import Transport


class RequestKind(Enum):
    SWAP = "SWAP"
    UNDO = "UNDO"
    RESTART = "RESTART"


@dataclass
class PendingRequest:
    kind: RequestKind
    direction: str  # "IN" (guest->host) or "OUT" (host->guest)


class HostController(BaseController):
    """
    Host (authoritative) controller:
      - Owns the authoritative Game state
      - Accepts one guest connection
      - Guest sends MOVE requests; host validates/applies and broadcasts APPLY/TURN/WIN
      - SWAP/UNDO/RESTART require mutual consent via REQ/RESP
    """

    def __init__(
        self,
        *,
        port: int = 33333,
        renju: bool = True,
        you_name: str = "Host",
        board_size: int = 15,
        tick_sec: float = 1.0,
    ) -> None:
        self.port = port
        self.renju = renju
        self.you_name = you_name
        self._you_color: Player = Player.BLACK
        
        self.transport: Optional[Transport] = None
        self.guest_name: str = "Guest"

        # authoritative game: host starts with you_color by default (can SWAP before first move)
        game = Game(board_size=board_size, starting_player=self._you_color, renju=renju)

        # placeholder view (updated after handshake)
        view = CliView(
            you_name=you_name,
            you_color=self._you_color,
            opp_name="(connecting...)",
            opp_color=self._you_color.opponent(),
        )

        cmd = CommandProcessor(board_size=board_size)

        super().__init__(game=game, view=view, command_processor=cmd, tick_sec=tick_sec)

        self._pending: Optional[PendingRequest] = None

    # ============================================================
    # Base hooks
    # ============================================================

    def on_start(self) -> None:
        # Accept connection synchronously before entering loop
        print(f"[HOST] Listening on 0.0.0.0:{self.port} ...")
        print("[HOST] Waiting for one opponent to join...")

        tr, srv = Transport.listen_and_accept("0.0.0.0", self.port)
        # close server socket; keep connection transport
        try:
            srv.close()
        except Exception:
            pass

        self.transport = tr

        # Handshake: expect HELLO
        hello = self._wait_for(MsgType.HELLO)
        if hello is None:
            self.view.set_message(Message(MessageType.ERR, "Handshake failed: no HELLO"))
            self.stop()
            return

        self.guest_name = hello.get("name", "Guest")

        # Replace view with correct opponent info
        self.view = CliView(
            you_name=self.you_name,
            you_color=self._you_color,
            opp_name=self.guest_name,
            opp_color=self._you_color.opponent(),
        )

        # Send WELCOME + MATCH + TURN + initial snapshot
        self.transport.send(NetMessage(MsgType.WELCOME, {"v": "1", "role": "HOST"}))
        self.transport.send(
            NetMessage(
                MsgType.MATCH,
                {
                    "size": str(self.game.board.size),
                    "renju": "1" if self.renju else "0",
                    "you": str(Player.WHITE.value),  # guest is WHITE
                },
            )
        )
        self.transport.send(NetMessage(MsgType.TURN, {"color": str(self.game.current_player.value)}))
        self._send_state_snapshot()

        self.view.set_info("Connected. Game ready.")
        self._dirty = True

    def on_stop(self) -> None:
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass

    def on_quit_requested(self) -> None:
        # notify guest
        if self.transport is not None:
            try:
                self.transport.send(NetMessage(MsgType.QUIT, {"msg": "host quit"}))
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
        """
        Drain transport inbox and push events.
        """
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
            self.view.set_quit("Opponent left.")
            self._dirty = True
            self.stop()
            return

        if msg.type == MsgType.MOVE:
            self._handle_guest_move(msg)
            return

        if msg.type == MsgType.STATE:
            self._send_state_snapshot()
            return

        if msg.type == MsgType.REQ:
            self._handle_incoming_request(msg)
            return

        if msg.type == MsgType.RESP:
            self._handle_response(msg)
            return

        if msg.type == MsgType.ERR:
            self.view.set_error(msg.get("msg", "Remote error"))
            self._dirty = True
            return

        # ignore others by default

    # ============================================================
    # User commands
    # ============================================================

    def handle_command(self, command: Command) -> None:
        # ACCEPT/DECLINE for incoming requests
        if command.type in (CommandType.ACCEPT, CommandType.DECLINE):
            self._handle_yes_no(command.type == CommandType.ACCEPT)
            return

        # Reject actions if already pending something
        if self._pending is not None:
            self.view.set_error(f"Pending {self._pending.kind.value}. Respond first (y/n).")
            self._dirty = True
            return

        if command.type == CommandType.SWAP:
            if not self.game.board.is_empty_board():
                self.view.set_error("Swap is only allowed before the game starts.")
                self._dirty = True
                return
            self._request_to_guest(RequestKind.SWAP)
            return

        if command.type == CommandType.RESTART:
            self._request_to_guest(RequestKind.RESTART)
            return

        if command.type == CommandType.UNDO:
            if not self.can_request_undo():
                self.view.set_error("You can undo only if the last stone is yours.")
                self._dirty = True
                return
            self._request_to_guest(RequestKind.UNDO)
            return
        
        self.view.set_error("Unknown/unsupported command. Use /help")
        self._dirty = True

    # ============================================================
    # User move
    # ============================================================

    def handle_move(self, pos: Position) -> None:
        # Must be host's turn (host is BLACK)
        if self.game.current_player != self._you_color:
            self.view.set_error("Not your turn.")
            self._dirty = True
            return

        result = self.game.make_move(pos)
        if not result.success:
            self.view.set_error(result.error_message)
            self._dirty = True
            return

        # Broadcast authoritative apply
        self._broadcast_apply(pos, self._you_color)

        # UI message
        self.view.set_move(f"{pos.x}, {pos.y} ({pos})", is_you=True)

        # Winner / turn
        self._broadcast_turn_or_win()
        self._dirty = True

    # ============================================================
    # Network handlers
    # ============================================================

    def _handle_guest_move(self, msg: NetMessage) -> None:
        if self.transport is None:
            return

        x = msg.get_int("x", 0)
        y = msg.get_int("y", 0)
        pos = Position(x, y)

        # Must be guest's turn (WHITE)
        if self.game.current_player != self.you_color.opponent():
            self.transport.send(NetMessage(MsgType.ERR, {"msg": "Not your turn"}))
            return

        result = self.game.make_move(pos)
        if not result.success:
            self.transport.send(NetMessage(MsgType.ERR, {"msg": result.error_message}))
            self.view.set_error(f"Guest invalid: {result.error_message}")
            self._dirty = True
            return

        self._broadcast_apply(pos, self.you_color.opponent())
        self.view.set_move(f"{pos.x}, {pos.y} ({pos})", is_you=False)
        self._broadcast_turn_or_win()
        self._dirty = True

    def _broadcast_apply(self, pos: Position, color: Player) -> None:
        if self.transport is None:
            return
        self.transport.send(
            NetMessage(
                MsgType.APPLY,
                {"x": str(pos.x), "y": str(pos.y), "color": str(color.value)},
            )
        )

    def _broadcast_turn_or_win(self) -> None:
        if self.transport is None:
            return
        if self.game.winner is not None:
            self.transport.send(
                NetMessage(
                    MsgType.WIN,
                    {
                        "color": str(self.game.winner.value),
                        "x": str(self.game.last_move.x if self.game.last_move else 0),
                        "y": str(self.game.last_move.y if self.game.last_move else 0),
                    },
                )
            )
        else:
            self.transport.send(NetMessage(MsgType.TURN, {"color": str(self.game.current_player.value)}))

    def _send_state_snapshot(self) -> None:
        """
        Send snapshot:
          BOARD size=..
          STONE x y color ...
          ENDSTATE turn=.. winner=..
        """
        if self.transport is None:
            return

        self.transport.send(NetMessage(MsgType.BOARD, {"size": str(self.game.board.size)}))
        for p, pl in self.game.board.iter_stones():
            self.transport.send(
                NetMessage(
                    MsgType.STONE,
                    {"x": str(p.x), "y": str(p.y), "color": str(pl.value)},
                )
            )
        winner_val = str(self.game.winner.value) if self.game.winner is not None else str(Player.EMPTY.value)
        self.transport.send(
            NetMessage(
                MsgType.ENDSTATE,
                {"turn": str(self.game.current_player.value), "winner": winner_val},
            )
        )

    # ============================================================
    # Consent flow (REQ/RESP)
    # ============================================================

    def _request_to_guest(self, kind: RequestKind) -> None:
        if self.transport is None:
            self.view.set_error("No connection.")
            self._dirty = True
            return

        # Some requests only allowed before game starts, etc.
        if kind == RequestKind.SWAP:
            # swap allowed only if game not started
            if not self.game.board.is_empty_board():
                self.view.set_error("Swap is only allowed before the game starts.")
                self._dirty = True
                return

        self._pending = PendingRequest(kind=kind, direction="OUT")
        self.transport.send(NetMessage(MsgType.REQ, {"kind": kind.value, "from": self.you_name}))
        self._set_request_message(kind, outgoing=True)

    def _handle_incoming_request(self, msg: NetMessage) -> None:
        if self.transport is None:
            return

        if self._pending is not None:
            # Already pending; refuse
            self.transport.send(NetMessage(MsgType.RESP, {"kind": msg.get("kind", ""), "ok": "0", "from": self.you_name, "msg": "busy"}))
            self.view.set_error("Got request while another is pending. Auto-declined.")
            self._dirty = True
            return

        kind_s = msg.get("kind", "")
        try:
            kind = RequestKind(kind_s)
        except Exception:
            self.transport.send(NetMessage(MsgType.RESP, {"kind": kind_s, "ok": "0", "from": self.you_name, "msg": "unknown kind"}))
            self.view.set_error(f"Unknown request kind: {kind_s}")
            self._dirty = True
            return

        # Validate basic constraints early
        if kind == RequestKind.SWAP and not self.game.board.is_empty_board():
            self.transport.send(NetMessage(MsgType.RESP, {"kind": kind.value, "ok": "0", "from": self.you_name, "msg": "swap only before start"}))
            self.view.set_swap("Guest requested SWAP (auto-declined: game already started).")
            self._dirty = True
            return

        self._pending = PendingRequest(kind=kind, direction="IN")
        self._set_request_message(kind, outgoing=False)

    def _handle_response(self, msg: NetMessage) -> None:
        # Response to our outgoing request
        if self._pending is None or self._pending.direction != "OUT":
            return

        kind_s = msg.get("kind", "")
        ok = msg.get_bool01("ok", False)

        # Only act if matches current pending kind
        if kind_s != self._pending.kind.value:
            return

        if ok:
            self._apply_request(self._pending.kind)
            self._set_result_message(self._pending.kind, accepted=True, by_guest=True)
        else:
            self._set_result_message(self._pending.kind, accepted=False, by_guest=True)

        self._pending = None

    def _handle_yes_no(self, accept: bool) -> None:
        """
        Handle local y/n for incoming requests.
        """
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

        # Send response first
        self.transport.send(NetMessage(MsgType.RESP, {"kind": kind.value, "ok": "1" if accept else "0", "from": self.you_name}))

        if accept:
            self._apply_request(kind)
            self._set_result_message(kind, accepted=True, by_guest=False)
        else:
            self._set_result_message(kind, accepted=False, by_guest=False)

        self._pending = None

    def _apply_request(self, kind: RequestKind) -> None:
        """
        Execute the agreed action locally (authoritative), and sync guest via snapshot.
        """
        if kind == RequestKind.SWAP:
            # swap is only allowed before start (already checked)
            # 1) swap colors (YOU <-> OPP)
            self._you_color = self._you_color.opponent()

            # 2) reset game to initial empty state
            self.game.reset()
            # Always black starts
            self.game.current_player = Player.BLACK

            # 3) update host view with new colors
            self.view = CliView(
                you_name=self.you_name,
                you_color=self._you_color,
                opp_name=self.guest_name,
                opp_color=self._you_color.opponent(),
            )
            
            if self.transport is not None:
                self.transport.send(NetMessage(
                    MsgType.MATCH,
                    {
                        "size": str(self.game.board.size),
                        "renju": "1" if self.renju else "0",
                        "you": str(self._you_color.opponent().value),  # guest color
                    }
                ))
                self.transport.send(NetMessage(MsgType.TURN, {"color": str(self.game.current_player.value)}))
                self._send_state_snapshot()

            self.view.set_swap("SWAP applied. Colors changed (Black always starts).")
            self._dirty = True
            return

        if kind == RequestKind.RESTART:
            self.game.reset()
            self._send_state_snapshot()
            self._dirty = True
            return

        if kind == RequestKind.UNDO:
            ok = self.game.undo_last_move()
            if not ok:
                # still sync to keep consistent
                self.view.set_error("No moves to undo.")
            self._send_state_snapshot()
            self._dirty = True
            return

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

    def _set_result_message(self, kind: RequestKind, *, accepted: bool, by_guest: bool) -> None:
        who = "Opponent" if by_guest else "You"
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
        """
        Pull messages from transport inbox until given type is found or timeout.
        """
        if self.transport is None:
            return None

        deadline = __import__("time").time() + timeout_sec
        while __import__("time").time() < deadline:
            try:
                msg = self.transport.inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg.type == mtype:
                return msg
            if msg.type == MsgType.QUIT:
                return None
            # ignore other messages during handshake
        return None
