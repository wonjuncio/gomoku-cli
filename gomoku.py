# gomoku.py
# Minimal CMD Gomoku 15x15 (5-in-a-row), line-based protocol over TCP.
# Usage:
#   Host: python gomoku.py host --port 33333
#   Join: python gomoku.py join --host <HOST_IP> --port 33333
#
# Controls:
#   - Enter move as: "x y"  (1..15)
#   - Or "h8" / "H8" style: letter (A-O) then number (1-15), e.g. H8
#   - Commands: /swap, /restart, /undo, /quit, /help

import argparse
import os
import queue
import socket
import sys
import threading
import select
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Callable

from computer import GomokuAI

# Windows non-blocking input
if os.name == "nt":
    import msvcrt

SIZE = 15
WIN = 5

# ---------------- Protocol helpers ----------------

def parse_line(line: str):
    line = line.strip()
    if not line:
        return None, {}
    parts = line.split()
    cmd = parts[0].upper()
    kv = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k] = v.strip()
    return cmd, kv

def fmt(cmd: str, **kv):
    # Simple: COMMAND key=value key=value
    items = [cmd]
    for k, v in kv.items():
        items.append(f"{k}={v}")
    return " ".join(items) + "\n"

# ---------------- Game logic ----------------

def in_bounds(x: int, y: int) -> bool:
    return 1 <= x <= SIZE and 1 <= y <= SIZE

def check_win(board: List[List[str]], x: int, y: int, stone: str, renju_rules: bool = False) -> bool:
    dirs = [(1,0),(0,1),(1,1),(1,-1)]
    for dx, dy in dirs:
        count = 1
        nx, ny = x + dx, y + dy
        while in_bounds(nx, ny) and board[ny-1][nx-1] == stone:
            count += 1
            nx += dx
            ny += dy
        nx, ny = x - dx, y - dy
        while in_bounds(nx, ny) and board[ny-1][nx-1] == stone:
            count += 1
            nx -= dx
            ny -= dy
        if renju_rules:
            if count == WIN:
                return True
        else:
            if count >= WIN:
                return True
    return False

def count_line(board: List[List[str]], x: int, y: int, stone: str, dx: int, dy: int) -> Tuple[int, bool]:
    """Count consecutive stones in one direction"""
    count = 1
    nx, ny = x + dx, y + dy
    while in_bounds(nx, ny) and board[ny-1][nx-1] == stone:
        count += 1
        nx += dx
        ny += dy
    forward_end_x, forward_end_y = nx, ny
    
    nx, ny = x - dx, y - dy
    while in_bounds(nx, ny) and board[ny-1][nx-1] == stone:
        count += 1
        nx -= dx
        ny -= dy
    backward_end_x, backward_end_y = nx, ny
    
    forward_open = in_bounds(forward_end_x, forward_end_y) and board[forward_end_y-1][forward_end_x-1] == "."
    backward_open = in_bounds(backward_end_x, backward_end_y) and board[backward_end_y-1][backward_end_x-1] == "."
    is_open = forward_open and backward_open
    
    return count, is_open

def check_forbidden_move(board: List[List[str]], x: int, y: int, stone: str, renju_rules: bool) -> Tuple[bool, Optional[str]]:
    """Check if move violates renju rules (6+, 33, 44)"""
    if not renju_rules:
        return True, None
    
    board[y-1][x-1] = stone
    
    dirs = [(1,0),(0,1),(1,1),(1,-1)]
    open_threes = 0
    open_fours = 0
    has_six_or_more = False
    
    for dx, dy in dirs:
        count, is_open = count_line(board, x, y, stone, dx, dy)
        
        if count >= 6:
            has_six_or_more = True
        elif count == 3 and is_open:
            open_threes += 1
        elif count == 4 and is_open:
            open_fours += 1
    
    board[y-1][x-1] = "."
    
    if has_six_or_more:
        return False, "FORBIDDEN: 6+ in a row (장목 금지)"
    if open_threes >= 2:
        return False, "FORBIDDEN: Double three (33 금지)"
    if open_fours >= 2:
        return False, "FORBIDDEN: Double four (44 금지)"
    
    return True, None

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def board_to_text(board: List[List[str]]) -> str:
    header_letters = "".join([chr(ord('A') + i).rjust(2) for i in range(SIZE)])
    out = []
    out.append("    " + header_letters)
    for y in range(1, SIZE+1):
        row = []
        for x in range(1, SIZE+1):
            c = board[y-1][x-1]
            if c == "O":
                row.append(" O")
            elif c == "X":
                row.append(" X")
            else:
                row.append(" .")
        out.append(str(y).rjust(3) + " " + "".join(row))
    out.append("")
    return "\n".join(out)

def format_move(x: int, y: int) -> str:
    if 1 <= x <= 15 and 1 <= y <= 15:
        col = chr(ord("A") + x - 1)
        return f"{x}, {y} ({col}{y})"
    return f"{x}, {y}"

def parse_move_input(s: str):
    s = s.strip()
    if not s:
        return None
    if s.startswith("/"):
        return s.lower()
    parts = s.split()
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        x, y = int(parts[0]), int(parts[1])
        return (x, y)
    if len(s) >= 2 and s[0].isalpha():
        col = s[0].upper()
        if "A" <= col <= "O":
            x = ord(col) - ord("A") + 1
            rest = s[1:].strip()
            if rest.isdigit():
                y = int(rest)
                return (x, y)
    return "invalid"

# ---------------- Networking ----------------

class LineSocket:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""
        self.lock = threading.Lock()

    def send_line(self, line: str):
        data = line.encode("utf-8")
        with self.lock:
            self.sock.sendall(data)

    def recv_line(self) -> Optional[str]:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("utf-8", errors="replace")

# ---------------- Game State ----------------

@dataclass
class GameState:
    """Manages the game board and state"""
    board: List[List[str]] = field(default_factory=lambda: [["." for _ in range(SIZE)] for _ in range(SIZE)])
    turn: str = "O"
    move_no: int = 0
    game_over: bool = False
    move_history: List[Tuple[int, int, str]] = field(default_factory=list)
    game_started: bool = False
    renju_rules: bool = True
    
    def reset(self):
        """Reset the game to initial state"""
        self.board = [["." for _ in range(SIZE)] for _ in range(SIZE)]
        self.turn = "O"
        self.move_no = 0
        self.game_over = False
        self.game_started = False
        self.move_history = []
    
    def apply_move(self, x: int, y: int, color: str) -> Tuple[bool, Optional[Tuple[str, str]]]:
        """Apply a move to the board. Returns (success, error_tuple_or_None)"""
        if self.game_over:
            return False, ("GAME_OVER", "game already finished")
        if color != self.turn:
            return False, ("NOT_YOUR_TURN", "wait")
        if not in_bounds(x, y):
            return False, ("OUT_OF_RANGE", "x/y must be 1..15")
        if self.board[y-1][x-1] != ".":
            return False, ("OCCUPIED", "already occupied")
        
        # Check renju rules (only for first player O)
        if self.renju_rules and color == "O":
            ok, msg = check_forbidden_move(self.board, x, y, color, self.renju_rules)
            if not ok:
                return False, ("FORBIDDEN_MOVE", msg)
        
        self.board[y-1][x-1] = color
        self.move_no += 1
        self.game_started = True
        self.move_history.append((x, y, color))
        
        # Check win
        if check_win(self.board, x, y, color, self.renju_rules):
            self.game_over = True
            return True, None
        
        # Next turn
        self.turn = "X" if self.turn == "O" else "O"
        return True, None
    
    def undo_last_move(self, requesting_color: str) -> Tuple[bool, Optional[str]]:
        """Undo the last move. Returns (success, error_message_or_None)"""
        if not self.move_history:
            return False, "No moves to undo"
        
        last_x, last_y, last_color = self.move_history[-1]
        if last_color != requesting_color:
            return False, "Can only undo your own last move"
        
        x, y, color = self.move_history.pop()
        self.board[y-1][x-1] = "."
        self.move_no -= 1
        self.turn = requesting_color
        self.game_over = False
        return True, None
    
    def apply_ok(self, x: int, y: int, color: str):
        """Apply a confirmed move (for client side)"""
        if in_bounds(x, y):
            self.board[y-1][x-1] = color
            self.move_history.append((x, y, color))
        self.move_no += 1
        if self.move_no > 0:
            self.game_started = True
    
    def clear_board(self):
        """Clear the board (for receiving BOARD command)"""
        for y in range(SIZE):
            for x in range(SIZE):
                self.board[y][x] = "."
        self.move_history = []
    
    def swap_colors(self):
        """Swap all stone colors on the board (O <-> X)"""
        for y in range(SIZE):
            for x in range(SIZE):
                if self.board[y][x] == "O":
                    self.board[y][x] = "X"
                elif self.board[y][x] == "X":
                    self.board[y][x] = "O"
        
        # Update move_history colors
        new_history = []
        for x, y, color in self.move_history:
            new_color = "X" if color == "O" else "O"
            new_history.append((x, y, new_color))
        self.move_history = new_history

# ---------------- Input Handler ----------------

class InputHandler:
    """Handles platform-specific non-blocking input"""
    
    def __init__(self, message_queue: queue.Queue, on_message: Callable):
        self.q_in = message_queue
        self.on_message = on_message
        self.input_buffer = ""
    
    def get_input(self) -> Optional[str]:
        """Get user input, handling messages while waiting"""
        if os.name == "nt":
            return self._get_input_windows()
        else:
            return self._get_input_unix()
    
    def _get_input_windows(self) -> Optional[str]:
        """Windows non-blocking input with msvcrt"""
        print("> ", end="", flush=True)
        self.input_buffer = ""
        
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch == b'\r':  # Enter
                    print()
                    return self.input_buffer.strip()
                elif ch == b'\x08':  # Backspace
                    if self.input_buffer:
                        self.input_buffer = self.input_buffer[:-1]
                        print('\b \b', end='', flush=True)
                elif ch == b'\x03':  # Ctrl+C
                    return "/quit"
                else:
                    try:
                        char = ch.decode('utf-8')
                        if char.isprintable():
                            self.input_buffer += char
                            print(char, end='', flush=True)
                    except:
                        pass
            else:
                # Check for messages
                result = self._check_messages_windows()
                if result == "disconnect":
                    return None
                time.sleep(0.1)
    
    def _check_messages_windows(self) -> Optional[str]:
        """Check for incoming messages while waiting for input (Windows)"""
        try:
            l = self.q_in.get_nowait()
            if l is None:
                return "disconnect"
            
            needs_reprompt = self.on_message(l)
            if needs_reprompt:
                print("> ", end="", flush=True)
                print(self.input_buffer, end="", flush=True)
            return None
        except queue.Empty:
            return None
    
    def _get_input_unix(self) -> Optional[str]:
        """Unix/Linux non-blocking input with select"""
        while True:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                try:
                    return input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    return "/quit"
            else:
                # Check for messages
                try:
                    l = self.q_in.get_nowait()
                    if l is None:
                        return None
                    self.on_message(l)
                except queue.Empty:
                    pass

# ---------------- Base Session ----------------

class GomokuSession(ABC):
    """Abstract base class for Gomoku game sessions"""
    
    def __init__(self):
        self.state = GameState()
        self.q_in: queue.Queue = queue.Queue()
        self.render_lock = threading.Lock()
        self.status = ""
        self.pending_request: Optional[str] = None
        self.pending_undo_color: Optional[str] = None
        self.my_color: Optional[str] = None
        self.opp_color: Optional[str] = None
        self.my_name = ""
        self.opp_name = ""
        self.ls: Optional[LineSocket] = None
        self.should_quit = False
    
    @abstractmethod
    def setup_connection(self) -> bool:
        """Setup the network connection. Returns True on success."""
        pass
    
    @abstractmethod
    def send_message(self, msg: str):
        """Send a message to the remote peer"""
        pass
    
    @abstractmethod
    def broadcast_state(self):
        """Broadcast the current game state"""
        pass
    
    @abstractmethod
    def handle_move(self, x: int, y: int, color: str) -> Tuple[bool, Optional[Tuple[str, str]]]:
        """Handle a move attempt"""
        pass
    
    @abstractmethod
    def cleanup(self):
        """Cleanup resources on exit"""
        pass
    
    def start_receiver_thread(self):
        """Start the message receiver thread"""
        def recv_loop():
            while True:
                try:
                    l = self.ls.recv_line()
                except Exception:
                    l = None
                self.q_in.put(l)
                if l is None:
                    break
        
        t = threading.Thread(target=recv_loop, daemon=True)
        t.start()
    
    def render(self, status_line: str = ""):
        """Render the game board and status"""
        clear_screen()
        print(board_to_text(self.state.board))
        if status_line:
            print(status_line)
        
        # Turn indicator
        if self.my_color is None or self.state.turn is None:
            turn_indicator = "Waiting..."
            you_stone = "?"
            opp_stone = "?"
        else:
            you_stone = self.my_color
            opp_stone = self.opp_color
            if not self.state.game_over:
                if self.state.turn == self.my_color:
                    turn_indicator = ">>> YOUR TURN <<<"
                else:
                    turn_indicator = ">>> OPP TURN <<<"
            else:
                turn_indicator = "GAME OVER"
        
        print(f"{turn_indicator}   You: {you_stone}   Opponent: {opp_stone} ({self.opp_name})")
        
        if self.state.game_over:
            print("GAME OVER. /restart or /quit")
    
    def handle_pending_request(self, s: str) -> bool:
        """Handle pending y/n request. Returns True if handled."""
        if not self.pending_request:
            return False
        
        s_lower = s.strip().lower()
        if s_lower not in ("y", "yes", "n", "no"):
            self.status = "[ERR] Please type 'y' or 'n' to respond to the request."
            with self.render_lock:
                self.render(self.status)
            return True
        
        response = "y" if s_lower in ("y", "yes") else "n"
        
        if self.pending_request == "swap":
            self._handle_swap_response(response)
        elif self.pending_request == "restart":
            self._handle_restart_response(response)
        elif self.pending_request == "undo":
            self._handle_undo_response(response)
        elif self.pending_request == "quit":
            self._handle_quit_response(response)
        
        self.pending_request = None
        self.pending_undo_color = None
        with self.render_lock:
            self.render(self.status)
        return True
    
    def _handle_swap_response(self, response: str):
        """Handle response to a swap request (base implementation)"""
        self.send_message(fmt("SWAP_RESPONSE", response=response))
        if response == "y":
            self.my_color, self.opp_color = self.opp_color, self.my_color
            self.state.swap_colors()  # Swap all stones on board
            # O is always first player, so turn goes to O
            self.state.turn = "O"
            self.status = f"[SWAP] Colors swapped. You are now {self.my_color}. Turn: {self.state.turn}"
        else:
            self.status = "[SWAP] You declined swap request."
    
    def _handle_restart_response(self, response: str):
        """Handle response to a restart request"""
        self.send_message(fmt("RESTART_RESPONSE", response=response))
        if response == "y":
            self.state.reset()
            self.broadcast_state()
            self.status = "[RESTART] Game restarted!"
        else:
            self.status = "[RESTART] You declined restart request."
    
    def _handle_undo_response(self, response: str):
        """Handle response to an undo request"""
        undo_color = self.pending_undo_color or self.opp_color
        self.send_message(fmt("UNDO_RESPONSE", response=response, color=undo_color))
        if response == "y":
            ok, err = self.state.undo_last_move(undo_color)
            if ok:
                self.broadcast_state()
                self.status = "[UNDO] Last move undone!"
            else:
                self.status = f"[UNDO] Failed: {err}"
        else:
            self.status = "[UNDO] You declined undo request."
    
    def _handle_quit_response(self, response: str):
        """Handle response to a quit request"""
        if response == "y":
            # Send message to opponent
            quit_message = "Opponent has left. Please use Ctrl+C or /quit to exit."
            self.send_message(fmt("SAY", text=quit_message))
            self.should_quit = True
            self.status = "[QUIT] Exiting game."
        else:
            self.status = "[QUIT] Cancelled."
    
    def handle_command(self, cmd: str) -> bool:
        """Handle a command. Returns True if should continue, False to quit."""
        if cmd == "/quit":
            self.pending_request = "quit"
            self.status = "Are you sure you want to quit? (y/n): "
            with self.render_lock:
                self.render(self.status)
            return True
        
        if cmd == "/help":
            help_cmds = "/swap /restart /undo /quit /help"
            if self.state.game_started:
                help_cmds = "/restart /undo /quit /help"
            self.status = f"Input: 'x y' (e.g. 8 8) or 'H8' (A-O + 1-15).\nCommands: {help_cmds}"
            with self.render_lock:
                self.render(self.status)
            return True
        
        if cmd == "/swap":
            return self._handle_swap_command()
        
        if cmd == "/restart":
            return self._handle_restart_command()
        
        if cmd == "/undo":
            return self._handle_undo_command()
        
        return True
    
    def _handle_swap_command(self) -> bool:
        """Handle /swap command"""
        if self.state.game_started:
            self.status = "[ERR] /swap is only available before the game starts."
            with self.render_lock:
                self.render(self.status)
            return True
        
        if self.my_color is None:
            self.status = "[ERR] Not connected yet. Wait for match to start."
            with self.render_lock:
                self.render(self.status)
            return True
        
        self.send_message(fmt("SWAP_REQUEST"))
        self.status = "[SWAP] Request sent. Waiting for response..."
        with self.render_lock:
            self.render(self.status)
        
        # Wait for response
        return self._wait_for_response("SWAP_RESPONSE", self._process_swap_response)
    
    def _process_swap_response(self, kv: dict):
        """Process SWAP_RESPONSE"""
        response = kv.get("response", "n").lower()
        if response == "y":
            self.my_color, self.opp_color = self.opp_color, self.my_color
            self.state.swap_colors()  # Swap all stones on board
            # O is always first player, so turn goes to O
            self.state.turn = "O"
            self.status = f"[SWAP] Colors swapped. You are now {self.my_color}. Turn: {self.state.turn}"
        else:
            self.status = f"[SWAP] {self.opp_name} declined swap request."
    
    def _handle_restart_command(self) -> bool:
        """Handle /restart command"""
        self.send_message(fmt("RESTART_REQUEST"))
        self.status = "[RESTART] Request sent. Waiting for response..."
        with self.render_lock:
            self.render(self.status)
        
        return self._wait_for_response("RESTART_RESPONSE", self._process_restart_response)
    
    def _process_restart_response(self, kv: dict):
        """Process RESTART_RESPONSE"""
        response = kv.get("response", "n").lower()
        if response == "y":
            self.state.reset()
            self.broadcast_state()
            self.status = "[RESTART] Game restarted!"
        else:
            self.status = f"[RESTART] {self.opp_name} declined restart request."
    
    def _handle_undo_command(self) -> bool:
        """Handle /undo command"""
        if self.state.game_over:
            self.status = "[ERR] Game is over. Cannot undo."
            with self.render_lock:
                self.render(self.status)
            return True
        
        if not self.state.game_started or not self.state.move_history:
            self.status = "[ERR] No moves to undo."
            with self.render_lock:
                self.render(self.status)
            return True
        
        last_x, last_y, last_color = self.state.move_history[-1]
        if last_color != self.my_color:
            self.status = "[ERR] Can only undo your own last move."
            with self.render_lock:
                self.render(self.status)
            return True
        
        self.send_message(fmt("UNDO_REQUEST", color=self.my_color))
        self.status = "[UNDO] Request sent. Waiting for response..."
        with self.render_lock:
            self.render(self.status)
        
        return self._wait_for_response("UNDO_RESPONSE", self._process_undo_response)
    
    def _process_undo_response(self, kv: dict):
        """Process UNDO_RESPONSE"""
        response = kv.get("response", "n").lower()
        if response == "y":
            ok, err = self.state.undo_last_move(self.my_color)
            if ok:
                self.broadcast_state()
                self.status = "[UNDO] Last move undone!"
            else:
                self.status = f"[UNDO] Failed: {err}"
        else:
            self.status = f"[UNDO] {self.opp_name} declined undo request."
    
    def _wait_for_response(self, expected_cmd: str, process_fn: Callable) -> bool:
        """Wait for a specific response command. Returns True to continue."""
        while True:
            try:
                l = self.q_in.get(timeout=30)
                if l is None:
                    self.status = "[DISCONNECTED] Opponent left."
                    self.state.game_over = True
                    with self.render_lock:
                        self.render(self.status)
                    return True
                
                cmd, kv = parse_line(l)
                if cmd == expected_cmd:
                    process_fn(kv)
                    with self.render_lock:
                        self.render(self.status)
                    return True
                else:
                    self.q_in.put(l)
                    time.sleep(0.1)
            except queue.Empty:
                self.status = f"[{expected_cmd.replace('_', ' ').title()}] Request timeout."
                with self.render_lock:
                    self.render(self.status)
                return True
    
    def process_incoming_messages(self) -> bool:
        """Process all pending incoming messages. Returns False if disconnected."""
        try:
            while True:
                l = self.q_in.get_nowait()
                if l is None:
                    self.status = "[DISCONNECTED] Opponent left."
                    self.state.game_over = True
                    with self.render_lock:
                        self.render(self.status)
                    return False
                
                if not self.process_message(l):
                    return False
        except queue.Empty:
            pass
        return True
    
    @abstractmethod
    def process_message(self, line: str) -> bool:
        """Process a single incoming message. Returns True to continue."""
        pass
    
    def run(self):
        """Main game loop"""
        if not self.setup_connection():
            return
        
        self.start_receiver_thread()
        self.render()
        
        input_handler = InputHandler(self.q_in, self._on_message_during_input)
        
        while True:
            # Process incoming messages
            if not self.process_incoming_messages():
                if self.state.game_over:
                    pass  # Allow /quit
                else:
                    break
            
            # Get input
            s = input_handler.get_input()
            
            if s is None:
                continue
            
            # Handle pending request
            if self.handle_pending_request(s):
                if self.should_quit:
                    break
                continue
            
            # Parse input
            parsed = parse_move_input(s)
            
            # Handle commands
            if isinstance(parsed, str) and parsed.startswith("/"):
                if not self.handle_command(parsed):
                    break
                continue
            
            if parsed == "invalid":
                self.status = "[ERR] Invalid input. Example: 8 8 or H8"
                with self.render_lock:
                    self.render(self.status)
                continue
            
            if isinstance(parsed, tuple):
                if not self._handle_move_input(parsed):
                    continue
        
        self.cleanup()
        print("Bye.")
    
    @abstractmethod
    def _on_message_during_input(self, line: str) -> bool:
        """Handle a message received during input. Returns True if reprompt needed."""
        pass
    
    @abstractmethod
    def _handle_move_input(self, coords: Tuple[int, int]) -> bool:
        """Handle move input. Returns True if move was attempted."""
        pass

# ---------------- Host Session ----------------

class HostSession(GomokuSession):
    """Host-side game session"""
    
    def __init__(self, port: int, renju_rules: bool = True):
        super().__init__()
        self.port = port
        self.state.renju_rules = renju_rules
        self.my_color = "O"
        self.opp_color = "X"
        self.my_name = "Host"
        self.srv: Optional[socket.socket] = None
        self.conn: Optional[socket.socket] = None
    
    def setup_connection(self) -> bool:
        """Setup the server and wait for connection"""
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("0.0.0.0", self.port))
        self.srv.listen(1)
        
        print(f"[HOST] Listening on 0.0.0.0:{self.port} ...")
        print("[HOST] Waiting for one opponent to join...")
        
        self.conn, addr = self.srv.accept()
        self.conn.settimeout(None)
        self.ls = LineSocket(self.conn)
        print(f"[HOST] Opponent connected from {addr[0]}:{addr[1]}")
        
        # Handshake
        line = self.ls.recv_line()
        if line is None:
            print("[HOST] Connection closed during HELLO.")
            return False
        
        cmd, kv = parse_line(line)
        if cmd != "HELLO":
            self.ls.send_line(fmt("ERR", code="BAD_HELLO", msg="expected HELLO"))
            print("[HOST] Bad HELLO, closing.")
            return False
        
        self.opp_name = kv.get("name", "Player")
        
        # Send welcome
        self.ls.send_line(fmt("WELCOME", v="1", id="remote", role="GUEST"))
        self.ls.send_line(fmt("MATCH", color="X", size=str(SIZE), win=str(WIN)))
        self.ls.send_line(fmt("TURN", color=self.state.turn))
        
        return True
    
    def send_message(self, msg: str):
        """Send message to the client"""
        self.ls.send_line(msg)
    
    def broadcast_state(self):
        """Broadcast the current game state to client"""
        self.ls.send_line(fmt("BOARD", size=str(SIZE)))
        for y in range(1, SIZE+1):
            for x in range(1, SIZE+1):
                c = self.state.board[y-1][x-1]
                if c in ("O", "X"):
                    self.ls.send_line(fmt("STONE", x=str(x), y=str(y), color=c))
        self.ls.send_line(fmt("TURN", color=self.state.turn))
    
    def handle_move(self, x: int, y: int, color: str) -> Tuple[bool, Optional[Tuple[str, str]]]:
        """Handle a move and broadcast result"""
        ok, err = self.state.apply_move(x, y, color)
        
        if ok:
            self.ls.send_line(fmt("OK", move=str(self.state.move_no), x=str(x), y=str(y), color=color))
            if self.state.game_over:
                self.ls.send_line(fmt("WIN", color=color, x=str(x), y=str(y)))
            else:
                self.ls.send_line(fmt("TURN", color=self.state.turn))
        
        return ok, err
    
    def cleanup(self):
        """Cleanup server resources"""
        try:
            self.ls.send_line(fmt("SAY", text="(host left)"))
        except:
            pass
        try:
            self.conn.close()
        except:
            pass
        try:
            self.srv.close()
        except:
            pass
    
    def process_message(self, line: str) -> bool:
        """Process incoming message from client"""
        cmd, kv = parse_line(line)
        
        if cmd == "MOVE":
            return self._process_move(kv)
        elif cmd == "SAY":
            self.status = f"[CHAT] {self.opp_name}: {kv.get('text','')}"
            with self.render_lock:
                self.render(self.status)
        elif cmd == "SWAP_REQUEST":
            return self._process_swap_request()
        elif cmd == "SWAP_RESPONSE":
            return self._process_swap_response_received(kv)
        elif cmd == "RESTART_REQUEST":
            self.pending_request = "restart"
            self.status = f"[REQUEST] {self.opp_name} wants to RESTART. Type 'y' to accept or 'n' to decline: "
            with self.render_lock:
                self.render(self.status)
        elif cmd == "RESTART_RESPONSE":
            return self._process_restart_response_received(kv)
        elif cmd == "UNDO_REQUEST":
            return self._process_undo_request(kv)
        elif cmd == "UNDO_RESPONSE":
            return self._process_undo_response_received(kv)
        elif cmd == "HELLO":
            pass  # Already handled
        else:
            self.ls.send_line(fmt("ERR", code="UNKNOWN_CMD", msg=f"unknown {cmd}"))
        
        return True
    
    def _process_move(self, kv: dict) -> bool:
        """Process a MOVE command from client"""
        try:
            x = int(kv.get("x", "0"))
            y = int(kv.get("y", "0"))
        except ValueError:
            self.ls.send_line(fmt("ERR", code="BAD_MOVE", msg="invalid x/y"))
            return True
        
        ok, err = self.handle_move(x, y, self.opp_color)
        if not ok:
            code, msg = err
            self.ls.send_line(fmt("ERR", code=code, msg=msg))
        
        self.status = f"[OPP MOVE] {format_move(x, y)}"
        with self.render_lock:
            self.render(self.status)
        return True
    
    def _process_swap_request(self) -> bool:
        """Process SWAP_REQUEST from client"""
        if self.state.game_started:
            self.ls.send_line(fmt("ERR", code="GAME_STARTED", msg="Cannot swap after game started"))
            return True
        
        self.pending_request = "swap"
        self.status = f"[REQUEST] {self.opp_name} wants to SWAP colors. Type 'y' to accept or 'n' to decline: "
        with self.render_lock:
            self.render(self.status)
        return True
    
    def _handle_swap_response(self, response: str):
        """Handle response to a swap request (HostSession override)"""
        self.send_message(fmt("SWAP_RESPONSE", response=response))
        if response == "y":
            self.my_color, self.opp_color = self.opp_color, self.my_color
            self.state.swap_colors()  # Swap all stones on board
            # O is always first player, so turn goes to O
            self.state.turn = "O"
            # Send updated match info and turn to guest
            self.ls.send_line(fmt("MATCH", color=self.opp_color, size=str(SIZE), win=str(WIN)))
            self.ls.send_line(fmt("TURN", color=self.state.turn))
            self.status = f"[SWAP] Colors swapped. You are now {self.my_color}. Turn: {self.state.turn}"
        else:
            self.status = "[SWAP] You declined swap request."
    
    def _process_swap_response_received(self, kv: dict) -> bool:
        """Process SWAP_RESPONSE from client (when we requested)"""
        response = kv.get("response", "n").lower()
        if response == "y":
            self.my_color, self.opp_color = self.opp_color, self.my_color
            self.state.swap_colors()  # Swap all stones on board
            # O is always first player, so turn goes to O
            self.state.turn = "O"
            self.ls.send_line(fmt("MATCH", color=self.opp_color, size=str(SIZE), win=str(WIN)))
            self.ls.send_line(fmt("TURN", color=self.state.turn))
            self.status = f"[SWAP] Colors swapped. You are now {self.my_color}. Turn: {self.state.turn}"
        else:
            self.status = f"[SWAP] {self.opp_name} declined swap request."
        with self.render_lock:
            self.render(self.status)
        return True
    
    def _process_restart_response_received(self, kv: dict) -> bool:
        """Process RESTART_RESPONSE from client"""
        response = kv.get("response", "n").lower()
        if response == "y":
            self.state.reset()
            self.broadcast_state()
            self.status = "[RESTART] Game restarted!"
        else:
            self.status = f"[RESTART] {self.opp_name} declined restart request."
        with self.render_lock:
            self.render(self.status)
        return True
    
    def _process_undo_request(self, kv: dict) -> bool:
        """Process UNDO_REQUEST from client"""
        requesting_color = kv.get("color", self.opp_color)
        if not self.state.move_history or self.state.move_history[-1][2] != requesting_color:
            self.ls.send_line(fmt("ERR", code="INVALID_UNDO", msg="Last move is not yours"))
            return True
        
        self.pending_request = "undo"
        self.pending_undo_color = requesting_color
        self.status = f"[REQUEST] {self.opp_name} wants to UNDO last move. Type 'y' to accept or 'n' to decline: "
        with self.render_lock:
            self.render(self.status)
        return True
    
    def _process_undo_response_received(self, kv: dict) -> bool:
        """Process UNDO_RESPONSE from client"""
        response = kv.get("response", "n").lower()
        if response == "y":
            requesting_color = kv.get("color", self.opp_color)
            ok, err = self.state.undo_last_move(requesting_color)
            if ok:
                self.broadcast_state()
                self.status = "[UNDO] Last move undone!"
            else:
                self.status = f"[UNDO] Failed: {err}"
        else:
            self.status = f"[UNDO] {self.opp_name} declined undo request."
        with self.render_lock:
            self.render(self.status)
        return True
    
    def _on_message_during_input(self, line: str) -> bool:
        """Handle message received during input"""
        cmd, kv = parse_line(line)
        
        if cmd == "MOVE":
            self._process_move(kv)
            return True
        elif cmd == "SAY":
            self.status = f"[CHAT] {self.opp_name}: {kv.get('text','')}"
            with self.render_lock:
                self.render(self.status)
            return True
        elif cmd == "SWAP_REQUEST":
            self._process_swap_request()
            return True
        elif cmd == "SWAP_RESPONSE":
            self._process_swap_response_received(kv)
            return True
        elif cmd == "RESTART_REQUEST":
            self.pending_request = "restart"
            self.status = f"[REQUEST] {self.opp_name} wants to RESTART. Type 'y' to accept or 'n' to decline: "
            with self.render_lock:
                self.render(self.status)
            return True
        elif cmd == "UNDO_REQUEST":
            self._process_undo_request(kv)
            return True
        
        return False
    
    def _handle_move_input(self, coords: Tuple[int, int]) -> bool:
        """Handle move input from local user"""
        x, y = coords
        ok, err = self.handle_move(x, y, self.my_color)
        if not ok:
            code, msg = err
            self.status = f"[ERR] {code}: {msg}"
        else:
            self.status = f"[YOU MOVE] {format_move(x, y)}"
        with self.render_lock:
            self.render(self.status)
        return True

# ---------------- Guest Session ----------------

class GuestSession(GomokuSession):
    """Guest-side game session"""
    
    def __init__(self, host: str, port: int, name: str):
        super().__init__()
        self.host = host
        self.port = port
        self.my_name = name
        self.opp_name = "Host"
        self.sock: Optional[socket.socket] = None
    
    def setup_connection(self) -> bool:
        """Connect to host, retrying until host is available"""
        print(f"[GUEST] Connecting to {self.host}:{self.port}...")
        print("[GUEST] Waiting for host to start server...")
        
        retry_count = 0
        while True:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(2)  # 2 second timeout for connection attempt
                self.sock.connect((self.host, self.port))
                self.sock.settimeout(None)  # Remove timeout after successful connection
                self.ls = LineSocket(self.sock)
                
                # Send HELLO
                self.ls.send_line(fmt("HELLO", v="1", name=self.my_name))
                print(f"[GUEST] Connected to host!")
                return True
            except (ConnectionRefusedError, OSError, socket.timeout) as e:
                retry_count += 1
                # Print status every 5 attempts (about every 10 seconds)
                if retry_count % 5 == 0:
                    print(f"[GUEST] Still waiting for host... (attempt {retry_count})")
                time.sleep(2)  # Wait 2 seconds before retrying
            except Exception as e:
                print(f"[GUEST] Connection error: {e}")
                return False
    
    def send_message(self, msg: str):
        """Send message to host"""
        self.ls.send_line(msg)
    
    def broadcast_state(self):
        """Guest doesn't broadcast - host handles this"""
        pass
    
    def handle_move(self, x: int, y: int, color: str) -> Tuple[bool, Optional[Tuple[str, str]]]:
        """Guest sends move to host"""
        self.ls.send_line(fmt("MOVE", x=str(x), y=str(y)))
        return True, None
    
    def cleanup(self):
        """Cleanup socket"""
        try:
            self.sock.close()
        except:
            pass
    
    def process_message(self, line: str) -> bool:
        """Process incoming message from host"""
        cmd, kv = parse_line(line)
        
        if cmd == "WELCOME":
            pass  # Ignore
        elif cmd == "MATCH":
            self.my_color = kv.get("color", "X")
            self.opp_color = "O" if self.my_color == "X" else "X"
            if self.pending_request == "swap":
                self.status = f"[SWAP] Colors swapped. You are now {self.my_color}."
                self.pending_request = None
            with self.render_lock:
                self.render(self.status)
        elif cmd == "TURN":
            self.state.turn = kv.get("color")
            with self.render_lock:
                self.render(self.status)
        elif cmd == "OK":
            x = int(kv.get("x", "0"))
            y = int(kv.get("y", "0"))
            color = kv.get("color", "?")
            self.state.apply_ok(x, y, color)
            self.status = f"[MOVE] {color} -> {format_move(x, y)}"
            with self.render_lock:
                self.render(self.status)
        elif cmd == "ERR":
            self.status = f"[ERR] {kv.get('code','')}: {kv.get('msg','')}"
            with self.render_lock:
                self.render(self.status)
        elif cmd == "WIN":
            color = kv.get("color", "?")
            self.status = f"[WIN] {color} wins!"
            self.state.game_over = True
            with self.render_lock:
                self.render(self.status)
        elif cmd == "BOARD":
            self.state.clear_board()
        elif cmd == "STONE":
            x = int(kv.get("x", "0"))
            y = int(kv.get("y", "0"))
            color = kv.get("color", ".")
            if in_bounds(x, y):
                self.state.board[y-1][x-1] = color
        elif cmd == "SAY":
            self.status = f"[CHAT] {self.opp_name}: {kv.get('text','')}"
            with self.render_lock:
                self.render(self.status)
        elif cmd == "CHAT":
            self.status = f"[CHAT] {kv.get('from','?')}: {kv.get('text','')}"
            with self.render_lock:
                self.render(self.status)
        elif cmd == "SWAP_REQUEST":
            if self.state.game_started:
                self.ls.send_line(fmt("ERR", code="GAME_STARTED", msg="Cannot swap after game started"))
                return True
            self.pending_request = "swap"
            self.status = f"[REQUEST] {self.opp_name} wants to SWAP colors. Type 'y' to accept or 'n' to decline: "
            with self.render_lock:
                self.render(self.status)
        elif cmd == "SWAP_RESPONSE":
            response = kv.get("response", "n").lower()
            if response == "y":
                self.my_color = "O" if self.my_color == "X" else "X"
                self.opp_color = "X" if self.my_color == "O" else "O"
                self.state.swap_colors()  # Swap all stones on board
                # Turn will be set by TURN message from host
                self.status = f"[SWAP] Colors swapped. You are now {self.my_color}."
            else:
                self.status = f"[SWAP] {self.opp_name} declined swap request."
            with self.render_lock:
                self.render(self.status)
        elif cmd == "RESTART_REQUEST":
            self.pending_request = "restart"
            self.status = f"[REQUEST] {self.opp_name} wants to RESTART. Type 'y' to accept or 'n' to decline: "
            with self.render_lock:
                self.render(self.status)
        elif cmd == "RESTART_RESPONSE":
            response = kv.get("response", "n").lower()
            if response == "y":
                self.state.reset()
                self.status = "[RESTART] Game restarted!"
            else:
                self.status = f"[RESTART] {self.opp_name} declined restart request."
            with self.render_lock:
                self.render(self.status)
        elif cmd == "UNDO_REQUEST":
            requesting_color = kv.get("color", "X")
            if not self.state.move_history or self.state.move_history[-1][2] != requesting_color:
                self.ls.send_line(fmt("ERR", code="INVALID_UNDO", msg="Last move is not yours"))
                return True
            self.pending_request = "undo"
            self.pending_undo_color = requesting_color
            self.status = f"[REQUEST] {self.opp_name} wants to UNDO last move. Type 'y' to accept or 'n' to decline: "
            with self.render_lock:
                self.render(self.status)
        elif cmd == "UNDO_RESPONSE":
            response = kv.get("response", "n").lower()
            if response == "y":
                requesting_color = kv.get("color", self.my_color)
                ok, err = self.state.undo_last_move(requesting_color)
                if ok:
                    self.status = "[UNDO] Last move undone!"
                else:
                    self.status = f"[UNDO] Failed: {err}"
            else:
                self.status = f"[UNDO] {self.opp_name} declined undo request."
            with self.render_lock:
                self.render(self.status)
        else:
            self.status = f"[WARN] Unknown cmd: {cmd}"
            with self.render_lock:
                self.render(self.status)
        
        return True
    
    def _on_message_during_input(self, line: str) -> bool:
        """Handle message received during input"""
        self.process_message(line)
        return True
    
    def _handle_move_input(self, coords: Tuple[int, int]) -> bool:
        """Handle move input from local user"""
        if self.state.game_over:
            self.status = "[ERR] Game over."
            with self.render_lock:
                self.render(self.status)
            return False
        
        if self.my_color is None or self.state.turn is None:
            self.status = "[ERR] Not ready yet."
            with self.render_lock:
                self.render(self.status)
            return False
        
        x, y = coords
        if self.state.turn != self.my_color:
            self.status = "[ERR] Not your turn."
            with self.render_lock:
                self.render(self.status)
            return False
        
        self.ls.send_line(fmt("MOVE", x=str(x), y=str(y)))
        self.status = f"[SENT] MOVE {format_move(x, y)}"
        with self.render_lock:
            self.render(self.status)
        return True

# ---------------- PvC Session ----------------

class PvCSession(GomokuSession):
    def __init__(self, renju_rules: bool = True, lvl: int = 2):
        super().__init__()
        self.state.renju_rules = renju_rules
        self.my_color = "O"
        self.opp_color = "X"
        self.my_name = "Player"
        self.opp_name = "Computer"
        self.ai = GomokuAI(self.opp_color, lvl)

    def setup_connection(self) -> bool:
        print("[PvC] Local game starting...")
        self.state.turn = "O"
        return True

    def start_receiver_thread(self):
        pass

    def process_incoming_messages(self) -> bool:
        return True

    def send_message(self, msg: str):
        pass

    def broadcast_state(self):
        pass

    def handle_move(self, x: int, y: int, color: str) -> Tuple[bool, Optional[Tuple[str, str]]]:
        ok, err = self.state.apply_move(x, y, color)
        return ok, err

    def process_message(self, line: str) -> bool:
        return True

    def _on_message_during_input(self, line: str) -> bool:
        return False

    def _handle_move_input(self, coords: Tuple[int, int]) -> bool:
        x, y = coords
        
        # 1. 플레이어 턴 처리
        ok, err = self.handle_move(x, y, self.my_color)
        if not ok:
            code, msg = err
            self.status = f"[ERR] {code}: {msg}"
            with self.render_lock: self.render(self.status)
            return False

        self.status = f"[YOU] {format_move(x, y)}"
        with self.render_lock: self.render(self.status)

        # 2. 게임 안 끝났으면 AI 턴 실행
        if not self.state.game_over:
            self._execute_ai_turn()
            
        return True

    def _execute_ai_turn(self):
        self.status = "AI is thinking..."
        with self.render_lock: self.render(self.status)
        
        time.sleep(0.5)
        
        move = self.ai.get_move(self.state.board)
        if move:
            ax, ay = move
            self.handle_move(ax, ay, self.opp_color)
            self.status = f"[AI] {format_move(ax, ay)}"
        
        with self.render_lock:
            self.render(self.status)
            
    def _handle_restart_command(self) -> bool:
        self.state.reset()
        self.status = "[RESTART] Game reset. Your turn (O)!"
        with self.render_lock:
            self.render(self.status)
        return True

    def _handle_undo_command(self) -> bool:
        """무르기: AI의 수와 나의 수를 모두 취소 (2수 무르기)"""
        if not self.state.game_started or len(self.state.move_history) == 0:
            self.status = "[ERR] No moves to undo."
            with self.render_lock: self.render(self.status)
            return True

        undo_count = 2 if len(self.state.move_history) >= 2 else 1
        
        for _ in range(undo_count):
            if self.state.move_history:
                last_move = self.state.move_history[-1]
                self.state.undo_last_move(last_move[2])

        self.status = f"[UNDO] Reverted {undo_count} move(s)."
        with self.render_lock:
            self.render(self.status)
        return True

    def _handle_swap_command(self) -> bool:
        if self.state.game_started:
            self.status = "[ERR] Cannot swap after game started."
            with self.render_lock: self.render(self.status)
            return True

        # 색상 교체
        self.my_color, self.opp_color = self.opp_color, self.my_color
        self.ai.color = self.opp_color
        self.state.swap_colors() # 혹시 돌이 있다면 교체
        
        # 선공(O) 설정
        self.state.turn = "O"
        
        self.status = f"[SWAP] You are now {self.my_color}. Turn: {self.state.turn}"
        
        # 만약 AI가 선공(O)이 되었다면 즉시 첫 수 실행
        if self.opp_color == "O":
            self.render(self.status)
            self._execute_ai_turn()
        else:
            with self.render_lock:
                self.render(self.status)
        
        return True

    # 부모 클래스의 handle_pending_request도 PvC에선 필요 없으므로 무시
    def handle_pending_request(self, s: str) -> bool:
        return False

    def cleanup(self):
        print("[PvC] Session closed.")

# ---------------- Wrapper functions for backward compatibility ----------------

def run_host(port: int, renju_rules: bool = True):
    """Run as host"""
    session = HostSession(port, renju_rules)
    session.run()

def run_join(host: str, port: int, name: str):
    """Run as guest"""
    session = GuestSession(host, port, name)
    session.run()

def run_pvc(renju_rules: bool = True, lvl: int = 2):
    session = PvCSession(renju_rules, lvl)
    session.run()

# ---------------- Main ----------------

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    ap_host = sub.add_parser("host")
    ap_host.add_argument("--port", type=int, default=33333)
    ap_host.add_argument("--renju", action=argparse.BooleanOptionalAction, default=True, help="Enable renju rules (default: True)")

    ap_join = sub.add_parser("join")
    ap_join.add_argument("--host", required=True)
    ap_join.add_argument("--port", type=int, default=33333)
    ap_join.add_argument("--name", default="Guest")

    ap_pvc = sub.add_parser("pvc")
    ap_pvc.add_argument("--renju", action=argparse.BooleanOptionalAction, default=True, help="Enable renju rules (default: True)")
    ap_pvc.add_argument(
        "--lvl", 
        type=int, 
        default=3, 
        choices=range(1, 6),
        help="Set computer difficulty level (1-5)"
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
