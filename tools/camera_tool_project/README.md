# camera_tool_project

Free camera / noclip mod for *James Cameron's AVATAR — THE GAME* (PC, 2009).

The short version: Dunia already contains a working free camera
(`CCameraFreeComponent`) and a script function to switch to it
(`SwitchCamera`). This project finds the switch and throws it, rather than
building a camera from scratch.

See **[NOTES.md](NOTES.md)** for the findings ledger — every confirmed address,
how it was established, and what is still unknown. That file is the source of
truth for this project; read it before changing anything here.

## Layout

```
camera_tool_project/
  NOTES.md                    findings ledger (read this first)
  analysis/
    extract_lua_api.py        dump the engine's registered script API
    disasm_at.py              disassemble Dunia.dll at any virtual address
    out/
      avatar_lua_api.txt      generated — 85 Domino script actions
```

## Tools

### `extract_lua_api.py`

Scans the Ghidra decompile for the script-registration pattern
(`FUN_100de5f0(0, "Name", &thunk)`) and writes every registered script function
with its thunk address to `out/avatar_lua_api.txt`. Prints camera, position and
input primitives to stdout as a convenience.

```bash
python analysis/extract_lua_api.py
```

### `disasm_at.py`

Disassembles `Dunia.dll` at a virtual address. Needed because the decompile only
covers addresses Ghidra promoted to functions — the script thunks weren't, so
their bodies have to be read from the binary directly. Call targets are
annotated when a decompiled body exists, so you can jump back into the pseudo-C.

```bash
python analysis/disasm_at.py 0x10a88680 --count 55
python analysis/disasm_at.py 0x10a89720 --dll "C:/path/to/other/Dunia.dll"
```

## Requirements

`capstone` and `pefile` (both already present in the level editor's
environment). `pymem` will be needed once live process work starts.

## Conventions

- **Never edit the source captures.** The decompile dumps and symbol files are
  frozen. All findings go in `NOTES.md`. This is inherited from the existing
  `Avatar_FC2_CrossReference_NOTES.txt` discipline and exists so a bad guess
  can't corrupt a source of truth.
- **Addresses assume image base `0x10000000`.** Apply the runtime ASLR slide;
  don't hardcode.
