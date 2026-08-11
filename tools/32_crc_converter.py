import tkinter as tk
from tkinter import ttk

POLY = 0xEDB88320
SEED = 0xFFFFFFFF


def crc_step(byte_val: int) -> int:
    """
    Exact match to FUN_10b5b060
    """
    crc = byte_val & 0xFF
    for _ in range(8):
        if crc & 1:
            crc = (crc >> 1) ^ POLY
        else:
            crc >>= 1
    return crc & 0xFFFFFFFF


def avatar_crc32(data: bytes) -> int:
    """
    Exact match to FUN_10b5b0e0 with FINAL XOR
    """
    crc = SEED
    for b in data:
        step = crc_step((b ^ crc) & 0xFF)
        crc = ((crc >> 8) ^ step) & 0xFFFFFFFF

    # Final XOR (required by Avatar item IDs)
    crc ^= 0xFFFFFFFF
    return crc & 0xFFFFFFFF


class AvatarCRCApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Avatar String to CRC ID Convertor")
        self.geometry("600x450")
        self.resizable(False, False)
        
        # Modern color scheme
        self.configure(bg="#1a1a2e")
        
        # Configure modern ttk style
        style = ttk.Style()
        style.theme_use("clam")
        
        # Configure custom styles
        style.configure("Modern.TLabel", 
                       background="#1a1a2e", 
                       foreground="#eee",
                       font=("Segoe UI", 10))
        
        style.configure("Title.TLabel",
                       background="#1a1a2e",
                       foreground="#00d9ff",
                       font=("Segoe UI", 16, "bold"))
        
        style.configure("Result.TLabel",
                       background="#16213e",
                       foreground="#00ff88",
                       font=("Consolas", 14, "bold"),
                       padding=15)
        
        style.configure("Modern.TEntry",
                       fieldbackground="#16213e",
                       foreground="#eee",
                       borderwidth=0,
                       relief="flat")
        
        style.configure("Modern.TButton",
                       background="#00d9ff",
                       foreground="#1a1a2e",
                       borderwidth=0,
                       focuscolor="none",
                       font=("Segoe UI", 11, "bold"),
                       padding=12)
        
        style.map("Modern.TButton",
                 background=[("active", "#00b8d4"), ("pressed", "#0097a7")])
        
        # Main container
        main_frame = tk.Frame(self, bg="#1a1a2e")
        main_frame.pack(expand=True, fill="both", padx=30, pady=30)
        
        # Title
        title = ttk.Label(main_frame, 
                         text="🎮 Avatar String to CRC ID Convertor",
                         style="Title.TLabel")
        title.pack(pady=(0, 25))
        
        # Input label
        input_label = ttk.Label(main_frame,
                               text="Enter string to generate CRC ID:",
                               style="Modern.TLabel")
        input_label.pack(pady=(0, 8))
        
        # Input entry with frame for border effect
        entry_frame = tk.Frame(main_frame, bg="#00d9ff", padx=2, pady=2)
        entry_frame.pack(pady=(0, 20), fill="x")
        
        self.entry = tk.Entry(entry_frame,
                             bg="#16213e",
                             fg="#eee",
                             font=("Segoe UI", 11),
                             relief="flat",
                             insertbackground="#00d9ff")
        self.entry.pack(fill="x", ipady=8, ipadx=8)
        self.entry.bind("<Return>", lambda e: self.generate())
        
        # Generate button
        self.generate_btn = ttk.Button(main_frame,
                                      text="⚡ Generate CRC",
                                      command=self.generate,
                                      style="Modern.TButton")
        self.generate_btn.pack(pady=(0, 25), fill="x")
        
        # Result frame
        result_frame = tk.Frame(main_frame, bg="#16213e", padx=2, pady=2)
        result_frame.pack(fill="x")
        
        result_inner = tk.Frame(result_frame, bg="#16213e")
        result_inner.pack(fill="x", padx=1, pady=1)
        
        self.result_label = ttk.Label(result_inner,
                                     text="CRC ID: ---",
                                     style="Result.TLabel",
                                     anchor="center")
        self.result_label.pack(fill="x", pady=10)
        
        # Copy button
        self.copy_btn = ttk.Button(main_frame,
                                   text="📋 Copy to Clipboard",
                                   command=self.copy_result,
                                   style="Modern.TButton",
                                   state="disabled")
        self.copy_btn.pack(pady=(15, 0), fill="x")
        
        self.last_crc = None

    def generate(self):
        text = self.entry.get()
        if not text:
            self.result_label.config(text="⚠️ Please enter a string")
            self.copy_btn.config(state="disabled")
            return
            
        data = text.encode("ascii", errors="ignore")
        crc = avatar_crc32(data)
        self.last_crc = crc
        
        self.result_label.config(text=f"CRC ID: {crc}")
        self.copy_btn.config(state="normal")
    
    def copy_result(self):
        if self.last_crc is not None:
            self.clipboard_clear()
            self.clipboard_append(str(self.last_crc))
            self.copy_btn.config(text="✓ Copied!")
            self.after(2000, lambda: self.copy_btn.config(text="📋 Copy to Clipboard"))


if __name__ == "__main__":
    app = AvatarCRCApp()
    app.mainloop()