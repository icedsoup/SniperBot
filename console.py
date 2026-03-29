import asyncio
import re
import sys
from datetime import datetime
from os import get_terminal_size

from colorama import Fore, Style

# color map
R    = Style.RESET_ALL
C_TEAL   = Fore.LIGHTCYAN_EX
C_PURPLE = Fore.LIGHTMAGENTA_EX
C_AMBER  = Fore.YELLOW
C_MINT   = Fore.LIGHTGREEN_EX
C_CORAL  = Fore.LIGHTRED_EX
C_GRAY   = Fore.LIGHTBLACK_EX
C_WHITE  = Fore.LIGHTWHITE_EX
C_GOLD   = Fore.LIGHTYELLOW_EX
C_BLUE   = Fore.LIGHTBLUE_EX
C_ROSE   = Fore.RED
C_DIM    = Fore.LIGHTBLACK_EX

# ascii art
_KARUTA = [
    r"  ██╗  ██╗  █████╗  ██████╗  ██╗   ██╗ ████████╗  █████╗  ",
    r"  ██║ ██╔╝ ██╔══██╗ ██╔══██╗ ██║   ██║ ╚══██╔══╝ ██╔══██╗ ",
    r"  █████╔╝  ███████║ ██████╔╝ ██║   ██║    ██║    ███████║  ",
    r"  ██╔═██╗  ██╔══██║ ██╔══██╗ ██║   ██║    ██║    ██╔══██║  ",
    r"  ██║  ██╗ ██║  ██║ ██║  ██║ ╚██████╔╝    ██║    ██║  ██║  ",
    r"  ╚═╝  ╚═╝ ╚═╝  ╚═╝ ╚═╝  ╚═╝  ╚═════╝     ╚═╝    ╚═╝  ╚═╝ ",
]
_SNIPER = [
    r"    ███████╗ ███╗   ██╗ ██╗ ██████╗  ███████╗ ██████╗  ",
    r"    ██╔════╝ ████╗  ██║ ██║ ██╔══██╗ ██╔════╝ ██╔══██╗ ",
    r"    ███████╗ ██╔██╗ ██║ ██║ ██████╔╝ █████╗   ██████╔╝ ",
    r"    ╚════██║ ██║╚██╗██║ ██║ ██╔═══╝  ██╔══╝   ██╔══██╗ ",
    r"    ███████║ ██║ ╚████║ ██║ ██║      ███████╗ ██║  ██║ ",
    r"    ╚══════╝ ╚═╝  ╚═══╝ ╚═╝ ╚═╝      ╚══════╝ ╚═╝  ╚═╝ ",
]

# animation sets
_SPINNER   = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
_SCAN_SPIN = ['◐', '◓', '◑', '◒']
_DROP_SPIN = ['▖', '▘', '▝', '▗']
_IDLE_DOTS = ['·', '·', '·', '○']

# regex helper
_ANSI = re.compile(r'\x1b\[[0-9;]*[mK]')

# check string len
def _vlen(s: str) -> int:
    return len(_ANSI.sub('', s))

# get console width
def _term_w() -> int:
    try:
        return get_terminal_size().columns
    except Exception:
        return 80

# console renderer
class KarutaConsole:
    def __init__(self, version: str = "", use_timestamp: bool = True):
        self.version       = version
        self.use_timestamp = use_timestamp
        self.grab_timer: int = 0
        self.drop_timer: int = 0
        self.collected:  int = 0
        self.missed:     int = 0
        self.state:      str = "IDLE"
        self._tick:         int  = 0
        self._status_drawn: bool = False
        self._running:      bool = False

    # prep timestamp
    def _ts(self) -> str:
        if self.use_timestamp:
            t = datetime.now().strftime('%H:%M:%S')
            return f"{C_GRAY}{t}{R}  "
        return ""

    # draw cd bar
    def _cd_bar(self, secs: int, cap: int, width: int = 10) -> str:
        if secs <= 0:
            return f"{C_MINT}READY     {R}"
        pct    = 1.0 - min(secs / cap, 1.0)
        filled = round(pct * width)
        bar    = C_TEAL + "█" * filled + C_GRAY + "░" * (width - filled) + R
        m, s   = divmod(secs, 60)
        label  = f"{C_AMBER}{m}m{s:02d}s{R}" if m else f"{C_AMBER}{s:3d}s {R}"
        return f"{bar} {label}"

    # build status str
    def _build_status(self) -> str:
        t   = self._tick
        sep = f" {C_GRAY}│{R} "

        if self.state == "SCANNING":
            sp   = _SCAN_SPIN[t % len(_SCAN_SPIN)]
            stat = f"{C_TEAL}{sp} SCANNING{R}"
        elif self.state == "WAITING":
            sp   = _SPINNER[t % len(_SPINNER)]
            stat = f"{C_AMBER}{sp} COOLDOWN{R}"
        elif self.state == "DROPPING":
            sp   = _DROP_SPIN[t % len(_DROP_SPIN)]
            stat = f"{C_PURPLE}{sp} DROPPING{R}"
        else:
            dp   = _IDLE_DOTS[t % len(_IDLE_DOTS)]
            stat = f"{C_GRAY}{dp} IDLE    {R}"

        line = (
            f"{C_GRAY}[{R}{stat}{C_GRAY}]{R}"
            f"{sep}{C_GRAY}Grab{R} {self._cd_bar(self.grab_timer, 600)}"
            f"{sep}{C_GRAY}Drop{R} {self._cd_bar(self.drop_timer, 1800)}"
            f"{sep}{C_MINT}✦{self.collected:>4}{R}"
            f"  {C_CORAL}✗{self.missed:>4}{R}"
        )

        w    = _term_w()
        vlen = _vlen(line)
        if vlen > w - 2:
            plain = _ANSI.sub('', line)
            line  = plain[:w - 5] + "..." + R

        return line

    # wipe current line
    def _erase_status(self):
        if self._status_drawn:
            w = _term_w()
            sys.stdout.write('\r' + ' ' * w + '\r')
            sys.stdout.flush()
            self._status_drawn = False

    # render current line
    def _draw_status(self):
        sys.stdout.write('\r' + self._build_status())
        sys.stdout.flush()
        self._status_drawn = True

    # print helper
    def _emit(self, icon: str, msg: str):
        self._erase_status()
        print(f"{self._ts()}{icon}  {msg}{R}")
        self._draw_status()

    # log generic
    def log(self, msg: str):
        self._erase_status()
        print(f"{self._ts()}{msg}{R}")
        self._draw_status()

    # log bare
    def log_raw(self, msg: str):
        self._erase_status()
        print(msg)
        self._draw_status()

    # log types
    def log_grab(self, msg: str): self._emit(f"{C_TEAL}[GRAB]{R}", msg)
    def log_collect(self, msg: str): self._emit(f"{C_MINT}[GOT ]{R}", msg)
    def log_drop(self, msg: str): self._emit(f"{C_PURPLE}[DROP]{R}", msg)
    def log_wl(self, msg: str): self._emit(f"{C_GOLD}[WL  ]{R}", msg)
    def log_kcd(self, msg: str): self._emit(f"{C_BLUE}[KCD ]{R}", msg)
    def log_debug(self, msg: str): self._emit(f"{C_ROSE}[DBG ]{R}", msg)
    def log_warn(self, msg: str): self._emit(f"{C_CORAL}[WARN]{R}", msg)
    def log_info(self, msg: str): self._emit(f"{C_BLUE}[INFO]{R}", msg)
    def log_farm(self, msg: str): self._emit(f"{C_PURPLE}[FARM]{R}", msg)

    # splash screen
    def print_banner(self):
        w = _term_w()
        self.log_raw("")
        for line in _KARUTA: self.log_raw(C_TEAL + line.center(w) + R)
        self.log_raw("")
        for line in _SNIPER: self.log_raw(C_PURPLE + line.center(w) + R)
        self.log_raw("")

    # render info box
    def print_startup_box(self, sections: list):
        inner = min(_term_w() - 6, 68)

        def _rule(lc, rc, fill="─"):
            return f"  {C_GRAY}{lc}{fill * inner}{rc}{R}"

        def _row(content):
            pad = max(inner - _vlen(content) - 2, 0)
            return f"  {C_GRAY}│{R} {content}{' ' * pad} {C_GRAY}│{R}"

        self.log_raw(_rule("╭", "╮"))
        first = True
        for header, items in sections:
            if not first:
                self.log_raw(_rule("├", "┤"))
            first = False
            self.log_raw(_row(f"{C_TEAL}{header}{R}"))
            for item in items:
                self.log_raw(_row(f"  {C_GRAY}▸{R}  {item}"))
        self.log_raw(_rule("╰", "╯"))
        self.log_raw("")

    # swap state
    def set_state(self, state: str):
        self.state = state

    # clock loop
    async def animate(self):
        self._running = True
        while self._running:
            await asyncio.sleep(0.12)
            self._tick += 1
            if self._status_drawn:
                self._draw_status()

    # stop clock
    def stop(self):
        self._running = False
        self._erase_status()