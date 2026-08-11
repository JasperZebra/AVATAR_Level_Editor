import struct
import tkinter as tk
from tkinter import ttk, messagebox
from enum import Enum
from typing import Dict, Callable


class BinHexConversions(Enum):
    STRING = "value-String"
    HASH32 = "value-ComputeHash32"
    FLOAT = "value-Float"
    INT64 = "value-Id64"
    INT32 = "value-Int32"
    VECTOR3 = "value-Vector3"
    HASH32_INT = "value-Hash32Int"
    BYTE = "value-Byte"
    BOOLEAN = "value-Boolean"
    UINT32 = "value-UInt32"
    ENUM = "value-Enum"


class BinHexConvert:
    def __init__(self, conversion_type: BinHexConversions):
        OPERATION_MAP: Dict[BinHexConversions, Callable[[str], str]] = {
            BinHexConversions.STRING: self.string_to_binhex,
            BinHexConversions.HASH32: self.compute_hash32,
            BinHexConversions.FLOAT: self.float_to_binhex,
            BinHexConversions.INT64: self.int64_to_binhex,
            BinHexConversions.INT32: self.int32_to_binhex,
            BinHexConversions.VECTOR3: self.vector3_to_binhex,
            BinHexConversions.HASH32_INT: self.hash32_to_binhex,
            BinHexConversions.BYTE: self.byte_to_binhex,
            BinHexConversions.BOOLEAN: self.boolean_to_binhex,
            BinHexConversions.UINT32: self.uint32_to_binhex,
            BinHexConversions.ENUM: self.enum_to_binhex,
        }
        self.convert = OPERATION_MAP[conversion_type]

    def string_to_binhex(self, text: str) -> str:
        return (text + '\x00').encode('ascii').hex().upper()

    def compute_hash32(self, text: str) -> str:
        hash_value = 0
        for char in text:
            hash_value = ((hash_value << 5) + hash_value) + ord(char)
            hash_value = hash_value & 0xFFFFFFFF
        return struct.pack('<I', hash_value).hex().upper()

    def float_to_binhex(self, float_str: str) -> str:
        return struct.pack('<f', float(float_str)).hex().upper()

    def int64_to_binhex(self, int_str: str) -> str:
        return struct.pack('<Q', int(int_str)).hex().upper()

    def int32_to_binhex(self, int_str: str) -> str:
        return struct.pack('<i', int(int_str)).hex().upper()

    def vector3_to_binhex(self, vector_str: str) -> str:
        parts = vector_str.split(',')
        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
        return struct.pack('<fff', x, y, z).hex().upper()

    def hash32_to_binhex(self, hash_str: str) -> str:
        return struct.pack('<I', int(hash_str) & 0xFFFFFFFF).hex().upper()

    def byte_to_binhex(self, byte_str: str) -> str:
        v = int(byte_str)
        if not 0 <= v <= 255:
            raise ValueError("Value must be 0–255")
        return format(v, '02X')

    def boolean_to_binhex(self, bool_str: str) -> str:
        lo = bool_str.lower().strip()
        if lo in ['true', '1', 'yes']:
            return '01'
        elif lo in ['false', '0', 'no']:
            return '00'
        raise ValueError("Use true/false, yes/no, or 1/0")

    def uint32_to_binhex(self, uint_str: str) -> str:
        return struct.pack('<I', int(uint_str) & 0xFFFFFFFF).hex().upper()

    def enum_to_binhex(self, enum_str: str) -> str:
        return struct.pack('<I', int(enum_str) & 0xFFFFFFFF).hex().upper()


HINTS = {
    BinHexConversions.STRING:    "Null-terminated ASCII string",
    BinHexConversions.HASH32:    "String → djb2 32-bit hash (little-endian)",
    BinHexConversions.FLOAT:     "IEEE 754 float (little-endian 4 bytes)",
    BinHexConversions.INT64:     "Unsigned 64-bit integer (little-endian 8 bytes)",
    BinHexConversions.INT32:     "Signed 32-bit integer (little-endian 4 bytes)",
    BinHexConversions.VECTOR3:   "x,y,z — comma-separated floats",
    BinHexConversions.HASH32_INT:"Integer as 32-bit hash (little-endian)",
    BinHexConversions.BYTE:      "Integer 0–255 → single byte",
    BinHexConversions.BOOLEAN:   "true/false, yes/no, 1/0",
    BinHexConversions.UINT32:    "Unsigned 32-bit integer (little-endian)",
    BinHexConversions.ENUM:      "Enum integer → 32-bit little-endian",
}

PLACEHOLDERS = {
    BinHexConversions.STRING:    "Hello",
    BinHexConversions.HASH32:    "myString",
    BinHexConversions.FLOAT:     "3.14",
    BinHexConversions.INT64:     "123456789",
    BinHexConversions.INT32:     "-42",
    BinHexConversions.VECTOR3:   "1.0,2.5,-0.5",
    BinHexConversions.HASH32_INT:"305419896",
    BinHexConversions.BYTE:      "255",
    BinHexConversions.BOOLEAN:   "true",
    BinHexConversions.UINT32:    "4294967295",
    BinHexConversions.ENUM:      "3",
}

BG       = "#1a1a1a"
BG2      = "#242424"
BG3      = "#2e2e2e"
FG       = "#e8e8e8"
FG2      = "#888888"
FG3      = "#555555"
ACCENT   = "#00d4aa"
ERR      = "#ff5c5c"
BORDER   = "#383838"
MONO     = ("Consolas", 10)
MONO_LG  = ("Consolas", 14, "bold")
MONO_SM  = ("Consolas", 9)


class BinHexGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BinHex Converter")
        self.configure(bg=BG)
        self.resizable(True, True)
        self._build()
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        self.minsize(w, h)
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build(self):
        self._ready = False
        root = tk.Frame(self, bg=BG, padx=20, pady=18)
        root.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(root, bg=BG)
        hdr.pack(fill="x", pady=(0, 14))
        tk.Label(hdr, text="BINHEX", font=("Consolas", 18, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Label(hdr, text=" CONVERTER", font=("Consolas", 18),
                 bg=BG, fg=FG).pack(side="left")

        self._pinned = False
        self._pin_btn = tk.Button(hdr, text="📌 PIN", font=MONO_SM,
                                  bg=BG, fg=FG3, relief="flat", bd=0,
                                  activebackground=BG, activeforeground=ACCENT,
                                  cursor="hand2", padx=8,
                                  command=self._toggle_pin)
        self._pin_btn.pack(side="right")
        self._pin_btn.bind("<Enter>", lambda _: self._pin_btn.config(fg=FG))
        self._pin_btn.bind("<Leave>", lambda _: self._pin_btn.config(
            fg=ACCENT if self._pinned else FG3))

        sep = tk.Frame(root, bg=BORDER, height=1)
        sep.pack(fill="x", pady=(0, 16))

        # Type row
        type_row = tk.Frame(root, bg=BG)
        type_row.pack(fill="x", pady=(0, 10))
        tk.Label(type_row, text="TYPE", font=MONO_SM, bg=BG, fg=FG2).pack(anchor="w")

        self._type_var = tk.StringVar(value=BinHexConversions.STRING.value)
        type_frame = tk.Frame(type_row, bg=BG2, highlightbackground=BORDER,
                              highlightthickness=1)
        type_frame.pack(fill="x", pady=(4, 0))

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("BH.TCombobox",
                        fieldbackground=BG2,
                        background=BG2,
                        foreground=FG,
                        selectbackground=BG2,
                        selectforeground=FG,
                        insertcolor=FG,
                        borderwidth=0,
                        relief="flat",
                        font=MONO)
        style.map("BH.TCombobox",
                  fieldbackground=[("readonly", BG2)],
                  selectbackground=[("readonly", BG2)],
                  selectforeground=[("readonly", FG)])

        values = [e.value for e in BinHexConversions]
        self._combo = ttk.Combobox(type_frame, textvariable=self._type_var,
                                   values=values, state="readonly",
                                   style="BH.TCombobox", font=MONO)
        self._combo.pack(fill="x", ipady=6, padx=8)
        self._combo.bind("<<ComboboxSelected>>", self._on_type_change)

        # Hint
        self._hint_var = tk.StringVar(value=HINTS[BinHexConversions.STRING])
        tk.Label(root, textvariable=self._hint_var, font=MONO_SM,
                 bg=BG, fg=FG3, anchor="w").pack(fill="x", pady=(4, 10))

        # Input row
        in_row = tk.Frame(root, bg=BG)
        in_row.pack(fill="x", pady=(0, 10))
        tk.Label(in_row, text="INPUT", font=MONO_SM, bg=BG, fg=FG2).pack(anchor="w")

        in_frame = tk.Frame(in_row, bg=BG2, highlightbackground=BORDER,
                            highlightthickness=1)
        in_frame.pack(fill="x", pady=(4, 0))

        self._is_placeholder = True
        self._input_var = tk.StringVar()
        self._input_var.trace_add("write", lambda *_: self._convert())
        self._entry = tk.Entry(in_frame, textvariable=self._input_var,
                               font=MONO, bg=BG2, fg=FG, insertbackground=ACCENT,
                               relief="flat", bd=0,
                               highlightthickness=0)
        self._entry.pack(fill="x", ipady=7, padx=10)
        self._placeholder_var = tk.StringVar(value=PLACEHOLDERS[BinHexConversions.STRING])
        self._entry.config(fg=FG3)
        self._entry.insert(0, self._placeholder_var.get())
        self._in_frame = in_frame
        self._entry.bind("<FocusIn>", lambda e: (self._in_frame.config(highlightbackground=ACCENT), self._clear_placeholder(e)))
        self._entry.bind("<FocusOut>", lambda e: (self._in_frame.config(highlightbackground=BORDER), self._restore_placeholder(e)))

        sep2 = tk.Frame(root, bg=BORDER, height=1)
        sep2.pack(fill="x", pady=(0, 14))

        # Result
        tk.Label(root, text="RESULT", font=MONO_SM, bg=BG, fg=FG2).pack(anchor="w")

        res_frame = tk.Frame(root, bg=BG3, highlightbackground=BORDER,
                             highlightthickness=1)
        res_frame.pack(fill="x", pady=(6, 0))

        self._result_var = tk.StringVar(value="—")
        self._result_label = tk.Label(res_frame, textvariable=self._result_var,
                                      font=MONO_LG, bg=BG3, fg=ACCENT,
                                      anchor="w", padx=12, pady=12)
        self._result_label.pack(side="left", fill="x", expand=True)

        self._copy_btn = tk.Button(res_frame, text="COPY", font=MONO_SM,
                                   bg=BG3, fg=FG2, relief="flat", bd=0,
                                   activebackground=BG3, activeforeground=ACCENT,
                                   cursor="hand2", padx=12,
                                   command=self._copy)
        self._copy_btn.pack(side="right", padx=6)
        self._copy_btn.bind("<Enter>", lambda _: self._copy_btn.config(fg=ACCENT))
        self._copy_btn.bind("<Leave>", lambda _: self._copy_btn.config(fg=FG2))

        # Byte count
        self._bytes_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self._bytes_var, font=MONO_SM,
                 bg=BG, fg=FG3, anchor="w").pack(fill="x", pady=(5, 0))
        self._ready = True

    def _toggle_pin(self):
        self._pinned = not self._pinned
        self.attributes("-topmost", self._pinned)
        self._pin_btn.config(
            text="📌 PINNED" if self._pinned else "📌 PIN",
            fg=ACCENT if self._pinned else FG3
        )

    def _on_type_change(self, _=None):
        enum_val = next(e for e in BinHexConversions if e.value == self._type_var.get())
        self._hint_var.set(HINTS[enum_val])
        new_ph = PLACEHOLDERS[enum_val]
        self._placeholder_var.set(new_ph)
        if self._is_placeholder:
            self._entry.delete(0, tk.END)
            self._entry.insert(0, new_ph)
            self._entry.config(fg=FG3)
        self._convert()

    def _clear_placeholder(self, _=None):
        if self._is_placeholder:
            self._entry.delete(0, tk.END)
            self._entry.config(fg=FG)
            self._is_placeholder = False

    def _restore_placeholder(self, _=None):
        if not self._entry.get():
            self._entry.insert(0, self._placeholder_var.get())
            self._entry.config(fg=FG3)
            self._is_placeholder = True

    def _convert(self):
        if not self._ready:
            return
        if self._is_placeholder:
            self._result_var.set("—")
            self._result_label.config(fg=FG3)
            self._bytes_var.set("")
            return

        raw = self._input_var.get().strip()
        if not raw:
            self._result_var.set("—")
            self._result_label.config(fg=FG3)
            self._bytes_var.set("")
            return

        try:
            enum_val = next(e for e in BinHexConversions if e.value == self._type_var.get())
            converter = BinHexConvert(enum_val)
            result = converter.convert(raw)
            self._result_var.set(result)
            self._result_label.config(fg=ACCENT)
            byte_count = len(result) // 2
            self._bytes_var.set(f"{byte_count} byte{'s' if byte_count != 1 else ''}  ·  0x{result}")
        except Exception as e:
            self._result_var.set(str(e))
            self._result_label.config(fg=ERR)
            self._bytes_var.set("")

    def _copy(self):
        val = self._result_var.get()
        if val in ("—", "") or self._result_label.cget("fg") == ERR:
            return
        self.clipboard_clear()
        self.clipboard_append(val)
        self._copy_btn.config(text="OK!", fg=ACCENT)
        self.after(1200, lambda: self._copy_btn.config(text="COPY", fg=FG2))


if __name__ == "__main__":
    app = BinHexGUI()
    app.mainloop()