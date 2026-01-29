from __future__ import annotations

import os
import queue
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List

from src.cli.commands import Command, CommandProcessor, CommandType, ParseResult
from src.cli.view import CliView, Message, MessageType
from src.core.board import Position
from src.core.game import Game, Player


# =========================
# Non-blocking input (1s polling)
# =========================

class InputPoller:
    """
    Non-blocking line input with polling.
    - Windows: msvcrt (character polling)
    - Unix: select
    """
    def __init__(self) -> None:
        self._buf: List[str] = []
        self._is_windows = (os.name == "nt")
        if self._is_windows:
            import msvcrt  # type: ignore
            self._msvcrt = msvcrt
        else:
            import select
            self._select = select

    def poll_line(self, timeout_sec: float = 1.0) -> Optional[str]:
        if self._is_windows:
            end = time.time() + timeout_sec
            while time.time() < end:
                if self._msvcrt.kbhit():
                    ch = self._msvcrt.getwch()

                    if ch in ("\r", "\n"):
                        line = "".join(self._buf)
                        self._buf.clear()
                        # move to next line after enter
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        return line.strip()

                    if ch == "\b":
                        if self._buf:
                            self._buf.pop()
                            # erase last char visually
                            sys.stdout.write("\b \b")
                            sys.stdout.flush()
                    else:
                        self._buf.append(ch)
                        sys.stdout.write(ch)
                        sys.stdout.flush()

                time.sleep(0.02)
            return None
        else:
            r, _, _ = self._select.select([sys.stdin], [], [], timeout_sec)
            if r:
                return sys.stdin.readline().strip()
            return None


# =========================
# Events (controller internal)
# =========================

class EventType(Enum):
    SYSTEM = "system"      # disconnect, etc.
    REMOTE = "remote"      # network message parsed
    AI = "ai"              # ai move, etc.


@dataclass(frozen=True)
class ControllerEvent:
    type: EventType
    payload: object


# =========================
# Base Controller
# =========================

class BaseController(ABC):
    """
    Common controller loop:
      - poll external events (network/ai/etc.)
      - poll user input (1s)
      - parse input into Command/Position
      - pump events + handle input
      - render(board + message + state)

    Concrete controllers implement:
      - poll_external_events()
      - handle_event()
      - handle_command()
      - handle_move()
      - on_quit_requested() (optional override)

    OOP rule:
      - Controller orchestrates.
      - Game handles gameplay.
      - View renders only.
      - CommandProcessor parses only.
    """

    def __init__(
        self,
        *,
        game: Game,
        view: CliView,
        command_processor: CommandProcessor,
        tick_sec: float = 1.0,
    ) -> None:
        self.game = game
        self.view = view
        self.cmd = command_processor
        self.tick_sec = tick_sec

        self._input = InputPoller()
        self._running = True

        # Event queue shared by receiver threads etc.
        self._events: "queue.Queue[ControllerEvent]" = queue.Queue()

        # If controllers want to show a one-off message, set it and mark dirty
        self._dirty = True

    # ---------- External event API (thread-safe) ----------

    def push_event(self, event: ControllerEvent) -> None:
        self._events.put(event)

    # ---------- Main loop ----------

    def run(self) -> None:
        """
        Main loop:
          1) pump external events
          2) render if dirty
          3) poll user input (tick_sec)
          4) handle parsed input
        """
        self.on_start()
        self._dirty = True
        self._render()

        while self._running:
            # 1) pull new events from external sources (network/ai threads, etc.)
            self.poll_external_events()

            # 2) handle queued events
            self._pump_events()

            # 3) render only when dirty (when there's input or state change)
            if self._dirty:
                self._render()

            # 4) poll input (non-blocking). Short tick_sec in PvP so we wake up often
            #    and process network events (e.g. opponent move) without ~1s delay.
            line = self._input.poll_line(timeout_sec=self.tick_sec)
            if line is None:
                continue

            parsed = self.cmd.parse(line, expecting_yn=self.expecting_yn())
            if not parsed.ok:
                # empty input is ok-noop
                if parsed.error:
                    self.view.set_message(Message(MessageType.ERR, parsed.error))
                    self._dirty = True
                continue

            if parsed.command is not None:
                self._handle_command(parsed.command)
            elif parsed.position is not None:
                self._handle_move(parsed.position)

        self.on_stop()

    # ---------- Rendering ----------

    def _render(self) -> None:
        # Only render when dirty (when there's input or state change)
        if not self._dirty:
            return
        self.view.render(self.game)
        self._dirty = False

    # ---------- Event pumping ----------

    def _pump_events(self) -> None:
        while True:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                return
            self.handle_event(ev)
            self._dirty = True

    # ---------- Input dispatch ----------

    def _handle_command(self, command: Command) -> None:
        # Common /help handling
        if command.type == CommandType.HELP:
            self.view.set_message(Message(MessageType.ERR, self.cmd.help_text()))
            self._dirty = True
            return

        # Common /quit handling (controllers can override behavior)
        if command.type == CommandType.QUIT:
            self.on_quit_requested()
            self._running = False
            return

        # Accept/Decline are context-dependent (pending requests), so delegate
        self.handle_command(command)

    def _handle_move(self, pos: Position) -> None:
        self.handle_move(pos)
        # Mark dirty after handling move (handle_move should set _dirty if it modifies state)

    # =========================
    # Hooks / Abstract methods
    # =========================
    @property
    @abstractmethod
    def you_color(self) -> Player:
        """Return the local player's stone color."""
        raise NotImplementedError

    def can_request_undo(self) -> bool:
        """PvP default: undo is allowed only if the last move is yours."""
        if not self.game.move_history:
            return False
        return self.game.move_history[-1].player == self.you_color

    def expecting_yn(self) -> bool:
        """True when waiting for y/n (e.g. swap/restart/undo). Override in PvP controllers."""
        return False
    
    def stop(self) -> None:
        self._running = False

    def on_start(self) -> None:
        """Optional hook before loop starts."""
        pass

    def on_stop(self) -> None:
        """Optional hook after loop ends."""
        pass

    def on_quit_requested(self) -> None:
        """
        Default quit behavior: just show message.
        Concrete controllers should override to notify opponent/cleanup.
        """
        self.view.set_message(Message(MessageType.QUIT, "Exiting..."))
        self._dirty = True

    @abstractmethod
    def poll_external_events(self) -> None:
        """
        Pull external events and push them into self.push_event(...).

        Examples:
          - Host/Guest: read network lines from a receiver thread's buffer
          - PVC: generate AI move events when it's AI's turn
        """
        raise NotImplementedError

    @abstractmethod
    def handle_event(self, event: ControllerEvent) -> None:
        """Handle one ControllerEvent."""
        raise NotImplementedError

    @abstractmethod
    def handle_command(self, command: Command) -> None:
        """
        Handle commands except /help and /quit (already processed).
        Must handle:
          - /swap, /restart, /undo
          - ACCEPT / DECLINE (y/n)
        """
        raise NotImplementedError

    @abstractmethod
    def handle_move(self, pos: Position) -> None:
        """Handle a user move input (Position)."""
        raise NotImplementedError
