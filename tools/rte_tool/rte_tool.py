"""rte_tool.py - external real-time editing panel for Avatar: The Game.

A standalone PyQt5 window that drives the running game through the live editor
link in avatar_console.dll. Separate process, separate window: drag it to a
second monitor, run the game in exclusive fullscreen, and it still works - which
the DLL's own in-game overlay structurally cannot do, because that is a layered
window and DISTRIBUTION.md says outright it "will not composite over exclusive
fullscreen".

    python rte_tool.py

Requires the game running with the mod loaded AND a level loaded. The link only
listens once the console object exists, which is after the main menu. This tool
hooks NOTHING itself - every hook lives in the DLL, and this is only a client of
the pipe the DLL already serves. Load the DLL with dist\\install.bat (drop-in) or
dist\\inject.py (development), never both at once.

WHY A WORKER THREAD, and why every request goes through it
----------------------------------------------------------
The link is strictly request/response and reads are blocking-with-deadline, so a
request on the GUI thread freezes the window for its duration - and the duration
is not small: listx is ~95 ms for 1,251 entities and bones ~438 ms for 8
characters, measured by the DLL author on the game's own main thread. LinkWorker
owns the one AvatarLink, serialises every request through a queue, and answers
with signals. Nothing else may touch the link.

That also enforces the server's own rule for free: its state machine is
IDLE -> REQ -> DONE with a single writer per field, one request in flight.

PyQt5, not PyQt6 - deliberately. This is standalone today, but the level editor
it sits next to is PyQt5 (44 modules to 11), and tests/test_tools_scripts_pyqt5.py
already enforces that for anything loadable in-process. PyQt5 keeps the option of
docking it later; PyQt6 would close that door for a crash that is hard to
diagnose.
"""

import os
import queue
import sys
import warnings

# PyQt5's sip emits one DeprecationWarning per QObject subclass on Python 3.11+
# ("sipPyTypeDict() is deprecated"). It is raised inside the extension module at
# class-definition time, so it names OUR line numbers while being entirely
# PyQt5's business - which reads as seven warnings about this file. Filtered
# here, before the classes below are defined, because that is the only point it
# can be caught. Nothing else is suppressed.
warnings.filterwarnings("ignore", category=DeprecationWarning,
                        message=r".*sipPyTypeDict.*")

try:
    from PyQt5.QtCore import Qt, QSize, QThread, QTimer, pyqtSignal
    from PyQt5.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
    from PyQt5.QtWidgets import (
        QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
        QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
        QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit,
        QPushButton, QSlider, QSpinBox, QStackedWidget, QStatusBar,
        QFileDialog, QMessageBox,
        QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
except ImportError:
    sys.stderr.write("rte_tool needs PyQt5:  pip install PyQt5\n")
    raise

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from avatar_link import AvatarLink, Busy, LinkError, NotConnected  # noqa: E402
import theme as theme_mod  # noqa: E402
import gamepath  # noqa: E402

try:
    import catalog
except ImportError:                       # generated file, may not exist yet
    catalog = None


# ===========================================================================
# worker
# ===========================================================================

class LinkWorker(QThread):
    """Owns the link. Every request in the app goes through this queue.

    Jobs are (tag, method_name, args, kwargs). The reply comes back on
    `finished_job` with the same tag, so a caller can tell its own answer from
    somebody else's without holding any state.
    """

    connected = pyqtSignal(bool, str)     # is_connected, message
    finished_job = pyqtSignal(str, object)
    failed_job = pyqtSignal(str, str)
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        QThread.__init__(self, parent)
        self._q = queue.Queue()
        self._link = AvatarLink()
        self._stop = False

    # -- called from the GUI thread ----------------------------------------

    def submit(self, tag, method, *args, **kwargs):
        self._q.put((tag, method, args, kwargs))

    def shutdown(self):
        self._stop = True
        self._q.put(None)

    # -- the thread --------------------------------------------------------

    def run(self):
        while not self._stop:
            try:
                job = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if job is None:
                break
            tag, method, args, kwargs = job
            try:
                if method == "connect":
                    self._link.connect()
                    self.connected.emit(True, "connected")
                    self.log.emit("connected to %s" % self._link.pipe_name)
                    continue
                if method == "disconnect":
                    self._link.close()
                    self.connected.emit(False, "disconnected")
                    continue
                if not self._link.connected:
                    self.failed_job.emit(tag, "not connected")
                    continue
                reply = getattr(self._link, method)(*args, **kwargs)
                self.finished_job.emit(tag, reply)
            except Busy as exc:
                self.connected.emit(False, str(exc))
                self.failed_job.emit(tag, str(exc))
            except (NotConnected, LinkError) as exc:
                # A transport error means the session is gone. Drop the handle
                # so the next connect() starts clean rather than reusing a dead
                # one - a half-open link answers every request with the same
                # error for ever otherwise.
                self._link.close()
                self.connected.emit(False, str(exc))
                self.failed_job.emit(tag, str(exc))
            except Exception as exc:                       # never kill the thread
                self.failed_job.emit(tag, "%s: %s" % (type(exc).__name__, exc))
        try:
            self._link.close()
        except Exception:
            pass


# ===========================================================================
# small shared widgets
# ===========================================================================

def hint(text):
    lbl = QLabel(text)
    lbl.setObjectName("Hint")
    lbl.setWordWrap(True)
    return lbl


def mono(text="-"):
    lbl = QLabel(text)
    lbl.setObjectName("Mono")
    return lbl


def value(text="-"):
    lbl = QLabel(text)
    lbl.setObjectName("Value")
    return lbl


def accent(button):
    button.setProperty("accent", "1")
    return button


class Page(QWidget):
    """A nav page: a title, a subtitle, then whatever the page adds."""

    def __init__(self, app, title, subtitle):
        QWidget.__init__(self)
        self.app = app
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)

        head = QLabel(title)
        f = head.font()
        f.setPointSize(15)
        f.setWeight(QFont.DemiBold)
        head.setFont(f)
        outer.addWidget(head)
        sub = hint(subtitle)
        outer.addWidget(sub)

        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        outer.addLayout(self.body, 1)


# ===========================================================================
# pages
# ===========================================================================

class ConnectionPage(Page):
    """The handshake, and a raw request box.

    The raw box is not a debugging leftover - it is the discovery path. `addr`
    hands out component POINTERS and decodes nothing precisely so that
    exploration happens here in Python instead of costing a DLL rebuild per
    guess, and that is only useful if you can type a verb by hand.
    """

    VERBS = ("hello, list, listx, poslist, bones, addr, player, get, select, "
             "move, cvar")

    def __init__(self, app):
        Page.__init__(self, app, "Connection",
                      "The mod must already be loaded in the game (install.bat "
                      "or inject.py) and a level must be loaded - the link only "
                      "listens once the console object exists.")

        box = QGroupBox("Session")
        form = QFormLayout(box)
        form.setSpacing(9)
        self.lbl_world = value()
        self.lbl_pid = mono()
        self.lbl_dll = mono()
        self.lbl_frame = mono()
        self.lbl_sel = mono()
        form.addRow("World", self.lbl_world)
        form.addRow("Process", self.lbl_pid)
        form.addRow("DLL build", self.lbl_dll)
        form.addRow("Frame", self.lbl_frame)
        form.addRow("Selection", self.lbl_sel)
        self.body.addWidget(box)

        raw = QGroupBox("Raw request")
        rl = QVBoxLayout(raw)
        rl.setSpacing(9)
        row = QHBoxLayout()
        self.ed_raw = QLineEdit()
        self.ed_raw.setPlaceholderText("listx 50")
        self.btn_send = accent(QPushButton("Send"))
        row.addWidget(self.ed_raw, 1)
        row.addWidget(self.btn_send)
        rl.addLayout(row)
        rl.addWidget(hint("Verbs: " + self.VERBS))
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setObjectName("Mono")
        self.out.setFont(QFont("Consolas", 9))
        rl.addWidget(self.out, 1)
        self.body.addWidget(raw, 1)

        self.btn_send.clicked.connect(self._send)
        self.ed_raw.returnPressed.connect(self._send)

    def _send(self):
        line = self.ed_raw.text().strip()
        if line:
            self.app.worker.submit("raw", "request", line)

    def show_hello(self, reply):
        h = reply.head
        self.lbl_world.setText(str(h.get("world", "-")))
        self.lbl_pid.setText(str(h.get("pid", "-")))
        self.lbl_dll.setText(str(h.get("dll", "-")))
        self.lbl_frame.setText(str(h.get("frames", "-")))
        self.lbl_sel.setText(str(h.get("sel", "-")))

    def show_raw(self, reply):
        lines = ["> %s   (%.1f ms)" % (reply.verb, reply.seconds * 1000.0)]
        if reply.busy:
            lines.append("  BUSY - the frame loop did not answer in 4 s "
                         "(loading or paused?)")
        elif not reply.ok:
            lines.append("  FAILED: %s" % reply.error)
        else:
            lines.append("  %s" % reply.head)
            for r in reply.rows[:200]:
                lines.append("    %s" % r)
            for r in reply.raw[:200]:
                lines.append("    %s" % r)
            extra = (len(reply.rows) + len(reply.raw)) - 200
            if extra > 0:
                lines.append("    ... %d more" % extra)
        self.out.appendPlainText("\n".join(lines))


class WorldPage(Page):
    """Time of day and the other env_ CVars.

    This whole page needs no change to the DLL: `cvar` already routes through
    CConsole::ExecuteLine, so the engine applies whatever a CVar change implies
    and we never have to know what that is. That is exactly why writing engine
    memory directly would be the wrong tool here.
    """

    PRESETS = [("Dawn", 6.0), ("Morning", 9.0), ("Noon", 12.0),
               ("Afternoon", 15.0), ("Dusk", 19.0), ("Night", 23.0)]

    def __init__(self, app):
        Page.__init__(self, app, "World",
                      "Engine CVars, applied through the game's own console. "
                      "COMMANDS.md documents 19 env_ and 171 gfx_ CVars.")

        box = QGroupBox("Time of day  --  env_Hour")
        v = QVBoxLayout(box)
        v.setSpacing(11)

        row = QHBoxLayout()
        self.sl_hour = QSlider(Qt.Horizontal)
        self.sl_hour.setRange(0, 240)          # tenths of an hour
        self.sl_hour.setValue(120)
        self.sp_hour = QDoubleSpinBox()
        self.sp_hour.setRange(0.0, 24.0)
        self.sp_hour.setSingleStep(0.5)
        self.sp_hour.setValue(12.0)
        self.sp_hour.setSuffix(" h")
        self.sp_hour.setFixedWidth(96)
        row.addWidget(self.sl_hour, 1)
        row.addWidget(self.sp_hour)
        v.addLayout(row)

        presets = QHBoxLayout()
        presets.setSpacing(7)
        for label, hour in self.PRESETS:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, h=hour: self._set_hour(h))
            presets.addWidget(b)
        presets.addStretch(1)
        v.addLayout(presets)
        v.addWidget(hint("The slider sends on release, not while dragging - one "
                         "request per pixel would cost main-thread time inside "
                         "the game's frame."))
        self.body.addWidget(box)

        box2 = QGroupBox("Time scale  --  env_TimeScale")
        h2 = QHBoxLayout(box2)
        self.sp_scale = QDoubleSpinBox()
        self.sp_scale.setRange(0.0, 100.0)
        self.sp_scale.setSingleStep(0.25)
        self.sp_scale.setValue(1.0)
        self.sp_scale.setFixedWidth(96)
        h2.addWidget(self.sp_scale)
        for label, val in (("Freeze", 0.0), ("Slow", 0.25),
                           ("Normal", 1.0), ("Fast", 2.0)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, x=val: self._set_scale(x))
            h2.addWidget(b)
        h2.addStretch(1)
        self.body.addWidget(box2)

        box3 = QGroupBox("Any CVar")
        g = QGridLayout(box3)
        g.setSpacing(9)
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("gfx_KillLodScale")
        self.ed_value = QLineEdit()
        self.ed_value.setPlaceholderText("0")
        self.ed_value.setFixedWidth(120)
        b3 = accent(QPushButton("Set"))
        b3.clicked.connect(self._set_free)
        self.ed_value.returnPressed.connect(self._set_free)
        g.addWidget(QLabel("Name"), 0, 0)
        g.addWidget(self.ed_name, 0, 1)
        g.addWidget(QLabel("Value"), 0, 2)
        g.addWidget(self.ed_value, 0, 3)
        g.addWidget(b3, 0, 4)
        g.addWidget(hint(
            "The name must be a bare identifier and the value a number. The "
            "server enforces both so a second command cannot be smuggled in "
            "behind either - this is deliberately not an exec verb."),
            1, 0, 1, 5)
        g.setColumnStretch(1, 1)
        self.body.addWidget(box3)
        self.body.addStretch(1)

        self.sl_hour.valueChanged.connect(
            lambda v_: self.sp_hour.setValue(v_ / 10.0))
        self.sp_hour.valueChanged.connect(
            lambda v_: self.sl_hour.setValue(int(round(v_ * 10))))
        self.sl_hour.sliderReleased.connect(
            lambda: self.app.set_cvar("env_Hour", self.sp_hour.value()))
        self.sp_hour.editingFinished.connect(
            lambda: self.app.set_cvar("env_Hour", self.sp_hour.value()))

    def _set_hour(self, hour):
        self.sp_hour.setValue(hour)
        self.app.set_cvar("env_Hour", hour)

    def _set_scale(self, val):
        self.sp_scale.setValue(val)
        self.app.set_cvar("env_TimeScale", val)

    def _set_free(self):
        name = self.ed_name.text().strip()
        val = self.ed_value.text().strip()
        if name and val:
            self.app.set_cvar(name, val)


class PlayerPage(Page):
    """Where the player is, and the two cheat flags that are confirmed live.

    cheat_GodMode and ai_IgnorePlayer are named in README.md as CONFIRMED
    WORKING. The Cheat_* family (capital C) is a dead Far Cry 2 leftover that
    executes and does nothing, so it is deliberately not offered - an inert
    toggle is worse than a missing one.
    """

    def __init__(self, app):
        Page.__init__(self, app, "Player",
                      "Position and orientation, read from the live entity.")

        box = QGroupBox("Live state")
        form = QFormLayout(box)
        form.setSpacing(9)
        self.lbl_name = value()
        self.lbl_world = mono()
        self.lbl_pos = mono()
        self.lbl_fwd = mono()
        self.lbl_right = mono()
        self.lbl_up = mono()
        form.addRow("Name", self.lbl_name)
        form.addRow("World", self.lbl_world)
        form.addRow("Position", self.lbl_pos)
        form.addRow("Forward", self.lbl_fwd)
        form.addRow("Right", self.lbl_right)
        form.addRow("Up", self.lbl_up)

        row = QHBoxLayout()
        b = accent(QPushButton("Refresh"))
        b.clicked.connect(lambda: self.app.worker.submit("player", "player"))
        self.chk_auto = QCheckBox("Auto")
        self.sp_rate = QSpinBox()
        self.sp_rate.setRange(1, 10)
        self.sp_rate.setValue(2)
        self.sp_rate.setSuffix(" Hz")
        self.sp_rate.setFixedWidth(84)
        row.addWidget(b)
        row.addWidget(self.chk_auto)
        row.addWidget(self.sp_rate)
        row.addStretch(1)
        form.addRow("", row)
        self.body.addWidget(box)

        flags = QGroupBox("Flags  --  confirmed working in this build")
        fl = QVBoxLayout(flags)
        fl.setSpacing(9)
        self.chk_god = QCheckBox("cheat_GodMode")
        self.chk_ign = QCheckBox("ai_IgnorePlayer")
        self.chk_god.toggled.connect(
            lambda on: self.app.set_cvar("cheat_GodMode", 1 if on else 0))
        self.chk_ign.toggled.connect(
            lambda on: self.app.set_cvar("ai_IgnorePlayer", 1 if on else 0))
        fl.addWidget(self.chk_god)
        fl.addWidget(self.chk_ign)
        fl.addWidget(hint(
            "Write-only: the link has no CVar read verb, so these show what you "
            "last set, not what the engine holds. They reset on connect for "
            "that reason. The capital-C Cheat_* family is a dead Far Cry 2 "
            "leftover and is deliberately not offered."))
        self.body.addWidget(flags)
        self.body.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.chk_auto.toggled.connect(self._auto)
        self.sp_rate.valueChanged.connect(
            lambda _: self._auto(self.chk_auto.isChecked()))

    def _auto(self, on):
        self._timer.stop()
        if on:
            self._timer.start(int(1000 / max(1, self.sp_rate.value())))

    def _tick(self):
        if self.app.is_connected:
            self.app.worker.submit("player", "player")

    @staticmethod
    def _vec(v):
        if not isinstance(v, list) or len(v) != 3:
            return "-"
        return "% 10.3f   % 10.3f   % 10.3f" % (v[0], v[1], v[2])

    def show_player(self, reply):
        h = reply.head
        self.lbl_name.setText(str(h.get("n", "-")))
        self.lbl_world.setText(str(h.get("world", "-")))
        self.lbl_pos.setText(self._vec(h.get("p")))
        self.lbl_fwd.setText(self._vec(h.get("f")))
        self.lbl_right.setText(self._vec(h.get("r")))
        self.lbl_up.setText(self._vec(h.get("u")))


class EntityPage(Page):
    """Live entity browser: listx for the fixed data, poslist for what moves.

    The split is the server's own design and it matters. listx re-sends names,
    class ids and bounding boxes that cannot change while the level is loaded -
    ~200 bytes an entity plus a GetWorldAABB call each - which is why it was
    measured at 95 ms for 1,251 entities and why auto-refreshing it slowed the
    game. poslist sends ~40 bytes and no engine call per entity.

    So: pull listx ONCE to populate the table, then refresh with poslist and
    join on the id.
    """

    COLS = ["Id", "Name", "Class", "X", "Y", "Z"]

    def __init__(self, app):
        Page.__init__(self, app, "Entities",
                      "listx populates the table once; poslist refreshes only "
                      "what moves, joined on the entity id.")
        self._rows = {}          # id -> table row index

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText("filter by name or class")
        self.sp_cap = QSpinBox()
        self.sp_cap.setRange(10, 20000)
        self.sp_cap.setValue(1500)
        self.sp_cap.setPrefix("cap ")
        self.sp_cap.setFixedWidth(110)
        b_load = accent(QPushButton("Load"))
        b_pos = QPushButton("Refresh positions")
        self.chk_auto = QCheckBox("Auto")
        self.sp_rate = QSpinBox()
        self.sp_rate.setRange(1, 10)
        self.sp_rate.setValue(2)
        self.sp_rate.setSuffix(" Hz")
        self.sp_rate.setFixedWidth(84)
        bar.addWidget(self.ed_filter, 1)
        bar.addWidget(self.sp_cap)
        bar.addWidget(b_load)
        bar.addWidget(b_pos)
        bar.addWidget(self.chk_auto)
        bar.addWidget(self.sp_rate)
        self.body.addLayout(bar)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setFont(QFont("Consolas", 9))
        self.body.addWidget(self.table, 1)

        edit = QGroupBox("Selected entity")
        g = QGridLayout(edit)
        g.setSpacing(9)
        self.lbl_sel = value("nothing selected")
        self.sp_x = QDoubleSpinBox()
        self.sp_y = QDoubleSpinBox()
        self.sp_z = QDoubleSpinBox()
        for sp in (self.sp_x, self.sp_y, self.sp_z):
            sp.setRange(-100000.0, 100000.0)
            sp.setDecimals(3)
            sp.setSingleStep(1.0)
            sp.setMinimumWidth(120)
        b_sel = QPushButton("Select in game")
        b_get = QPushButton("Read position")
        b_move = accent(QPushButton("Move here"))
        g.addWidget(self.lbl_sel, 0, 0, 1, 6)
        g.addWidget(QLabel("X"), 1, 0)
        g.addWidget(self.sp_x, 1, 1)
        g.addWidget(QLabel("Y"), 1, 2)
        g.addWidget(self.sp_y, 1, 3)
        g.addWidget(QLabel("Z  (up)"), 1, 4)
        g.addWidget(self.sp_z, 1, 5)
        btns = QHBoxLayout()
        btns.addWidget(b_sel)
        btns.addWidget(b_get)
        btns.addWidget(b_move)
        btns.addStretch(1)
        g.addLayout(btns, 2, 0, 1, 6)
        g.addWidget(hint(
            "move reports whether the entity ACTUALLY moved - a lot of things "
            "silently refuse, and the reply says so rather than pretending. "
            "Watch the status bar."), 3, 0, 1, 6)
        self.body.addWidget(edit)

        b_load.clicked.connect(self._load)
        b_pos.clicked.connect(self._refresh_pos)
        b_sel.clicked.connect(self._select)
        b_move.clicked.connect(self._move)
        b_get.clicked.connect(self._get)
        self.ed_filter.textChanged.connect(self._apply_filter)
        self.table.itemSelectionChanged.connect(self._on_pick)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.chk_auto.toggled.connect(self._auto)
        self.sp_rate.valueChanged.connect(
            lambda _: self._auto(self.chk_auto.isChecked()))

    # -- requests ----------------------------------------------------------

    def _load(self):
        self.app.worker.submit("listx", "listx", self.sp_cap.value())

    def _refresh_pos(self):
        self.app.worker.submit("poslist", "poslist", self.sp_cap.value())

    def _auto(self, on):
        self._timer.stop()
        if on:
            self._timer.start(int(1000 / max(1, self.sp_rate.value())))

    def _tick(self):
        if self.app.is_connected:
            self._refresh_pos()

    def current_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.text() if item else None

    def _select(self):
        eid = self.current_id()
        if eid:
            self.app.worker.submit("select", "select", eid)

    def _get(self):
        eid = self.current_id()
        if eid:
            self.app.worker.submit("get", "get", eid)

    def _move(self):
        eid = self.current_id()
        if eid:
            self.app.worker.submit("move", "move", eid, self.sp_x.value(),
                                   self.sp_y.value(), self.sp_z.value())

    # -- view --------------------------------------------------------------

    def _on_pick(self):
        row = self.table.currentRow()
        if row < 0:
            return
        eid = self.table.item(row, 0).text()
        name = self.table.item(row, 1).text()
        self.lbl_sel.setText("%s    %s" % (eid, name))
        for col, sp in ((3, self.sp_x), (4, self.sp_y), (5, self.sp_z)):
            item = self.table.item(row, col)
            if item:
                try:
                    sp.setValue(float(item.text()))
                except ValueError:
                    pass

    def show_listx(self, reply):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._rows = {}
        rows = reply.rows
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            eid = r.get("id", "")
            pos = r.get("p") or [0.0, 0.0, 0.0]
            cells = [eid, r.get("n", ""), r.get("c", ""),
                     "%.2f" % pos[0], "%.2f" % pos[1], "%.2f" % pos[2]]
            for c, text in enumerate(cells):
                self.table.setItem(i, c, QTableWidgetItem(text))
            self._rows[eid] = i
        self.table.setSortingEnabled(True)
        self.table.resizeColumnToContents(0)
        self._apply_filter(self.ed_filter.text())

    def show_poslist(self, reply):
        """Join on the id. Ids absent from the table are skipped - the world
        streams, so a poslist can legitimately name entities that were not
        there when listx ran."""
        for eid, x, y, z in reply.positions():
            row = self._rows.get(eid)
            if row is None:
                continue
            for col, val in ((3, x), (4, y), (5, z)):
                item = self.table.item(row, col)
                if item:
                    item.setText("%.2f" % val)

    def _apply_filter(self, text):
        text = (text or "").strip().lower()
        for i in range(self.table.rowCount()):
            if not text:
                self.table.setRowHidden(i, False)
                continue
            name = self.table.item(i, 1)
            cls = self.table.item(i, 2)
            hay = ((name.text() if name else "") + " " +
                   (cls.text() if cls else "")).lower()
            self.table.setRowHidden(i, text not in hay)


class SetupPage(Page):
    """Point the tool at the game, and get the mod loaded into it.

    THIS IS NOT NEEDED TO CONNECT. The link pipe is a fixed kernel name, so the
    install location is irrelevant to `connect` - the path matters for the step
    BEFORE it. The pipe exists only because the DLL is loaded and serving it, so
    a failed connect nearly always means the mod is not in the game, and fixing
    that needs the folder.

    No auto-detection, on purpose: retail, Uplay, GOG and a copied folder all
    look different, scanning drives is slow and can reach network shares, and a
    wrong guess writes a DLL into a folder the user did not choose. One dialog,
    once, remembered.
    """

    def __init__(self, app):
        Page.__init__(self, app, "Setup",
                      "Where the game is, and how the mod gets into it. Needed "
                      "once - the connection itself needs no path.")
        self.game = gamepath.GameInstall()

        box = QGroupBox("Avatar install")
        v = QVBoxLayout(box)
        v.setSpacing(9)
        row = QHBoxLayout()
        self.lbl_path = mono("not set")
        b_browse = accent(QPushButton("Browse for Avatar.exe"))
        b_browse.clicked.connect(self.browse)
        row.addWidget(self.lbl_path, 1)
        row.addWidget(b_browse)
        v.addLayout(row)
        v.addWidget(hint("Pick bin\\Avatar.exe, or the folder containing it."))
        self.body.addWidget(box)

        box2 = QGroupBox("Status")
        f2 = QFormLayout(box2)
        f2.setSpacing(8)
        self.lbl_built = mono()
        self.lbl_installed = mono()
        self.lbl_running = mono()
        f2.addRow("DLL built", self.lbl_built)
        f2.addRow("Dropped in bin", self.lbl_installed)
        f2.addRow("Game running", self.lbl_running)
        b_refresh = QPushButton("Refresh")
        b_refresh.clicked.connect(self.refresh)
        f2.addRow("", b_refresh)
        self.body.addWidget(box2)

        box3 = QGroupBox("Load the mod   --   pick ONE of these, never both")
        g = QGridLayout(box3)
        g.setSpacing(9)
        self.b_install = QPushButton("Install to bin")
        self.b_uninstall = QPushButton("Uninstall")
        self.b_inject = QPushButton("Inject now")
        self.b_install.clicked.connect(self.do_install)
        self.b_uninstall.clicked.connect(self.do_uninstall)
        self.b_inject.clicked.connect(self.do_inject)
        g.addWidget(QLabel("Drop-in"), 0, 0)
        g.addWidget(self.b_install, 0, 1)
        g.addWidget(self.b_uninstall, 0, 2)
        g.addWidget(hint("Copies dinput8.dll into bin\\. The game loads it "
                         "itself at startup - no Python, no timing. Needs the "
                         "game CLOSED. Uninstall deletes that one file; nothing "
                         "else is ever written."), 1, 0, 1, 3)
        g.addWidget(QLabel("Injection"), 2, 0)
        g.addWidget(self.b_inject, 2, 1)
        g.addWidget(hint("Injects into the running game. Needs NO install path - "
                         "inject.py finds the process itself. Better while "
                         "the mod is still changing: rebuild and re-inject "
                         "without restarting, and End unloads it cleanly."),
                    3, 0, 1, 3)
        g.addWidget(hint("Both at once means two sets of hooks on one vtable "
                         "slot, which the project's own docs call not "
                         "survivable. inject.py refuses when it sees the "
                         "drop-in, and so does this."), 4, 0, 1, 3)
        g.setColumnStretch(2, 1)
        self.body.addWidget(box3)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setObjectName("Mono")
        self.out.setFont(QFont("Consolas", 9))
        self.out.setMaximumHeight(150)
        self.body.addWidget(self.out, 1)

        self.refresh()

    # -- actions -----------------------------------------------------------

    def browse(self):
        start = self.game.bin_dir or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Avatar.exe", start,
            "Avatar.exe (Avatar.exe);;Executables (*.exe);;All files (*)")
        if not path:
            return
        ok, msg = self.game.set_path(path)
        if not ok:
            QMessageBox.warning(self, "Not the game", msg)
            self._log("path rejected: %s" % msg)
        else:
            self._log("game set: %s" % msg)
        self.refresh()

    def ensure_path(self):
        """-> True once a valid install is known. Opens the dialog if not."""
        if self.game.status()["configured"]:
            return True
        self.browse()
        return self.game.status()["configured"]

    def do_install(self):
        if not self.ensure_path():
            return
        ok, msg = self.game.install()
        self._log(msg)
        self.refresh()
        if not ok:
            QMessageBox.warning(self, "Install failed", msg)

    def do_uninstall(self):
        if not self.ensure_path():
            return
        ok, msg = self.game.uninstall()
        self._log(msg)
        self.refresh()
        if not ok:
            QMessageBox.warning(self, "Uninstall failed", msg)

    def do_inject(self):
        ok, msg = self.game.inject()
        self._log(msg)
        self.refresh()
        if ok:
            self._log("\nNow load a level if you have not, then press Connect.")
        else:
            QMessageBox.warning(self, "Inject failed", msg)

    # -- view --------------------------------------------------------------

    def _log(self, text):
        self.out.appendPlainText(str(text))

    def refresh(self):
        st = self.game.status()
        self.lbl_path.setText(st["exe"] or "not set")
        self.lbl_built.setText("yes" if st["have_build"]
                               else "NO - run build.bat in %s"
                                    % os.path.dirname(st["dist"]))
        if not st["configured"]:
            self.lbl_installed.setText("unknown - set the path first")
        else:
            self.lbl_installed.setText("yes" if st["installed"] else "no")
        self.lbl_running.setText("yes" if st["running"] else "no")

        # The buttons say what is possible right now rather than failing later.
        self.b_install.setEnabled(st["configured"] and st["have_build"]
                                  and not st["running"])
        self.b_uninstall.setEnabled(st["configured"] and st["installed"]
                                    and not st["running"])
        self.b_inject.setEnabled(st["have_build"] and st["running"]
                                 and not st["installed"])
        if st["installed"] and st["running"]:
            self.b_inject.setToolTip("The drop-in is already in this process - "
                                     "a second copy is not survivable.")
        elif not st["running"]:
            self.b_inject.setToolTip("The game is not running.")
        else:
            self.b_inject.setToolTip("")

    def explain_failure(self):
        """Called when connect fails with the pipe missing."""
        st = self.game.status()
        self._log("-" * 62)
        self._log("The pipe does not exist, which means the mod is not loaded "
                  "in the game.")
        # Order matters. Injection needs NO install path - inject.py finds the
        # process itself and takes the DLL from dist\\ - so telling someone with
        # a running game to go set a path first is a wrong instruction, not
        # merely a slow one. Test that case before the unconfigured one.
        if st["running"] and not st["installed"] and st["have_build"]:
            self._log("The game is running with no mod in it. Press 'Inject "
                      "now' - injection needs no install path.")
        elif not st["configured"]:
            self._log("Set the Avatar install below, then Install or Inject.")
        elif st["installed"] and not st["running"]:
            self._log("The drop-in IS installed - just start the game and load "
                      "a level.")
        elif st["installed"] and st["running"]:
            self._log("The drop-in is installed and the game is up, so the mod "
                      "should be loading.\nIf you are past the main menu and "
                      "this still fails, the log says why - look for\n"
                      "'[link] listening on' in:\n  %s" % st["log_path"])
        elif st["running"]:
            self._log("The game is running with no mod loaded. Press "
                      "'Inject now'.")
        else:
            self._log("Install to bin, then start the game.")


class CommandsPage(Page):
    """Every console command and CVar known for this build - 551 of them.

    Built from catalog.py, which gen_catalog.py derives from COMMANDS.md and the
    DLL's dispatch chain. Nothing here is typed by hand: COMMANDS.md is itself
    generated from the binary and says "do not hand-edit", so duplicating it into
    a GUI would be stale within a week and wrong silently.

    THE RUN BUTTON IS HONEST, and that is most of this page's design. Only the
    entries the pipe can actually reach get one:

      yes     name + one number. `cvar` validates a bare identifier and a numeric
              value, then hands "<name> <value>" to ExecuteLine - and it never
              checks that the name is really a CVar. So this covers every engine
              command of that shape, not just CVars: set_health 50, hit_me 10,
              stats 3, draw_method 1.
      noargs  offered, but labelled UNVERIFIED. `cvar` requires a value, so the
              only way to send one of these is with a dummy 0 and hope the Lua
              wrapper ignores it. It might; nobody has checked.
      args    string or multiple arguments. Unreachable until a `cmd` verb
              exists. Shown greyed rather than hidden - a catalogue that omits
              what it cannot do is a catalogue you cannot trust.
      mod     the DLL's own commands. `cvar` calls RunConsoleLine, which is
              ExecuteLine; it does NOT go through TryModCommand, and that
              dispatcher is only consulted in hkUpdateUI on lines from the
              hotkey queue. So warp/spawn/freecam cannot be reached through the
              pipe however they are spelled.
    """

    STATUS = {
        "yes": ("Ready", "runs now"),
        "noargs": ("No args", "unverified - would be sent with a dummy 0"),
        "args": ("Needs cmd verb", "takes a string or several arguments"),
        "mod": ("Mod command", "cvar bypasses TryModCommand - needs a cmd verb"),
    }
    COLS = ["Command", "Group", "Status", "Description"]

    def __init__(self, app):
        Page.__init__(self, app, "Commands",
                      "Every console command and CVar recovered for PC retail "
                      "1.02, from COMMANDS.md and the DLL's own dispatch chain.")
        self._entries = list(catalog.ENTRIES) if catalog else []
        self._shown = []

        if not catalog:
            self.body.addWidget(hint(
                "catalog.py is missing. Run:    python gen_catalog.py"))
            self.body.addStretch(1)
            return

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("search name or description")
        self.cb_group = QComboBox()
        self.cb_group.addItem("all groups")
        for g in catalog.GROUPS:
            self.cb_group.addItem("%s  (%d)" % (g, catalog.GROUP_COUNTS[g]), g)
        self.cb_group.setFixedWidth(180)
        self.chk_ready = QCheckBox("Runnable only")
        bar.addWidget(self.ed_search, 1)
        bar.addWidget(self.cb_group)
        bar.addWidget(self.chk_ready)
        self.body.addLayout(bar)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.body.addWidget(self.table, 1)

        run = QGroupBox("Run")
        g = QGridLayout(run)
        g.setSpacing(9)
        self.lbl_cmd = value("select a command")
        self.lbl_help = hint("")
        self.ed_val = QLineEdit()
        self.ed_val.setPlaceholderText("value")
        self.ed_val.setFixedWidth(130)
        self.btn_run = accent(QPushButton("Run"))
        self.btn_run.setEnabled(False)
        self.lbl_why = hint("")
        g.addWidget(self.lbl_cmd, 0, 0, 1, 3)
        g.addWidget(self.lbl_help, 1, 0, 1, 3)
        g.addWidget(QLabel("Value"), 2, 0)
        g.addWidget(self.ed_val, 2, 1)
        g.addWidget(self.btn_run, 2, 2)
        g.addWidget(self.lbl_why, 3, 0, 1, 3)
        g.setColumnStretch(2, 1)
        self.body.addWidget(run)

        self.ed_search.textChanged.connect(self._refill)
        self.cb_group.currentIndexChanged.connect(self._refill)
        self.chk_ready.toggled.connect(self._refill)
        self.table.itemSelectionChanged.connect(self._on_pick)
        self.btn_run.clicked.connect(self._run)
        self.ed_val.returnPressed.connect(self._run)
        self._refill()

    # -- view --------------------------------------------------------------

    def _refill(self):
        needle = self.ed_search.text().strip().lower()
        group = self.cb_group.currentData()
        ready_only = self.chk_ready.isChecked()

        rows = []
        for e in self._entries:
            if group and e["group"] != group:
                continue
            if ready_only and e["runnable"] not in ("yes", "noargs"):
                continue
            if needle:
                hay = (e["name"] + " " + e["help"] + " " + e["usage"]).lower()
                if needle not in hay:
                    continue
            rows.append(e)

        self._shown = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, e in enumerate(rows):
            label = self.STATUS[e["runnable"]][0]
            desc = e["help"] or e["usage"] or ""
            for c, text in enumerate((e["name"], e["group"], label, desc)):
                item = QTableWidgetItem(text)
                if c == 2 and e["runnable"] not in ("yes", "noargs"):
                    item.setForeground(Qt.gray)
                self.table.setItem(i, c, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(2)
        self.app.command_count(len(rows), len(self._entries))

    def _current(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        name = self.table.item(row, 0).text()
        for e in self._shown:
            if e["name"] == name:
                return e
        return None

    def _on_pick(self):
        e = self._current()
        if not e:
            return
        self.lbl_cmd.setText(e["name"])
        self.lbl_help.setText(e["help"] or e["usage"] or "no description recovered")
        self.lbl_why.setText(self.STATUS[e["runnable"]][1])
        can = e["runnable"] in ("yes", "noargs")
        self.btn_run.setEnabled(can and self.app.is_connected)
        self.ed_val.setEnabled(can)
        if e["runnable"] == "noargs":
            self.ed_val.setText("0")
        elif e["arg"] and e["arg"].strip("<>[]").replace(".", "").replace(
                "-", "").isdigit():
            self.ed_val.setText(e["arg"].strip("<>[]"))
        else:
            self.ed_val.setText("1")

    def _run(self):
        e = self._current()
        if not e or e["runnable"] not in ("yes", "noargs"):
            return
        val = self.ed_val.text().strip()
        if not val:
            return
        self.app.set_cvar(e["name"], val)

    def refresh_enabled(self):
        """Called when the connection changes - the Run button tracks it."""
        e = self._current()
        can = bool(e) and e["runnable"] in ("yes", "noargs")
        self.btn_run.setEnabled(can and self.app.is_connected)


# ===========================================================================
# main window
# ===========================================================================

class RteWindow(QMainWindow):

    # Names only, and the icons beside them are PAINTED, not glyphs.
    #
    # This project has a standing cp1252 hazard: tests/test_scan_print_encoding.py
    # exists because a tick-mark character in a print() raised UnicodeEncodeError
    # and aborted a whole folder scan ("0 worlds found"), and a commit is titled
    # "theme loading survives cp1252 consoles". Qt renders any glyph happily -
    # the failure is at the OTHER end, the moment UI text reaches a print() or a
    # log on a cp1252 stdout.
    #
    # This file is deliberately pure ASCII for that reason. Painted icons carry
    # the visual weight instead, and they cannot raise anywhere.
    NAV = ["Connection", "Setup", "Commands", "World", "Player", "Entities"]

    def __init__(self):
        QMainWindow.__init__(self)
        self.setWindowTitle("Avatar RTE")
        self.resize(1120, 760)
        self.is_connected = False
        self._dark = True

        self.worker = LinkWorker(self)
        self.worker.connected.connect(self._on_connected)
        self.worker.finished_job.connect(self._on_reply)
        self.worker.failed_job.connect(self._on_failed)
        self.worker.log.connect(self._say)
        self.worker.start()

        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._build_header())

        split = QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFixedWidth(178)
        self.nav.setFrameShape(QFrame.NoFrame)
        self.nav.setIconSize(QSize(10, 10))
        for label in self.NAV:
            QListWidgetItem(label, self.nav)
        split.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.page_conn = ConnectionPage(self)
        self.page_setup = SetupPage(self)
        self.page_cmds = CommandsPage(self)
        self.page_world = WorldPage(self)
        self.page_player = PlayerPage(self)
        self.page_ents = EntityPage(self)
        for p in (self.page_conn, self.page_setup, self.page_cmds,
                  self.page_world, self.page_player, self.page_ents):
            self.stack.addWidget(p)
        split.addWidget(self.stack, 1)
        rl.addLayout(split, 1)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.apply_theme(dark=True)
        self._set_enabled(False)
        self._say("Start the game, load a level, then press Connect.")

    # -- chrome ------------------------------------------------------------

    def _build_header(self):
        bar = QFrame()
        bar.setObjectName("Header")
        bar.setFixedHeight(62)
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 16, 0)
        h.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel("Avatar RTE")
        t.setObjectName("HeaderTitle")
        self.lbl_hdr_world = QLabel("no world")
        self.lbl_hdr_world.setObjectName("HeaderWorld")
        titles.addWidget(t)
        titles.addWidget(self.lbl_hdr_world)
        h.addLayout(titles)
        h.addStretch(1)

        self.pill = QLabel("OFFLINE")
        self.pill.setObjectName("Pill")
        self.pill.setProperty("state", "off")
        self.pill.setAlignment(Qt.AlignCenter)
        h.addWidget(self.pill)

        self.btn_connect = accent(QPushButton("Connect"))
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_theme = QPushButton("Theme")
        self.btn_theme.setFixedWidth(72)
        self.btn_theme.setToolTip("Light / dark")
        self.btn_connect.clicked.connect(self.do_connect)
        self.btn_disconnect.clicked.connect(self.do_disconnect)
        self.btn_theme.clicked.connect(lambda: self.apply_theme(not self._dark))
        h.addWidget(self.btn_connect)
        h.addWidget(self.btn_disconnect)
        h.addWidget(self.btn_theme)
        return bar

    def apply_theme(self, dark=True):
        self._dark = bool(dark)
        palette = theme_mod.DARK if self._dark else theme_mod.LIGHT
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme_mod.stylesheet(palette))
        self.setWindowIcon(QIcon(self._chip(palette["accent"], 32, 7)))
        for i in range(self.nav.count()):
            self.nav.item(i).setIcon(
                QIcon(self._chip(palette["accent"], 10, 3)))

    @staticmethod
    def _chip(colour, size, radius):
        """A rounded square, painted. Used for the window icon and the nav dots.

        Painted rather than a glyph or an asset: no font has to carry it, no
        file has to ship beside the script, and nothing here can ever reach a
        cp1252 stdout and raise (see the NAV comment).
        """
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(colour))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, size, size, radius, radius)
        p.end()
        return pm

    def _pill(self, state, text):
        self.pill.setProperty("state", state)
        self.pill.setText(text)
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)

    # -- plumbing ----------------------------------------------------------

    def _say(self, msg):
        self.statusBar().showMessage(msg, 9000)

    def _set_enabled(self, on):
        for i in range(3, self.nav.count()):
            self.nav.item(i).setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable if on else Qt.NoItemFlags)
        for w in (self.page_cmds, self.page_world, self.page_player,
                  self.page_ents):
            w.setEnabled(on)
        self.page_cmds.refresh_enabled()
        self.btn_connect.setEnabled(not on)
        self.btn_disconnect.setEnabled(on)
        if not on:
            self.nav.setCurrentRow(0)

    def do_connect(self):
        self._pill("busy", "CONNECTING")
        self._say("connecting...")
        self.worker.submit("connect", "connect")

    def do_disconnect(self):
        self.worker.submit("disconnect", "disconnect")

    def command_count(self, shown, total):
        self._say("commands: showing %d of %d" % (shown, total))

    def set_cvar(self, name, val):
        self.worker.submit("cvar", "cvar", name, val)

    def _on_connected(self, ok, msg):
        self.is_connected = ok
        self._set_enabled(ok)
        if ok:
            self._pill("on", "LIVE")
            self.worker.submit("hello", "hello")
        else:
            good = msg == "disconnected"
            self._pill("off" if good else "err", "OFFLINE")
            self.lbl_hdr_world.setText("no world")
            # Flags are write-only, so a reconnect must not imply the engine
            # still holds whatever was last ticked.
            self.page_player.chk_god.setChecked(False)
            self.page_player.chk_ign.setChecked(False)
        self._say(msg)

    def _on_failed(self, tag, msg):
        self._say("%s failed: %s" % (tag, msg))
        # A failed CONNECT is the one failure with an actionable next step, and
        # the step is never "try again" - it is "the mod is not in the game".
        # Send the user to the page that fixes that instead of leaving a red
        # pill and no route forward.
        if tag == "connect" and "pipe" in msg.lower():
            self.page_setup.refresh()
            self.page_setup.explain_failure()
            self.nav.setCurrentRow(self.NAV.index("Setup"))
            if not self.page_setup.game.status()["configured"]:
                self.page_setup.browse()

    def _on_reply(self, tag, reply):
        if reply.busy:
            self._pill("busy", "LOADING")
            self._say("%s: the frame loop did not answer in 4 s - loading?" % tag)
            if tag == "raw":
                self.page_conn.show_raw(reply)
            return
        if self.is_connected:
            self._pill("on", "LIVE")
        if not reply.ok and tag != "raw":
            self._say("%s: %s" % (tag, reply.error))
            return

        if tag == "hello":
            self.page_conn.show_hello(reply)
            world = reply.head.get("world") or "?"
            self.lbl_hdr_world.setText(world)
            self.setWindowTitle("Avatar RTE - %s" % world)
            if not reply.head.get("level"):
                self._say("Connected, but no level is loaded - the entity verbs "
                          "will refuse until one is.")
            else:
                self._say("connected to %s" % world)
        elif tag == "player":
            self.page_player.show_player(reply)
        elif tag == "listx":
            self.page_ents.show_listx(reply)
            self._say("listx: %d entities in %.0f ms"
                      % (len(reply.rows), reply.seconds * 1000.0))
        elif tag == "poslist":
            self.page_ents.show_poslist(reply)
            self._say("poslist: %d rows in %.0f ms"
                      % (len(reply.raw), reply.seconds * 1000.0))
        elif tag == "move":
            moved = reply.head.get("moved")
            note = reply.head.get("note")
            self._say("move: %s%s" % ("moved" if moved else "REFUSED",
                                      (" - " + note) if note else ""))
        elif tag == "select":
            self._say("selected %s" % reply.head.get("n"))
        elif tag == "get":
            self._say("%s at %s" % (reply.head.get("n"), reply.head.get("p")))
        elif tag == "cvar":
            self._say("%s = %s" % (reply.head.get("set"),
                                   reply.head.get("value")))
        elif tag == "raw":
            self.page_conn.show_raw(reply)

    def closeEvent(self, event):
        self.worker.shutdown()
        self.worker.wait(3000)
        QMainWindow.closeEvent(self, event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Avatar RTE")
    win = RteWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
