# AudioFuse 16Rig Linux Control Centre · BETA RC

An independent Linux desktop control panel for the Arturia AudioFuse 16Rig. Mix analog, ADAT and USB channels, patch sources to destinations, and manage presets stored on the interface. The app reads the rig’s channel names when it connects.

![Main Mix with nine named channel strips and the Phones, Monitor and Main Master outputs](docs/screenshots/main-mix-beta-rc.png)

*BETA RC on a connected 16Rig. Each analog strip has Mute, Solo and PAD (P). USB 1/2 sits beside the analog channels, followed by Phones, Monitor and Main Master.*

## Install on Linux

Download the repository with **Code → Download ZIP** and extract it, or clone it with Git. Open a terminal in the folder containing `run.sh`. The application uses Python 3, Tk, system libusb and ALSA. On CachyOS or Arch Linux you can install the dependencies with:

```sh
sudo pacman -S --needed python tk libusb alsa-lib
```

With the 16Rig connected by USB, run:

```sh
bash setup-usb-access.sh
bash install-desktop.sh
```

Open **AF16Rig Linux Control** from the applications menu. The first script installs a udev rule for the 16Rig MIDI/control USB device. The second installs the application for your user, including its boxed 16 RIG icon. You can then move or delete the downloaded folder. To update, close the app and run the installer from the new copy.

You can also run it directly with `bash run.sh`, or explore the interface offline with `bash run.sh --demo`.

## Using the mixer

- **Main Mix and Cue Mix** have separate faders, sends, pan, mute and solo. The Analog page includes the USB 1/2 return so you can adjust computer playback alongside the hardware inputs.
- **Front and rear inputs** expose the controls available for the selected source. Linked pairs share a gain knob. The Phones, Monitor and Main Master strips sit together at the right.
- **Routing** presents a patchbay. Select one of eight cable colours, then drag a cable between compatible jacks.
- **Presets** reads, names, saves and loads presets on the device. Mixer scenes are files on your computer. Open a scene to preview differences before recalling them. Sample-rate changes require internal clock and idle ALSA streams.

## BETA RC test results

| Check | Result |
| --- | --- |
| Automated suite on the BETA RC source | 1,388 passed |
| Desktop GUI on the TEST167 base used for BETA RC | 61 of 61 passed on CachyOS, with zero callback errors (Python 3.14.9, Tk 8.6.16) |

Two physical desktop checks remain: confirm a scene recall on the 16Rig (input sources, stereo links and sample rate), and confirm the installed app's menu entry and taskbar icon on the desktop.

MIDI Learn and immersive/bass management are outside this release. Phantom-power control remains unmapped.
