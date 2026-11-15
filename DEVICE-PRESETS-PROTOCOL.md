TEST128 — Copy stored presets between device slots

PRESETS now has Copy selected preset to slot. Select a stored source (Factory
or slots 1–8), choose a different destination (1–8), and review the confirmation.
Copy loads the stored source, replacing the current live mix and all unsaved
changes, then saves those settings over the destination. The destination keeps
its existing name and becomes the active preset. Use Rename separately if needed.
This is a compound load/save operation, not a newly invented device copy opcode.
There is no automatic rollback or restoration of the previously active mix.

Both captured slot names and the initial current/dirty state are checked before
writes. Source load must be confirmed before destination save. Destination name
and the newly loaded clean state are checked again before saving. Each operation
is sent at most once. An error stops the sequence and reports whether loading
was confirmed. A disconnect or application shutdown prevents the remaining save.
Mixer/name caches invalidate when source loading is attempted; reconnect never
replays a queued copy. Meter polling is serviced between the load and save.
No save, copy or load runs automatically on startup.

Run: bash run.sh. PRESETS -> select source -> Copy selected preset to slot.
Only choose a destination whose stored settings you intend to overwrite.

Validation: 1071 automated tests passed; Python compilation passed. Mock-native
checks verify the exact two packets, copied contents, unchanged other slots and
names, factory source, invalid destinations, external changes, failed/uncertain
load, failed save, no retries or rollback, disconnect, cancelled UI prompts,
stale connection and cache invalidation. Optional demo GUI runner now has 49
stages including preset copy. Rendered UI and physical copy are not yet verified
here. Acceptance is based on existing load/save completion and current-slot /
clean-state readback, not a byte-for-byte device preset-content readback.

Remaining protocol research: MIDI type packing was reconfirmed at agent
0x1404c33d7..0x1404c33e0, but Off/CC/Note enum labels remain unverified. Clock
frequency labels use a runtime UI string vector at 0x140498b35..0x140498b4b;
this does not establish their numeric meanings. No guessed type or clock writes
were enabled. The user-confirmed TEST126 preset-name boundary fix is retained.

Previous release notes:

TEST126 — Preset name field boundary correction

The supplied TEST125 hardware report identifies 12-byte preset-name fields.
Slot 2 contains MergedFronts at bytes 0–11; Preset3 starts at byte 12 and
Preset4 at byte 24. Bytes before and after the rename are identical. The
previous reader crossed the field boundary when a full 12-byte name had no
NUL, incorrectly displaying MergedFrontsPreset3. Padding did not fix that
read-boundary bug. Prior suffix-copy explanations were not the actual cause.

Preset reads now request exactly six 16-bit words per pass and require two
matching passes. Decoding stops at NUL or the 12-byte field boundary. A full
12-byte UTF-8 name needs no terminator beyond its field. Rename payloads are
bounded to 12 bytes, shorter names are zero-padded, and overlength names are
rejected rather than truncated. The dialog now states the 12-byte limit.
Raw rename diagnostics are also restricted to the same field. Channel-name
encoding is unchanged. No automatic hardware write is performed.

Run: bash run.sh, open PRESETS, then Read presets.
The existing hardware name should now show MergedFronts; there is no need to
rename, load or save the preset contents to correct this display issue.

Validation: 1042 automated tests passed; Python compilation passed. The exact
raw bytes from the user's report decode as MergedFronts with indices 0–5 only.
Tests also cover UTF-8 at the 12-byte boundary, shorter-name padding, no-op
renames, overlength rejection and unchanged adjacent preset storage.
No physical hardware was attached here for a new end-to-end run.


Historical protocol notes (name-field assumptions below are superseded):

# Native device presets — TEST85

Source: AudioFuse Control Center Agent 2.5.0.1665, Windows x64.
SHA256: `7a6b805d11170c9f35731b40f83c48efacfd248edc95c7baf6c6e01faad13513`.
All addresses below are native virtual addresses (image base 0x140000000).
Relevant disassembly is included in PRESET-NATIVE-EVIDENCE.txt.

## Operation evidence

The UI Load0…Load8 dispatch at 0x140496771–0x14049677d subtracts the
Load0 control ID and passes the resulting literal slot to 0x1404e4a00.
This function calls the USB transport vtable slot +0x60 at 0x1404e4aa9
with OUT direction, request 0x48, value 0, index equal to the slot,
length 1, and a zero byte initialized at 0x1404e4a2b.

Save dispatch at 0x140496407–0x140496413 computes the selected user slot
as control-ID offset +1, and calls 0x1404e4bb0. SaveCurrent (string
referenced at 0x140496466) reads CurrentPreset and passes it to the same
function at 0x140496562. The save function calls the same USB transport
at 0x1404e4c59, with request 0x48, value 1, literal slot index, length 1,
and a zero byte initialized at 0x1404e4bdb.

The known parameter OUT wrapper at 0x1407c74b0 calls this same transport
interface with the same argument layout (0x1407c7503–0x1407c7549), providing
the cross-check against the application's established vendor OUT 0x40.

| Action | bmRequestType | bRequest | wValue | wIndex | Payload |
| --- | --- | --- | --- | --- | --- |
| Load | 0x40 | 0x48 | 0 | Slot 0–8 | One zero byte |
| Save | 0x40 | 0x48 | 1 | Slot 1–8 | One zero byte |

The shipped Arturia manual also describes eight writable presets and
Factory preset 0 as load-only:
https://dl.arturia.net/products/audiofuse-16rig/manual/audiofuse-16rig_Manual_2_0_2_EN.pdf

## Readback evidence and bounds

The recovered global parameter table (group 3) contains CurrentPreset ID 8,
PresetHasChanged ID 9, and PresetName1…8 IDs 10…17. Existing scalar reads use
vendor IN 0xc0, request 0x90+group, parameter in wValue, word index in wIndex,
and two-byte little-endian data. Thus preset reads use request 0x93.
Name strings are read twice with at most 16 words per pass. Only matching,
terminated packed UTF-8 is accepted; unknown encodings block actions.
This applies the name-word packing already observed for analog channel names;
the preset-name response itself still requires physical confirmation.

Writes are restricted to the project's supported state version 18 and
explicit UI actions. Factory save is rejected in both UI and backend.
Before an operation, the current slot/dirty flag and selected slot name must
still match the page. Neither guard promises an atomic snapshot of every
setting; hardware controls can still change active settings concurrently.
Exactly one OUT is sent. Readback is bounded and never resends an uncertain
write. Success requires OUT length 1, current slot equal to the requested
slot, and dirty flag zero. This is the application's conservative acceptance
condition, not proof of flash persistence or an exhaustive content comparison.

After any actual load attempt, including uncertain completion, cached mixer,
preamp, routing and name data are invalidated and refreshed. Stale preflight
rejections send no command and do not clear the current state.

## Verification limits

Automated tests use a simulated USB transport and headless page logic. No
physical AF16Rig or rendered GUI verification was available for this update.
Native command behavior, preset-name packing and power-cycle persistence
need a short hardware check. No proprietary executable is included.

## TEST89 preset renaming

The recovered global table provides iPRESETNAME1…8 at IDs 10…17. The native
string writer at VA 0x1407c6ef0 appends a NUL byte, uses request 0x18+group
and index zero, and calls the established OUT wrapper at 0x1407c6f52. Thus
user slot s is written with vendor OUT 0x40, request 0x1b, wValue s+9,
wIndex 0, and UTF-8 plus NUL. This is distinct from preset load/save 0x48.
The command addresses and group layout are recovered evidence; physical
preset-name writes still need confirmation. No guessed content writes occur.

The backend requires state version 18, a valid user slot, a matching fresh
old-name read and a bounded printable name. After one OUT, a stable matching
name read confirms the new value, including if OUT completion was uncertain.
A disconnect stops immediately. Tests assert no load/save packet is sent.


TEST124 rename correction
-------------------------
TEST124 — Preset rename terminator and leftover-tail fix

Preset Rename now sends a zero-filled 16-byte payload: up to 15 UTF-8 name
bytes plus termination/padding. The former variable-length packet could have
an odd byte count, allowing a word-copying device to omit the trailing NUL.
A regression reproduces MergedFrontspreset3 from the old 13-byte packet against
an in-place, whole-word-copy USB model. The new packet reads back MergedFronts
and prevents retained suffixes. This firmware copy behavior is a model fitting
the user report, not a measured hardware trace.

Preset readback now stops at the first zero byte in either half of a packed
word, instead of requiring an entirely zero word. Both reads must still match;
unrecognized text and unterminated data still fail. Only preset-name handling
changed; channel names and preset contents are untouched. Renames remain one
OUT request with confirmation reads, and no write retry.

To repair the existing slot: launch with bash run.sh, open PRESETS, select the
slot displaying MergedFrontspreset3, and Rename it to MergedFronts again.
No automatic rename or preset-content save/load is performed by this update.

Validation: 1036 automated tests passed; compilation passed. New tests cover
the exact reported suffix, repair of an already-corrupted label, all 0–15 byte
lengths, UTF-8, adjacent-slot isolation, and both terminator positions with
nonzero old bytes following them. Physical confirmation remains pending.

