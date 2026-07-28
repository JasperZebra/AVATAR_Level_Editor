![GitHub release (latest by date)](https://img.shields.io/github/v/release/JasperZebra/AVATAR-The-Game-Level-Editor?style=for-the-badge&logo=github&color=00ffff&logoColor=white&labelColor=1a4d66)
![Total Downloads](https://img.shields.io/github/downloads/JasperZebra/AVATAR-The-Game-Level-Editor/total?style=for-the-badge&logo=github&color=00ffff&logoColor=white&labelColor=1a4d66) 
![Platform](https://img.shields.io/badge/platform-windows-00ffff?style=for-the-badge&logo=windows&logoColor=00ffff&labelColor=1a4d66)
![Made for](https://img.shields.io/badge/made%20for-2009_AVATAR:_The_Game-00ffff?style=for-the-badge&logo=gamepad&logoColor=00ffff&labelColor=1a4d66) 
![Tool Type](https://img.shields.io/badge/type-level%20editor-00ffff?style=for-the-badge&logo=edit&logoColor=00ffff&labelColor=1a4d66)

# Avatar: The Game Level Editor

A comprehensive level editor for modifying **Avatar: The Game** and **Far Cry 2** level files with full FCB to XML conversion support and real-time visual editing capabilities.

## Features

- **Two games, one editor**: Full support for Avatar: The Game and Far Cry 2 — FC2 worlds load all 25 grid cells (5×5, each 16×16 sectors) as one editable map with real 3D models
- **Dual-Format Support**: Seamlessly works with both FCB and XML file formats with automatic conversion
- **Visual Entity Management**: Drag-and-drop positioning, rotation gizmos, and real-time property editing
- **Smart Entity Operations**: Copy/paste, duplication with auto-generated IDs, and batch operations
- **Interactive Canvas**: Color-coded entity visualization with adaptive grid system
- **Sector Management**: Visual boundary display with violation detection; entities moved across sector (or FC2 cell) borders are re-homed to the correct sector file on save
- **Terrain Editor**: In-app heightmap editing with brush tools and live preview — Avatar `.csdat` and Far Cry 2 `.sdat`
- **PAK Archive Support** *(Avatar)*: Select a `.pak` archive as your patch source — the editor unpacks it and uses the resulting folder automatically — then repack when you're done, either in full or as a small mod archive containing only what you changed

## Quick Start

### Game Selection
1. Select you game you want to start modding

| **New Game selection** |
|---|
| <img width="600" height="500" alt="Screenshot 2025-12-01 161755" src="https://github.com/user-attachments/assets/b5a75f8d-18e9-4a16-b099-4fd6be77b5c2" /> |

### Loading a Level
1. Set your `patch` folder for the game type you're currently modding
2. Level folders and files will be automatically read, loaded and converted as needed.
3. Select the level you want to load into the editor from the UI screen

#### Working straight from a `.pak` archive (Avatar)

You no longer need an external tool to unpack the game first. In the level
selector, **Change PAK File...** asks for an archive such as `patch.pak`,
unpacks it next to the archive, and selects the resulting folder as the patch
folder automatically. Everything after that works exactly as it does with a
folder you set by hand — the archive is only how the data arrives.

*(Far Cry 2 ships `.fat`/`.dat` archives, which aren't supported, so that button
stays **Change Patch Folder...** and browses for a folder as before.)*

When you're finished editing, **File ▸ 📦 Repack Patch Folder to .pak...**
builds an archive again, with two modes:

- **Everything in the folder** — a complete archive, replacing the original.
- **Only files changed since unpacking** — a small archive containing just your
  edits. The game layers archives over one another, so dropping this in as the
  next `patch.pakN` applies your changes without shipping a copy of the game.

Notes:
- Editor scratch files (`*.fcb.converted.xml`, `*.bak`) are never packed.
- An existing archive at the target is backed up to `.bak` before being replaced,
  and the new archive is only moved into place once it has been written in full.
- If the destination folder already holds edits, the editor tells you how many
  and asks before overwriting anything — it never silently discards work.

| **AVATAR** | **FARCRY 2** |
|---|---|
| <img width="1329" height="1096" alt="Screenshot 2025-12-01 161837" src="https://github.com/user-attachments/assets/0cd89cef-c05c-4341-ad62-7aef36d47eb4" /> | <img width="1600" height="1300" alt="Screenshot 2025-12-01 161923" src="https://github.com/user-attachments/assets/8c837629-b9b9-4c09-a856-eefbde5e8a31" /> |

## View Modes

### 2D Mode:
| **AVATAR** | **FARCRY 2** | 
|---|---|
| <img width="1808" height="1133" alt="Screenshot 2025-12-01 163403" src="https://github.com/user-attachments/assets/e69512a0-83c8-48e5-a2ec-b46e2506c165" /> | <img width="1807" height="1131" alt="Screenshot 2025-12-01 163745" src="https://github.com/user-attachments/assets/d2aa097d-7065-4440-8263-589983715e4d" /> |

### 3D Mode:
| **AVATAR** | **FARCRY 2** | 
|---|---|
| <img width="1801" height="1134" alt="Screenshot 2025-12-01 163508" src="https://github.com/user-attachments/assets/49fc5790-9758-4286-969c-474379842edb" /> | <img width="1803" height="1131" alt="Screenshot 2025-12-01 164020" src="https://github.com/user-attachments/assets/e310a42d-be1f-4485-9eef-4474f5669040" /> | 



### Basic Controls
- **Select**: Left-click (Ctrl+click for multi-select)
- **Move**: Drag entities or use Entity Editor
- **Rotate**: Use the blue rotation gizmo
- **Edit**: Open Entity Editor (Ctrl+E) for detailed properties
- **Save**: Use "Save Level" to convert back to FCB format

## Keyboard Shortcuts

### File Operations
| Action | Shortcut | Description |
|--------|----------|-------------|
| Open Level | `Ctrl` + `O` | Two-step level loading |
| Save Level | `Ctrl` + `S` | Save changes to FCB format |

### Entity Editing
| Action | Shortcut | Description |
|--------|----------|-------------|
| Entity Editor | `Ctrl` + `E` | Open property editor |
| Copy | `Ctrl` + `C` | Copy selected entities |
| Paste | `Ctrl` + `V` | Paste entities |
| Duplicate | `Ctrl` + `D` | Duplicate with +20 X/Y offset |
| Delete | `Delete` | Remove selected entities |


### View Controls
| Action | Shortcut | Description |
|--------|----------|-------------|
| Toggle 2D/3D | `Tab` or `T` | Switch between view modes |
| Reset View | `R` | Center and reset camera |
| Toggle Entities | `` ` `` | Show/hide entity visibility |
| Toggle Grid | `G` | Show/hide grid lines |

### 2D Camera Controls
| Action | Shortcut | Description |
|--------|----------|-------------|
| Pan Up | `W` | Move camera up |
| Pan Down | `S` | Move camera down |
| Pan Left | `A` | Move camera left |
| Pan Right | `D` | Move camera right |
| Speed Boost | `Shift` + `W`/`A`/`S`/`D` | 2.5x camera speed |
| Zoom | `Mouse Wheel` | Cursor-centered zooming |

### 3D Camera Controls
| Action | Shortcut | Description |
|--------|----------|-------------|
| Move Forward | `W` | FPS-style forward movement |
| Move Backward | `S` | FPS-style backward movement |
| Strafe Left | `A` | FPS-style left movement |
| Strafe Right | `D` | FPS-style right movement |
| Move Up | `E` | Vertical upward movement |
| Move Down | `Q` | Vertical downward movement |
| Speed Boost | `Shift` + movement | 2.5x movement speed |
| Look Around | `Right Mouse` + `Drag` | Rotate camera view |

### 3D Entity Movement
| Action | Shortcut | Description |
|--------|----------|-------------|
| Move Left | `←` | Move entity left on X-axis |
| Move Right | `→` | Move entity right on X-axis |
| Height Up | `↑` | Move entity up on Z-axis |
| Height Down | `↓` | Move entity down on Z-axis |
| Forward | `.` or `>` | Move entity forward on Y-axis |
| Backward | `,` or `<` | Move entity backward on Y-axis |
| Fine Control | `Shift` + arrow/`,`/`.` | Precise movement (0.01 units) |

### 3D Entity Rotation
| Action | Shortcut | Description |
|--------|----------|-------------|
| Rotate Left | `K` | Rotate entity CCW by 1° |
| Rotate Right | `L` | Rotate entity CW by 1° |
| Fine Rotation | `Shift` + `K`/`L` | Rotate by 0.1° increments |

## Entity Types & Visualization

Entities are automatically color-coded by type with size-based scaling:

- **Blue**: Vehicles (cars, boats, aircraft)
- **Green**: NPCs/Characters  
- **Red**: Weapons/Combat items
- **Orange**: Spawn points
- **Purple**: Mission objects
- **Yellow**: Triggers/Zones
- **Light Yellow**: Lights
- **Teal**: Effects/Particles
- **Gray**: Props/Static objects
- **Dark Gray**: Unknown types

## Supported Files

### Primary Files
- ``mapsdata.xml/.fcb`` - Main map data and entities
- ``managers.xml/.fcb`` - Game system managers
- ``omnis.xml/.fcb`` - Universal objects
- ``sectorsdep.xml/.fcb`` - Sector dependencies
- ``worldsector*.data.fcb`` - Individual sector data

Both FCB (native game format) and XML (human-readable) formats are supported with automatic conversion.

### Archives
- ``*.pak`` *(Avatar)* — `PAK!` version 4 archives (`data.pak`, `patch.pak`,
  `patch.pak0/1/...`). Read and written natively by the editor; unpacking an
  archive and repacking it untouched reproduces the original file byte-for-byte.

## Editor Components

### Entity Editor
- Real-time property editing with live preview
- Component system support (vehicle physics, graphics, missions)
- Direct XML field manipulation with type detection
- Optional auto-save functionality

### Visual Tools
- **Rotation Gizmo**: Interactive rotation with real-time angle display
- **Grid System**: Multi-level grids that adapt to zoom level
- **Sector Boundaries**: Visual boundaries with violation detection
- **Entity Browser**: Searchable, filterable entity management
- **Collision Viewer**: *View → Toggle Collision (Selected)* draws the selected
  entities' real in-game collision shapes (.hkx — boxes, spheres, capsules,
  convex hulls, triangle meshes) as orange wireframes over the model in 3D.
  Works in both games.
- **CS Camera Preview**: the *CS Camera Preview* section in the right panel
  shows the level through a cutscene camera's lens. Pick a sequence in the
  *Sequences* tab, choose a camera, then play or scrub — the preview flies the
  camera along its animation while the entities act out the sequence in the
  main view. Both games.
- **Armed vehicles render complete**: mounted weapons (the Dove's rear turret
  gun, FC2's jeep/boat .50cals) are attached automatically from the games'
  entity-library data, so vehicles no longer show up missing their guns.

## Safety & Best Practices

⚠️ **Important**: Always backup your level files before editing

## Contributing
Found a bug or want to contribute? Please create an issue or submit a pull request.

## Support
For issues and support, please create a GitHub issue with:
- Level file version
- Error message/logs
- Steps to reproduce the problem
