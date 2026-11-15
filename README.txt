BETA RC — see README.md for installation, screenshots and validation.

Development history

TEST167 — Linux GUI check corrections

Checks the eleven current navigation tabs by label and order at both window sizes.
Navigation failures are reported separately from mixer geometry and panel checks.
Scene rate matching and setting recall use ttk's enabled-state query.
Run bash test-gui.sh from the extracted folder on a Linux desktop.
All 1,388 automated unit tests passed. A desktop run of TEST167 is pending.

TEST166 — Linux installation reliability and current GUI checks

The per-user installer now activates the new release only after copying its
icons and writing the desktop launcher successfully. Icons and launcher files
are replaced atomically instead of being overwritten in place. Copy, launcher
or activation failures keep the previous active application selected and clean
up the incomplete new release and staging files. Previous successful releases
remain available. Some completed icon updates can remain after a later failure;
the previous application itself stays active.

The unattended Demo GUI check has been updated for the current Phones level
control and the Main Mix fit-to-width layout. It now exercises mixer scene save,
rate matching, fresh preview and setting recall through real Tk widgets when
run inside a Linux desktop session. Physical USB access is blocked by the check;
it uses Demo mode and does not require the Rig16. The harness allows additional
time for the complete scene readback stages.

Validation performed here:
- 1,388 automated tests passed; Python compilation passed.
- Simulated mid-icon-copy, launcher replacement and final activation failures
  preserve the previous active release. Staging files are cleaned up.
- Installed the real package into a temporary user-data directory, deleted the
  extracted download, then successfully ran the installed launcher with --help.
- desktop-file-validate passed for that installed launcher.

Live GUI validation was attempted but blocked: this runtime has no DISPLAY or
X server. The GUI check reported blocked, not passed. The existing package tool
could not locate Xvfb. Real Rig16 testing and desktop/taskbar appearance remain
unverified here. No claim of a real GUI or hardware pass is made.

To run the unattended GUI check on your Linux desktop, from this extracted
folder: bash test-gui.sh
It writes AF16Rig-GUI-check.json. No physical button testing is required.

Scene format remains v16. No hardware commands, mixer layout or polling
frequency changed. MIDI Learn and immersive/bass management remain deferred.

Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST165 — Internal sample rate in mixer scenes

PRESETS → Mixer scene files… now captures the device's Internal sample rate.
When it differs from a saved scene, Match sample rate applies that rate through
the existing idle-device ALSA path, confirms device readback and reads a new
scene preview. Recall listed settings remains a separate action afterwards.

Supported rates are 44.1, 48, 88.2, 96, 176.4 and 192 kHz. Both selected and
preferred clock must be Internal. AF16Rig audio streams must be closed; close
or release the device in your DAW/JACK/PipeWire before matching. The app does
not stop audio services, detach USB drivers or start playback. An audio
application may choose a different rate when it reopens the interface.

External-clock captures store no Internal rate target. A scene targeting an
external clock does not request an Internal sample-rate change. If an Internal
scene is opened while external clock is selected, select Internal on the Clock
page and refresh the scene preview first.

The action checks the preview rate, uses the established clock-state and ALSA
idle guards, applies once and confirms the rate after closing the ALSA handle.
No uncertain apply is retried or rolled back. Stop takes effect after the
current rate operation. A failed confirmation may leave a changed rate; refresh
to inspect it. New capture handles any resulting mixer-layout differences.

Scene format v16 adds a sample-rate record. Formats v1–v15 retain their existing
scope and never request rate matching. Existing hardware-link, source matching,
layout matching and clock configuration features remain available. Main mixer
layout and polling frequency are unchanged.

Validation: 1,383 automated tests passed; Python compilation passed.
New tests cover all 36 rate transitions in Demo, invalid/stale/external states,
a native-path simulated ALSA apply with device readback, busy-stream rejection,
match → fresh preview → explicit recall, legacy v15, external-clock scenes,
Stop and malformed saved rates. Existing ALSA resource cleanup, stream races
and no-retry checks also pass. Real Rig16 and live GUI verification remain
pending; simulated checks are not hardware confirmation.

The listed scene-recall feature gaps now have implementations. Remaining work
is hardware verification, final Linux GUI/install checks, and investigation of
unmapped controls. MIDI Learn and immersive/bass management remain deferred.

Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST164 — Match mixer layout from a saved scene

PRESETS → Mixer scene files… now offers Match mixer layout when Main/Cue
channel inclusion or mono/stereo selection differs from the saved scene.
The preview lists each affected pair as Not included, individual Mono members,
or Stereo across Analog, ADAT and USB. Click Match mixer layout, then review
the fresh scene preview before recalling settings. Input source matching can
follow if the saved front/rear sources also differ.

The action uses the existing checked single-bit membership commands. Obsolete
selections are removed first, then replacement selections are added, avoiding
simultaneous mono/stereo membership. Only differing bits are written. Both Main
and Cue layouts are checked before and after each write. Native OUT commands
are not retried; an unexpected state or rejection stops subsequent steps.
Stop works between individual writes. Previously confirmed changes remain.

Matching layout can change audible channels at their current levels. It does
not recall saved levels or other controls automatically. After successful
matching, a complete new capture and preview must be reviewed before clicking
Recall listed settings. Hardware and Demo scenes cannot be mixed. Scene format
remains v15; older mixer scenes retain their setting recall scope.

Validation: 1,374 automated tests passed; Python compilation passed.
Native fake-device coverage includes all 1,600 pair transitions (five possible
membership states, 32 pairs, both Main/Cue buses), exact packets and indexes,
no-op layouts, rejection without retry, stale layout, malformed steps,
unexpected side effects, Stop between writes, fresh-preview workflow and
hardware/Demo separation. Real Rig16 and live GUI verification remain pending.

Main mixer layout and polling frequency are unchanged. Remaining work includes
sample-rate scene support, hardware verification and unmapped controls. MIDI
Learn and immersive/bass management remain deferred.

Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST163 — Match input sources from a scene preview

PRESETS → Mixer scene files… now offers Match input sources when the active
input kinds differ from a saved scene. Review the KIND rows, click Match input
sources, then review the fresh preview before clicking Recall listed settings.
The source-matching action does not recall gains, PAD, links or mixer settings.

Matching uses the existing pair front-detection/rear-override commands for
inputs 1/2 and 3/4. Both pairs are planned against live jack detection before
any writes. Compatible front Line/Mic and mini-jack connections must physically
be present. Unreachable saved source combinations (including some mixed
front/rear pairs) require manual connection/source changes; the action does
not guess or substitute a different source. Unchanged pairs are left alone.
Other override bits are preserved. Mixer source/stereo layout must still match.

Live source status is checked before each pair switch and read back twice after
it. Changed connections, stale source state, rejected writes or layout changes
stop the action without retries or rollback. Earlier source changes remain.
Stop takes effect after this source-matching operation, at most four checked
native writes. A fresh full scene capture follows successful matching, and
setting recall requires a separate click after that new preview. Hardware
scenes and Demo scenes cannot be mixed.

File format remains v15; no saved fields were added. Older scenes containing
input source kinds can use this explicit matching step. Their original recall
scope and link rules remain unchanged. Scenes predating input capture have no
source-matching action. Polling and mixer layout are unchanged.

Validation: 1,364 automated tests passed; Python compilation passed.
New tests cover 1,536 planner combinations, exact native commands for both
pairs and directions, other-bit preservation, rejected writes, an unreachable
second pair blocking all writes, connection changes, invalid/stale states,
source match → fresh preview → explicit recall, Stop, older scenes and Demo/
hardware separation. Real Rig16 and live GUI verification remain pending.

Remaining work includes mixer source/stereo layout recall, sample-rate scene
support, hardware verification and unmapped controls. MIDI Learn and immersive/
bass management remain deferred.

Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST162 — Front Line/Mic hardware links in mixer scenes

PRESETS → Mixer scene files… now restores the front 1/2 hardware stereo link
when both inputs already use the same front Line or Mic mode. Existing rear
hardware-link recall remains supported. Source selection is not changed.
Mixed Line/Mic, front/rear and mini-jack pairs are not automatically linked.

Unlinking happens before restoring independent input settings; linking happens
after restoring the matching saved gain/PAD/polarity/HPF and, for front Line,
Instrument settings. Incompatible linked targets are rejected during preview.
The complete active-pair state and mixer layout are checked before and after
the established native link command. A stale state, rejected write or unexpected
side effect stops recall with no repeated write or rollback. Previously
confirmed changes remain. A front link operation sends at most one native write.
Device firmware may still reject a link; real hardware verification is pending.

Format v15 adds front-link recall semantics. Older formats keep their original
behavior: v14 supports rear-link recall only, and v1–v13 require matching input
hardware links. Output link recall from v13 and clock recall from v12 remain
supported. No GUI layout or polling-frequency changes.

Validation: 1,355 automated tests passed; Python compilation passed.
New checks cover native Line/Mic link and unlink packets, unrelated link-bit
preservation, rejection without retry, full scene recall in both directions,
Instrument mismatch, mixed and mini sources, stale source/settings, unexpected
side effects and v14 rear/output-link compatibility. These checks simulate the
device; real Rig16 and live GUI verification remain pending.

Remaining scene work: automatic input source selection, mixer source/stereo
layout recall and sample rate. Unmapped controls remain unimplemented. MIDI Learn
and immersive/bass management remain deferred.

Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST161 — Rear-input hardware links in mixer scenes

PRESETS → Mixer scene files… now restores rear-input hardware stereo links
for all eight analog pairs, provided both members are already using rear inputs.
These are hardware preamp links, separate from the mixer stereo-strip layout.
Input source selection, front hardware links and mixer layout still must match.

For a link-state change, unlinking runs before restoring independent input
settings; linking runs after the saved gain/PAD/polarity/HPF settings are restored.
Link targets require consistent flags and matching gain/PAD/polarity/HPF values
on both members. Preview rejects incompatible targets rather than guessing
which side should win. Existing linked-state recall behavior is retained when
the link itself does not change.

Each link operation checks the complete saved active-input pair state before
and after the existing native link writer. Changed sources, mixer layout,
settings or unexpected side effects stop recall. There is no write retry or
rollback. Partial writes remain; later scene steps are not sent. Stop applies
after the current link operation, which sends up to two checked native writes.
Final full scene readback verifies the saved scope.

Format v14 adds rear-link recall semantics while retaining the existing file
shape. Formats v1–v13 remain supported with their original input-link matching
requirement. Output link recall from v13 and clock recall from v12 remain intact.

Validation: 1,348 automated tests passed; Python compilation passed.
New tests check exact native packets for link and unlink on all eight pairs,
preservation of other pairs, complete scene-controller batches in both
directions, operation ordering, stale sources/settings, incompatible targets,
unexpected side effects, partial failure stopping later writes, preflight
changes and v13 compatibility. Real hardware and live GUI verification remain
pending; simulated checks are not hardware confirmation.

Remaining scene work: automatic input source/front-link and mixer-layout recall,
and sample rate. Unmapped controls remain unimplemented. MIDI Learn and
immersive/bass management remain deferred. Mixer layout and polling unchanged.

Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST160 — Analog output stereo-link scene recall

PRESETS → Mixer scene files… now recalls output stereo links together with
levels for pairs 3/4, 5/6, 7/8 and 9/10. Each pair has one preview row showing
its link status and both levels. New scenes no longer require manually matching
output links before recall. Mixer source/layout and input hardware links still
must match.

When needed, recall temporarily unlinks the output pair, restores its individual
levels, then restores the saved stereo link. Linking happens after both levels
are equal, avoiding gain mirroring overwriting a different saved value. Mixed
current link flags can be repaired. A saved mixed link state, or linked pair
with unequal saved levels, is rejected during planning if it needs recall.
Such snapshots remain readable and unchanged pairs need no writes.

Pair levels and link flags are checked before and after each operation; layout
changes also stop recall. Failed or uncertain writes are not repeated or rolled
back. Earlier confirmed changes remain. Stop takes effect after the current
pair operation (up to six checked native writes). A complete final scene readback
checks the result. Output pairs restore before speaker A/B and Monitor controls.

Scene format v13 retains the saved output data shape. Formats v1–v12 remain
supported with their original behavior: versions containing output levels still
require matching output links and do not change those links. Their preview rows
also show the combined pair state.

Validation: 1,340 automated tests passed; Python compilation passed.
New fake-device checks cover 96 output-pair combinations, all four pairs and
starting link-bit states, simulated firmware gain mirroring, preservation of
other outputs, invalid and stale state, partial link failure, unexpected gain
changes, layout changes, new and legacy scene-controller recall. These tests
are automated simulations; real Rig16 and live GUI verification remain pending.

Linux installer, boxed 16 RIG icon, USB 1/2 on page 1, accepted mixer layout and
polling frequency are retained. MIDI Learn and immersive/bass management remain
deferred. Remaining scene work includes automatic mixer/input source and link
recall, plus sample rate. Unmapped controls are not implemented.

Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST159 — Clock configuration in mixer scenes

PRESETS → Mixer scene files… now saves and recalls clock source (Internal,
ADAT or Word clock), word-clock termination, word-clock thru and Double SMUX.
The preview shows these as one CLOCK configuration row.

Clock configuration is recalled after the other scene controls. Termination,
thru and SMUX are set before selecting the clock source. Each changed setting
uses the existing checked native write and full configuration readback. Before
any clock writes, external clock targets require a recognized frequency; the
source setter checks again immediately before switching. Clock changes can
interrupt audio. Earlier scene changes remain if clock recall fails.

Sample rate is not stored or changed by scenes; use the Clock page for that.
Preferred source is device-managed and is not written by scene recall.
No retries of uncertain writes, no rollback. Stop takes effect after the current
configuration operation (at most four checked writes). Final scene readback
checks all saved controls. Scene format v12; v1–v11 remain supported and do not
change clock settings.

Validation: 1,332 automated tests passed; Python compilation passed.
Fake-device tests cover all 576 clock configuration transitions with exact
packets and ordering, absent external clock, invalid/stale state, rejected
writes, unexpected side effects, clock loss before source switching, v11
compatibility and incremental scene preview/recall. Real hardware and live GUI
verification remain pending.

Remaining work: automatic source/layout/hardware-link recall; scene sample-rate
support; unmapped controls and hardware verification. MIDI Learn and immersive/
bass management remain deferred. Polling and mixer layout are unchanged.

Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST158 — Speaker A/B scene configuration

PRESETS → Mixer scene files… now includes A/B enable, selected speaker and
B output pair as one configuration row. Preview shows Enabled/Disabled,
Speaker A/B and B outputs 3/4, 5/6, 7/8 or 9/10.

Recall follows existing device requirements: select A before reassigning an
active B pair; temporarily enable A/B when needed to restore a stored speaker
selection; restore the saved enable state last. These temporary speaker changes
are explained on the scene page. Each intermediate configuration is read back
before continuing. A mismatch stops the sequence with earlier changes retained;
uncertain writes are not retried or rolled back. Stop takes effect after the
current configuration operation (at most five checked writes).

A/B configuration restores after routing, output levels and B trim, before
Monitor/Phones settings. Complete final scene readback confirms the saved scope.
Format v11 adds the configuration record; v1–v10 remain compatible and leave
A/B enable/selection/output assignment untouched.

Remaining scene work includes automatic source/layout/hardware-link recall
and clocks. Unmapped controls such as phantom power are not implemented.
MIDI Learn and immersive/bass management remain deferred.

Validation: 1,322 automated tests passed; Python compilation passed.
The new native fake-device tests exercise all 256 A/B configuration transitions,
exact packets and operation order, stale state, failed-write stop without retry,
unexpected side effects, v10 compatibility and incremental scene recall.
Real Rig16 and live GUI verification remain pending.

Linux installer, boxed 16 RIG icon and USB 1/2 on page 1 are retained.
Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST157 — Front Line/Instrument mode in scenes

PRESETS → Mixer scene files… now captures and recalls Line/Instrument mode on
front inputs 1 and 2 when those front jacks are active. Other input modes show
N/A; scenes cannot force an Instrument setting onto rear, mic or mini inputs.
Writes reuse the checked front_line_instrument control, preserving unrelated
packed bits. Source and hardware-link context are rechecked before each write.
Both members retain separate settings, followed by full-scene verification.

Scene format v10 adds Instrument mode. v1–v9 remain supported and leave this
setting unchanged. Existing gain/PAD/polarity/HPF recall remains included.
Phantom power is not mapped in the current backend and is not added by this
release. Automatic source/layout/link recall, speaker A/B enable/selection/
assignment and clock recall remain outstanding. MIDI Learn and immersive/bass
management remain deferred.

Validation: 1,315 automated tests passed; Python compilation passed.
New tests cover both native front-jack packet addresses, on/off readback and
unrelated-bit preservation; v9 compatibility; inactive-mode and invalid-value
rejection; incremental preview/recall and stale-source cancellation.
Hardware and live GUI verification remain pending.

Linux installation, boxed 16 RIG icon and USB 1/2 on page 1 are retained.
Close the app, extract and update: bash install-desktop.sh
Then launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST156 — Input polarity and high-pass filter scene recall

PRESETS → Mixer scene files… now also captures and recalls polarity inversion
on all 16 active analog inputs and high-pass filter switches on rear/front-mic/
front-line inputs. Active front mini inputs expose polarity but no HPF in the
existing supported control path; their HPF preview is N/A and no write is sent.

Input gain/PAD, polarity and HPF keep independent member values. Recall requires
matching active input modes and hardware-link context. Writes use the existing
checked input APIs, with context rechecked throughout and complete final scene
readback. A mismatch stops the batch; uncertain writes are not retried.

Scene format v9 adds phase/HPF fields. v1–v8 remain supported. v8 files leave
phase/HPF unchanged; earlier formats retain their original recall scope.

Still excluded: phantom/impedance and other input-mode controls, automatic
source/layout/link recall, A/B enable/selection/output assignment and clocks.
MIDI Learn and immersive/bass management remain deferred.

Validation: 1,310 automated tests passed; Python compilation passed.
New tests verify native switch packets across rear/front-line/front-mic/mini
paths and preservation of unrelated packed bits; legacy v8 compatibility;
mini HPF rejection; stale source rejection; full incremental recall batches.
Live Rig16 and GUI verification remain pending.

Linux installer, boxed 16 RIG icon and USB 1/2 on page 1 are retained.
Close the app, extract and update with: bash install-desktop.sh
Launch AF16Rig Linux Control from the application menu.

Previous release notes:

TEST155 — Active input gain and PAD scene recall

PRESETS → Mixer scene files… now includes gain and PAD for all 16 analog
inputs, using each input's active rear/front-mic/front-line/mini path. Eight
pair records retain each member's gain and PAD independently, together with
source modes and hardware-link context. Those modes and links must match before
recall; this update does not switch source modes or alter hardware input links.

Input settings restore before mixer/routing/output settings. Pair targets and
context are checked before writes, and source/link context is checked again
throughout recall. Front mic/line gain uses integer dB hardware units; rear/mini
gain preserves fractional Q8 values. Rear PAD uses the existing active-low
writer. Matching linked-partner results skip redundant writes; unexpected
changes stop the batch. Final full-scene readback verifies the saved scope.

Scene format v8 adds these records; v1–v7 remain compatible and leave input
gain/PAD unchanged. Other input controls (phase, high-pass, phantom, impedance),
automatic source/layout/link recall, speaker A/B enable/selection/assignment and
clock recall remain outside this scene format. MIDI Learn and immersive/bass
management remain deferred.

Validation: 1,305 automated tests passed; Python compilation passed.
New tests cover all 16 inputs in front/rear demo modes, gain/PAD roundtrip,
native gain packets for rear/line/mic/mini, old-scene compatibility, stale source
context, invalid second-member gain blocking all pair writes, and incremental
full-scene GUI-controller recall. Live hardware and GUI validation are pending.

Linux installation, boxed 16 RIG icon and USB 1/2 on page 1 are retained.
Close the app, extract this release, then install/update with:
    bash install-desktop.sh
Launch AF16Rig Linux Control from the application menu. Direct launch is still
    bash run.sh

Previous release notes:

TEST154 — Managed Linux installation

Run bash install-desktop.sh to install a standalone per-user copy of the app.
It now lives under $XDG_DATA_HOME/af16rig-linux-control (normally
~/.local/share/af16rig-linux-control). The application-menu launcher points to
this installed copy. The extracted download can be moved or deleted afterward.
No sudo is needed. System Python, Tk and libusb remain runtime requirements.

Updates: close the running app, extract the new release, and run its installer.
The installer copies the release before switching the current-version symlink.
Earlier installed releases are retained. Failed copy/missing assets leave the
previous current version in place. Reinstalling from the installed copy works.
User preferences and exported scenes are not removed. Boxed 16 RIG icons and
window/launcher matching remain included. Main Analog retains USB 1/2 on page 1.

Validation: full suite 1,299 tests passed; Python compilation passed. Installer
checks cover paths with spaces, deleting the download, updating/reinstalling,
missing assets and failed copies. The installed run.sh --help was successfully
executed after deleting the download folder. Live taskbar/GUI verification and
hardware verification remain pending. This release changes Linux packaging,
not hardware controls.

Previous release notes:

TEST153 — Boxed 16 RIG application icon

Added a boxed 16 / RIG icon in the app's cyan/charcoal colours, with PNG sizes
16–256 and an SVG source. Tk uses the icon for this app and child windows.
The window class is AF16RigLinuxControl, matching the supplied Linux launcher.

To install the menu/taskbar identity for your user, extract this folder to its
permanent location, then run:
    bash install-desktop.sh
Launch AF16Rig Linux Control from the applications menu. If you pinned the old
Python/generic icon, remove that pin and pin the new launcher. No sudo needed.
If you move the folder or extract a later release elsewhere, rerun the installer
from that folder to update the launcher path. Direct launch remains bash run.sh.

The installer writes only this app's desktop file and icon files in your user
XDG data directory. It supports spaces in the application path and repeated
installation. Source code/audio controls/layout/polling are otherwise unchanged.

Validation: Python compile passed; isolated temporary-directory installation
and repeated installation passed. Icon rendered and visually inspected.
Live desktop/taskbar verification is pending. This visual update did not rerun
the unchanged hardware suite (TEST152 baseline: 1,295 passing tests).

Previous release notes:

TEST152 — Keep USB 1/2 on the first Main Mix Analog page

Main Mix → Analog now keeps all analog strips and the USB 1/2 mirror together.
Channel paging is disabled for this bank. Strip columns share the available
viewport width rather than enforcing the old 164-pixel minimum and moving USB
to another page. USB remains directly before Phones, Monitor and Main Master.
Fonts and control heights retain their existing sizes. Other banks keep their
existing paging behavior. No device mappings or polling rates were changed.

Validation: 1,295 automated tests passed; Python compile check passed.
Layout checks cover viewport widths 1280–2560, linked/unlinked strip counts,
column-width totals and keeping the mirror on page 1. Live GUI/hardware
verification is pending.

Extract into a new folder and run: bash run.sh

Previous release notes:

TEST151 — Analog output levels in scenes

PRESETS → Mixer scene files… now captures and recalls all eight analog output
levels (outputs 3–10). Four pair rows show both saved levels and both stereo-link
bits. Recall requires the saved and current output links to match; it does not
change links automatically. Link state is checked again throughout each pair
write. Unsupported/mismatched state blocks recall rather than being guessed.

Exact signed-Q8 output levels are preserved in the −60 to 0 dB range, including
fractions below the UI's 0.25 dB entry step. The existing numeric entry UI still
uses its established step. The raw scene path reuses the checked output register
write and expected-current-level protection.

If a linked write brings its partner exactly to the target, no redundant partner
write is sent. An unexpected partner change stops recall. Complete final scene
readback checks for effects on earlier settings. Earlier writes remain on failure;
there is no automatic rollback or repeated uncertain OUT.

Format v7 adds analog output records. v1–v6 scenes remain compatible and leave
output levels and output links untouched. Outputs restore after routing/names
and before speaker B trim and Monitor/Phones settings.

Still excluded: input gain/PAD, automatic source/stereo layout changes, speaker
A/B enable/selection/output assignment, clocks and hardware preset slots.
MIDI Learn and immersive/bass management remain deferred.

Validation: 1,294 automated tests passed; Python compile check passed.
New tests cover all eight native indices and fractional values, legacy v6,
link mismatch/stale context, linked partner side effects, invalid ranges/shapes,
and incremental full-scene preview and recall. Hardware and live GUI verification
remain pending; no AF16Rig was connected here.

Extract into a new folder and run: bash run.sh

Previous release notes:

TEST150 — Exact speaker B trim in scenes

PRESETS → Mixer scene files… now captures and recalls speaker B calibration
trim. The new exact-value adapter uses the established native ab_trim register
(group 1, parameter 75) and preserves signed Q8 fractional values within ±12 dB.
It checks the expected current trim and state version, performs one write, and
verifies the result. It does not simulate an absolute change with 1 dB steps.

Format v6 adds a SPEAKER B · TRIM preview row. v1–v5 scenes remain compatible;
older scenes leave B trim untouched. Trim restores after names/routing and
before Monitor/Phones settings. Final full-scene readback includes B trim.
Existing B trim step controls and normal polling remain unchanged.

A/B enable, selected speaker and assigned output pair remain outside scene
recall and are not changed by this feature. Other exclusions remain input
gain/PAD, source/stereo layout selection, clock and hardware preset slots.
MIDI Learn and immersive/bass management remain deferred.

Validation: 1,287 automated tests passed; Python compile check passed.
New tests check exact native packets across negative/positive fractional trim,
range and version rejection, stale state, no repeated uncertain OUT, legacy
v5 compatibility, incremental preview and verified full-scene recall.
No connected AF16Rig or live GUI verification was available here.

Extract into a new folder and run: bash run.sh

Previous release notes:

TEST149 — Monitor and Phones in mixer scenes

PRESETS → Mixer scene files… now includes Monitor level, Mute, Mono, Dim,
Dim depth (−10/−20 dB) and Phones level. These six controls appear in the preview
and use existing checked write APIs. Levels use signed Q8 values without a
fader-scale change. Their supported recall range is −60 to 0 dB.

Monitor/Phones settings restore after mixer, routing and names: levels first,
Dim depth, Mono, Dim, then Monitor Mute last. Each step checks current state;
a full readback verifies the complete saved scope afterward. A failed step
stops the batch without retrying uncertain writes or rolling back earlier ones.

Format v5 adds these controls. v1/v2/v3/v4 scenes remain compatible and leave
Monitor/Phones unchanged. Unsupported readbacks, including Phones minus-infinity,
block a v5 capture rather than being silently clamped or guessed.

Still outside these scenes: input gain/PAD, source/stereo layout selection,
speaker A/B configuration, clock settings and hardware preset slots.
MIDI Learn and immersive/bass management remain deferred.

Validation: 1,281 automated tests passed; Python compile check passed.
New checks cover all six native packet mappings, four legacy formats, invalid
ranges and stale state, preview/recall order and final readback side effects.
No connected AF16Rig or live GUI verification was available here.

Extract into a new folder and run: bash run.sh

Previous release notes:

TEST148 — Mixer scenes include equipment names

PRESETS → Mixer scene files… now captures all 60 analog/ADAT input and output
names alongside mixer levels, pan, switches, Aux settings and output routing.
Names have separate preview rows and are recalled last. Each name is checked
against current hardware state before writing, then read back; final full-scene
verification detects side effects. Confirmed changes refresh mixer labels.
Blank names and printable UTF-8 are supported. USB mixer sources do not have
mapped hardware name slots and are not assigned invented name parameters.

Scene format v4 adds names. v1/v2/v3 remain supported and leave names unchanged.
Capture accepts existing names up to 31 UTF-8 bytes. The existing conservative
15-byte name-write limit remains: if recall requires changing a longer name,
preview rejects the whole plan before any writes. Matching long names are OK.
Each name is captured separately, allowing other worker tasks between names.
Normal polling rates and fader scaling are unchanged.

Not a full-device preset: source/stereo selection must match before recall;
input gain/PAD, Phones, Monitor, clock and hardware preset slots remain outside
this format. MIDI Learn and immersive/bass management remain deferred.

Validation: 1,275 automated tests passed; Python compile check passed.
Added checks cover native packets for all 60 name IDs, v1/v2/v3 compatibility,
long-name preflight blocking, invalid/stale values, blank/UTF-8 names, batch
recall order, final-readback side effects and worker name-cache notifications.
No connected AF16Rig or live GUI validation was available here.

Extract into a new folder and run: bash run.sh

Previous release notes:

TEST147 — Mixer scenes include audio output routing

PRESETS → Mixer scene files… now captures and restores all 60 mapped audio
output routes alongside the existing Main/Cue mixer and Aux settings.
The preview shows destination and source names. Routes apply after mixer
settings and Aux links, with stale-state checks before each write and a
complete scene readback afterward. Capture remains incremental between worker
commands; normal polling rates are unchanged.

Scene format v3 adds routing. Existing v1/v2 scenes remain supported and leave
routing unchanged. Reserved/unmapped output slots 60–61 are never written.
Unknown source codes cause capture/validation to fail rather than guessing.
Match the mixer source/stereo layout before recall. Input gain/PAD, Phones,
Monitor, names, clock settings and hardware preset slots remain outside this
scene format. MIDI Learn and immersive/bass management remain deferred.

Validation: 1,268 automated tests passed; Python compile check passed.
New tests cover all 60 native output-route packet addresses, reserved-slot
preservation, legacy scenes, invalid codes, stale state, incremental preview/
recall and final readback detecting an unrelated route changed by a write.
No connected AF16Rig or live GUI validation was available here.

Extract into a new folder and run: bash run.sh

Previous release notes:

TEST146 — Aux/Cue controls in mixer scenes and final recall verification
PRESETS > Mixer scene files now also captures and restores:
- Aux 1–4 master levels, mutes and pre/post-fader settings (12 settings)
- Aux stereo links 1/2 and 3/4
- Cue enable
Scene file format is now af16rig-mixer-scene-v2. TEST145 v1 files still load and
restore their original fields only; newly covered controls remain untouched.
Existing channel levels/pan/mute/solo/sends and Main/Cue master levels remain.
Aux link writes run last. After the recall batch, the app captures the entire
active mixer again and compares every saved field before reporting completion.
If firmware linking or an external edit changed an earlier setting, the result
is reported as a mismatch. There is no automatic retry or rollback.
Existing guarded Aux/Cue native commands are reused, including Aux link bits
1 and 3. No new unverified vendor command has been introduced.
1262 automated tests passed; Python compile passed. Coverage includes exact
packets for all 15 fields, unrelated bit preservation, v1 compatibility,
stale-state rejection and full final-scene confirmation/mismatch handling.
Physical Rig16 recall and rendered GUI verification remain pending.
Excluded from these mixer files: input gain/PAD, source layout changes, audio
routing, Phones/Monitor, names, clocks and hardware preset-slot storage.
Full-device configuration export/import remains unfinished. MIDI Learn and
immersive/bass-management remain deferred.
Run: bash run.sh

TEST145 — Expanded Main/Cue mixer scene files
Open PRESETS > Mixer scene files…
Read active mixer settings, save a JSON scene, or open a scene to preview recall.
Included: Main/Cue channel levels, pan, mute and solo; Main Aux 1–4 send levels
and send mutes; Main/Cue master levels. Analog, ADAT and USB sources 1–64 are
supported. Stereo entries retain independent L/R values, including custom pan
and different levels; recall restores the saved values rather than an offset.
Recall requires matching source inclusion/stereo layout. A complete preflight
capture compares against the preview before any write. Each changed control
then checks current values and topology, writes only changed members, and
confirms readback. Levels/pans apply before mute/solo/send switches. A failure
stops recall; earlier changes remain. Stop/Close cancels unsent steps. No retry
of failed writes or automatic rollback. Capture/recall uses incremental worker
requests; the polling intervals are unchanged.
Excluded: source-layout changes, input gain/PAD, routing, Aux master settings,
Phones/Monitor, names, clocks and device preset storage. Full-device audio
configuration files remain unfinished. MIDI Learn and immersive functions
remain deferred. Existing level-only Fader scenes remain available separately.
1255 automated tests passed; Python compilation passed. New tests include exact
native packets for every supported channel field across sources 1–64 in both
buses, independent stereo restore, schema rejection, changed-state guards,
partial-write failure, and headless preview/preflight/recall UI flow.
Physical hardware recall and rendered GUI verification remain pending.
Run: bash run.sh

TEST144 — Supported MIDI configuration export/import
Open MIDI, wait for assignment capture, then open Ports / sync.
New Export MIDI configuration and Import MIDI configuration buttons save/restore
one JSON file containing all 71 assignments (channel/type/number), channels per
bank, preferred Standalone/Hosted mode, USB Host cable, DIN clock mode, mixer
control source, and DIN1/DIN2/Sync/USB Host output-source routing.
Import shows current/proposed settings before applying. It sends one checked
change at a time, with normal worker polling between entries. Preferred mode is
applied last. Stop/Close cancels unsent changes; an in-flight command can finish.
A failed confirmation stops the batch; earlier changes remain. No automatic
rollback or retry is performed. Hardware state changes reject stale writes.
Legacy assignment-only backups and their existing restore workflow remain.
This is a Linux-app MIDI configuration format, not an Arturia AFCC preset file.
Audio mixer/preamp/output/clock settings, names, device preset slots, live bank
index and unimplemented MIDI routing are not included. Full audio configuration
export/import remains outstanding; MIDI Learn and immersive functions deferred.
Export uses stable captured assignments and freshly read port values; it is not
an atomic snapshot. Refresh assignments before exporting recent hardware edits.
1243 automated tests passed, including one complete 80-change demo restore and
failure/stop/reconnect/schema checks. Python compilation passed. Physical device
restoration and rendered GUI layout remain unverified.
Run: bash run.sh

TEST143 — Idle-device sample-rate selection
CLOCK now has a Sample rate selector and Apply rate button for 44.1, 48,
88.2, 96, 176.4 and 192 kHz. Select Internal clock; all AF16Rig ALSA playback
and capture streams must be closed. The page explains why rate edits are disabled.
This Linux implementation uses ALSA hardware PCM configuration, not guessed
vendor writes or a detached USB driver. It sends no audio and starts no playback.
An exact rate is requested; unsupported rates fail instead of silently rounding.
The PCM is closed and the Rig16 frequency registers must confirm the rate twice.
No retry of the ALSA apply or automatic rollback occurs. No audio services stop,
and no PipeWire/JACK/DAW configuration is modified. When an audio application
reopens the interface, it can choose its own sample rate.
1233 automated tests passed; Python compile and ALSA library bindings passed.
No hardware or GUI-render verification available; actual rate switching needs
physical confirmation. Sample rate can alter available channels at high rates.
Run: bash run.sh
MIDI Learn and immersive/bass management remain deferred. Full configuration
file export/import remains outstanding.

TEST142 — Channel-strip PAD buttons
Added P beside M and S on mixer channel strips; removed GAIN / PAD top tab.
P follows the active front/rear input; cyan means PAD enabled. A stereo pair
uses one button for both inputs; P± indicates mixed PAD states. Clicking mixed
sets both on, then a second click sets both off. Readback confirms changes.
PAD editing is available on the Main analog bank; digital channels and Cue
show disabled P controls. Input gain remains in the mixer strips.
Source/selection changes reject stale edits. A failed pair write stops without
retrying or rolling back; refreshed device state shows the actual result.
1217 automated tests passed; Python compilation passed.
No attached Rig16 or rendered GUI verification was available.
Run: bash run.sh

TEST141 — Smooth channel faders and knobs
All ValueControl faders and knobs now use the same immediate drag preview as
the Phones, Monitor and Main Master faders. This includes channel levels,
Aux sends, pan/stereo pan and input gain knobs.
The handle/indicator follows the pointer while USB confirmation is pending.
The numeric readout remains device-confirmed. Intermediate drag targets are
coalesced; the latest target is sent when ready. Polling, hardware resolution,
drag sensitivity, Shift fine adjustment and readback checks are unchanged.
1211 automated tests passed; Python compilation passed.
New tests cover default preview, busy dragging, old readback, release and
invalid-state cancellation. No physical Rig16 or GUI rendering was available.
Run: bash run.sh
MIDI Learn and immersive/bass management remain deferred.

TEST140 — MIDI preferred operating mode
Added MIDI > Ports/sync > Preferred MIDI mode: Standalone / Hosted.
Reads the stored preference, validates existing state, writes once, and confirms
stable readback. Other MIDI settings and routes are preserved.
Updated MIDI page help to reflect available port routing.
1206 automated tests passed; Python compile passed.
No physical Rig16 verification or GUI rendering available in this environment.
Immersive/bass-management remains deferred.
Run: bash run.sh
See MIDI-PREFERRED-MODE.txt for protocol evidence and limitations.

TEST139 — Standalone MIDI output-source routing

MIDI > Ports / sync now includes four output-source selectors:
DIN1 and DIN2: None, DIN, USB Host, or USB Host + DIN.
Sync: None, DIN, or USB Host.
USB Host: None or DIN.
These select standalone MIDI routes, separate from the mixer-control source.

Current routes are read from the device. Apply changes only the selected
output's source flags, confirms each write, then rereads the complete settings.
A failed or partial change stops immediately; no automatic retry or rollback.
Refresh after an error to see the actual route. Unknown current encodings
are displayed but cannot be edited. Assignments and polling rates are unchanged.

1,202 automated tests passed; Python compilation passed. Actual MIDI traffic
and rendered GUI verification remain pending. Launch with bash run.sh.
MIDI learn and preferred operating mode remain unfinished. Immersive and
bass-management features remain deferred. Routes are not in assignment backups.

TEST138 — MIDI mixer-control source

MIDI > Ports / sync now includes Mixer control source:
Disabled, DIN, USB Host or USB Device. This selects the MIDI input used for
main-mixer control and does not rewrite controller assignments.

The current source is read from the device. Apply sends one checked write
and waits for matching readback. Unknown source codes are shown but disabled.
USB host cable number and DIN clock mode remain available in the same popup.

1,192 automated tests passed; Python compilation passed. Physical Rig16 and
rendered GUI verification were unavailable. Launch with bash run.sh.
DIN output / USB host / sync source routes still require verification of their
paired bitfield transfers. Immersive/bass-management remains deferred.

TEST137 — USB host cable and DIN sync settings

Open MIDI, wait for assignment capture, then choose Ports / sync…
Added two native device settings:
- USB Host Cable Number: 1–16 (a USB MIDI cable/port, not message channel).
- DIN clock mode: 4 PPQN, 24 PPQN, 48 PPQN or Korg.

Refresh reads current device values. Choose a value and Apply; the display
updates only after matching device readback. Unsupported current values are
shown as Unknown and cannot be edited. Failed confirmation requires refresh.
Normal mixer/meter polling rates are unchanged. Port settings use on-demand
reads. MIDI source routing and learn remain unfinished; immersive functions
remain deferred. These settings are not included in MIDI assignment backups.

1,187 automated tests passed; Python compilation passed. Physical device and
rendered GUI verification were not available. Launch with bash run.sh.

TEST136 — Restore MIDI message types from backups

New MIDI backups include channel, CC/Note/Off type and number for all 71
assignments. Restoring shows the exact before/after changes before applying.
Type-only changes and disabled (Off) assignments are now restored too.
Older v1 backups retain their original channel/number-only behavior and
require matching types. Bank size, bank index and MIDI routing are excluded.

The restore preview warns about duplicate active assignments using the
proposed type, channel and number. Off assignments do not cause conflicts.
Changes are sent one at a time and checked against device readback. Failure
stops the batch; already-confirmed changes remain. Stop cancels unsent entries.

Use MIDI > Save MIDI backup / Restore MIDI backup. Launch: bash run.sh.
1,176 automated tests passed; Python compilation passed. Physical device and
GUI rendering verification were not available. Immersive functions remain deferred.

TEST135 — MIDI controller bank size

The MIDI page now has a MIDI channels per bank selector, from 1 to 8.
After the assignment capture completes, choose a size and Apply bank size.
The app confirms the setting from device readback and refreshes the MIDI table,
including the current bank index. Existing assignment words are not rewritten.
This controls how many mixer channels a MIDI controller handles per bank;
it is not the MIDI message channel (1–16).

Validation: 1,169 automated tests passed, including all 64 size transitions,
stale-state, rejection, reconnect, packet, UI queue and readback checks.
Python compilation passed. Hardware and GUI rendering remain unverified here.
Launch with bash run.sh. Immersive/bass-management remains deferred.

TEST134 — MIDI message types

MIDI assignment editor now offers CC, Note and Off alongside channel and number.
Select an assignment, choose the type, then Apply. Off disables that assignment.
Only confirmed device readback updates the table. Batch templates and backups
continue preserving the existing message types.

The previous single stereo pan knob remains in place for linked pairs.
Immersive/bass-management functions remain deferred.

Validation: 1,159 automated tests passed; Python compilation passed.
No physical Rig16 or GUI rendering verification was available in this environment.
Run with: bash run.sh

TEST133 — One stereo pan knob per linked strip

Linked Main/Cue strips now have one active STEREO PAN knob. This applies to
analog, ADAT and USB stereo pairs, including the USB1/2 mirror on Analog.
Mono strips keep their existing pan control. Strip dimensions stay unchanged.
Drag, mouse wheel/arrows and numeric entry use the existing knob interaction.
The numeric range is0..254:0 left,127 centre,254 right.

This is a combined stereo-position control over the two native pans, not a
new hardware balance register and not attenuation of channel fader levels.
For knob position p:
  left pan=max(0,2*p-254)
  right pan=min(254,2*p)
Centre restores left hard-left/right hard-right. Turning left moves the right
member toward the left; turning right moves the left member toward the right.
At an extreme both members are panned to that side. This narrows the stereo
image toward the extremes. Channel gains, levels, mute and solo are untouched.

The two actual native values are read on each stereo strip refresh. Existing
independent values outside this curve display Custom L/R; they are preserved
until you adjust the knob. The first adjustment then adopts the curve above.
The displayed custom knob position is the mean of the two pan positions.

See STEREO-PAN.txt for protocol and validation notes.

TEST132 — Decoded clock status and native clock settings

CLOCK now shows Internal / ADAT / Word clock and frequency values in Hz.
Use the four selectors and Apply buttons for source, word-clock impedance,
word-clock pass-through and forced SMUX. Clock changes may interrupt audio.
The currently selected and preferred sources remain separately visible.
Preferred source is read-only. The clock validity field remains a raw bitmask;
no unsupported physical-lock claim is made. Linux ALSA configured rates remain
separate from device frequency readback.

Writes require state version18 and fresh supported settings. The worker checks
all five configuration values against the displayed snapshot before one OUT,
then retries only readback. Stale connection requests, changed settings, unknown
enums and missing/unknown external-source frequency are rejected before OUT.
No automatic rollback, repeated OUT, or writes on page opening/reconnection.
Demo state is explicitly synthetic. Native USB acceptance needs hardware review.

Sample-rate selection is not implemented in this release: the supplied XML
places it on audio-control interface0, entity40 (clock IDs29/2B/2C hex). It is
not a scalar write to the volatile frequency-code registers. The current Linux
audio application remains responsible for its configured stream sample rate.

See CLOCK-CONTROLS.txt for evidence.

TEST131 — Checked Phones level adjustment

Phones now has minus/plus buttons, a draggable fader and numeric entry.
Adjustment is limited to -60..0 dB. A current in-range readback and supported
state version18 are required. The strip follows hardware knob changes.

Each adjustment carries the current raw value and connection identity. The
worker rereads Phones before writing and refuses if it changed. It sends one
OUT and confirms with IN reads; it never repeats an uncertain OUT. Errors
remain visible in the Phones strip and detailed status line. Reconnect and
preset resets discard pending UI state; stale replies cannot restore it.
Persistent Phones preset parameter30 is untouched.

First hardware check: with Phones already between -60 and 0 dB, press its
minus button once. Confirm the device level drops by1 dB and the strip says
Level confirmed. If rejected, retain the error text and save the usual report.
No repeated mixer/button test batch is needed for this change.

See PHONES-WRITE.txt for protocol evidence.

TEST130 — Live Phones level readback

The Phones strip now displays signed dB from the device and its fader follows
hardware level changes. It remains read-only: no new USB writes are enabled.
Unknown/missing reads clear the display rather than showing a stale level.
Text updates are cached; polling rates and strip geometry are unchanged.

See PHONES-READBACK.txt for protocol evidence and remaining work.

TEST129 — Computer-saved Main/Cue fader scenes

Open MIXER -> Fader scenes (beside the Analog/ADAT/USB bank buttons).
Read current faders, then Save fader scene to keep a JSON file on the computer.
Open scene / preview reads fresh device values and lists current vs saved dB.
Recall listed levels first recaptures all faders; any change since preview stops
before writing. Changes then apply sequentially, with a fresh expected-value
check and confirmed readback per fader. Stop/Close cancels remaining steps;
an already-sent step, including both members of a stereo pair, may finish.
A failure stops the batch. Earlier confirmed changes remain, with no automatic
rollback or retry. No scene is recalled automatically on startup or reconnect.

Scope: selected Main and Cue channel faders across analog 1–16, ADAT 1–16 and
USB 1–32, plus the Main and Cue master faders. Hidden channels are excluded.
The file is a LEVEL scene, not a full device preset. It does not include routing,
preamp gain, pan, mute/solo, aux sends/masters, Phones, Monitor or channel names.
Source selection and stereo linking must match the saved layout exactly. Linked
pairs retain their L/R level offset; a different offset blocks the whole preview.
Scene capture uses matching reads per fader and matching layout at beginning/end;
it is sequential, not an atomic device snapshot. Keep faders still during capture.

Demo files are marked and cannot be applied to real hardware. JSON is bounded
to 64 KiB and validates masks, exact expected addresses, unique entries, signed
integer ranges and stereo shapes. Missing/extra/duplicate faders and ambiguous
mono/stereo membership are rejected. No firmware, address, type enum or guessed
write command is introduced: recall uses the existing guarded console setters.
The worker handles capture one entry at a time, with normal polling between
requests. No polling interval or mixer font/control sizing is changed.

Run: bash run.sh
Validation: 1102 automated tests passed; Python compilation passed. New tests
cover all 64 source indices on both buses, analog/digital writes, two-member
stereo offsets, master writes, file roundtrip/validation, read errors, ignored
writes/no retry, disconnect, stale values/layout, fresh preflight before recall,
preview with zero writes, cancellation and worker event integration. The optional
demo GUI runner now has 54 stages, adding capture/save/preview/recall/reread.
Rendered UI and physical hardware behavior of the new scene workflow remain
unverified here. Native packet checks use a mock transport; no AF16Rig attached.

Previous release notes:

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

TEST127 — Full eight-strip MIDI assignment template

MIDI now offers All controls (64) in the batch selector. Choose a MIDI channel
(1–16) and starting number (0–64), then Preview assignments. The template uses
eight consecutive numbers each for Fader, Pan, Mute, Solo, Aux 1, Aux 2, Aux 3
and Aux 4, in that order. For example, starting at 0 maps faders 0–7, pans 8–15,
mute 16–23, solo 24–31 and aux sends 32–63. Master and bank assignments remain
unchanged. Existing per-control eight-strip batches remain available.

Preview performs no device writes. The preview warns when proposed mappings
duplicate another supported stored channel/type/number assignment, including
master and bank-switch controls. Message-type meanings remain unverified;
this comparison does not claim all semantic MIDI conflicts are identifiable.
Stored type bits are kept unchanged; this does not activate an Off assignment.
Unsupported encodings block the entire template. Unchanged assignments are
omitted. Save MIDI backup before applying if you want to restore old mappings.

Apply uses the existing sequential guarded writer: fresh matching preflight,
one OUT per changed assignment, confirmation readback, and stop on first
failure. Stop/Close prevents remaining submissions; it cannot undo an already
sent write. Connection changes invalidate the preview. Normal polling stays
at its existing rate. No hardware change occurs automatically on startup.

Run: bash run.sh, open MIDI, wait for capture, choose All controls (64).
Validation: 1051 automated tests passed and Python compilation passed. New
checks cover all 64 mappings, numeric boundaries, retained type bits, unchanged
master/bank values, demo apply/reread/no-op, unsupported states, stale connection,
no-write preview and collision detection. The optional demo GUI runner now has
48 stages, including full-template preview, apply and reread; these new rendered
stages have not been run here (no display). No AF16Rig is attached here.
The user confirmed TEST126's preset-name boundary fix works on their device.

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

Previous release notes:

TEST125 — Targeted preset rename diagnostics (not a confirmed suffix fix)

The user reports TEST124 still appends the preset suffix. Its whole-word-copy
simulation did not establish the actual device behavior. The original AFCC
string writer was rechecked at 0x1407c6ef0: it appends NUL through 0x1404156a0,
uses request 0x18+group, index zero and the stored string length. The known
request/address mapping remains supported, but the suffix cause is unresolved.
No further speculative write command is introduced in this release.

Each preset rename now retains the requested/expected names, exact payload,
USB completion result, raw 32-byte name storage read twice before and after
the write, and subsequent decoded confirmation reads. Error text identifies
the requested and received names. Read-only diagnostic capture preserves bytes
after NUL so suffix/padding behavior is visible. There is still only one OUT
per rename; no clearing operation, automatic retry or content save/load occurs.

PRESETS now includes Save rename report. Attempt the affected rename once,
then save AF16Rig-preset-rename-report.json and send it back. If the name later
changes when using Read presets, do that before saving the report so its current
records show the later result. The report remains available after a failed
rename and while navigating away/back in the same app session.

Run: bash run.sh
Validation: 1039 automated tests passed; Python compilation passed. New tests
verify preserved tail bytes, failure diagnostics, one-write behavior and report
export. Actual preset suffix repair is NOT claimed; hardware evidence is needed.

Previous release notes:

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

Previous release notes:

TEST123 — Use spare mixer space

Visible channel, Phones, Monitor and Main Master strips now share the spare
horizontal space evenly, with at most a one-pixel width difference. Their
bottom edges extend to the available mixer height, making fader tracks longer
instead of leaving an empty band above the footer. Fonts, knob heights, button
sizes and the three output headers retain their existing sizes. No global Tk
scaling, tab wrapping or scrollbars are introduced. Repeated readback with the
same layout does not reconfigure the canvas. Existing minimum strip width and
height are retained; channel paging still handles narrower windows.

Run: bash run.sh
Phones volume remains read-only; its live meters and raw knob readback remain.
Validation: 1031 automated tests passed; compilation passed. Tests verify full
width/height use, equal strip widths, unchanged dial/header sizing and no
layout mutation for an unchanged viewport. Actual desktop appearance has not
been rendered in this environment.

Previous release notes:

TEST122 — Phones / Monitor / Main Master output strips

The mixer now places output strips after its visible channel bank in this
order: PHONES, MONITOR, MAIN MASTER. The old top-right monitor control group
is removed. Monitor includes the existing minus/plus, Mute, Dim and Mono
controls, plus an absolute fader using the established speaker-level register
and the existing send-once/readback-confirmed writer. Its range is -60 to 0 dB.
Monitor and Phones use the native speakers and phones stereo meter taps.

IMPORTANT: Phones is a read-only strip in this release. Its hardware knob is
read automatically, shown explicitly as a raw value, and its level fader is
disabled. The headphone dB calibration and software setter are not verified;
no dB value or writable headphone control is invented. Thus the visual layout
is implemented, but the editable Phones level from the mockup is unfinished.

Navigation and mixer scrollbars are removed. Tabs keep their native-size row;
keyboard focus or wheel over the navigation row can reveal tabs on a narrow
screen. Mixer controls use fixed 164-pixel strips and 850-pixel height, with
52-pixel knobs. All three output faders start below equal 400-pixel headers.
When all source strips do not fit, Channels arrows page through them while
keeping the three output strips present. Window width changes page capacity,
not control sizes. Larger windows can still have a small fixed-layout margin.
A tall enough window is needed to display the full fixed-height mixer.

Run: bash run.sh
Optional automated demo GUI run: bash test-gui.sh
The demo check has 45 stages, including monitor target/readback/restore and
checking that Phones stays read-only while its stereo meter receives data.

Validation: 1028 automated tests passed; Python compilation passed. Added
monitor boundary/invalid-value/firmware guards, native writer/no-op checks,
UI pending guard, worker integration, Phones read-only behavior, and output
order across channel pages. Existing physical button sweeps are not requested.
This environment cannot render Tk or access the rig; final appearance and the
new monitor fader on physical hardware remain unverified.

Previous release notes:

TEST121 — Fixed layout and restored single-row navigation

Replaces the wrapping tab bar with a single native-size row. Buttons are now
created inside their actual content frame; resizing never reparents or repacks
them. A horizontal scrollbar keeps all 12 tabs accessible on narrow displays.
Keyboard focus scrolls the selected tab into view.

Mixer strips no longer stretch or shrink to fit the window. Channel and master
strips use 180 logical pixels (or the master label minimum at desktop DPI),
with a 900-pixel strip height and 52-pixel dial height. Resizing changes only
the viewport. Horizontal and vertical scrollbars remain present, so small
windows can reach every control without automatic resizing or scaling.
Large windows can have unused space; it is no longer absorbed by stretching
controls. Stereo linking still intentionally combines paired strips, without
changing the size of the remaining strips. Native desktop DPI is respected.

Run: bash run.sh
Optional demo GUI check: bash test-gui.sh
The 42-stage GUI runner now checks fixed dimensions, one-row navigation and
scroll access to the master strip, instead of expecting everything to squeeze
inside the viewport. Existing polling and flicker fixes remain in place.

Validation: 1019 automated tests passed; Python compilation passed.
Tests now verify fixed dimensions across window sizes and source counts,
no layout mutation on viewport resize, and stable tab placement/focus scrolling.
The rendered desktop result has not been verified in this environment.

Previous release notes:

TEST120 — Prevent meter starvation and alternating footer messages

TEST119 avoided redundant paint calls but did not stop real state changes
caused by delayed meter reads. Previously meters were serviced only after the
command queue was empty and other polls were not due. TEST118's faster mixer
request scheduling could keep that queue busy. A due meter frame is now read
between queued operations, and between individual analog preamp reads.
All USB access remains on the one worker thread. Meter period remains 50 ms;
no extra read is sent before it is due. A queued operation can be delayed by
one due meter transfer. Long individual device transactions can still cause
gaps; failures and stale-data warnings are not suppressed.

Normal channel and master snapshot replies now use the same console footer:
"Live mixer readback". They no longer alternate two different strings on
every reply. Errors and operation confirmations retain their original text.
The status beneath ANALOG still indicates real live/stale transitions.
The white meter line remains the peak-hold marker; it should move as levels
change, but should no longer repeatedly vanish due to command-queue starvation.

Run: bash run.sh
Validation: 1015 automated tests passed; compilation passed. Includes a busy
worker regression that maintains a nonempty queue of slow snapshot commands
and verifies meter frames arrive between them, plus interval, error,
disconnect and shared-footer checks.
Physical USB timing and the final visual result need desktop confirmation.
No repeat physical button test is requested.

Previous release notes:

TEST119 — Reduce meter and label flashing

L/R captions are static canvas items: live level updates no longer repaint
those labels. Meter coordinates are rounded to screen pixels and changed only
when the displayed pixel changes. Colours and peak visibility update only on
transitions. The live/stale status below ANALOG and unchanged strip titles no
longer receive repeated text updates.
Compact Aux meters now use their actual 16-pixel width and reserve no empty
caption footer, leaving usable bar travel at 40 pixels high.
Initial empty meters hide their peak marker correctly. Stale data still clears
bars and hides peaks; captions remain labels rather than changing to dashes.
Real live/stale status transitions are still shown.

No USB polling or meter animation intervals changed in this release.
Run: bash run.sh
Validation: 1009 automated tests passed; Python compilation passed.
Visual flicker on the user's desktop remains to be confirmed. No physical
hardware behavior is claimed as tested here.

Previous release notes:

TEST118 — Faster startup reads and steadier initial mixer layout

Name scanning now reads up to eight words per idle turn with an 8 ms budget
checked after each word. It yields before the next word when a user command,
monitor poll, input poll or meter read is due. A single USB transfer can take
longer than the budget; transfers remain sequential. Two-pass name validation
is preserved. No new device write commands are introduced.

UI event delivery interval: 80 ms -> 20 ms.
Mixer request scheduling interval: 100 ms -> 40 ms.
Master, meter, monitor and input polling intervals are unchanged, as is the
one-second pause between full channel sweeps. Faster UI response removes
avoidable waits between serialized channel reads.

Initial stereo layout changes are collected until the first mixer pass ends,
then applied together. Values still populate progressively; subsequent live
link changes remain responsive. Bank changes and reconnects restart this
initial-layout grouping. A single layout change can still occur after load.

Run normally: bash run.sh
Optional automated demo GUI check: bash test-gui.sh
No repeated physical button sweep is required. Startup latency and visual
behavior on the physical rig are not verified in this environment.

Validation: 1004 automated tests passed; compilation passed. Tests cover
bounded name slices, yielding to commands and due live polls, two-pass name
sync/reconnect, and one initial stereo-layout update per completed pass.
The supplied TEST117 GUI report passed all 42 stages with zero callback errors.
TEST118 has not yet been rendered in a desktop session here.

Previous release notes:

TEST117 — GUI report fixes and eight-strip MIDI assignment

Fixed FRONT 3–4 and OUTPUTS failing to finish opening: their single Refresh
button list was incorrectly constructed and raised a tuple-unpacking error.
Fixed master-strip clipping when switching to a new USB bank with the same
strip count. The layout now recalculates newly visible frames even when the
viewport and count are unchanged; unchanged banks retain the redraw cache.

MIDI: a new "Assign one control across strips 1–8" section lets you select
Fader, Pan, Mute, Solo or Aux 1–4; choose channel 1–16 and a first number 0–120.
Preview shows only changed assignments. Apply uses the existing single-flight
readback-checked batch engine. Each strip keeps its stored message type.
It does not change bank settings or MIDI routing. It does not detect conflicts
with other assigned controls. Stop cancels remaining entries; confirmed changes
remain. No device writes occur merely by preparing the preview.

Run normally: bash run.sh
Automatic demo UI check: bash test-gui.sh
The GUI runner now checks 42 stages, including the eight-strip preview, apply
and fresh reread. No rig or manual clicking is required; it saves
AF16Rig-GUI-check.json beside the script.

Validation: 997 automated tests passed; Python compilation passed.
The user's TEST116 desktop report completed all 39 stages: 33 passed, six
failed and two callback errors were recorded. This release addresses their
identified causes with regressions. A new desktop GUI run is still required
to confirm the rendered result. Physical hardware was not available here.

Previous release notes:

TEST116 — Automatic demo GUI checks and wrapping navigation

Top navigation wraps onto additional rows when the window is narrow, so newer
pages remain accessible. Unchanged layouts are not repacked on refresh.

Run: bash test-gui.sh
This opens the app in isolated demo mode and automatically checks navigation,
main/cue mixer banks at two window sizes, routing filters, presets, names,
clock, meter hold/export/resume, MIDI backup/edit/restore, and reconnect.
No physical USB device is opened. Window preferences and cable colours are
not saved. Temporary backups are removed. Results are saved beside the script
as AF16Rig-GUI-check.json. Allow up to three minutes; do not interact with the
check window while it runs. Closing it records an interrupted run.

Normal app launch remains: bash run.sh

Validation: 984 automated tests passed; Python compilation passed.
The real Tk GUI run was blocked here because no display session is available.
Visual results and physical hardware behavior are not claimed as verified.
The demo checks do not replace firmware/audio validation.

Previous release notes:

TEST115 — Batch MIDI channel/number backup and restore

MIDI adds Save MIDI backup and Restore MIDI backup. Read all assignments
first. Backups retain all 71 strip/master/bank-switch assignment words.
Restore previews only the changed channels and numbers, then applies them
one at a time through the existing guarded MIDI remap command. No writes
occur until Restore listed assignments is clicked in the preview.

The entire file and plan are checked before the first write. Message types
must match current readback; this does not restore Off/CC/Note selections.
Bank size/index, MIDI port routing and audio controls are excluded. Unknown
unchanged words can be preserved in a backup, but unsupported changed words
block restoration. Demo backups cannot be applied to a physical device.
The earlier Save assignments report remains a separate diagnostic format;
use Save MIDI backup to create a restorable file.

Each assignment is checked against fresh device reads immediately before
writing and updated in the page only after confirmation. Any failed write,
external change or disconnect stops the batch. Earlier confirmed changes
remain. Stop after current assignment or Close cancels the remaining entries;
an already-sent assignment may finish. Closing the preview refreshes device
readback. A stopped or failed batch is never automatically resumed or rolled
back. Normal polling intervals are unchanged; batches yield between entries.

Validation: 975 automated tests pass; all Python modules compile. New checks
cover complete 71-entry backup/restore, strict bounded file loading, malformed
and duplicate entries/keys, demo isolation, type mismatches, unsupported
encodings, partial failures, stopping, reconnects, late replies and preview
without writes. GUI rendering and physical restore remain unverified. This
uses the TEST114 remap command; no additional device write protocol is added.

TEST114 — Edit existing MIDI assignment channel and number

MIDI now lets you select a captured strip/master/bank-switch assignment,
choose MIDI channel 1–16 and CC/Note number 0–127, then Apply assignment.
The stored message type is preserved exactly. This does not switch Off/CC/
Note type or implement MIDI learn. Bank size/index remain read-only.

Only stable supported assignment words are editable. Reserved bits, type
code 3, out-of-range stored numbers and unsupported state versions block
writes. Before writing, two fresh reads must still match the captured word.
External changes and connection changes reject the edit. Unchanged targets
send no OUT. Exactly one native OUT is sent for a changed target, followed
by bounded readback checks. Uncertain writes are never automatically resent.
Confirmed readback updates the row; failed confirmation disables that entry
until Refresh. Other device controls and normal polling are unchanged.

Refresh and report export are blocked during an edit; closing/reconnecting
invalidates its UI request. No pending edit is replayed after reconnect.
The report continues to preserve raw type/channel/number codes, while the
page now shows user-facing channel numbers 1–16. Unsupported rows explain
why they cannot be edited. Demo edits remain local and are labeled demo.

Validation: 952 automated tests pass; all Python modules compile. Mock USB
checks cover all 71 assignment addresses, preserved type bits, no-op writes,
stale/unstable preflight, unsupported encodings, readback failures, uncertain
OUT completion, disconnection and UI generation changes. GUI rendering and
physical remapping remain unverified. A single already-configured controller
assignment is enough for the first hardware check; no full button retest is
needed for this update. Extract this folder and run bash run.sh.

TEST113 — Native MIDI controller assignment reader

New MIDI tab reads the device's saved mixer-controller assignments: eight
strips with fader, pan, mute, solo and four Aux controls; master fader and
four master Aux controls; next/previous bank; channels-per-bank and bank
index. Total: 73 entries. Opening the page starts a capture; Refresh reads
subsequent changes. Normal polling intervals are unchanged.

Each entry is read twice and marked Matching reads or Changed. The page
shows decoded channel/type/number codes and the raw word. Message-type names
and disabled/unassigned encodings remain unverified and are not guessed.
This page is read-only: MIDI editing, learning and port routing are not yet
implemented. No new device writes are enabled.

Save assignments report exports one JSON capture, including partial results,
errors, connection generation, raw words and both reads. Demo values are
explicitly labeled. Close/reconnect/refresh invalidates previous requests.
Reports are diagnostic captures, not files that can be restored to the rig.

Validation: 934 automated tests pass; all Python modules compile. Checks
cover every new register/index, read-only transfers, decode bit preservation,
short replies, changing data, stale connections, the full incremental page
capture, close/reconnect, canceled exports and disk failures. GUI rendering
and physical MIDI readback remain unverified here. See MIDI-PROTOCOL.txt for
recovered addresses, bit-field evidence and remaining limitations.

TEST112 — Meter hold and complete snapshot export

METERS now has Hold / Resume and Save snapshot. Hold captures all 118 taps,
peaks and equipment labels together, including banks not currently visible.
Live USB polling and background peak collection continue unchanged. Resume
returns to current readings. Disconnects, preset resets and meter errors clear
Hold. Peak resets apply to both the held view and the live session.

Save snapshot writes every bank to JSON, captured before the file dialog opens.
Includes linear amplitude, dBFS, peak values, full-scale observations, labels,
connection generation, freshness and demo/held flags. Silence has amplitude 0
and null dBFS; unavailable samples have null amplitude. Stale readings are
explicitly historical. For held exports, freshness/frame age describe the held
capture, not the time of export. These are meter-frame peaks, not true peaks.
No additional device requests or writes are introduced.

917 automated tests pass; Python compilation passes. GUI rendering and physical
hardware verification remain pending. Stereo-pan research reconfirms indexed
Main/Cue fields 37/51 but does not yet establish linked-pair semantics, so
stereo-pan writing remains disabled. No hardware testing requested for this
research checkpoint.

AF16Rig Linux Control — TEST111

Run
    bash run.sh
Offline preview
    bash run.sh --demo

The Python application runs directly; no compiler is needed.
Requires Python 3, tkinter and libusb, as in the previous release.
Existing USB permissions continue to apply. If permissions have not been set:
    bash setup-usb-access.sh

TEST111 — Precise analog output levels

OUTPUTS now includes Set level beside the existing +/-1 dB buttons. Select
output 3–10, then enter a level from -60 to 0 dB. Values are quantized to
0.25 dB steps using the existing signed 8.8 output-gain field.

The worker checks the connection generation and rereads the selected output
before writing. If its value differs from the value shown when the dialog
opened, the target is rejected rather than overwriting that change. Invalid,
nonfinite, unchanged and canceled entries do not send writes. The native
write uses the existing output_gain request/index and checked readback;
an unconfirmed OUT is never automatically repeated. Demo mode stays offline.

Validation: 908 automated tests passed; all Python modules compile. Added
checks cover all eight output indices, fractional scaling, unchanged values,
invalid/range inputs, connection races, stale readback and failed readback
without repeated writes. GUI and physical target-entry verification remain
pending; the underlying output gain command was already in use.

TEST110 — Fresh page state after reconnection

The Names page now clears old rows, selected text and rename request state
when the device disconnects/reconnects or the application invalidates state
after a preset load. An open name restore is stopped and closed; it is not
resumed automatically. Old replies cannot reenable the previous editor.
Automatic name scanning repopulates the current device's names, and rows
absent from the current cache are removed rather than retained indefinitely.

An open routing page now discards its previous capture, cable gesture,
pending batch and Undo/Redo history on reconnection, then requests a fresh
read automatically. An open clock page clears the old values/export state
and requests a fresh read. Application diagnostic snapshots from the prior
connection are also cleared before new readbacks arrive.

This adds read requests only on state reset. No pending writes are replayed,
no connection-loss restore is retried, and normal polling is unchanged.
Validation: 895 automated tests passed; all Python modules compile. Tests
cover row/editor clearing, stopped restores, ignored late rename replies,
routing reload and clock export invalidation. GUI and physical reconnection
verification remain pending.

TEST109 — Rename inputs directly from mixer titles

Double-click or right-click an analog/ADAT strip title to rename its hardware
equipment name. A linked strip offers separate left/right menu choices;
selecting one changes only that input's name. USB inputs have no verified
hardware-name slots and do not offer rename. Existing Names page remains
available for all supported input and output names and backups.

The shortcut uses the existing name_set worker command with the confirmed
current name, source and connection generation. Device preflight and readback
checks remain unchanged. Labels update through the shared name cache only
after a confirmed reply. Cancel/unchanged names cause no writes; the existing
15-byte UTF-8 limit is enforced. A changed connection, unsupported state
version, missing initial name read or another pending quick rename prevents
submission. Error replies are shown in the footer and retained in Log.

Validation: 888 automated tests passed; all Python modules compile. Tests
cover specific left/right menu actions, mono and USB titles, stale connection,
UTF-8 bounds, unchanged/canceled values and request-specific completion.
Rendered GUI and new shortcut behavior on physical hardware are unverified.
Clock editing remains pending verified enum mapping and a hardware capture.

TEST108 — Retained session error and connection log

Click Log in the bottom bar to open a separate event-history window without
leaving the mixer. It retains errors, readback failures, reconnect/disconnect
events and discarded-command notices independently of the high-rate meter
trace. Live meter frames and successful polling cannot evict these entries.
The log retains up to 300 distinct entries; repeated identical events in the
same connection/context are counted with first and last timestamps.

Select an entry to read its full message and context, then Copy selected or
Save log to JSON. Clear log affects only this session's log. The normal
application diagnostic report also includes these retained events. The log
is not automatically persisted between launches; save it before closing the
app when needed. Demo exports are explicitly labeled.

No device commands, audio settings or polling intervals were changed.
Validation: 875 automated tests passed; all Python modules compile. Checks
include meter flooding, repeat grouping, connection separation, bounded
retention, full-text copying, export cancellation/failure and window closure.
GUI rendering remains unverified in this environment.

TEST107 — Precise numeric mixer entry

Double-click an enabled mixer fader or knob to enter a numeric value. Enter
also opens the dialog when the control has keyboard focus. This covers
channel/master levels, Aux sends/master levels, input gain, and editable
mono pan. Levels use dB; pan uses -100 left, 0 centre, +100 right.

The dialog shows the permitted range. Values are quantized to the control's
existing step size and sent once through its existing guarded target handler.
No optimistic device state is substituted for readback. Cancel, unchanged
values, nonfinite numbers and out-of-range values cause no writes. Opening
the dialog cancels any queued drag target. A disconnect, navigation, destroyed
control, busy control or changed range while the dialog is open prevents
submission. A rejected callback is not retried automatically.

Validation: 858 automated tests passed; all Python modules compile. Added
checks for conversion/quantization, single-write dispatch, canceled dialogs,
stale connection context, invalid values and pending-drag cancellation.
Rendered dialogs and physical hardware behavior remain unverified here.

TEST106 — Patch-bay search and history shortcuts

ROUTING now has Find source and Find output fields. Search matches equipment
names and native port labels, case-insensitively, within the selected bank.
Multiple words must all match; matching is literal, not regular expressions.
Choose All in the relevant bank selector to search every bank. Connected
sources are restricted to the currently matching destinations.

Clear search (or Escape in a search field) restores the unfiltered view while
preserving bank choices. No-match results are explicitly labeled. Changing
search cancels an in-progress cable gesture and clears its selection; it
never sends routing commands, deletes cables or clears Undo/Redo history.
Hardware-name updates refresh search results when no cable drag is active.

With patch-bay canvas focus, Ctrl+Z uses the established guarded Undo handler;
Ctrl+Y or Ctrl+Shift+Z uses Redo. History shortcuts are ignored while carrying
or dragging a source cable. Text entries retain their keyboard behavior.

Validation: 843 automated tests passed; all Python modules compile. Added
coverage for named/native port search, bank restrictions, empty results,
Unicode/literal matching, route preservation and history dispatch. GUI
rendering and physical verification are pending. Prior USB alignment fix
and all previous features are included.

TEST105 — Align mirrored USB and analog strips

Digital strips now reserve the analog input-gain section's height when shown
beside analog strips. This aligns Link/Unlink, pan, mute/solo and fader rows.
The spacer uses actual heading/label font metrics and the current gain-dial
height, including compact/tall window layouts. Digital controls use the same
container padding as analog controls. No dummy gain control is shown.

The spacer is removed on digital-only banks and restored when returning to
the mixed analog/USB view. Repeated refreshes do not repack the spacer.
No audio commands, routing, link state or polling intervals were changed.

Validation: 831 automated tests passed; all Python modules compile. Includes
mixed/digital bank transitions, resized dials and scaled label metrics.
Rendered GUI and hardware verification remain pending.

TEST104 — Master width and USB 1/2 mirror

The master strip now keeps a minimum width of 170 pixels, increased to fit
its title and cue button at larger font sizes. Channel strips share the
remaining viewport width. ADAT and USB banks no longer squeeze the master
to the same narrow width as every channel. The bank still fills the window
exactly, with no blank gap beside the master and no new scrollbar.

Main Mix / ANALOG now includes USB 1/2 immediately before the master.
This is the same source 33/34 controller used on the USB bank, including live
fader, Aux, mute, solo and meter state. It is one stereo strip when USB 1/2
is linked on the device, or two mono strips when unlinked. No link state or
routing is changed automatically. Cue Mix and the digital banks retain their
existing source lists. The read cycle now includes the mirrored pair.

Validation: 826 automated tests passed; all Python modules compile. Checks
cover stereo/mono mirror layout, shared USB controller identity, live read
sequencing, error progression, and exact window fill across screen widths
and scaled master minimums. No physical or rendered GUI verification here.

TEST103 — Complete meter bridge

Open METERS in the top navigation bar. Four banks expose all 118 decoded
meter-frame values: Inputs (16 analog + 16 ADAT), USB (32), Outputs (8 line,
speakers L/R, phones L/R, 16 ADAT and loopback L/R), and Buses (main/cue L/R,
4 Aux and 16 immersive taps). Availability of a signal depends on the rig's
current configuration. Existing native meter-frame offsets are unchanged.

The page uses the existing 20 Hz read-only meter stream: no new USB commands,
no extra polling, and no audio setting changes. Meter canvases update in
place; only switching banks rebuilds their layout. All banks accumulate
peak readings while the METERS page remains open, including hidden banks.
Click a peak to reset that channel, or use Reset all peaks. A peak at or above
0 dBFS stays red until reset. These are observed meter-frame maxima, not
sample-accurate or inter-sample true-peak measurements or hardware clip flags.

Hardware names are used for analog/ADAT inputs and ADAT outputs. Analog output
names are not assigned to physical ports until their slot order is verified.
Stale data blanks the live bars and is explicitly marked; historical peak
values remain. Disconnect, reconnection, preset load or meter-read failure
clears the meter session. Closing the page clears its peak history and cancels
its draw callback. Existing mixer meters and control polling are unchanged.

Validation: 819 automated tests; all Python modules compile. Includes complete
frame coverage, bank layouts, peak/reset/stale/connection handling, and a
headless page construction/navigation/close check. No GUI rendering (no X
display available) or physical meter verification performed here.

TEST102 — Automatic USB reconnect and digital-bank refresh

Auto reconnect is enabled by default, with a session-only checkbox in the
header. After a failed connection or a lost device, retry delays are 1, 2,
5, 10 and then 30 seconds. Manual Reconnect remains available. Turning auto
reconnect off cancels retries; an explicit disconnect also stops them.
A connection is announced only after the initial device snapshot succeeds.
Names and live state are read again after reconnecting.

Pending writes are discarded across connection loss/reconnect. Interrupted
changes are never replayed. Ordinary rejected controls do not trigger a
reconnect. Existing connected polling intervals are unchanged.

Returning to the mixer now resumes polling the selected digital bank rather
than mistakenly starting at Analog channel 1.

Validation: 798 automated tests passed, including simulated disconnection,
failed initial reads, queued-write discard, retry cancellation and digital
bank navigation. All Python modules compile. GUI rendering and physical USB
reconnect have not been verified in this environment.

TEST101 — Multi-step routing Undo / Redo

The routing patch bay now has Undo and Redo buttons with available-step counts.
It keeps the last 50 fully confirmed operations while the patch-bay page is
open. A mono cable patch is one step; a stereo L/R patch is one step; a full
routing-preset import is one step. Both sides of a stereo operation remain
part of the preflight check even when one side was already unchanged.

Undo/Redo uses the established routing preflight and per-destination checked
writer. The expected current sources are checked against the actual device
before writes begin, and every destination is confirmed. History moves to
the opposite stack only after the complete operation succeeds. New confirmed
edits clear Redo; no-op recolouring does not create a history entry.

A failed/uncertain write or routing error clears both stacks and requires a
fresh routing read. Partial changes remain as reported; no rollback or retry
of an uncertain OUT is attempted. Unrelated control errors and stale request
replies do not alter routing history. Disconnect, changed connection generation
and leaving the routing page clear history. History is not saved across app
sessions. Cable colours remain local preferences; colour-only edits are not
part of hardware routing Undo/Redo.

Validation: 781 automated tests passed; all Python modules compiled.
New coverage includes multi-step mono Undo/Redo, stereo and imported-preset
grouping, stack movement after full confirmation, history limits, new-edit
Redo invalidation, exact expected-source reversal, unchanged stereo partners,
no-op colour changes, preflight rejection without writes, partial failure,
old/unrelated replies, duplicate-click blocking and disconnect clearing.
Physical Undo/Redo workflow and rendered GUI remain unverified. The feature
reuses the existing routing protocol; no new device parameter is introduced.

Short optional check: make two cable changes, Undo twice, then Redo twice.
Normal routing changes affect audio destinations. No full mixer-button batch
is needed. Save a routing preset first if you want a persistent restore file.

Previous release notes

TEST100 — Equipment-name backup and batch restore

MIXER > Names… now offers Save names backup… and Restore names….
For a complete backup, wait until Names 60/60 is shown. A backup can also
contain a smaller set of successfully read names; its count is displayed.
The backup stores actual names reconstructed from two matching device reads,
not merely the display candidate. The existing diagnostic report remains
separate and is not accepted as a restore file.

Restore validates the device/schema, channel IDs, native parameter mapping,
unique entries, UTF-8 text and file size. It reads the current name cache to
prepare a complete Current/Saved preview, skipping unchanged names. No write
runs until Restore these names is clicked. Only the names listed in the
backup can be changed. A demo backup cannot be restored to hardware.

Each name uses the existing guarded rename worker: current name and connection
are checked, one string OUT is sent, and readback confirms the new value.
The next name is queued only after confirmation, with a 120 ms yield between
names so normal polling can run. First error stops the batch without rollback.
Stop after current name waits for the outstanding result. Closing stops
future names; an already-sent write may still finish. Results report only
confirmed names, and ambiguous/disconnected writes are not counted as success.
The normal Names editor stays locked until the preview dialog is closed.

Backups preserve stable names up to 31 UTF-8 bytes (the bounded read format).
The existing conservative 15-byte rename limit still applies to changed
restore targets. An unchanged longer name is skipped; a changed longer name
blocks the preview with a clear error. Names are never truncated.

This format contains no mixer levels, routing, preamp, clock or device-preset
changes. It is a name backup, not a native AFCC preset-file import/export.

Validation: 760 automated tests passed; all Python modules compiled. New
coverage includes 60-name roundtrip/restore packets, blank and Unicode names,
long-name behavior, bad/duplicate/mismatched IDs, invalid JSON/oversized
files, demo isolation, no-op skipping, missing current reads, single-flight
batch writes, cancellation, stale replies and connections, partial failure,
confirmed counts and editor locking. Rendered GUI and physical batch restore
remain unverified. No full hardware button sweep is requested.

Previous release notes

TEST99 — Output equipment names and named patch-bay jacks

Automatic name sync and MIXER > Names… now cover 60 native name slots:
16 analog inputs, 16 ADAT inputs, 12 analog output name slots, and 16 ADAT
outputs. Select a row to rename it using the existing guarded write/readback
workflow. Refresh and report export cover the complete set. Startup remains
read-only, incremental and lower priority than control/meter polling.

The routing patch bay now displays equipment names beside analog/ADAT input
jacks and ADAT output jacks. Native port numbers remain visible, so duplicate
custom names cannot hide a connection's identity. Name arrival/rename updates
only text items; cables are not redrawn and a drag in progress is preserved.
Routing addresses, files and write semantics are unchanged.

Analog output names are shown as ANALOG OUT SLOT 1–12 in Names…. Their mapping
to speakers, line outputs and headphones is not independently verified, so
physical analog patch-bay labels remain unchanged. ADAT output names map by
ADAT channel number. USB returns still use their numbered labels.

Input name IDs retain their original identities1–32; output cache IDs65–92
are separate from digital mixer input IDs33–64. Native group2 parameters are
0–15 analog inputs,16–27 analog output slots,28–43 ADAT inputs,44–59 ADAT
outputs. Immersive names and unmapped parameters remain excluded.

Validation: 737 automated tests passed; all Python modules compiled.
Added coverage includes all 28 output rename packets, input-name isolation,
60-slot scan completion, generic/blank fallbacks, stale writes, failed and
disconnected writes, demo output names, manual scan transitions, patch-bay
identity labels and in-place updates without cable or drag changes.
Physical output-name read/write confirmation and rendered GUI are pending.

Optional short check: inspect output names in Names…. If using ADAT, rename
one output and confirm its patch-bay label updates. No routing or audio setup
changes and no repeat mixer-button batch are needed.

Clock source/rate editing remains pending the TEST98 clock capture/decoding.
Other major gaps remain stereo pan/balance, MIDI configuration, native
preset-file transfer and immersive/bass-management controls.

Previous release notes

TEST98 — Read-only Clock / audio status

Open the new CLOCK tab. It displays the AF16Rig's Linux ALSA playback and
capture stream configuration: configured rate, channel count, format and
stream state. Closed streams have no claimed rate. Multiple AF16Rig audio
cards are listed separately; MIDI and unrelated sound cards are excluded.
These values describe the Linux streams, not proof of the physical clock's
source, frequency or lock. No sample-rate or clock changes are implemented.

The device diagnostics table reads the clock validity, frequency, selected
and preferred source, word-clock impedance/thru and double-SMUX registers.
Values are explicitly raw codes: their enums/units are not verified. Two
passes are compared, and a changing capture is marked unstable. Nothing in
this feature sends a USB OUT or opens an audio stream.

Status updates once per second while the page is open. Failed native reads
pause after the first error until Refresh / retry or reconnect; ALSA status
continues updating. Existing monitor/meter polling intervals are unchanged.
Unchanged table rows are retained. Disconnect clears old values.

Save clock report exports raw register passes, ALSA configuration, errors,
connection generation and capture time to JSON. This is the evidence needed
to finish native clock decoding without guessed labels or blind writes.

Validation: 723 automated tests passed; all Python modules compiled.
Coverage includes exact read requests and no OUT, two-pass instability,
short reads and retry suppression, disconnects, unknown state versions,
card identity filtering, playback/capture rate parsing, closed/missing
streams, stale connection replies, demo labeling and stable table rows.
Physical clock-register capture and rendered GUI remain unverified here.

For the next protocol step, a saved clock report plus the clock source and
sample rate currently shown on the rig would provide a useful comparison.
No audio configuration changes or repeated button testing are required.

Remaining major gaps: verified native clock/sample-rate editing and source
labels, stereo pan/balance, MIDI configuration, native preset-file transfer,
and immersive/bass-management controls. Previous release notes below retain
historical limitations that may have been addressed in newer builds.

Previous release notes

TEST97 — Direct digital stereo Link / Unlink

ADAT and USB mixer strips now have Link / Unlink buttons below Aux 4.
They work in Main and Cue. Both mono members must be included to link; the
stereo pair must be included to unlink. Otherwise use Sources… first.
The linked pair collapses to one strip after device readback confirms it.
Buttons use local ADAT/USB numbers, including USB 31/32 at the final pair.

Conversion only writes mixer membership flags. It does not write preamp,
level, pan, mute, solo or Aux settings. Linking removes the two mono flags
then enables the stereo flag; unlinking reverses that sequence. The driver
checks full selection masks before each step and confirms every write.
Both members are locked while the operation is pending; duplicate clicks
and bank/bus changes are blocked. Reconnect invalidates outstanding replies.

A failed step stops the sequence without repeated OUT or automatic rollback.
Partial conversion is reported and both strips are refreshed from the rig.
If only one mono member remains after an error, inspect Sources… to restore
the desired membership before trying again. A conversion can briefly remove
the pair from the mix while the membership flags change.

Validation: 705 automated tests passed; Python compilation passed.
New coverage: all 24 digital pairs, both buses, both directions, exact indexed
write order, preserved unrelated flags and levels, stale selection checks,
external changes between steps, no-op conversions, partial failure stopping,
disconnects, demo mode, old-connection rejection, duplicate clicks, pending
state cleanup and confirmed collapse state. GUI rendering and physical digital
pair conversion remain unverified here.

Short hardware check: on one already-included ADAT or USB mono pair, click
Link, check it collapses and retains its levels, then Unlink. No repeat analog
or full digital control batch is needed.

Previous release notes

TEST96 — ADAT equipment names

Analog 1–16 and ADAT 1–16 names are now read automatically when connecting
or after loading a device preset. The scan stays at low priority and reads
at most one USB word per step; control and meter polling are unchanged.
ADAT equipment names appear on the ADAT mixer bank and Sources page. Stereo
strips combine the two names, avoiding duplication when they are identical.
Blank/default labels fall back to ADAT channel numbers.

MIXER > Names… now lists both banks and supports guarded ADAT renaming.
The Input column identifies Analog/ADAT explicitly. Select a row, enter a
name, and click Save name to rig. The existing 15-byte UTF-8 app limit,
connection checks, current-name checks and exact readback confirmation apply.
The table scrolls to all 32 names. Automatic startup reads never write names.
USB returns retain numbered labels: no USB name addresses are assumed.

ADAT input names use group 2 parameters 28–43. Analog inputs remain 0–15.
The intervening analog-output name parameters 16–27 are excluded from this
input-name API. Each name must agree across two reads before it is used.

Validation: 688 automated tests passed and all Python modules compiled.
New coverage includes all 16 ADAT rename addresses and packet payloads,
automatic scan boundaries, output-name exclusion, analog name isolation,
failed/stale/disconnected writes, demo mode, mono/stereo labels, and manual
refresh completing across both banks. No rendered GUI or physical ADAT name
verification was available here.

Optional hardware check if you use ADAT: open Names…, confirm an ADAT name,
rename one input, then reconnect and confirm it is read back on its mixer
strip. No repeat mixer-control or analog-name test batch is needed.

Previous release notes

TEST95 — Digital mixer banks and controls

MIXER now has ANALOG, ADAT 1–16, USB 1–16 and USB 17–32 bank buttons.
Choose MAIN MIX or CUE MIX, then the bank. Use Sources… to include the
wanted digital mono inputs or stereo pairs first. Unselected strips remain
read-only. Digital labels identify their actual ADAT/USB channel numbers.

Digital strips provide level faders, mute, solo and mono pan. Main mix also
provides Aux 1–4 send levels and send mutes. Linked pairs collapse to one
strip and adjust both members while retaining any relative level offset.
Stereo pan remains unavailable, as in the analog view. Digital inputs do not
show analog input-gain, front/rear or preamp-link controls. Change their
mono/stereo membership on Sources….

ADAT and USB meters use the existing 236-byte meter stream and polling rate.
Master stays beside the visible bank. Bank switches cancel drags, reject
switching during pending channel writes, and wait for fresh channel state.
Late replies from another bank cannot advance or populate the current bank.

The analog driver is unchanged. Digital controls use its existing guarded
mono/stereo logic through a separate bounded addressing facade. Packed mask
reads assemble all 4 channel words (2 for stereo flags); writes address one
native bit. Level/pan writes address native elements 16–63. OUT is sent once,
then readback is retried. Partial stereo failures stop and are reported.

Validation: 674 automated tests passed, including digital mono controls on
all 48 inputs and both buses, all 24 digital stereo pairs on both buses,
all four Aux sends, meter boundary mapping, bank layout/polling, short reads,
failed writes, disconnects, version checks and demo isolation. Python compile
checks passed. GUI rendering and physical digital controls were not verified
in this environment.

Short hardware check: use one included ADAT source and one USB return with
a signal. Check meter identity, fader, mute/solo and an Aux send; if using a
stereo pair, check both sides respond. No repeat analog test batch is needed.

Previous release notes

TEST94 — ADAT and USB mixer-source selection

Open MIXER > Sources… and choose Main or Cue, then the Analog, ADAT or USB
bank. The page now covers Analog 1–16, ADAT 1–16 and USB returns 1–32.
Include/remove individual mono sources or adjacent stereo pairs. Source
membership changes affect the device mixer; they do not change signal routing.

Before enabling stereo, remove both mono members; before enabling mono,
remove the stereo pair. Existing levels, mute, solo and sends are retained.
This update adds selection controls only: the main fader view is still analog-
only. Digital faders/sends are not claimed as implemented in this release.

The new full-mask selection path reads mono words 0–3 and stereo words 0–1
twice, rejects unstable captures, checks the selected connection generation
and expected 64/32-bit masks, writes a single indexed boolean, and compares
all selection words afterward. Other selections must remain unchanged.
Commands are not repeated on uncertain completion. Hardware state version
18 is required. Analog-only controls outside the Sources page retain their
existing backend. Demo selection keeps upper digital bits separately so
older simulated analog controls cannot erase them.

652 automated tests passed. New tests exercise all 64 mono inputs and all
32 stereo pairs (both member addresses) on both buses; exact read-word/write-
bit indexes, other-word/other-bus preservation, stale snapshots, conflicts,
no-ops, ignored/side-effect writes, uncertain completion, disconnects, version
checks, demo isolation, UI bank mapping and worker connection generation.
Python compilation passed. Physical digital source mapping/selection and
rendered GUI have not been verified in this environment.

One small hardware batch: check one ADAT source and one USB source on the
Sources page, confirm their inclusion on the rig, then restore their original
selection if needed. Prior analog controls and routing tests need not repeat.

Remaining major gaps: digital mixer faders/sends, stereo mixer pan/balance,
clock/sample-rate controls, MIDI configuration and native preset-file transfer.

Historical release notes:

TEST93 — stereo-pair routing and pair Undo

ROUTING now has a Stereo pairs (L/R) checkbox. It is off by default, preserving
individual-jack patching. Enable it to route adjacent L/R channels together:
Main Mix L/R, Analog 1/2…15/16, ADAT 1/2…15/16 and USB 1/2…31/32.
Dropping either member normalizes the pair to L→L and R→R. Destination pairs
follow the existing native Speakers, Analog, Phones, ADAT and USB numbering.
Aux buses remain mono in this feature; switch Stereo pairs off to patch Aux.
This does not change preamp, mixer or auxiliary link settings on the device.

Both destination values are checked before the first write. Each member then
uses the established expected-value guard and readback confirmation. Members
that already match send no hardware OUT. Writes are sequential, not atomic:
a failure stops the pair and reports how many routes were confirmed; earlier
changes can remain, and an uncertain failed write requires a fresh read.
There is no automatic rollback or retransmission of uncertain commands.

After a successful pair, Undo stereo patch restores both original sources
through the same preflight/readback flow. A later mono patch or routing-file
batch replaces that pair Undo. Failed/partial operations require inspection
and a routing reread; they do not advertise a completed pair Undo.

Hovering a valid stereo target previews both cables where their source jacks
are visible. The chosen colour is applied to each confirmed member. Repatching
an unchanged pair recolours both without hardware writes. Mono patching,
colour persistence, routing-file save/load and polling are unchanged.

634 automated tests passed. New coverage includes pair boundaries and right-
jack normalization, missing/unknown partner reads, Aux rejection, preflight
before either write, two-step completion, pair Undo, first/second write failure,
no-op recolouring, mono compatibility and irrelevant/stale event isolation.
Python compilation passed. Desktop rendering and physical stereo interaction
were not available here.

One new hardware check: enable Stereo pairs, patch one known source/output
pair, confirm both L/R routes, then Undo stereo patch. No repeat full control
batch is needed.

Remaining major gaps: stereo mixer pan/balance, ADAT/USB mixer-source editing,
clock/sample-rate settings, MIDI configuration and native preset-file transfer.

Historical release notes:

TEST92 — eight-colour cable picker

The routing page now has a top colour picker: Red, Orange, Yellow, Green,
Cyan, Blue, Purple and Pink. A checkmark, border and label identify the chosen
colour. Select one before dragging; the free cable and plug use that colour.
Once the routing write is confirmed, the connected cable and destination plug
retain the colour selected at drop time. Failed writes do not assign colours.

To recolour an existing cable, select a colour and patch its same source to
its same destination again. This changes only the local appearance and sends
no USB write. Colours are stored by source/destination pair, so undo or later
returning to a prior route can recover its chosen colour. Existing uncoloured
routes keep their bank colours. Selection still dims unselected cables.

Colour preferences are local to the computer, in the app's configuration
folder (cable-colors.json); they are not stored on the rig or in routing-preset
files. The picker choice and assigned colours are loaded at the next launch.
Unwritable preference storage leaves the current session's colours usable.

620 automated tests passed, including all eight palette entries, preview
colour, confirmed/failed drops, unchanged-route recolouring without writes,
preference persistence, malformed preference handling and per-route isolation.
Python compilation passed; desktop visual verification was not available.
No hardware retest is needed for this appearance-only feature.

Historical release notes:

TEST91 — rack-style panels and cable handling

The patch bay now uses metal module faces with mounting screws, rack rails,
section legends, coloured signal indicators and detailed socket nuts/plugs.
Cables have thicker shaded bodies with a bright ridge, shadows and slack.
All graphics are native canvas drawings; no external assets are required.
This is an independent rack-inspired interface, not a VCV Rack integration.

Drag from a source jack to an output jack: a solid cable and free plug follow
the pointer. Hover over a writable mapped destination and the plug snaps to
it with a green ring. Release to submit the existing guarded routing change.
You can also drag from an output jack back to a source. Clicking a source
without dragging carries a visible cable with the pointer until you click
an output. Escape or right-click cancels. Dropping a dragged cable on blank
space cancels without writing. Clicking a cable still selects its route.

Preview motion only updates canvas items and sends no USB commands. Existing
routes remain confirmed readback until the device accepts a completed drop.
The established stale-value guard, undo, routing-file save/load, filters and
polling behavior remain in place. Factory and other preset controls are
unchanged. No guessed disconnection source or additional hardware routing
parameters have been introduced.

612 automated tests passed, including six new interaction tests for solid
preview and plug movement, target snapping, reverse drag, blank-drop cancel,
click-to-carry and canceling both drag directions. After tightening hover
availability checks, all 18 patch-bay tests passed again. Python compilation
passed. Desktop rendering and physical-device interaction remain unverified
in this environment.

Quick UI check: drag one cable and confirm the plug follows the pointer,
drop on a known output, then use Undo last route. Cancel a second drag with
Escape to check it leaves routing unchanged. No full hardware batch needed.

Historical release notes:

TEST90 — modular-style routing patch bay

The ROUTING tab now opens a dark patch-bay view with source jacks on the left,
destination jacks on the right and curved coloured cables between them.
Drag a source to an output, or click a source and then an output. Each action
uses the existing guarded single-output routing command and readback flow.
Confirmed cables do not move until the hardware change is accepted and the
routing capture is reread. Repatching an output replaces its prior source.

Source filters: Connected (default), All, Mix buses, Analog, USB, ADAT.
Output filters: Physical (default), ADAT, USB, All. Scroll vertically for
larger banks. A filtered-out source is identified in its destination label.
Click a cable/output to inspect its route; other cables dim for clarity.
Clear selection only clears the highlight; it does not alter routing.
Undo last route, routing-preset save/load previews and report saving retain
the existing behavior. Loading a routing file can change several outputs and
stops at the first failure, as before; it is not an atomic hardware operation.

This first implementation uses actual verified native labels and individual
mono jacks. L and R are patched separately, rather than pretending that two
writes are atomic. The recovered mapping has Main Mix L/R, Aux 1–4, analog,
ADAT and USB sources; it does not expose all the illustrative sockets from
the proposed mockup. No guessed Cue source or extra headphones endpoint is
added. An explicit Disconnect operation is omitted because no unassigned
source code has been verified. Unknown/unread destinations cannot be written.

606 automated tests passed, including source/destination filtering, guarded
patch commands, unchanged and invalid routes, pending/disconnected/version
blocking, click/drag behavior, cable selection, undo and failed-write handling.
Python compilation passed. Rendered desktop GUI and physical-device checks
were not available here. The USB routing protocol and polling are unchanged.

Quick new UI check: open ROUTING, select a source bank, patch one known output,
then Undo last route. No repeat full hardware button-test batch is required.

Historical release notes:

TEST89 — rename device presets

Open PRESETS, select a user slot (1–8), and click Rename selected preset.
Enter its new name and press OK. Factory remains read-only. The current slot
heading and selected row update only after matching hardware name readback.
An unchanged name sends no write. Renaming does not issue a save or load
command and does not replace the slot's stored settings.

This build uses the same conservative 15-byte UTF-8 editing limit as channel
names. This is an application limit, not a firmware capacity claim. Blank
names appear as Unnamed. Control characters and overlong names are rejected.
Before writing, the app checks the connection and rereads the old slot name;
a changed name blocks the edit. Exactly one name command is sent, followed
by bounded readback attempts. Uncertain writes are never retransmitted.
If confirmation fails, Read presets inspects the actual stored name.

Background status polls neither disable nor repaint the rename button when
nothing changed. The renamed table row updates in place. Normal polling,
mixer layout, fader controls, and existing load/save behavior are unchanged.
Demo renames exist only within the current simulated connection.

594 automated tests passed. New coverage includes all eight exact name-write
packets, Factory rejection, no save/load commands, stale names/connections,
UTF-8 and blank names, ignored writes, uncertain completion, disconnects,
worker event routing, dialog cancellation and stable button rendering logic.
Python compilation passed; rendered GUI and physical rename verification
were not available here. Native read/save/load remains user-confirmed.

One new hardware check: rename one user slot, press Read presets, and check
the name remains. There is no need to repeat prior control or save/load tests.
Power-cycle persistence of the renamed label is not yet independently checked.

Remaining major gaps: stereo pan/balance, ADAT/USB mixer-source editing,
clock/sample-rate settings, MIDI configuration and preset-file transfer.

Historical release notes:

TEST88 — fill the window through the master strip

Removed the 170-pixel maximum strip width that left unused space at the end
of the mixer. All channel strips and Main Master now divide the full mixer
viewport equally, growing when maximized and narrowing in smaller windows.
The master ends at the viewport's right edge. Integer rounding pixels are
distributed across the channels; widths differ by at most one pixel. Only
normal strip dividers remain. No scrollbars are added. Linking/unlinking
recalculates widths across the complete bank.

577 automated tests pass, including exact full-width coverage across 50
combinations of channel counts and widths from 800 to 3840 pixels. Existing
preset functionality, fader caps, drag response and polling are unchanged.
Python compilation passed; a rendered GUI check was not available here.

Historical release notes:

TEST87 — adjacent master strip and hardware-style fader caps

Main Master now belongs to the same packed mixer bank as the channel strips,
positioned immediately after the last visible channel. Resizing/fullscreen
cannot insert expanding space between them. The normal divider is 8 pixels.
Unused width is after the complete mixer bank. Channel and master strips
retain equal widths, narrowing together as needed, without scrollbars.
Link/unlink rearranges channels and then repacks the master last.

Channel and master faders now have dark rectangular caps with bevelled edges,
a subtle shadow and a white horizontal position marker, following the supplied
Novation Launch Control XL reference. Caps are native canvas drawings; no
external image assets are needed. Fader travel, dragging, fine adjustment,
readback and USB/polling behavior are unchanged.

576 automated tests passed, including equal-width viewport fitting and master
packing after mono/stereo banks. Python compilation passed. No rendered GUI
or physical-device testing was available here. Existing hardware functionality
and the user's prior preset confirmation remain unchanged.

Historical release notes:

TEST86 — uniform mixer strips and steady preset buttons

Channel strips now use the same width as Main Master: 170 pixels when space
allows. They no longer expand across unused mixer space. If the window is
narrow or more mono strips are visible, all channel strips and Main Master
narrow equally to fit without introducing scrollbars. Linking and unlinking
recalculates the common width.

Preset status polling now has its own request tracking and does not set the
load/save busy state. Buttons remain clickable during background reads and
unchanged widgets are not reconfigured. Real load/save actions still disable
the buttons while pending. Late background replies cannot finish or clear a
pending operation. Status polling remains at its existing one-second interval;
monitor and meter polling rates are unchanged.

575 automated tests passed, including equal-width layouts at wide and narrow
sizes, background reads remaining clickable, unchanged readback causing no
button/label reconfiguration, pending-save isolation and read-error handling.
Python compilation passed. GUI rendering was not available in this environment.
The user confirmed device preset functionality works in TEST85. No repeat
physical save/load batch is needed for this GUI update. Power-cycle persistence
has not been separately confirmed.

Historical release notes:

TEST85 — native device presets

Open the new PRESETS tab across the top. Opening it reads the current slot,
the device's unsaved-changes flag, and names for user slots 1–8. Factory (0)
is shown as load-only. Select a row, then Load selected from rig or Save
current settings to selected slot. The confirmation identifies the exact
slot and whether it replaces active settings or overwrites a saved preset.
Names are read from the device; preset renaming and preset-file import/export
are not part of this update. Existing routing-file presets remain separate.

Load/save use the native AFCC USB command path recovered from the Windows
agent, not a partial replay of the controls our app currently supports.
Connection generation, current preset/dirty state and selected name are
checked before writing. The app sends one command and never automatically
retries it. A full USB completion plus matching current-slot and clean-state
readback is required for success. Failure messages remain visible; Read
presets rereads actual state. An unconfirmed command may still have applied.

After a load attempt, mixer/preamp/routing caches are invalidated, current
settings are polled again, and equipment names are reread automatically.
Normal monitor and meter polling intervals are unchanged. Preset metadata
reads occur only while opening/using this page; opening it never loads or
saves a slot. Demo mode simulates preset metadata/operation status only; it
does not emulate full preset contents or touch USB.

568 automated tests pass, including exact native request fields, read-only
slot browsing, factory-save rejection, stale selections/connections,
short reads, rejected/uncertain writes, disconnects, single-command behavior,
cache invalidation and headless confirmation/page logic. No GUI rendering or
physical preset-operation verification was possible in this environment.
Physical save/load behavior and power-cycle persistence remain unverified.

One short hardware check (no repeated full button batches):
1. Open PRESETS and check that slot names match the rig.
2. Save current settings to a user slot you are willing to overwrite.
3. Change one recognizable setting, then load that slot and check it returns.
If the app reports an error, read presets again and inspect the rig before
retrying. Save the usual application report if readback fails.

Remaining major gaps: stereo pan/balance, ADAT/USB mixer-source editing,
clock/sample-rate settings, MIDI configuration, preset renaming/file transfer.
See DEVICE-PRESETS-PROTOCOL.md for native command evidence and limitations.

Historical release notes:

TEST84 — edit equipment names from Linux

Open MIXER > Names…, select an analog input, edit its equipment name, and
press Save name to rig. This explicitly writes only that input's name.
Mixer labels update only after matching hardware readback. Blank names use
the generic mixer heading. The editor uses a conservative 15-byte UTF-8 limit
for this build; this is not a claim about the firmware's maximum capacity.
Multibyte characters consume more than one byte. Control characters are rejected.

Before writing, the worker checks the connection generation and reads the
current name twice. If it differs from the selected original, it refuses to
overwrite it. An unchanged name sends no OUT. A changed name sends exactly
one USB OUT (0x40/0x1a, parameter=input-1, index=0, UTF-8 plus NUL). It then
performs bounded readback attempts; uncertain OUTs are never retransmitted.
Readback success is required before accepting the new label. Errors stay in
the names panel, and Refresh names can inspect the actual device state.
A write may have applied even if its confirmation fails. Demo editing affects
only the current simulated connection and never accesses hardware.

Protocol evidence: the native AFCC agent's string-write helper at VA
0x1407c6ef0 appends a terminator and uses request 0x18+group with index zero.
Recovered analog name group 2 provides request 0x1a and parameter IDs 0–15.
Source SHA256 remains 7a6b805d11170c9f35731b40f83c48efacfd248edc95c7baf6c6e01faad13513.
Packed UTF-8 reads were confirmed by the user's name report. String WRITES
are newly implemented and have not yet been verified on physical hardware;
persistence through a power cycle is not claimed without confirmation.

539 automated tests pass. New tests cover exact USB fields/payload, stale
names/connections, unchanged names, UTF-8 bounds, blank names, bad input,
readback failure, ambiguous OUT completion, disconnects and demo isolation.
No GUI rendering or new hardware verification was performed here. No full
physical control test batch is required; one deliberate rename is sufficient
to confirm this feature's basic device behavior.

Remaining major gaps: stereo pan/balance, ADAT/USB mixer-source editing,
clock/sample-rate settings, native device presets and MIDI configuration.
These remain separate from the existing analog mixer and app routing presets.

Historical release notes:

TEST83 — one stereo gain knob and horizontal Aux rows

Each stereo mixer strip now shows one input-gain knob for its pair, labelled
with both input numbers. Mono strips retain one gain knob for their own input.
The shared knob sets both gains to the same requested value. If current gains
differ, its readout shows L / R values until adjusted rather than hiding the
mismatch. Inputs with incompatible source modes cannot use shared adjustment.

Pair gain adjustment checks stereo membership and both active input modes and
ranges before writing. It verifies each change, skips a partner write if the
hardware already propagated the gain, and confirms both final readings. A
failure stops the operation; no successful pair readback is claimed if only
one member changed. Source changes prevent writes to an unintended input.

Aux send rows now place AUX 1–4 labels on the left, the corresponding knob in
the middle and M on the right. Labels/buttons align with the dial centre above
its numeric readout. Master Aux rows use the same horizontal arrangement,
with their PRE control retained beneath M and their meter beside the dial.
The common Front/Rear row still keeps channel fader tracks aligned.
No scrolling or polling-frequency changes are introduced.

527 automated tests pass, including both rear gains, front native gain steps,
unlinked-pair rejection, source/range guards and skipping unchanged writes.
No rendered desktop or physical hardware verification was performed here.

Historical release notes:

TEST82 — aligned channel fader rows

The screenshot showed the extra Front/Rear button on input 1/2 pushing its pan,
mute/solo and fader track below the other strips. Every strip now reserves the
same optional source-control row. Its height is measured from the actual
button plus padding, respecting Tk font scaling rather than a fixed constant.
No blank button is added to other channels. The reserved space keeps the
lower controls and fader scales aligned when linking or unlinking channels.
Repeated layout updates configure the row only when its height changes.

The two knobs directly above a stereo pair's Link/Unlink button are individual
input gains. The single knob below Link/Unlink is pan; stereo pairs currently
show it disabled with LINKED L/R. No pan, gain or USB behavior changed here.

All 521 automated tests pass, and Python compilation passes. No rendered GUI
verification was possible in this environment; the supplied screenshot was
used to identify the extra source-row height. This is a layout-only fix and
does not require another hardware button test batch.

Historical release notes:

TEST81 — enabled button hover/click fix

Tk buttons use state='active' while hovered; this is an enabled state.
Several action guards accepted only state='normal', rejecting valid pointer
clicks while the native button was active. They now accept normal and active,
while continuing to reject disabled controls and retaining pending-operation,
source, connection and readback guards. Native full-rectangle hit testing and
keyboard activation are unchanged; no text-only hit region is introduced.

The correction covers Link 1/2, Front/Rear and the same state checks on other
controls (including Aux, master, source selection and detailed mixer buttons).
The USB protocol and polling intervals are unchanged.

521 automated tests pass, including hovered Link and Front/Rear dispatch,
identical normal/active actions, disabled and pending guards, and Aux master
hover handling. No rendered desktop verification was possible here; the
reported pointer behavior still needs confirmation in normal use.

Historical release notes:

TEST80 — link input 1/2 using the active front/rear bank

The reported rear_link error originated from the Rear Inputs tab using the
rear link parameter unconditionally, even when the front inputs were active.
That tab now uses matching front line/instrument, front microphone, or rear
link parameters according to current source detection. Both reads and writes
use the selected bank; stored rear link bits no longer masquerade as front
link state. Source detection is checked again when the command executes.
The link detail identifies Front line / instrument, Front microphone or Rear.
No automatic front/rear switch is performed by linking.

Mixed source modes and unavailable source detection disable linking rather
than sending to the wrong bank. Other rear-input controls retain their prior
behavior. Main Mix stereo conversion and its source-aware input link remain
as in TEST78. The old generic Try pair 5–6 wording was removed from rear-link
failures; actual rear-source context is now included instead.

515 automated tests pass, including front line parameter 22, front mic
parameter 23, no rear parameter 24 write while front inputs are active,
readback from the active bank, changing source before execution, mixed-mode
rejection and demo parity. These verify the corrected software path, not a
new physical test. Stay on the front inputs and retry linking 1/2. If it still
fails, Copy error preserves the exact new error without a full test batch.

Historical release notes:

TEST79 — aligned Aux controls, no mixer scrollbars, persistent errors

Aux labels are centered over their corresponding knobs in a shared column,
including the master Aux controls. Mute/Pre buttons remain beside them.
The mixer horizontal and vertical scrollbars have been removed. Its channel
bank uses the actual viewport dimensions instead of a larger fixed minimum;
strip widths are recalculated when stereo linking changes the visible count.
Dial heights still adapt to the window. Very narrow/short windows can compress
controls; maximize the app for the full mixer. Window-size persistence remains.

Rear Inputs: command errors now remain yellow through live polling. They clear
when you retry a control, explicitly Refresh/select another input, dismiss the
error, or close the panel. Copy error puts the exact text on the clipboard;
Dismiss error restores live status. Polling and control readback continue.
This change makes the reported input-1 link error readable; it does not claim
to fix the unknown underlying hardware error. Copy its message if it recurs.

509 automated tests pass. New regressions cover repeated polls preserving an
error, exact error copying, dismissal, viewport-sized banks and recalculation
after unlinking. No rendered GUI or physical hardware verification performed.
No full button test batch is requested.

Historical release notes:

TEST78 — pair source buttons and stereo mixer Link

The channel 1/2 source buttons now explicitly identify the shared pair:
1/2 → FRONT or 1/2 → REAR. Both dispatch the same pair operation. Source-button
availability follows shared source readback instead of each separate mixer
strip's stale flag. Background preamp reads no longer clear a pending write
or replace its displayed state before command completion. Repeated clicks
from either pair member are suppressed until completion.

The Link button now performs the stereo mixer conversion the user expected,
as well as the existing input-settings link. Linking removes the two mono
members and includes their stereo pair using the existing checked API.
Unlinking removes the stereo pair and includes the two mono members. Both
members must initially be present as mono, or already selected as stereo.
Each write checks selection masks and readback; input source compatibility
is checked first. The UI collapses only from confirmed mixer selection.
Gain, levels, sends and unrelated pair selections are not explicitly reset.
Native input-link side effects remain device-defined.

Conversion takes multiple USB writes and can briefly interrupt the pair's
signal. If a step fails, no later steps are attempted. The message explicitly
reports that some changes may have applied and directs inspection in Sources;
there is no unsafe automatic rollback or claimed atomic conversion.
Physical behavior and the rig's display indication still require confirmation.

The knob immediately above INPUT GAIN is Aux 4 send, not an empty control.
The four Aux knobs are now labelled SEND 1–4 to distinguish them from input
gain. Their effect on audible output depends on existing Aux routing.

504 automated tests pass, including both source buttons, pending background
read isolation, front and rear stereo conversion, unlinking, stale masks,
partial failures and preserving unrelated selections/levels. No new physical
or rendered desktop verification was performed here. Test only the reported
source and link actions; no full button batch is requested.

Historical release notes (TEST78 supersedes the earlier Link behavior):

TEST77 — input controls on Main mixer strips and responsive master

Under Aux 4 on each Main mixer strip:
- Active input gain, selected from rear, front line/instrument, microphone,
  or front minijack according to current device source detection.
- Link/Unlink for the existing hardware input pair. This links input settings;
  it does not convert Main/Cue source membership or change routing.
- Channels 1/2: Use Front / Use Rear button, switching the pair together.
  Use Front clears rear override and enables front detection. If no compatible
  front cable is present, the rig can continue using rear input. The button
  still allows switching back to forced Rear. Gain labels show actual sources.

Grouped stereo strips display a separate gain dial for each member. Rear and
minijack gain use the existing 0–12 dB range; front 1/2 gains use native steps
0–55 as in the prior gain panel. Gain targets use integer steps, with fresh
source/range/version guards and confirmed readback. A changed source blocks a
queued gain write rather than redirecting it to another physical input.
Link is disabled for mixed-source pairs and the unmapped front-minijack link.
Detailed existing input panels remain available. Cue shows the same readings
but input editing is available from Main. These are shared physical-input
controls, so changes also affect any other mix using those inputs.

Main/Cue master readback now runs independently at a 200 ms target interval
while the mixer is visible, rather than waiting for the full channel scan.
The master handle also previews its pointer position immediately during drag;
the numeric readout stays hardware-confirmed. Other polling intervals remain
unchanged. Coalescing, verified writes and error handling remain in place.

The added controls use compact dials on shorter windows. A 600-pixel bank
minimum retains usable faders; scrolling remains necessary on very small
screens. Startup sizing/window persistence and VU meters remain from TEST76.

496 automated tests passed. New coverage includes active rear/line/mic/mini
selection, correct gain units, stale-source guards, range/version checks,
front detection without cables, pair source switching, demo readback, master
poll scheduling and immediate handle feedback. No hardware or rendered GUI
verification was performed in this environment. No full button-test batch is
requested; use the moved controls normally.

TEST76 — screen sizing and live VU/peak meters

The first launch opens maximized using the available screen. Closing the app
saves its size/maximized state in ~/.config/af16rig-control/window.json (or
$XDG_CONFIG_HOME/af16rig-control/window.json). Reopening restores it, bounded
to the current screen. Mixer dial heights adapt to the viewport; the old
forced 720-pixel bank height is removed. All 16 strips fit at a normal full-HD
maximized size. Scrolling remains a fallback on screens too small for controls.

Analog input signal meters appear beside channel faders. Stereo groups show
separate L/R bars. The master shows Main or Cue L/R; the Aux dials have meters.
These input bars measure incoming signal, not the channel fader position.
Cyan bars turn amber near the top and red at full scale, with one-second peak
hold and falling-level animation. Raw native words are normalized by 32767;
the display uses a logarithmic -60 to 0 dBFS scale. Transport/mapping come from
the Windows agent; physical meter movement and absolute calibration are not
yet verified on the user's device.

Reads run automatically, targeting a 50 ms interval when the worker is free.
Commands and existing monitor/input polls retain priority and their intervals.
A single 236-byte USB IN request obtains the complete meter frame; the timeout
is bounded to 20 ms. No audio device is opened, and no configuration writes are
sent. No ALSA/PipeWire capture device or DAW routing changes are required.
Meter rendering changes only the small meter canvases, not knobs or faders.
Data older than 500 ms is blanked. A meter transfer error disables metering
until reconnect while leaving normal controls/polling active. The status line
shows the error. Demo mode explicitly uses synthetic signals.

482 automated tests pass, including frame offsets, USB request/length/timeout,
short reads, disconnects, failed-meter isolation, reconnect, stale data, stereo
bars, peak decay, window persistence and full-HD viewport fitting.
No physical hardware run was possible here. Visual desktop verification was
blocked by the X server failing to create its listening sockets.
Only one focused check is needed: open normally and play existing audio to
confirm bars respond on the expected inputs. No button test batch is needed.

TEST70 fixes
- Tab selection hides all other pages, including any leftover embedded page.
- Pending writes no longer flash every control on a channel strip.
- Identical labels, values and canvas dimensions cause no Tk redraw mutation.
- All USB worker logic and console polling timing are unchanged from TEST69.
- No physical hardware or rendered GUI verification performed here.

TEST71: output source routing
Open ROUTING, select a mapped output_source row, choose its source and click
Apply source. Only that destination is written. Undo last route restores the
previous code if the route has not changed since the last successful edit.
The app rereads the current slot before writing, confirms the same slot after
writing and then refreshes the routing capture. Reconnects invalidate old
captures. Unknown source/destination codes and partial/unstable captures
cannot be edited. There are no automatic routing changes on launch or selection.

This is the first writable routing implementation. The protocol address and
names come from the recovered native descriptors/tables. Actual routing writes
and audible destinations have NOT yet been confirmed on hardware. The Analog
names retain AFCC's native numbering; do not assume they equal rear jack labels.
One deliberately chosen route and Undo is the focused confirmation for this
feature; there is no reason to rerun the full mixer/button hardware batch.

TEST72: routing preset files
In ROUTING, choose Save routing preset to save all currently mapped routes.
Unmapped routes are omitted and the saved route count is displayed.
Load routing preset opens a before/after preview. Nothing is written until
Apply these changes is pressed. Presets with matching routes produce no writes.
Demo presets are kept separate from hardware presets.

Apply checks all original routes first, then writes one changed destination at
a time using the existing readback guard. Earlier successful changes remain
applied if a later change fails; the app stops and reports confirmed progress.
Switching to another page cancels the remaining queue. An already in-flight
change may still finish. Undo last route restores only the LAST destination;
save the original routing preset before loading another if you want a complete
routing restore later. To restore, load the saved original and review its preview.

These are app routing files, not the hardware's built-in device presets.
The routing write protocol remains unchanged from TEST71 and is still awaiting
physical verification. No full mixer/button test batch is required.

TEST73: Main/Cue analog source selection
On the MIXER page, click Sources… beside Main Mix / Cue Mix.
Choose Main or Cue and an analog input (1–16). The panel shows whether each
member is included as mono and whether its stereo pair is included.
Use Include/Remove mono input or Include/Remove stereo pair as available.

To convert two mono inputs to stereo, remove each mono input first, then include
the stereo pair. To convert back, remove the stereo pair then include the mono
inputs separately. These operations change mix membership and can affect audio.
Stored channel levels, mutes, solos and send settings are not reset.
Only the selected inclusion flag is sent; both selection masks are checked
before the write, and the flag plus surrounding masks are verified afterward.
ADAT/USB source selection is not enabled. Source inclusion writes are new and
have not been verified on physical hardware yet. Simulator tests cover all
16 mono inputs and eight stereo pairs on both mixers. Demo mode shows source
membership/grouping, but stereo channel-control writes remain unsimulated.
Polling intervals and the overall GUI layout are unchanged.

TEST75: automatic equipment names
Names are read automatically after the app connects, including reconnects.
The Main/Cue mixer headings use the names stored on the AF16Rig. Analog channel
numbers remain visible. A stereo pair uses its custom name when the other
member is the default ANALOG IN; two different custom names are both shown.

The supplied TEST74 hardware report confirmed all 16 name slots and the packed
text format for the observed names. This release uses live device reads, not
hardcoded equipment names. Names load incrementally in the background, with
normal polling and user commands taking priority. Polling intervals are unchanged.
No hardware configuration is written by automatic name loading.

MIXER > Names… displays the cached results immediately. Refresh names performs
an explicit reread; Save name report exports the results. No manual name button
is needed on normal startup. Reconnect clears old labels before loading names
again. Failed/unstable reads retain generic channel labels. Demo names are
synthetic and never presented as hardware names.

Command-line capture remains available (close the GUI first):
    python3 channel_names.py

New console
- Charcoal and cyan interface based on the approved Arturia-style mixer mockup.
- Main/Cue selector, automatically grouped mono/stereo analog channel strips.
- Four Aux send dials per strip, send mute, mono pan, channel mute and solo.
- Long level faders and fixed Aux/Main/Cue master section.
- Monitor level, mute, dim and mono remain visible above every page.
- Input, output and monitor controls open within the main window.
- Confirmed pan-recording and report buttons removed from normal controls.
- Offline and focused diagnostic tests remain available from the command line.

Controls
Faders follow the distance you drag along their tracks. Knobs span their full
range in 120 pixels of vertical dragging. Hold Shift for 10x finer dragging.
Level drag targets use 0.25 dB resolution; pan uses its native integer steps.
Scroll or arrow keys retain 1 dB / single-pan-step adjustments.
The newest pointer target replaces unsent intermediate positions, and each
write is verified before the next is sent. Stereo level differences are
preserved and both channels stay within range. Switching pages cancels unsent
drag targets. The Mixer button explicitly restores and raises the mixer page.
When stereo members differ, the readout displays L / R values.
Main/Cue channel inclusion and stereo grouping follow device readback and can now be edited through Mixer > Sources.
Use horizontal/vertical scrolling when all strips do not fit the window.
Cue Aux sends remain unavailable because these are Main mixer sends.
Known output_source routes can be edited. Cue destination/selection and unmapped codes remain read-only.
Live input, Main/Cue master and Aux meter bars are now shown (TEST76).

Validation
482 automated tests pass, including console/controller and drag checks covering
mono/stereo command selection, readback, duplicate-click suppression, stale
and disconnected guards, Cue restrictions, and read-only overview polling.
No new physical hardware verification was performed. Absolute targets reuse the existing selection, range and readback guards. Rendering could not be inspected here: the environment
has no display, and its socket restrictions prevent starting an X server.

No full hardware test batch is requested. Launch normally and use the controls.

Previous feature and diagnostic documentation follows:

AF16Rig Linux Control — TEST67
=============================
Native Python 3 + Tk + system libusb. Independent experimental software.
Full source, USB setup, automated tests and protocol research are included.

Run
---
    python3 af16rig_gui.py

For a fresh CachyOS/Arch setup:
    sudo pacman -S --needed python tk libusb
    bash setup-usb-access.sh

Offline preview:
    python3 af16rig_gui.py --demo

TEST67 routing labels
---------------------
The Routing window now displays recovered source/destination labels beside
the raw codes. The original AFCC agent contains 70 source labels and 60 native
destination identifiers. The executable hash and evidence addresses are saved
in recovered-routing-labels.json. Unknown values remain explicit.

Main Mix L/R are 192/193, Aux 1–4 are 194–197, Analog input 1–16 are 64–79,
ADAT input 1–16 are 80–95 and USB source 1–32 are 128–159.
Destination identifiers use AFCC's native names. Analog1..8 are slots 2..9;
physical jack labels require separate confirmation. Codes 160/161/240 and
destination slots 60/61 remain unresolved. Cue-specific codes remain raw.

Open Routing from the main window and choose Read routing. The labels also
appear in saved routing JSON. Editing is still unavailable while write
semantics and unresolved codes are investigated. No new device test is
requested for this update. All 354 offline tests passed. The graphical
layout has not been visually verified in this environment.

Testing
-------
Offline regressions:
    python3 auto_test.py

Focused hardware check example:
    python3 auto_test.py --only "main 1 solo"

Several named checks in one report:
    python3 auto_test.py --only "main 1 solo" --only "Speaker level"

Names match case-insensitive text fragments. Broad fragments select multiple
checks. The selected patterns and executed cases appear in the JSON.
--only enables all hardware categories and filters the writable cases.
Read-only connection, state and routing checks still run. A name that matches
nothing produces no_matching_checks and a nonzero exit code.

Before hardware tests, close the app and pause playback/live input audio.
Leave device controls alone while a test runs. The runner reads each original
state, tests a change, verifies readback and verifies restoration. Levels
normally step down 1 dB; levels below -59 dB step up 1 dB before restoration.
Source/routing guards stop writes when context changes.
Failures with unverified restoration stop the run and identify the affected
settings in the report. Input/level failures with verified restoration may
continue collecting results. A report containing failures remains failed.
Mixed/unsupported states and unresolved controls are explicitly skipped.

Full hardware regression, reserved for release-candidate checks:
    python3 auto_test.py --all

Each hardware run prints the path to its new JSON report.
