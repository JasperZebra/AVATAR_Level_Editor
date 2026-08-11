# .ai.rml prefix regeneration spec (BlackBox.AI brains)

Goal: regenerate the entire file prefix `[0 : nodeStart]` byte-exact purely from the node
tree (`C.decode_ai_rml(data)` root `<BlackBox.AI>`), so brain nodes can be added / removed /
edited and the file repacked byte-exact.

`nodeStart = len(file) - tailSize`. The prefix consists of:
`header(16) | class-template table | path/hash table`.
The tail `[nodeStart:]` is the node-tree + shared-string-pool, a self-contained Dunia
binary-XML object reproduced byte-exact by `C.encode(node_tree_root)`.

All multi-byte integers are little-endian. "crc32" everywhere = the avatar crc32 (zlib
poly 0xEDB88320, init/final 0xFFFFFFFF). `crc32(name)` is over the exact ASCII bytes.

Validation status of this spec (29 brains, 19675 addressable objects):
- header fields ......................... 29/29 files byte-exact
- class-template table ................... 29/29 files byte-exact
- value-hash (valHashes) list ............ 29/29 files byte-exact
- record list + ordering + A trailer ..... 29/29 files (A: see open item)
- per-object metadata-blob SLICE CONTENT .. 19675/19675 objects byte-exact
- blob-slice ORDER (the B offsets) ........ OPEN (1/29; see section 8). Everything else
  is fully derived; only the order in which slices are concatenated into the blob is
  not yet a closed formula. Slice bytes themselves are 100% solved.

Terminology:
- "addressable object" = a direct child of the root `<BlackBox.AI>` that has a `Class`
  attribute (Brain / Plan / Task / Scanner). Tag is `Brain`, `Plan` or `Task`.
- "full name" / path = the object's `Name` attribute (e.g.
  `::EmptyBrain/EmptyBrain/Sleep`).
- "record index" (ridx) = the object's position in the path/hash RECORD order (section 4).
  recordCount == number of addressable objects (verified 29/29, including the large
  blueprint brains; there is NO inflated/expanded node array — the earlier "records <
  objects" discrepancy was a heuristic-parser bug, not a real index space).
- "Add tree" = containment tree formed by `<Add Task=path/>` (also `Brain`/`Plan`) children.
  parent(X) = the unique object whose `<Add>` declares X. Objects with no parent are
  either the root brain(s) or orphan blueprint plans.

================================================================================
1. CLASS-TEMPLATE TABLE  (already solved; restated, re-verified 29/29)
================================================================================
For each addressable object, build a `<Parameters>` element:
  - attrs in order: `Name=" "` (a single space), then `Looping`, then `Independent`
    (each only if present on the object), then one attribute per top-level
    `<Parameter Name=X Value=Y>` as `X="Y"` (empty Value -> `X=""`), in document order.
  - THEN append one CHILD element per top-level `<Parameter>` that itself contains nested
    `<Parameter>` children: child tag = that parameter's `Name`; child attrs = each nested
    `<Parameter Name=a Value=v>` as `a="v"`.
Encode it: `enc = C.encode(thatParametersElement)`. Entry = `crc32(object.Class)(u32)
+ len(enc)(u32) + enc`.
Dedup entries by the pair `(crc, enc)` keeping FIRST-occurrence order across objects
(document order). `classCount` = number of unique entries. The table is the concatenation
of the unique entries.

================================================================================
2. VALUE-HASH LIST  (valHashes)  — re-verified 29/29 byte-exact
================================================================================
A de-duplicated (by crc32) list of crc32 values of "port/connection-participating"
strings, in FIRST-OCCURRENCE order under a pre-order DFS over the brain tree
(ElementTree `root.iter()` / document order). Walk every element of every addressable
object; a string qualifies and is appended (if its crc32 not already present) when:
  (a) element is `<Selectable>` AND has BOTH a `Task` attr AND a `Filter` attr  -> add Filter
  (b) element is `<Anchor>`/`<Exit>`/`<Event>`/`<UserEvent>` that has >=1 connection
      child (a `<Connection>` OR a `<UserEvent>` child) -> add its `Name`
  (c) for each connection child (`<Connection>` or `<UserEvent>`) of such a port
      -> add that child's `TargetAnchor`
The codes used throughout the slice encoding are indices INTO this list:
`code(name) = valHashes.index(crc32(name))`.
Index 0 is always `crc32("DefaultSelectable")` because emptybrain / every simple brain
has a Task-bearing `DefaultSelectable` Selectable that is the first qualifying string.

================================================================================
3. PER-OBJECT METADATA-BLOB SLICE  (the hard part — SOLVED, 19675/19675)
================================================================================
Each addressable object owns one contiguous slice `blob[B : B+C]`. The slice encodes the
object's Selectable membership and its outgoing connection graph. It is built from the
object's tree as follows.

Helper definitions (per file):
  ridx(path)      = record index of path (section 4 ordering)
  code(name)      = valHashes.index(crc32(name))
  parent(path)    = Add-tree parent of path (None if it has none)
  is_brain(cls)   = "Brain" in cls            (Class string contains the substring "Brain")
  is_container(cls) = is_brain(cls) OR "PlayActionBrain" in cls
                      (in practice: any class whose name contains "Brain", i.e. every
                       CBrain* / CPlayActionBrain / BrainTapirus / BrainHexapede / ...)
  source ports of o = the `<Anchor>/<Exit>/<Event>/<UserEvent>` descendants of o (any
                      depth) that have >=1 connection child, IN DOCUMENT ORDER. A
                      connection child is `<Connection>` or (rare) `<UserEvent>`.

3.1 SLICE HEADER  (decided by the object's role in the Add tree)
  Let cls = o.Class, name = o.Name.
  - ROOT BRAIN: name has no parent AND is_brain(cls).
        header = [0x00] [X u16] [marker u16]
        X      = ridx(Task of the FIRST `<Selectable>` of o whose Task resolves to a record)
        marker = code(Filter of that same first Selectable)
                 (this is 0x0000 only by coincidence when that Filter's code is 0,
                  e.g. AnimalBhvIdle/DefaultSelectable; it is 0x19 for CBrainLayeredPatrol
                  whose first Filter "stateFollowPatrol" has code 25 — so the marker is
                  NOT a constant, it is the first-Selectable filter code).
        If the brain has no resolvable Selectable, X=0, marker=0.
  - HEADERLESS ORPHAN: name has no parent AND NOT is_brain(cls).
        NO header bytes at all. The slice begins directly with the connection groups.
        These are exactly the "Blueprints/Template*" pass-through CPlans that nothing
        `<Add>`s. (Discriminator is exact: no-parent & not-a-brain => headerless. 71 such
        objects corpus-wide, 0 mispredictions.)
  - STANDARD (has a parent):
        header = [0x04] [ridx(parent(name)) u16]
        i.e. byte0 = 0x04, the next u16 = the parent object's record index.

3.2 MEMBERSHIP ENTRIES  (only for container classes, never for headerless orphans)
  Emitted only when is_container(cls) and the object is not headerless. One entry per
  qualifying `<Selectable>` child IN DOCUMENT ORDER, where qualifying = has a Task that
  resolves to a record AND has a Filter. For a ROOT brain, SKIP the first qualifying
  Selectable (it is already encoded as the header X/marker); for a non-root container,
  emit all qualifying Selectables.
        entry = [0x00] [ridx(Selectable.Task) u16] [code(Selectable.Filter) u16]
  Note the field order: child record index FIRST, then the filter code.
  (Plain `CPlan` containers that have `<Add>` children but are NOT a Brain class emit NO
  membership — membership is gated purely on is_container, i.e. the "Brain" class family.)

3.3 CONNECTION GROUPS  (all object kinds, after header+membership)
  One group per source port (section 3 "source ports", document order):
        group = [srcType u8] [code(port.Name) u16] [connCount u16]
                then connCount connections
        srcType: 1 for <Anchor>, 2 for <Exit>, 3 for <Event> and 3 for <UserEvent> (port).
        connection = [ridx(conn.Target) u16] [code(conn.TargetAnchor) u16] [st2 u8]

  st2 rule (validated to the byte, 0 exceptions over all parseable connections):
        if the connection child tag is <UserEvent>:                       st2 = 6
        elif Target == name or Target.startswith(name + "/")  (descendant): st2 = 1
        elif parent(Target) == parent(name)  (true sibling) AND
             lastcomponent(Target).startswith(lastcomponent(name)):        st2 = 1
        else:                                                              st2 = 2
   (The sibling+name-prefix branch is the "split/clone task" case, e.g. source `Shoot`
    -> sibling `ShootErrorWeaponJam1`, `WaitMountedWeaponState` -> `...State1`,
    `CTaskWait1` self-loop. 56 such cases, all st2=1, zero false positives. The
    `<UserEvent>`-child connection appears in exactly 1 object corpus-wide, st2=6.)

  Worked examples (byte-exact):
   - chalicebrain WaitIsNotAware: 04 06 00 | 01 0100 0100 | 02 0300 0200
     = standard header parent ridx 6; Anchor OnStart(code1) 1 conn -> (ridx4, Start code2,
       st2=1 descendant); Exit Success(code3) 2 conns -> (ridx3,code2,st2=2)(ridx4,code4,2).
   - combatscorpion Main/AimingPlan (CBrainVehicle, non-root container):
     04 07 00 | 00 0c00 0700 ... (membership: [00][ridx 12][filterCode 7=taskNoOwner], ...
     11 entries, one per Selectable) | 01 0100 0100 1900 0200 01 (OnStart -> ridx25 Start).
   - tapirus BrainTapirus (root): 00 0400 0000 (header X=4=ridx(Idle), marker=0=
     code(AnimalBhvIdle)) then 5 membership entries for Selectables 2..6 (the first is
     skipped) | (no groups).
   - ampsuit Blueprints/TemplatePathFind (headerless orphan CPlan):
     05 00 01 00 32 00 06 00 01  =  group Anchor OnStart(code5) 1 conn -> (ridx50 PathFind,
     Start code6, st2=1). No header bytes precede it.

================================================================================
4. RECORD LIST + TRAILERS  (path/hash table records)
================================================================================
recordCount == number of addressable objects (always; 29/29).
RECORD ORDER: ascending by crc32(fullPath). To regenerate, take all addressable-object
full Names, sort by crc32(name) ascending (no ties occur). This defines ridx.
Each record = crc32(path)(u32) + len(path)(u32) + path(ASCII bytes) + trailer[A,B,C].
  A (u32) = a tree-traversal ordinal over the Add containment tree (Brain root = 0). Two
            observed numbering classes (chalice-style = pure DFS preorder ordinal over the
            Add tree; dronebomb-style = every container Plan stamped 1, leaves counted from
            2). The exact class discriminator is OPEN (see section 8); A is not needed for
            the slice content and does not gate the connection grammar.
  B (u32) = byte offset of this object's slice within the metadata blob.
  C (u32) = slice length = len(emit_slice(o)) from section 3 (fully derivable, 19675/19675).
The (B,C) pairs TILE the blob with no gaps. B is assigned by the blob-slice ORDER
(section 8), which is the one remaining open ordering.

================================================================================
5. METADATA BLOB + COUNTS (path/hash table layout)
================================================================================
Path/hash table (immediately after the class-template table, ending at nodeStart):
  [blobSize u32] [blob (blobSize bytes)]
  [valHashCount u32] [valHashCount * crc32 u32]   (section 2 list)
  [recordCount u32] [recordCount records]         (section 4)
  blobSize       = sum of all slice lengths C = len(blob).
  blob           = the slices (section 3) concatenated in blob-slice order (section 8).
  valHashCount   = len(valHashes).
  recordCount    = number of addressable objects.

================================================================================
6. HEADER  [0:16]  — re-verified 29/29 byte-exact
================================================================================
  [0:4]   ver       = 4 (constant in all 29 files)
  [4:8]   poolSize  = nodeStart - 12
                    = 4 + len(class-template table) + len(path/hash table)
                    (the +4 is the classCount u32 at offset 12)
  [8:12]  tailSize  = len(C.encode(node_tree_root))  (length of the tail object)
  [12:16] classCount = number of unique class-template entries (section 1)
nodeStart = 12 + poolSize = len(file) - tailSize. Class table starts at offset 16; path/
hash table starts right after it and ends at nodeStart.

================================================================================
7. END-TO-END REGENERATION ORDER
================================================================================
  1. root = C.decode_ai_rml(data); objs = addressable objects (document order).
  2. ridx: sort obj names by crc32 -> record order (section 4).
  3. valHashes (section 2); code(name) = valHashes.index(crc32(name)).
  4. For each object emit_slice (section 3); C = its length.
  5. Decide blob-slice order (section 8 — OPEN), assign B offsets by tiling in that order,
     concatenate slices -> blob, blobSize = len(blob).
  6. Build records (crc32(path), len, path, A, B, C) in record order; A per section 4.
  7. Assemble path/hash table (section 5).
  8. Class-template table (section 1); classCount.
  9. tail = C.encode(root); tailSize = len(tail).
 10. poolSize = nodeStart - 12 where nodeStart = 16 + len(classTable) + len(pathTable).
 11. file = header(ver=4, poolSize, tailSize, classCount) + classTable + pathTable + tail.

================================================================================
8. OPEN ITEMS
================================================================================
A. BLOB-SLICE ORDER (the only thing blocking full byte-exact blob reassembly). The slice
   CONTENT and length C are 100% solved; B offsets tile the blob in a third ordering that
   is neither record order (crc32-asc), document/preorder, plain post-order, reverse-pre,
   nor leaves-first post-order (each reproduces only the single trivial file chalicebrain).
   Evidence (chalicebrain, blob order with each slice's A ordinal):
     Delay(A9) ReleaseWasp(A8) IsTargetInRange(A7) StartSpawn(A3) StopSpawn(A4)
     AttackPlan(A6) WaitIsAware(A5) WaitIsNotAware(A2) MainPlan(A1) ChaliceBrain(A0)
   It is a children-before-parent DFS variant (root/containers trend toward the end,
   deepest leaves toward the front) but the child visitation order within a parent is not
   plain forward or reverse Add order. It is almost certainly the tail Dunia-encoder's
   internal object emission order; resolving it likely also closes the A-trailer class
   discriminator (B). Until then, B offsets must be read from the source file rather than
   regenerated, which is sufficient for EDIT operations that preserve object set/order but
   not for arbitrary add/remove.
B. A-trailer numbering class discriminator (chalice-style sequential-preorder vs
   dronebomb-style container=1 + leaf-counter). Not needed for slice content; likely tied
   to (A).

================================================================================
RESOLVED INVESTIGATOR CONTRADICTIONS (checked against the files)
================================================================================
- "records < objects in big files / inflated blueprint node array" (investigators 1 & 3):
  FALSE. recordCount == addressable-object count for ALL 29 files (mercbrain
  10836==10836). The discrepancy was purely the heuristic path-table scanner; reading
  recordCount forward from the structure recovers every record. Therefore b1/X is plain
  record index everywhere (parent record index for standard slices, byte-exact incl.
  mercbrain 10791/10791), with NO inflated index space.
- "slice header = [0x04][parentRecordIndex u16]" (inv 1) vs "[b0][u16 X]" (inv 3): both
  describe the STANDARD case correctly; the full set of header forms is in section 3.1
  (root brain 0x00, headerless orphan = none, standard 0x04). slice[2] is just the high
  byte of the u16, nonzero when the parent index >= 256.
- "anchor codes = per-file table with mysterious base offset" (inv 1) vs
  "code = valHashes.index(crc32(name))" (inv 2): inv 2 is correct and exact; the codes ARE
  valHashes indices, the "base offset/gaps" were just where anchor names land in the
  first-occurrence list. Re-verified: all source codes, all target codes, all membership
  filter codes, and the root marker are valHashes indices, 0 mismatches.
- membership entry field order: it is [0x00][childRecordIndex u16][filterCode u16] for
  ALL containers (root and non-root alike); the earlier "[code][ridx]" reading was a
  mis-alignment. Root brains additionally skip their first Selectable (stored as header X).
- st2: descendant-vs-not is the base rule; the documented exceptions are exactly the
  sibling-name-prefix clones (st2=1) and the single <UserEvent>-child connection (st2=6).
