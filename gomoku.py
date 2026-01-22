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
from dataclasses import dataclass

# Windows non-blocking input
if os.name == "nt":
    import msvcrt
else:
    import select

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

def in_bounds(x, y):
    return 1 <= x <= SIZE and 1 <= y <= SIZE

def check_win(board, x, y, stone, renju_rules=False):
    # board indexed [y-1][x-1]
    dirs = [(1,0),(0,1),(1,1),(1,-1)]
    for dx, dy in dirs:
        count = 1
        # forward
        nx, ny = x + dx, y + dy
        while in_bounds(nx, ny) and board[ny-1][nx-1] == stone:
            count += 1
            nx += dx
            ny += dy
        # backward
        nx, ny = x - dx, y - dy
        while in_bounds(nx, ny) and board[ny-1][nx-1] == stone:
            count += 1
            nx -= dx
            ny -= dy
        if renju_rules:
            if count == WIN:  # Exactly 5
                return True
        else:
            if count >= WIN:
                return True
    return False

def count_line(board, x, y, stone, dx, dy):
    """Count consecutive stones in one direction"""
    count = 1
    # Forward
    nx, ny = x + dx, y + dy
    while in_bounds(nx, ny) and board[ny-1][nx-1] == stone:
        count += 1
        nx += dx
        ny += dy
    forward_end_x, forward_end_y = nx, ny
    
    # Backward
    nx, ny = x - dx, y - dy
    while in_bounds(nx, ny) and board[ny-1][nx-1] == stone:
        count += 1
        nx -= dx
        ny -= dy
    backward_end_x, backward_end_y = nx, ny
    
    # Check if line is open (both ends are empty)
    forward_open = in_bounds(forward_end_x, forward_end_y) and board[forward_end_y-1][forward_end_x-1] == "."
    backward_open = in_bounds(backward_end_x, backward_end_y) and board[backward_end_y-1][backward_end_x-1] == "."
    is_open = forward_open and backward_open
    
    return count, is_open

def check_forbidden_move(board, x, y, stone, renju_rules):
    """Check if move violates renju rules (6+, 33, 44)"""
    if not renju_rules:
        return True, None
    
    # Temporarily place stone
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
    
    # Remove temporary stone
    board[y-1][x-1] = "."
    
    if has_six_or_more:
        return False, "FORBIDDEN: 6+ in a row (장목 금지)"
    if open_threes >= 2:
        return False, "FORBIDDEN: Double three (33 금지)"
    if open_fours >= 2:
        return False, "FORBIDDEN: Double four (44 금지)"
    
    return True, None

def clear_screen():
    # CMD-friendly
    os.system("cls" if os.name == "nt" else "clear")

def board_to_text(board):
    # header - x-axis as letters A-O
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


def parse_move_input(s: str):
    s = s.strip()
    if not s:
        return None
    if s.startswith("/"):
        return s.lower()  # command
    # format: "x y"
    parts = s.split()
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        x, y = int(parts[0]), int(parts[1])
        return (x, y)
    # format: H8
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

    def recv_line(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("utf-8", errors="replace")

# ---------------- Server (host) ----------------

@dataclass
class ClientConn:
    ls: LineSocket
    name: str = "Player"

def run_host(port: int, renju_rules: bool = True):
    board = [["." for _ in range(SIZE)] for _ in range(SIZE)]
    turn = "O"  # O starts (first player)
    move_no = 0
    game_over = False
    move_history = []  # List of (x, y, color) for undo
    game_started = False  # Track if game has started

    # connections: host acts as player O locally; remote is X
    remote = None

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)

    print(f"[HOST] Listening on 0.0.0.0:{port} ...")
    print("[HOST] Waiting for one opponent to join...")
    conn, addr = srv.accept()
    conn.settimeout(None)
    remote = ClientConn(LineSocket(conn))
    print(f"[HOST] Opponent connected from {addr[0]}:{addr[1]}")

    # handshake: receive HELLO
    line = remote.ls.recv_line()
    if line is None:
        print("[HOST] Connection closed during HELLO.")
        return
    cmd, kv = parse_line(line)
    if cmd != "HELLO":
        remote.ls.send_line(fmt("ERR", code="BAD_HELLO", msg="expected HELLO"))
        print("[HOST] Bad HELLO, closing.")
        return
    remote.name = kv.get("name", "Player")

    # send WELCOME + MATCH + initial TURN
    remote.ls.send_line(fmt("WELCOME", v="1", id="remote", role="GUEST"))
    remote.ls.send_line(fmt("MATCH", color="X", size=str(SIZE), win=str(WIN)))
    remote.ls.send_line(fmt("TURN", color=turn))

    # host local player details (O = first player, X = second player)
    my_color = "O"
    opp_color = "X"
    my_name = "Host"
    opp_name = remote.name

    # Receiver thread for remote messages -> queue
    q_in = queue.Queue()

    def recv_loop():
        while True:
            try:
                l = remote.ls.recv_line()
            except Exception:
                l = None
            q_in.put(l)
            if l is None:
                break

    t = threading.Thread(target=recv_loop, daemon=True)
    t.start()

    def broadcast_state():
        # send BOARD header then all stones then TURN
        remote.ls.send_line(fmt("BOARD", size=str(SIZE)))
        for y in range(1, SIZE+1):
            for x in range(1, SIZE+1):
                c = board[y-1][x-1]
                if c in ("O", "X"):
                    remote.ls.send_line(fmt("STONE", x=str(x), y=str(y), color=c))
        remote.ls.send_line(fmt("TURN", color=turn))

    def apply_move(x, y, color):
        nonlocal move_no, turn, game_over, move_history, game_started
        # renju_rules is accessible via closure
        if game_over:
            return False, ("GAME_OVER", "game already finished")
        if color != turn:
            return False, ("NOT_YOUR_TURN", "wait")
        if not in_bounds(x, y):
            return False, ("OUT_OF_RANGE", "x/y must be 1..15")
        if board[y-1][x-1] != ".":
            return False, ("OCCUPIED", "already occupied")
        
        # Check renju rules (only for first player O)
        if renju_rules and color == "O":
            ok, msg = check_forbidden_move(board, x, y, color, renju_rules)
            if not ok:
                return False, ("FORBIDDEN_MOVE", msg)
        
        board[y-1][x-1] = color
        move_no += 1
        game_started = True  # Game has started after first move
        move_history.append((x, y, color))  # Save move for undo
        # broadcast OK
        remote.ls.send_line(fmt("OK", move=str(move_no), x=str(x), y=str(y), color=color))
        # check win
        if check_win(board, x, y, color, renju_rules):
            game_over = True
            remote.ls.send_line(fmt("WIN", color=color, x=str(x), y=str(y)))
            return True, None
        # next turn
        turn = "X" if turn == "O" else "O"
        remote.ls.send_line(fmt("TURN", color=turn))
        return True, None
    
    def reset_game():
        nonlocal board, turn, move_no, game_over, move_history, game_started
        board = [["." for _ in range(SIZE)] for _ in range(SIZE)]
        turn = "O"
        move_no = 0
        game_over = False
        game_started = False
        move_history = []
        broadcast_state()
    
    def undo_last_move(requesting_color):
        nonlocal board, turn, move_no, game_over, move_history, game_started
        if not move_history:
            return False, "No moves to undo"
        # Check if last move belongs to the requester
        last_x, last_y, last_color = move_history[-1]
        if last_color != requesting_color:
            return False, "Can only undo your own last move"
        # Remove only the last move (1 move)
        x, y, color = move_history.pop()
        board[y-1][x-1] = "."
        move_no -= 1
        # Turn goes back to the requester
        turn = requesting_color
        game_over = False  # Reset win state
        broadcast_state()
        return True, None

    def render(status_line=""):
        nonlocal show_commands
        clear_screen()
        print(board_to_text(board))
        if status_line:
            print(status_line)
        # Turn indicator
        if not game_over:
            if turn == my_color:
                turn_indicator = ">>> YOUR TURN <<<"
            else:
                turn_indicator = ">>> OPP TURN <<<"
        else:
            turn_indicator = "GAME OVER"
        print(f"{turn_indicator}   You: O   Opponent: X ({opp_name})")
        if game_over:
            print("GAME OVER. /quit to exit.")
        # Show commands list only on first render
        if show_commands:
            help_cmds = "/swap /restart /undo /quit /help"
            if game_started:
                help_cmds = "/restart /undo /quit /help"
            print(f"\nCommands: {help_cmds}")
            print("Input: 'x y' (e.g. 8 8) or 'H8' (A-O + 1-15)")

    status = ""
    show_commands = True  # Show commands list on first render
    render()
    show_commands = False  # Don't show commands list after first render
    
    # Render lock for thread safety
    render_lock = threading.Lock()
    pending_request = None  # "restart" or "undo" when waiting for y/n response

    while True:
        # handle inbound remote messages (non-blocking)
        try:
            while True:
                l = q_in.get_nowait()
                if l is None:
                    status = "[DISCONNECTED] Opponent left."
                    game_over = True
                    with render_lock:
                        render(status)
                    break
                cmd, kv = parse_line(l)
                if cmd == "MOVE":
                    try:
                        x = int(kv.get("x", "0"))
                        y = int(kv.get("y", "0"))
                    except ValueError:
                        remote.ls.send_line(fmt("ERR", code="BAD_MOVE", msg="invalid x/y"))
                        continue
                    ok, err = apply_move(x, y, opp_color)
                    if not ok:
                        code, msg = err
                        remote.ls.send_line(fmt("ERR", code=code, msg=msg))
                    status = f"[OPP MOVE] {x},{y}"
                    with render_lock:
                        render(status)
                elif cmd == "SAY":
                    # optional chat
                    status = f"[CHAT] {opp_name}: {kv.get('text','')}"
                    with render_lock:
                        render(status)
                elif cmd == "SWAP":
                    # Swap colors
                    if not game_started:
                        my_color, opp_color = opp_color, my_color
                        turn = my_color  # Current player's turn
                        remote.ls.send_line(fmt("MATCH", color=opp_color, size=str(SIZE), win=str(WIN)))
                        remote.ls.send_line(fmt("TURN", color=turn))
                        status = f"[SWAP] Colors swapped. You are now {'O' if my_color=='O' else 'X'}."
                        with render_lock:
                            render(status)
                elif cmd == "RESTART_REQUEST":
                    pending_request = "restart"
                    status = f"[REQUEST] {opp_name} wants to RESTART. Type 'y' to accept or 'n' to decline: "
                    with render_lock:
                        render(status)
                elif cmd == "RESTART_RESPONSE":
                    response = kv.get("response", "n").lower()
                    if response == "y":
                        reset_game()
                        status = "[RESTART] Game restarted!"
                    else:
                        status = f"[RESTART] {opp_name} declined restart request."
                    with render_lock:
                        render(status)
                elif cmd == "UNDO_REQUEST":
                    requesting_color = kv.get("color", opp_color)
                    # Verify that last move belongs to the requester
                    if not move_history or move_history[-1][2] != requesting_color:
                        remote.ls.send_line(fmt("ERR", code="INVALID_UNDO", msg="Last move is not yours"))
                        continue
                    pending_request = "undo"
                    pending_undo_color = requesting_color
                    status = f"[REQUEST] {opp_name} wants to UNDO last move. Type 'y' to accept or 'n' to decline: "
                    with render_lock:
                        render(status)
                elif cmd == "UNDO_RESPONSE":
                    response = kv.get("response", "n").lower()
                    if response == "y":
                        requesting_color = kv.get("color", opp_color)
                        ok, err = undo_last_move(requesting_color)
                        if ok:
                            status = "[UNDO] Last move undone!"
                        else:
                            status = f"[UNDO] Failed: {err}"
                    else:
                        status = f"[UNDO] {opp_name} declined undo request."
                    with render_lock:
                        render(status)
                elif cmd == "HELLO":
                    # ignore (already)
                    pass
                else:
                    # unknown
                    remote.ls.send_line(fmt("ERR", code="UNKNOWN_CMD", msg=f"unknown {cmd}"))
        except queue.Empty:
            pass

        if game_over and status.startswith("[DISCONNECTED]"):
            # still allow /quit
            pass

        # local input (non-blocking with periodic updates)
        s = None
        if os.name == "nt":  # Windows
            print("> ", end="", flush=True)
            input_buffer = ""
            while True:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch == b'\r':  # Enter
                        print()  # newline
                        s = input_buffer.strip()
                        break
                    elif ch == b'\x08':  # Backspace
                        if input_buffer:
                            input_buffer = input_buffer[:-1]
                            print('\b \b', end='', flush=True)
                    elif ch == b'\x03':  # Ctrl+C
                        s = "/quit"
                        break
                    else:
                        try:
                            char = ch.decode('utf-8')
                            if char.isprintable():
                                input_buffer += char
                                print(char, end='', flush=True)
                        except:
                            pass
                else:
                    # Check for messages and render updates
                    try:
                        l = q_in.get_nowait()
                        if l is None:
                            status = "[DISCONNECTED] Opponent left."
                            game_over = True
                            with render_lock:
                                render(status)
                            break
                        cmd, kv = parse_line(l)
                        if cmd == "MOVE":
                            try:
                                x = int(kv.get("x", "0"))
                                y = int(kv.get("y", "0"))
                            except ValueError:
                                remote.ls.send_line(fmt("ERR", code="BAD_MOVE", msg="invalid x/y"))
                                continue
                            ok, err = apply_move(x, y, opp_color)
                            if not ok:
                                code, msg = err
                                remote.ls.send_line(fmt("ERR", code=code, msg=msg))
                            status = f"[OPP MOVE] {x},{y}"
                            with render_lock:
                                render(status)
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "SAY":
                            status = f"[CHAT] {opp_name}: {kv.get('text','')}"
                            with render_lock:
                                render(status)
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "SWAP":
                            if not game_started:
                                my_color, opp_color = opp_color, my_color
                                turn = my_color
                                remote.ls.send_line(fmt("MATCH", color=opp_color, size=str(SIZE), win=str(WIN)))
                                remote.ls.send_line(fmt("TURN", color=turn))
                                status = f"[SWAP] Colors swapped. You are now {'O' if my_color=='O' else 'X'}."
                                with render_lock:
                                    render(status)
                                print("> ", end="", flush=True)
                                print(input_buffer, end="", flush=True)
                        elif cmd == "RESTART_REQUEST":
                            pending_request = "restart"
                            status = f"[REQUEST] {opp_name} wants to RESTART. Type 'y' to accept or 'n' to decline: "
                            with render_lock:
                                render(status)
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "UNDO_REQUEST":
                            requesting_color = kv.get("color", opp_color)
                            if not move_history or move_history[-1][2] != requesting_color:
                                remote.ls.send_line(fmt("ERR", code="INVALID_UNDO", msg="Last move is not yours"))
                                print("> ", end="", flush=True)
                                print(input_buffer, end="", flush=True)
                                continue
                            pending_request = "undo"
                            pending_undo_color = requesting_color
                            status = f"[REQUEST] {opp_name} wants to UNDO last move. Type 'y' to accept or 'n' to decline: "
                            with render_lock:
                                render(status)
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                    except queue.Empty:
                        pass
                    time.sleep(0.1)
        else:  # Unix/Linux
            try:
                if select.select([sys.stdin], [], [], 1.5)[0]:
                    s = input("> ").strip()
                else:
                    # Timeout - check for messages and continue
                    continue
            except (EOFError, KeyboardInterrupt):
                s = "/quit"

        if s is None:
            # No input available, continue to check messages
            continue

        # Check for pending request (y/n response)
        if pending_request:
            s_lower = s.strip().lower()
            if s_lower in ("y", "yes", "n", "no"):
                response = "y" if s_lower in ("y", "yes") else "n"
                if pending_request == "restart":
                    remote.ls.send_line(fmt("RESTART_RESPONSE", response=response))
                    if response == "y":
                        reset_game()
                        status = "[RESTART] Game restarted!"
                    else:
                        status = f"[RESTART] You declined restart request."
                elif pending_request == "undo":
                    undo_color = pending_undo_color if pending_undo_color else opp_color
                    remote.ls.send_line(fmt("UNDO_RESPONSE", response=response, color=undo_color))
                    if response == "y":
                        ok, err = undo_last_move(undo_color)
                        if ok:
                            status = "[UNDO] Last move undone!"
                        else:
                            status = f"[UNDO] Failed: {err}"
                    else:
                        status = f"[UNDO] You declined undo request."
                pending_request = None
                pending_undo_color = None
                with render_lock:
                    render(status)
                continue
            else:
                status = "[ERR] Please type 'y' or 'n' to respond to the request."
                with render_lock:
                    render(status)
                continue

        parsed = parse_move_input(s)
        if parsed == "/quit":
            try:
                remote.ls.send_line(fmt("SAY", text="(host left)"))
            except Exception:
                pass
            break
        if parsed == "/help":
            help_cmds = "/swap /restart /undo /quit /help"
            if game_started:
                help_cmds = "/restart /undo /quit /help"
            status = f"Input: 'x y' (e.g. 8 8) or 'H8' (A-O + 1-15).\nCommands: {help_cmds}"
            with render_lock:
                render(status)
            continue
        if parsed == "/swap":
            if game_started:
                status = "[ERR] /swap is only available before the game starts."
                with render_lock:
                    render(status)
                continue
            # Swap colors
            my_color, opp_color = opp_color, my_color
            turn = my_color  # Current player's turn
            remote.ls.send_line(fmt("SWAP"))
            remote.ls.send_line(fmt("MATCH", color=opp_color, size=str(SIZE), win=str(WIN)))
            remote.ls.send_line(fmt("TURN", color=turn))
            status = f"[SWAP] Colors swapped. You are now {'O' if my_color=='O' else 'X'}."
            with render_lock:
                render(status)
            continue
        if parsed == "/restart":
            if game_over:
                status = "[ERR] Game is over. Cannot restart."
                with render_lock:
                    render(status)
                continue
            remote.ls.send_line(fmt("RESTART_REQUEST"))
            status = "[RESTART] Request sent to opponent. Waiting for response..."
            with render_lock:
                render(status)
            # Wait for response
            response_received = False
            while not response_received:
                try:
                    l = q_in.get(timeout=30)  # 30 second timeout
                    if l is None:
                        status = "[DISCONNECTED] Opponent left."
                        game_over = True
                        with render_lock:
                            render(status)
                        break
                    cmd, kv = parse_line(l)
                    if cmd == "RESTART_RESPONSE":
                        response = kv.get("response", "n").lower()
                        if response == "y":
                            reset_game()
                            status = "[RESTART] Game restarted!"
                        else:
                            status = f"[RESTART] {opp_name} declined restart request."
                        with render_lock:
                            render(status)
                        response_received = True
                    else:
                        # Handle other commands normally
                        q_in.put(l)  # Put back for normal processing
                        time.sleep(0.1)
                except queue.Empty:
                    status = "[RESTART] Request timeout. Opponent did not respond."
                    with render_lock:
                        render(status)
                    response_received = True
            continue
        if parsed == "/undo":
            if game_over:
                status = "[ERR] Game is over. Cannot undo."
                with render_lock:
                    render(status)
                continue
            if not game_started or not move_history:
                status = "[ERR] No moves to undo."
                with render_lock:
                    render(status)
                continue
            # Check if last move belongs to the requester
            last_x, last_y, last_color = move_history[-1]
            if last_color != my_color:
                status = "[ERR] Can only undo your own last move."
                with render_lock:
                    render(status)
                continue
            remote.ls.send_line(fmt("UNDO_REQUEST", color=my_color))
            status = "[UNDO] Request sent to opponent. Waiting for response..."
            with render_lock:
                render(status)
            # Wait for response
            response_received = False
            while not response_received:
                try:
                    l = q_in.get(timeout=30)  # 30 second timeout
                    if l is None:
                        status = "[DISCONNECTED] Opponent left."
                        game_over = True
                        with render_lock:
                            render(status)
                        break
                    cmd, kv = parse_line(l)
                    if cmd == "UNDO_RESPONSE":
                        response = kv.get("response", "n").lower()
                        if response == "y":
                            ok, err = undo_last_move(my_color)
                            if ok:
                                status = "[UNDO] Last move undone!"
                            else:
                                status = f"[UNDO] Failed: {err}"
                        else:
                            status = f"[UNDO] {opp_name} declined undo request."
                        with render_lock:
                            render(status)
                        response_received = True
                    else:
                        # Handle other commands normally
                        q_in.put(l)  # Put back for normal processing
                        time.sleep(0.1)
                except queue.Empty:
                    status = "[UNDO] Request timeout. Opponent did not respond."
                    with render_lock:
                        render(status)
                    response_received = True
            continue
        if parsed == "invalid":
            status = "[ERR] Invalid input. Example: 8 8 or H8"
            with render_lock:
                render(status)
            continue
        if isinstance(parsed, tuple):
            x, y = parsed
            ok, err = apply_move(x, y, my_color)
            if not ok:
                code, msg = err
                status = f"[ERR] {code}: {msg}"
            else:
                status = f"[YOU MOVE] {x},{y}"
            with render_lock:
                render(status)
            continue

    try:
        conn.close()
    except Exception:
        pass
    try:
        srv.close()
    except Exception:
        pass
    print("Bye.")

# ---------------- Client (join) ----------------

def run_join(host: str, port: int, name: str):
    board = [["." for _ in range(SIZE)] for _ in range(SIZE)]
    my_color = None
    turn = None
    game_over = False
    move_no = 0
    move_history = []  # List of (x, y, color) for undo
    game_started = False  # Track if game has started

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    ls = LineSocket(sock)

    # HELLO
    ls.send_line(fmt("HELLO", v="1", name=name))

    q_in = queue.Queue()

    def recv_loop():
        while True:
            try:
                l = ls.recv_line()
            except Exception:
                l = None
            q_in.put(l)
            if l is None:
                break

    threading.Thread(target=recv_loop, daemon=True).start()

    status = ""

    def render():
        clear_screen()
        print(board_to_text(board))
        if status:
            print(status)
        # Turn indicator
        if my_color is None or turn is None:
            turn_indicator = "Waiting..."
            you_stone = "?"
            opp_stone = "?"
        else:
            you_stone = "O" if my_color == "O" else "X"
            opp_stone = "X" if my_color == "O" else "O"
            if not game_over:
                if turn == my_color:
                    turn_indicator = ">>> YOUR TURN <<<"
                else:
                    turn_indicator = ">>> OPP TURN <<<"
            else:
                turn_indicator = "GAME OVER"
        print(f"{turn_indicator}   You: {you_stone}   Opponent: {opp_stone}")
        if game_over:
            print("GAME OVER. /quit to exit.")

    show_commands = True  # Show commands list on first render
    render()
    show_commands = False  # Don't show commands list after first render
    
    # Render lock for thread safety
    render_lock = threading.Lock()
    pending_request = None  # "restart" or "undo" when waiting for y/n response
    pending_undo_color = None  # Color of player requesting undo

    def apply_ok(x, y, color):
        nonlocal move_no, move_history, game_started
        if in_bounds(x, y):
            board[y-1][x-1] = color
            move_history.append((x, y, color))  # Save move for undo
        move_no += 1
        if move_no > 0:
            game_started = True
    
    def reset_game():
        nonlocal board, turn, move_no, game_over, move_history, game_started
        board = [["." for _ in range(SIZE)] for _ in range(SIZE)]
        turn = "O"  # O starts
        move_no = 0
        game_over = False
        game_started = False
        move_history = []
        # Request board state from host
        ls.send_line(fmt("BOARD", size=str(SIZE)))
    
    def undo_last_move(requesting_color):
        nonlocal board, turn, move_no, game_over, move_history, game_started
        if not move_history:
            return False, "No moves to undo"
        # Check if last move belongs to the requester
        last_x, last_y, last_color = move_history[-1]
        if last_color != requesting_color:
            return False, "Can only undo your own last move"
        # Remove only the last move (1 move)
        x, y, color = move_history.pop()
        board[y-1][x-1] = "."
        move_no -= 1
        # Turn goes back to the requester
        turn = requesting_color
        game_over = False  # Reset win state
        ls.send_line(fmt("BOARD", size=str(SIZE)))
        return True, None

    while True:
        # pump inbound
        try:
            while True:
                l = q_in.get_nowait()
                if l is None:
                    status = "[DISCONNECTED] Host left."
                    game_over = True
                    with render_lock:
                        render()
                    break
                cmd, kv = parse_line(l)
                if cmd == "MATCH":
                    my_color = kv.get("color", "X")
                    status = f"[MATCH] You are {'O (first)' if my_color=='O' else 'X (second)'}"
                    with render_lock:
                        render()
                elif cmd == "SWAP":
                    if my_color:
                        my_color = "O" if my_color == "X" else "X"
                        turn = my_color
                        status = f"[SWAP] Colors swapped. You are now {'O' if my_color=='O' else 'X'}."
                        with render_lock:
                            render()
                elif cmd == "TURN":
                    turn = kv.get("color")
                    with render_lock:
                        render()
                elif cmd == "OK":
                    x = int(kv.get("x", "0")); y = int(kv.get("y", "0"))
                    color = kv.get("color", "?")
                    apply_ok(x, y, color)
                    status = f"[MOVE] {('X(B)' if color=='B' else 'O(W)')} -> {x},{y}"
                    with render_lock:
                        render()
                elif cmd == "ERR":
                    status = f"[ERR] {kv.get('code','')}: {kv.get('msg','')}"
                    with render_lock:
                        render()
                elif cmd == "WIN":
                    color = kv.get("color", "?")
                    status = f"[WIN] {('X(B)' if color=='B' else 'O(W)')} wins!"
                    game_over = True
                    with render_lock:
                        render()
                elif cmd == "BOARD":
                    # reset board snapshot and move history
                    for yy in range(SIZE):
                        for xx in range(SIZE):
                            board[yy][xx] = "."
                    move_history = []  # Clear history when board is reset
                    status = "[STATE] Board snapshot..."
                    with render_lock:
                        render()
                elif cmd == "STONE":
                    x = int(kv.get("x", "0")); y = int(kv.get("y", "0"))
                    color = kv.get("color", ".")
                    if in_bounds(x, y):
                        board[y-1][x-1] = color
                elif cmd == "CHAT":
                    status = f"[CHAT] {kv.get('from','?')}: {kv.get('text','')}"
                    with render_lock:
                        render()
                elif cmd == "RESTART_REQUEST":
                    pending_request = "restart"
                    status = f"[REQUEST] Host wants to RESTART. Type 'y' to accept or 'n' to decline: "
                    with render_lock:
                        render()
                elif cmd == "RESTART_RESPONSE":
                    response = kv.get("response", "n").lower()
                    if response == "y":
                        reset_game()
                        status = "[RESTART] Game restarted!"
                    else:
                        status = "[RESTART] Host declined restart request."
                    with render_lock:
                        render()
                elif cmd == "UNDO_REQUEST":
                    requesting_color = kv.get("color", "X")
                    # Verify that last move belongs to the requester
                    if not move_history or move_history[-1][2] != requesting_color:
                        ls.send_line(fmt("ERR", code="INVALID_UNDO", msg="Last move is not yours"))
                        continue
                    pending_request = "undo"
                    pending_undo_color = requesting_color
                    status = f"[REQUEST] Host wants to UNDO last move. Type 'y' to accept or 'n' to decline: "
                    with render_lock:
                        render()
                elif cmd == "UNDO_RESPONSE":
                    response = kv.get("response", "n").lower()
                    if response == "y":
                        requesting_color = kv.get("color", my_color)
                        ok, err = undo_last_move(requesting_color)
                        if ok:
                            status = "[UNDO] Last move undone!"
                        else:
                            status = f"[UNDO] Failed: {err}"
                    else:
                        status = "[UNDO] Host declined undo request."
                    with render_lock:
                        render()
                elif cmd == "WELCOME":
                    # ignore
                    pass
                else:
                    status = f"[WARN] Unknown cmd: {cmd}"
                    with render_lock:
                        render()
        except queue.Empty:
            pass

        # local input (non-blocking with periodic updates)
        s = None
        if os.name == "nt":  # Windows
            print("> ", end="", flush=True)
            input_buffer = ""
            while True:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch == b'\r':  # Enter
                        print()  # newline
                        s = input_buffer.strip()
                        break
                    elif ch == b'\x08':  # Backspace
                        if input_buffer:
                            input_buffer = input_buffer[:-1]
                            print('\b \b', end='', flush=True)
                    elif ch == b'\x03':  # Ctrl+C
                        s = "/quit"
                        break
                    else:
                        try:
                            char = ch.decode('utf-8')
                            if char.isprintable():
                                input_buffer += char
                                print(char, end='', flush=True)
                        except:
                            pass
                else:
                    # Check for messages and render updates
                    try:
                        l = q_in.get_nowait()
                        if l is None:
                            status = "[DISCONNECTED] Host left."
                            game_over = True
                            with render_lock:
                                render()
                            break
                        cmd, kv = parse_line(l)
                        if cmd == "MATCH":
                            my_color = kv.get("color", "X")
                            status = f"[MATCH] You are {'O (first)' if my_color=='O' else 'X (second)'}"
                            with render_lock:
                                render()
                        elif cmd == "SWAP":
                            if my_color:
                                my_color = "O" if my_color == "X" else "X"
                                turn = my_color
                                status = f"[SWAP] Colors swapped. You are now {'O' if my_color=='O' else 'X'}."
                                with render_lock:
                                    render()
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "TURN":
                            turn = kv.get("color")
                            with render_lock:
                                render()
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "OK":
                            x = int(kv.get("x", "0")); y = int(kv.get("y", "0"))
                            color = kv.get("color", "?")
                            apply_ok(x, y, color)
                            status = f"[MOVE] {('X(B)' if color=='B' else 'O(W)')} -> {x},{y}"
                            with render_lock:
                                render()
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "ERR":
                            status = f"[ERR] {kv.get('code','')}: {kv.get('msg','')}"
                            with render_lock:
                                render()
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "WIN":
                            color = kv.get("color", "?")
                            status = f"[WIN] {('X(B)' if color=='B' else 'O(W)')} wins!"
                            game_over = True
                            with render_lock:
                                render()
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "BOARD":
                            for yy in range(SIZE):
                                for xx in range(SIZE):
                                    board[yy][xx] = "."
                            move_history.clear()  # Clear history when board is reset
                            status = "[STATE] Board snapshot..."
                            with render_lock:
                                render()
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "STONE":
                            x = int(kv.get("x", "0")); y = int(kv.get("y", "0"))
                            color = kv.get("color", ".")
                            if in_bounds(x, y):
                                board[y-1][x-1] = color
                        elif cmd == "CHAT":
                            status = f"[CHAT] {kv.get('from','?')}: {kv.get('text','')}"
                            with render_lock:
                                render()
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "RESTART_REQUEST":
                            pending_request = "restart"
                            status = f"[REQUEST] Host wants to RESTART. Type 'y' to accept or 'n' to decline: "
                            with render_lock:
                                render()
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                        elif cmd == "UNDO_REQUEST":
                            requesting_color = kv.get("color", "X")
                            if not move_history or move_history[-1][2] != requesting_color:
                                ls.send_line(fmt("ERR", code="INVALID_UNDO", msg="Last move is not yours"))
                                print("> ", end="", flush=True)
                                print(input_buffer, end="", flush=True)
                                continue
                            pending_request = "undo"
                            pending_undo_color = requesting_color
                            status = f"[REQUEST] Host wants to UNDO last move. Type 'y' to accept or 'n' to decline: "
                            with render_lock:
                                render()
                            print("> ", end="", flush=True)
                            print(input_buffer, end="", flush=True)
                    except queue.Empty:
                        pass
                    time.sleep(0.1)
        else:  # Unix/Linux
            # Non-blocking input: check for messages while waiting
            input_ready = False
            while not input_ready:
                # Check stdin with short timeout
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    try:
                        s = input("> ").strip()
                        input_ready = True
                    except (EOFError, KeyboardInterrupt):
                        s = "/quit"
                        input_ready = True
                else:
                    # Check for incoming messages
                    try:
                        l = q_in.get_nowait()
                        if l is None:
                            status = "[DISCONNECTED] Host left."
                            game_over = True
                            with render_lock:
                                render()
                            s = None
                            input_ready = True
                            break
                        cmd, kv = parse_line(l)
                        if cmd == "MATCH":
                            my_color = kv.get("color", "X")
                            status = f"[MATCH] You are {'O (first)' if my_color=='O' else 'X (second)'}"
                            with render_lock:
                                render()
                        elif cmd == "SWAP":
                            if my_color:
                                my_color = "O" if my_color == "X" else "X"
                                turn = my_color
                                status = f"[SWAP] Colors swapped. You are now {'O' if my_color=='O' else 'X'}."
                                with render_lock:
                                    render()
                                print("> ", end="", flush=True)
                                print(input_buffer, end="", flush=True)
                        elif cmd == "TURN":
                            turn = kv.get("color")
                            with render_lock:
                                render()
                        elif cmd == "OK":
                            x = int(kv.get("x", "0")); y = int(kv.get("y", "0"))
                            color = kv.get("color", "?")
                            apply_ok(x, y, color)
                            status = f"[MOVE] {('X(B)' if color=='B' else 'O(W)')} -> {x},{y}"
                            with render_lock:
                                render()
                        elif cmd == "ERR":
                            status = f"[ERR] {kv.get('code','')}: {kv.get('msg','')}"
                            with render_lock:
                                render()
                        elif cmd == "WIN":
                            color = kv.get("color", "?")
                            status = f"[WIN] {('X(B)' if color=='B' else 'O(W)')} wins!"
                            game_over = True
                            with render_lock:
                                render()
                        elif cmd == "BOARD":
                            for yy in range(SIZE):
                                for xx in range(SIZE):
                                    board[yy][xx] = "."
                            move_history.clear()  # Clear history when board is reset
                            status = "[STATE] Board snapshot..."
                            with render_lock:
                                render()
                        elif cmd == "STONE":
                            x = int(kv.get("x", "0")); y = int(kv.get("y", "0"))
                            color = kv.get("color", ".")
                            if in_bounds(x, y):
                                board[y-1][x-1] = color
                        elif cmd == "CHAT":
                            status = f"[CHAT] {kv.get('from','?')}: {kv.get('text','')}"
                            with render_lock:
                                render()
                        elif cmd == "SWAP":
                            if my_color:
                                my_color = "O" if my_color == "X" else "X"
                                turn = my_color
                                status = f"[SWAP] Colors swapped. You are now {'O' if my_color=='O' else 'X'}."
                                with render_lock:
                                    render()
                        elif cmd == "RESTART_REQUEST":
                            pending_request = "restart"
                            status = f"[REQUEST] Host wants to RESTART. Type 'y' to accept or 'n' to decline: "
                            with render_lock:
                                render()
                        elif cmd == "UNDO_REQUEST":
                            pending_request = "undo"
                            status = f"[REQUEST] Host wants to UNDO last move. Type 'y' to accept or 'n' to decline: "
                            with render_lock:
                                render()
                    except queue.Empty:
                        pass

        if s is None:
            # No input available, continue to check messages
            continue

        # Check for pending request (y/n response)
        if pending_request:
            s_lower = s.strip().lower()
            if s_lower in ("y", "yes", "n", "no"):
                response = "y" if s_lower in ("y", "yes") else "n"
                if pending_request == "restart":
                    ls.send_line(fmt("RESTART_RESPONSE", response=response))
                    if response == "y":
                        reset_game()
                        status = "[RESTART] Game restarted!"
                    else:
                        status = "[RESTART] You declined restart request."
                elif pending_request == "undo":
                    undo_color = pending_undo_color if pending_undo_color else "X"
                    ls.send_line(fmt("UNDO_RESPONSE", response=response, color=undo_color))
                    if response == "y":
                        ok, err = undo_last_move(undo_color)
                        if ok:
                            status = "[UNDO] Last move undone!"
                        else:
                            status = f"[UNDO] Failed: {err}"
                    else:
                        status = "[UNDO] You declined undo request."
                pending_request = None
                pending_undo_color = None
                with render_lock:
                    render()
                continue
            else:
                status = "[ERR] Please type 'y' or 'n' to respond to the request."
                with render_lock:
                    render()
                continue

        parsed = parse_move_input(s)
        if parsed == "/quit":
            break
        if parsed == "/help":
            help_cmds = "/swap /restart /undo /quit /help"
            if game_started:
                help_cmds = "/restart /undo /quit /help"
            status = f"Moves: 'x y' or 'H8'. Commands: {help_cmds}"
            with render_lock:
                render()
            continue
        if parsed == "/swap":
            if game_started:
                status = "[ERR] /swap is only available before the game starts."
                with render_lock:
                    render()
                continue
            if my_color is None:
                status = "[ERR] Not connected yet. Wait for match to start."
                with render_lock:
                    render()
                continue
            ls.send_line(fmt("SWAP"))
            status = "[SWAP] Request sent to host. Waiting for response..."
            with render_lock:
                render()
            continue
        if parsed == "/restart":
            if game_over:
                status = "[ERR] Game is over. Cannot restart."
                with render_lock:
                    render()
                continue
            ls.send_line(fmt("RESTART_REQUEST"))
            status = "[RESTART] Request sent to host. Waiting for response..."
            with render_lock:
                render()
            # Wait for response
            response_received = False
            while not response_received:
                try:
                    l = q_in.get(timeout=30)  # 30 second timeout
                    if l is None:
                        status = "[DISCONNECTED] Host left."
                        game_over = True
                        with render_lock:
                            render()
                        break
                    cmd, kv = parse_line(l)
                    if cmd == "RESTART_RESPONSE":
                        response = kv.get("response", "n").lower()
                        if response == "y":
                            reset_game()
                            status = "[RESTART] Game restarted!"
                        else:
                            status = "[RESTART] Host declined restart request."
                        with render_lock:
                            render()
                        response_received = True
                    else:
                        # Handle other commands normally
                        q_in.put(l)  # Put back for normal processing
                        time.sleep(0.1)
                except queue.Empty:
                    status = "[RESTART] Request timeout. Host did not respond."
                    with render_lock:
                        render()
                    response_received = True
            continue
        if parsed == "/undo":
            if game_over:
                status = "[ERR] Game is over. Cannot undo."
                with render_lock:
                    render()
                continue
            if not game_started or not move_history:
                status = "[ERR] No moves to undo."
                with render_lock:
                    render()
                continue
            # Check if last move belongs to the requester
            last_x, last_y, last_color = move_history[-1]
            if last_color != my_color:
                status = "[ERR] Can only undo your own last move."
                with render_lock:
                    render()
                continue
            ls.send_line(fmt("UNDO_REQUEST", color=my_color))
            status = "[UNDO] Request sent to host. Waiting for response..."
            with render_lock:
                render()
            # Wait for response
            response_received = False
            while not response_received:
                try:
                    l = q_in.get(timeout=30)  # 30 second timeout
                    if l is None:
                        status = "[DISCONNECTED] Host left."
                        game_over = True
                        with render_lock:
                            render()
                        break
                    cmd, kv = parse_line(l)
                    if cmd == "UNDO_RESPONSE":
                        response = kv.get("response", "n").lower()
                        if response == "y":
                            requesting_color = kv.get("color", my_color)
                            ok, err = undo_last_move(requesting_color)
                            if ok:
                                status = "[UNDO] Last move undone!"
                            else:
                                status = f"[UNDO] Failed: {err}"
                        else:
                            status = "[UNDO] Host declined undo request."
                        with render_lock:
                            render()
                        response_received = True
                    else:
                        # Handle other commands normally
                        q_in.put(l)  # Put back for normal processing
                        time.sleep(0.1)
                except queue.Empty:
                    status = "[UNDO] Request timeout. Host did not respond."
                    with render_lock:
                        render()
                    response_received = True
            continue
        if parsed == "invalid":
            status = "[ERR] Invalid input. Example: 8 8 or H8"
            with render_lock:
                render()
            continue
        if isinstance(parsed, tuple):
            if game_over:
                status = "[ERR] Game over."
                with render_lock:
                    render()
                continue
            if my_color is None or turn is None:
                status = "[ERR] Not ready yet."
                with render_lock:
                    render()
                continue
            x, y = parsed
            if turn != my_color:
                status = "[ERR] Not your turn."
                with render_lock:
                    render()
                continue
            ls.send_line(fmt("MOVE", x=str(x), y=str(y)))
            status = f"[SENT] MOVE {x},{y}"
            with render_lock:
                render()
            continue

    try:
        sock.close()
    except Exception:
        pass
    print("Bye.")

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

    args = ap.parse_args()

    if args.mode == "host":
        run_host(args.port, args.renju)
    else:
        run_join(args.host, args.port, args.name)

if __name__ == "__main__":
    main()
